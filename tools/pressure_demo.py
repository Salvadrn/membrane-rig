#!/usr/bin/env python3
"""Log pressure vs time on the real rig and plot it — the hardware bring-up demo.

    ./.venv/bin/python tools/pressure_demo.py            # 60 s
    ./.venv/bin/python tools/pressure_demo.py --seconds 30

Runs the FULL software path — Config, build_hal, the real Ads1115Sensor — so a
trace out of this is evidence about the shipped code, not about a side script
that happens to read the same chip. Writes a CSV and a PNG into runs/.

Point of the exercise: apply pressure by hand partway through (squeeze the line,
blow into the port) and the trace shows the rig responding. That converts "the
sensing chain reads a stable number" into "the sensing chain measures", which
are different claims and only the second one is worth putting in a talk.

Reports mean and peak-to-peak of the quiet section too, because a bring-up trace
that does not state its own noise floor cannot support any later claim about
resolution.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config          # noqa: E402
from src.hal import build_hal          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    cfg = Config.load(args.config)
    if cfg.mode != "hardware":
        print(f"mode is '{cfg.mode}' — this tool is for the real rig. "
              f"Set mode: hardware in config.yaml.")
        return 2

    sensor, valve, diverter, temp, _ = build_hal(cfg)
    print(f"ratio configurado : {cfg.sensor.divider_ratio}")
    print(f"valvula           : {cfg.valve.type}")
    print(f"temperatura       : {temp.read_c():.1f} C  ({temp.source})")
    print()
    print(f"Grabando {args.seconds:.0f} s a {args.hz:.0f} Hz.")
    print("APLICA PRESION a la mitad (aprieta la linea o sopla el puerto).")
    print()

    outdir = ROOT / "runs"
    outdir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    csv_path = outdir / f"pressure_demo_{stamp}.csv"

    rows = []
    t0 = time.time()
    period = 1.0 / args.hz
    nxt = t0
    while (t := time.time()) - t0 < args.seconds:
        r = sensor.read()
        rows.append((t - t0, r.raw, r.pressure_kpa, int(r.healthy)))
        if len(rows) % int(args.hz) == 0:
            print(f"  {t - t0:5.1f} s   {r.raw:7.4f} V   {r.pressure_kpa:8.2f} kPa"
                  f"   {'ok' if r.healthy else 'FALLA'}")
        nxt += period
        time.sleep(max(0.0, nxt - time.time()))

    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "v_sensor", "pressure_kpa", "healthy"])
        w.writerows(rows)

    ts = [r[0] for r in rows]
    ps = [r[2] for r in rows]

    # Noise floor from the first 20 % — assumed quiet, since the instruction is
    # to apply pressure partway through. Stated as an assumption because if the
    # operator squeezed early it is not a noise floor, it is a signal.
    quiet = ps[: max(2, len(ps) // 5)]
    mean = sum(quiet) / len(quiet)
    p2p = max(quiet) - min(quiet)

    print()
    print(f"  reposo (primer 20 %) : {mean:8.3f} kPa")
    print(f"  ruido pico a pico    : {p2p:8.3f} kPa")
    print(f"  maximo alcanzado     : {max(ps):8.3f} kPa")
    print(f"  excursion            : {max(ps) - mean:8.3f} kPa sobre el reposo")
    print()
    print(f"  CSV: {csv_path.relative_to(ROOT)}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(ts, ps, lw=1.2, color="#1f5e8b")
        ax.axhline(mean, ls="--", lw=1, color="#9e9e9e",
                   label=f"reposo {mean:.2f} kPa (±{p2p / 2:.3f})")
        ax.set_xlabel("tiempo (s)")
        ax.set_ylabel("presión (kPa)")
        ax.set_title(f"Rig de membranas — presión medida en hardware · {stamp}")
        ax.grid(alpha=.3)
        ax.legend(loc="upper left", fontsize=9)
        fig.tight_layout()
        png = outdir / f"pressure_demo_{stamp}.png"
        fig.savefig(png, dpi=150)
        print(f"  PNG: {png.relative_to(ROOT)}")
    except Exception as e:  # matplotlib missing or headless trouble
        print(f"  (sin gráfica: {e})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
