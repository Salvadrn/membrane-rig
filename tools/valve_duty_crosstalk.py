#!/usr/bin/env python3
"""Does the pressure zero move with the valve command? Random noise vs a bias.

    sudo ./.venv/bin/python tools/valve_duty_crosstalk.py
    sudo ./.venv/bin/python tools/valve_duty_crosstalk.py --commands 0,5,15,25,50

Connecting the servo raised the pressure noise floor from ±0.04 to ~0.35 kPa p-p
(measured 2026-08-06/07). Whether that matters depends entirely on a question a
noise measurement cannot answer, and Datos framed it exactly right:

  CASE A — the coupling is random. It averages away. A fit uses `mean_kpa` over
  ~1200 samples, so the error of the mean is ~0.0025 kPa and the effect on k is
  nil. Nothing to do.

  CASE B — the coupling scales with the valve command. It does NOT average away,
  because it is a pressure error that depends on the pressure: the valve works
  harder at higher setpoints, so each point is pulled by a different amount and
  the SLOPE tilts. That biases k in one fixed direction — and R² stays ~0.99999,
  so the Darcy criterion never flags it. A bias the goodness-of-fit cannot see is
  worse than noise it can.

The test that separates them: hold the pressure constant (atmosphere is fine —
nothing needs to be pressurised) and read the zero at several valve commands. If
the mean does not move, it is Case A. If the mean tracks the command, Case B.

Two phases, because a held position and a moving servo stress the supply in
different ways: a SUSTAINED duty is what Case B needs, while the transients of
starting and reversing are a separate mechanism a static sweep cannot see.

THE RESULT IS ASYMMETRIC and the tool says so rather than letting a clean run
read as an all-clear: a "yes" in dry conditions is definitive, a "no" is
provisional. At atmosphere the servo works against no pressure and draws less
than it will in a real run, so if the source is its current, the effect grows
with load. A dry null has to be repeated under pressure before the question is
closed.

This cannot be answered in simulation: MockPlant models sensor noise as
independent gaussian, so by construction it only ever produces Case A. Only the
bench can tell us.

SAFETY
  * Shut the air at the panel. This moves the valve through its range.
  * Every command goes through the real driver, so the clamp to the calibrated
    travel applies — the servo cannot be sent outside its endpoints.
  * Leaves the valve at 0 % (safe) and holding.
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402

US_PER_DEG = 2000.0 / 270.0
HIS_OFFSET = 90.0


def pulse_for(v, command: float) -> float:
    frac = command / 100.0
    if v.invert:
        frac = 1.0 - frac
    lo, hi = sorted((float(v.servo_min_us), float(v.servo_max_us)))
    return max(lo, min(hi, v.servo_min_us + frac * (v.servo_max_us - v.servo_min_us)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commands", default="0,5,15,25,50",
                    help="comandos de valvula en %%, separados por comas")
    ap.add_argument("--settle", type=float, default=3.0, help="s de asentamiento tras mover")
    ap.add_argument("--samples", type=int, default=300, help="lecturas por punto")
    ap.add_argument("--moving", type=float, default=20.0,
                    help="s de la fase con el servo moviendose (0 para saltarla)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    cfg = Config.load(args.config)
    if cfg.mode != "hardware":
        print(f"mode es '{cfg.mode}' — esta prueba es para el rig real.")
        return 2
    cmds = [float(c) for c in args.commands.split(",")]

    from src.hal import build_hal  # noqa: E402

    sensor, valve, diverter, temp, _ = build_hal(cfg)
    print()
    print("  CIERRA EL AIRE EN EL PANEL. Esto mueve la valvula por su recorrido.")
    print(f"  {args.samples} lecturas por punto, {args.settle:.0f} s de asentamiento.")
    print()
    print("   cmd     pulso    tu angulo      media kPa    p2p     sd")

    rows = []
    for c in cmds:
        valve.set_command(c)
        time.sleep(args.settle)
        ps = []
        for _ in range(args.samples):
            r = sensor.read()
            if r.healthy:
                ps.append(r.pressure_kpa)
        if len(ps) < args.samples // 2:
            print(f"  {c:5.0f} %   lecturas no sanas — sensor caido, abortando")
            valve.to_safe()
            return 1
        us = pulse_for(cfg.valve, c)
        deg = (us - 500.0) / US_PER_DEG + HIS_OFFSET
        m = st.fmean(ps)
        rows.append((c, m))
        print(f"  {c:5.0f} %  {us:7.0f}    {deg:5.0f}      {m:+9.4f}   "
              f"{max(ps) - min(ps):6.3f}  {st.pstdev(ps):6.4f}")

    # --- fase 2: el servo MOVIENDOSE, no sosteniendo -------------------------
    # Datos' point: a held position and a moving servo stress the rail in
    # different ways. A sustained duty is what Case B needs; the transients of
    # starting and reversing are a separate mechanism that a static sweep cannot
    # see at all. Sampled while the valve is driven back and forth.
    print()
    print("  fase 2 — el servo MOVIENDOSE entre 5 % y 25 %")
    moving = []
    t0 = time.time()
    flip = True
    while time.time() - t0 < args.moving:
        valve.set_command(25.0 if flip else 5.0)
        flip = not flip
        t1 = time.time()
        while time.time() - t1 < 1.5:
            r = sensor.read()
            if r.healthy:
                moving.append(r.pressure_kpa)
    valve.to_safe()

    quiet = [y for _, y in rows]
    if moving:
        m_mov, p_mov = st.fmean(moving), max(moving) - min(moving)
        print(f"  {'moviendo':>9}          {'':7}    {'':5}      {m_mov:+9.4f}   "
              f"{p_mov:6.3f}  {st.pstdev(moving):6.4f}")
    else:
        m_mov = p_mov = float("nan")

    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    n = len(xs)
    mx, my = st.fmean(xs), st.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
    spread = max(ys) - min(ys)

    # Reference: the standard deviation of a single point's MEAN. If the spread
    # across commands sits inside a few of these, the shift is not distinguishable
    # from the noise already averaged into each point.
    sem = st.pstdev(ps) / (len(ps) ** 0.5)

    print()
    print(f"  pendiente        : {slope:+.5f} kPa por % de comando")
    print(f"  corrimiento total: {spread:.4f} kPa entre {min(xs):.0f} % y {max(xs):.0f} %")
    print(f"  error de la media: {sem:.4f} kPa por punto (referencia)")
    print()
    if moving:
        print(f"  moviendo vs quieto: {m_mov - st.fmean(quiet):+.4f} kPa de diferencia "
              f"en la media, ruido {p_mov:.3f} vs {max(quiet) - min(quiet):.3f} p-p")
    print()
    if spread < 4 * sem:
        print("  >>> CASO A (en seco) — el cero NO se mueve con el comando.")
        print("      El ruido es aleatorio, se promedia, y no sesga k.")
        print()
        print("      PERO ESTE 'NO' ES PROVISIONAL. A atmosfera el servo no hace")
        print("      fuerza contra presion y consume menos que en una corrida real.")
        print("      Si la fuente es su corriente, crecera con la carga. Hay que")
        print("      repetirlo CON presion despues del gate 8.3 antes de cerrarlo.")
    else:
        print("  >>> CASO B — el cero SIGUE al comando.")
        print("      Es un sesgo que NO se promedia y que R^2 no puede ver.")
        print("      Esto SI es definitivo: en seco basta para confirmarlo.")
        print("      Antes del primer k publicable: apantalla el cable de señal")
        print("      del transductor y separa el retorno del servo.")
    print()
    print("  Pásale la pendiente, el corrimiento y la fila 'moviendo' a Datos:")
    print("  con eso calculan el sesgo en k para los setpoints reales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
