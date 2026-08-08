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
from typing import Optional

from ..app import RigController
from ..config import Config


def _print_held(st: dict, u: str) -> None:
    """Announce a run parked at its ceiling, and say what to do about it."""
    a = st.get("held_alarm") or {}
    print("\n\n" + "=" * 68)
    print("  RIG HELD AT THE CEILING — the feed is shut and it is waiting for you")
    print("=" * 68)
    if a:
        print(f"  reached {a.get('pressure_reached')} {u} · ceiling {a.get('ceiling')} {u} "
              f"({a.get('ceiling_source')}) · setpoint {a.get('setpoint')} {u}")
        print(f"  hit {a.get('retry_n')} of max {a.get('retry_max')} · layer: {a.get('layer')}")
    # Same rule as the web page: the machine flag decides, never the prose, and
    # anything unexpected is treated as the dangerous case.
    print("\n  " + (a.get("recommendation")
                    or "No detail came through. Treat this as the unsafe case and "
                       "check the rig before doing anything."))
    print()


def _resolve_held(ctl, st: dict, u: str) -> None:
    """Ask the operator what to do. Only offered on a real terminal."""
    a = st.get("held_alarm") or {}
    known = a.get("severity") == "overshoot"
    retry_ok = known and a.get("retry_advised") is True
    # Retry can be off for two very different reasons, and telling the operator
    # the wrong one is costly: "go and check the rig" for a cell that is simply
    # still bleeding down wastes a trip, and blurs the warning that matters.
    waiting = known and a.get("retry_advised") is False
    raise_ok = bool(a) and (a.get("raise_max") or 0) > (a.get("ceiling") or 0)
    opts = []
    if retry_ok:
        opts.append("[r] retry this point")
    elif waiting:
        why = a.get("retry_blocked_reason") or "the pressure is still at or above the ceiling"
        print(f"  Retry is not available yet — {why}.")
        print("  It becomes available on its own once the pressure falls; re-run this "
              "command, or use the web page, to pick it up then.")
    else:
        print("  Retry is NOT advised here — retrying would repeat the excursion.")
    if raise_ok:
        opts.append(f"[a] raise the ceiling (up to {a.get('raise_max')} {u})")
    opts.append("[s] stop the run")
    print("  " + "   ".join(opts))
    while True:
        try:
            choice = input("  choice> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Leaving the rig held; it is safe and waiting.")
            return
        if choice == "s":
            res = ctl.recover_stop()
        elif choice == "r" and retry_ok:
            res = ctl.recover_retry()
        elif choice == "a" and raise_ok:
            try:
                v = float(input(f"  new ceiling in {u}> ").strip())
            except (ValueError, EOFError):
                print("  Not a number.")
                continue
            res = ctl.recover_raise(v)
        else:
            print("  Pick one of the options shown.")
            continue
        if res.get("ok"):
            print(f"  → {res.get('action')}\n")
            return
        print(f"  ! {res.get('error')}")


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
    was_held = False
    weighed_here = {"v": False}     # edge-trigger: ask once per pause, not per tick
    try:
        while True:
            st = ctl.get_status()
            if st["fault"]:
                print(f"\n!! FAULT: {st['fault']}")
            # A held run keeps `running` true and `finished` false, so without
            # this the loop would print a normal-looking status line for ever
            # while the rig sat waiting for a decision nobody knew it wanted.
            # Over SSH this line is the whole instrument.
            if st.get("held") and not was_held:
                was_held = True
                _print_held(st, u)
                if sys.stdin.isatty():
                    _resolve_held(ctl, st, u)
                else:
                    # No terminal to ask (systemd): say so and keep waiting. The
                    # feed is shut, so waiting is safe — and deciding at a safety
                    # boundary with nobody watching is exactly what the rig is
                    # built not to do.
                    print("   No terminal attached — the rig will wait. Resolve it from "
                          "the web UI, or re-run this from a shell.\n")
            elif not st.get("held"):
                was_held = False
            phase = "HELD" if st.get("held") else st["phase"]
            line = (
                f"[{phase:<11}] {st['index']+ (0 if st['phase']=='done' else 1)}/{st['total']} "
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
            # Parked between points with the feed sealed, waiting to be weighed.
            # Asking here rather than at the end is the whole point: the beaker
            # has to come off a rig that is not still filling it, and the next
            # point's stabilise clock only starts on resume, so taking a while at
            # the balance costs nothing.
            if st.get("awaiting_operator") and not weighed_here["v"]:
                weighed_here["v"] = True
                print()
                _weigh_and_resume(ctl, st)
            elif not st.get("awaiting_operator"):
                weighed_here["v"] = False
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
        # Only points still without a weight — the pauses have normally caught
        # them already, so this is the tail case (a skipped prompt, or a run that
        # did not pause), not the main path.
        needs_vol = cfg.mode == "hardware" and any(
            r["success"] and r.get("flow_m3s", 0) <= 0 for r in results)
        if needs_vol and sys.stdin.isatty():
            _prompt_masses(ctl, results, u)

        # Auto Q-vs-ΔP fit + Darcy k + pore size (+ PNG plot).
        _print_analysis(ctl.compute_and_save_analysis())
        ctl.shutdown()
    return 0


# A balance reading, not a meniscus. Weighing takes the manual error from ~0.4 %
# to ~0.01 %, and the controller keeps the grams as the primary datum — the
# millilitres are derived from them with the density at the recorded temperature,
# so a better density later can recompute the volume from what was actually
# measured.
MIN_G, MAX_G = 0.05, 3000.0


def _ask_mass_g(label: str) -> Optional[float]:
    """One weight, in grams, with the unit spelled out and absurd values refused.

    Both halves earn their keep. There are now TWO units in play (g and mL), and
    a number typed in the wrong one is invisible downstream — it just makes k
    wrong, and R² does not notice. The range catches the obvious slip; naming the
    unit on every line is what stops the slip at eleven at night after six hours
    at the bench.
    """
    while True:
        try:
            raw = input(f"  {label} — weight in GRAMS (g): ").strip()
        except EOFError:
            print("  (skipped)")
            return None
        if not raw:
            print("  (skipped)")
            return None
        try:
            g = float(raw.replace(",", "."))
        except ValueError:
            print(f"  Not a number. Type the grams, e.g. 98.76  (or Enter to skip)")
            continue
        if not (MIN_G <= g <= MAX_G):
            print(f"  {g:g} g is outside {MIN_G:g}–{MAX_G:g} g. This asks for GRAMS,"
                  f" not millilitres — retype it, or Enter to skip.")
            continue
        return g


def _weigh_and_resume(ctl, st: dict) -> None:
    """The pause between points: weigh this one, then let the rig carry on.

    Without a terminal there is nobody to ask, so it does NOT resume by itself —
    the rig stays parked with the feed sealed, which is the safe state, and says
    where to finish the job. Guessing a weight, or continuing without one, would
    put a made-up number into k.
    """
    pt = st.get("awaiting_point")
    label = f"point {pt}" if pt else "this point"
    print("=" * 64)
    print(f"  COLLECTED — weigh {label}. The feed is shut and the rig is waiting.")
    print("=" * 64)
    if not sys.stdin.isatty():
        print("  No terminal attached, so nothing is being asked here and the rig")
        print("  will stay parked. Enter the weight from the web page, or re-run")
        print("  this from a shell.\n")
        return
    g = _ask_mass_g(label)
    if g is None:
        print("  No weight recorded for this point. Resuming anyway — you can still")
        print("  enter it afterwards, but the point has no flow until you do.")
    else:
        idx = (pt - 1) if pt else 0          # status is 1-based, results are 0-based
        try:
            ctl.set_volumes(volumes_g={idx: g})
            print(f"  Recorded {g:g} g for {label}.")
        except Exception as exc:
            print(f"  Could not record it: {exc}")
    print("  Empty the beaker and put it back before continuing.")
    try:
        input("  Press Enter to run the next point... ")
    except EOFError:
        pass
    res = ctl.resume_next_point()
    print("  Resuming.\n" if res.get("ok") else f"  Could not resume: {res.get('error')}\n")


def _prompt_masses(ctl, results, u) -> None:
    """Fallback for a run that finished without pausing between points."""
    print("\nWeigh what each point collected. Grams, from the balance:")
    masses = {}
    for i, r in enumerate(results):
        if not r["success"]:
            continue
        g = _ask_mass_g(f"point {i + 1} — setpoint {r['setpoint_kpa']:.1f} kPa, "
                        f"t={r['collection_s']:.0f}s")
        if g is not None:
            masses[i] = g
    if masses:
        ctl.set_volumes(volumes_g=masses)


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
