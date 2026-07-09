"""Headless CLI runner — drives a full sequence and prints live status.

Great for tuning logic/PID on a laptop in sim mode:
    python run.py cli --config config.yaml
Runs the setpoints from the config, prints a status line each second, and
writes the same CSV + metadata as the web UI. Ctrl+C stops safely.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from ..app import RigController
from ..config import Config


def run(cfg: Config, setpoints=None) -> int:
    ctl = RigController(cfg)
    stopping = {"v": False}

    def handle_sigint(signum, frame):
        stopping["v"] = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    sp_disp = setpoints if setpoints else [cfg.disp(x) for x in cfg.test.setpoints_kpa]
    res = ctl.start_sequence(sp_disp)
    if not res.get("ok"):
        print(f"ERROR: {res.get('error')}", file=sys.stderr)
        ctl.shutdown()
        return 2

    u = cfg.units
    print(f"Run {res['run_name']} started — setpoints {sp_disp} {u} "
          f"(mode={cfg.mode}). Ctrl+C to stop.\n")
    try:
        while True:
            st = ctl.get_status()
            if st["fault"]:
                print(f"\n!! FAULT: {st['fault']}")
            line = (
                f"[{st['phase']:<11}] {st['index']+ (0 if st['phase']=='done' else 1)}/{st['total']} "
                f"P={st['pressure_disp']:6.2f}{u} "
                f"SP={st['setpoint_disp'] if st['setpoint_disp'] is not None else '  -  '} "
                f"valve={st['valve_command']:5.1f}% "
                f"div={'MEASURED' if st['diverter_measured'] else 'waste'} "
                f"t={st['elapsed_s']:6.1f}s"
            )
            if st["phase"] == "collecting":
                line += f" collect_left={st['collect_remaining_s']:.0f}s"
            print("\r" + line + " " * 6, end="", flush=True)

            if st.get("finished"):
                break
            if stopping["v"]:
                print("\nStopping (operator)...")
                ctl.stop("stopped by operator (SIGINT)")
                break
            time.sleep(1.0)
    finally:
        results = ctl.get_status()["results"]
        print("\n\nResults:")
        for r in results:
            ok = "OK " if r["success"] else "FAIL"
            print(f"  [{ok}] setpoint {cfg.disp(r['setpoint_kpa']):6.2f}{u}  "
                  f"mean {cfg.disp(r['mean_kpa']):6.2f}{u}  "
                  f"std {cfg.disp(r['std_kpa']):5.3f}  "
                  f"in-band {r['in_band_fraction']*100:5.1f}%  "
                  f"n={r['n_samples']}  {r['note']}")
        if ctl.logger.meta_path:
            print(f"\nCSV : {ctl.logger.ts_path}")
            print(f"Meta: {ctl.logger.meta_path}")

        # On hardware there's no flow sensor -> ask for the measured volumes.
        needs_vol = cfg.mode == "hardware" and any(
            r["success"] and r.get("flow_m3s", 0) <= 0 for r in results)
        if needs_vol and sys.stdin.isatty():
            _prompt_volumes(ctl, results, u)

        # Auto Q-vs-ΔP fit + Darcy k + pore size (+ PNG plot).
        _print_analysis(ctl.compute_and_save_analysis())
        ctl.shutdown()
    return 0


def _prompt_volumes(ctl, results, u) -> None:
    print("\nEnter the permeate volume collected for each point (mL):")
    volumes = {}
    for i, r in enumerate(results):
        if not r["success"]:
            continue
        prompt = (f"  point {i} — setpoint {r['setpoint_kpa']:.1f} kPa, "
                  f"t={r['collection_s']:.0f}s: ")
        try:
            volumes[i] = float(input(prompt))
        except (ValueError, EOFError):
            print("  (skipped)")
    if volumes:
        ctl.set_volumes(volumes)


def _print_analysis(a) -> None:
    print("\nQ vs ΔP analysis (slope method):")
    if not a or a.get("n", 0) < 2:
        print(f"  not enough flow points to fit ({a.get('note') if a else 'no data'})")
        return
    print(f"  slope  = {a['slope_per_kpa']:.4e} (m³/s)/kPa   R² = {a['r2']:.6f}")
    print(f"  Darcy k = {a['k_darcy_m2']:.4e} m²   pore d = {a['pore_size_um']:.3f} µm"
          f"   ({'follows Darcy' if a['follows_darcy'] else 'low R²'})")
    if a.get("plot_file"):
        print(f"  plot:  runs/{a['plot_file']}")
    if a.get("xlsx_file"):
        print(f"  excel: runs/{a['xlsx_file']}")
    if a.get("json_file"):
        print(f"  data:  runs/{a['json_file']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Membrane rig CLI runner")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--sim", action="store_true", help="force simulation mode")
    ap.add_argument("--hardware", action="store_true", help="force hardware mode")
    args = ap.parse_args(argv)
    cfg = Config.load(args.config)
    if args.sim:
        cfg.mode = "sim"
    if args.hardware:
        cfg.mode = "hardware"
    return run(cfg)


def _read_points_csv(path):
    """Read (pressure_kPa, flow) rows from a CSV. Accepts headers like
    pressure/pressure_kpa and flow/flow_rate/flow_m3s/q (case-insensitive)."""
    import csv
    p_keys = ("pressure_kpa", "pressure", "dp", "p")
    q_keys = ("flow_m3s", "flow_rate", "flow", "q")
    points = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        norm = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        pk = next((norm[k] for k in p_keys if k in norm), None)
        qk = next((norm[k] for k in q_keys if k in norm), None)
        if not pk or not qk:
            raise SystemExit(f"CSV needs a pressure column {p_keys} and a flow column {q_keys}; "
                             f"got {list(norm)}")
        for row in reader:
            try:
                points.append((float(row[pk]), float(row[qk])))
            except (ValueError, KeyError):
                continue
    return points


def analyze_main(argv=None) -> int:
    """Fit + plot an existing dataset (pressure, flow) with no rig/run."""
    from ..analysis import fit_permeability
    from ..config import MembraneConfig
    from ..export_excel import export_permeability_xlsx, xlsx_available
    from ..plotting import plot_permeability, plot_available

    ap = argparse.ArgumentParser(description="Fit Q vs ΔP from a CSV, plot + export xlsx")
    ap.add_argument("data", help="CSV with pressure (kPa) and flow (m^3/s) columns")
    ap.add_argument("--area-cm2", type=float, default=0.64)
    ap.add_argument("--thickness-mm", type=float, default=0.117)
    ap.add_argument("--viscosity", type=float, default=1.0e-3, help="Pa·s (water ~20C)")
    ap.add_argument("--label", default="")
    ap.add_argument("--title", default="Q vs ΔP")
    ap.add_argument("--out", default=None, help="output base path (.png/.xlsx derived)")
    args = ap.parse_args(argv)

    points = _read_points_csv(args.data)
    mb = MembraneConfig(area_m2=args.area_cm2 * 1e-4,
                        thickness_m=args.thickness_mm * 1e-3,
                        viscosity_pa_s=args.viscosity, label=args.label)
    result = fit_permeability(points, mb)
    print(f"n points = {result.n}")
    _print_analysis({
        "n": result.n, "slope_per_kpa": result.slope_per_kpa, "r2": result.r2,
        "k_darcy_m2": result.k_darcy_m2, "pore_size_um": result.pore_size_m * 1e6,
        "follows_darcy": result.follows_darcy, "note": result.note,
        "plot_file": None, "json_file": None, "xlsx_file": None,
    })
    base = args.out.rsplit(".", 1)[0] if args.out else str(args.data).rsplit(".", 1)[0]
    if plot_available() and result.n >= 2:
        plot_permeability(result, base + "_plot.png", title=args.title, units="kPa")
        print(f"  plot written : {base}_plot.png")
    else:
        print("  (matplotlib not installed — no plot)")
    if xlsx_available() and result.n >= 1:
        export_permeability_xlsx(result, base + ".xlsx", title=args.title, units="kPa")
        print(f"  excel written: {base}.xlsx")
    else:
        print("  (openpyxl not installed — no xlsx)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
