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

  CASE B — the coupling scales with something that tracks the setpoint. It does
  NOT average away: each point is pulled by a different amount, the SLOPE tilts,
  and k is biased in one fixed direction while R² stays ~0.99999 — the Darcy
  criterion never flags it. A bias the goodness-of-fit cannot see is worse than
  noise it can.

THE SIGN OF THE SLOPE IDENTIFIES THE MECHANISM, and the two predict opposite
things (Datos, 2026-08-07). The valve command and the signal line's electrical
duty move in OPPOSITE directions: commands of 4.2 / 11.1 / 25.0 % at 20/40/60 kPa
are pulses of 1731 / 1685 / 1592 us, so the duty goes 8.66 -> 8.42 -> 7.96 % as
the pressure rises.

  offset RISES with the command  -> tracks the servo's holding CURRENT -> k biased
                                    about -0.72 %. This is the one that matters.
  offset FALLS with the command  -> tracks the signal's electrical duty. The range
                                    is so narrow that k moves about +0.07 %:
                                    negligible even if it is the real mechanism.

That is also why a dry null is weak rather than merely cautious: at atmosphere
the servo works against nothing, so its holding current is the minimum possible.
The dangerous mechanism is barely exercised, and a clean result here mostly rules
out the harmless one.

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
import csv
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
        rows.append((c, m, us, deg, max(ps) - min(ps), st.pstdev(ps), len(ps)))
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

    quiet = [r[1] for r in rows]
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
    signo = ("SUBE con el comando -> sigue la CORRIENTE de sostenimiento"
             if slope > 0 else
             "BAJA con el comando -> sigue el DUTY ELECTRICO de la señal")
    print(f"  pendiente        : {slope:+.5f} kPa por % de comando")
    print(f"  lectura del signo: el offset {signo}")
    print(f"  corrimiento total: {spread:.4f} kPa entre {min(xs):.0f} % y {max(xs):.0f} %")
    print(f"  error de la media: {sem:.4f} kPa por punto (referencia)")
    print()
    if moving:
        print(f"  moviendo vs quieto: {m_mov - st.fmean(quiet):+.4f} kPa de diferencia "
              f"en la media, ruido {p_mov:.3f} vs {max(quiet) - min(quiet):.3f} p-p")
    print()
    if spread < 4 * sem:
        print("  >>> EN SECO NO SE VE — el cero no se mueve con el comando.")
        print()
        print("      ESTE 'NO' ES DEBIL, y por una razon precisa: a atmosfera el")
        print("      servo no hace fuerza contra nada, asi que su corriente de")
        print("      sostenimiento es la MINIMA posible. El mecanismo peligroso es")
        print("      justamente ese, de modo que en seco casi no se ejercita.")
        print("      Un nulo aqui descarta sobre todo el mecanismo que de todas")
        print("      formas era inofensivo. REPETIR CON PRESION tras el gate 8.3.")
    elif slope > 0:
        print("  >>> SIGUE A LA CORRIENTE — el offset SUBE con el comando.")
        print("      Este es el caso que importa: sesga k en una direccion fija")
        print("      (~ -0.7 %% segun Datos) y R^2 no lo puede ver.")
        print("      Antes del primer k publicable: separa el retorno del servo")
        print("      y apantalla el cable de señal del transductor.")
    else:
        print("  >>> SIGUE AL DUTY ELECTRICO — el offset BAJA con el comando.")
        print("      El duty de la linea de señal va de 8.66 %% a 7.96 %% al subir")
        print("      la presion, o sea AL REVES que el comando. Rango tan estrecho")
        print("      que el sesgo en k es ~ +0.07 %%: despreciable.")
        print("      No hace falta mitigar nada por esto.")
    # Written to disk rather than left on screen. Datos needs the five RAW
    # points, not the fitted slope: only the points can separate a non-linear
    # coupling from a linear one, and only they can show a mixed mechanism
    # (current and signal duty acting at once, with opposite signs) that a global
    # fit would average into nothing. Transcribing five rows of four decimals by
    # hand at the bench is precisely where that detail gets lost.
    outdir = ROOT / "runs"
    outdir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = outdir / f"crosstalk_{stamp}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["phase", "command_pct", "pulse_us", "dial_deg",
                    "mean_kpa", "p2p_kpa", "sd_kpa", "n"])
        for c, m, us, deg, p2p, sd, nn in rows:
            w.writerow(["held", c, f"{us:.0f}", f"{deg:.1f}",
                        f"{m:.5f}", f"{p2p:.4f}", f"{sd:.5f}", nn])
        if moving:
            w.writerow(["moving", "", "", "", f"{m_mov:.5f}", f"{p_mov:.4f}",
                        f"{st.pstdev(moving):.5f}", len(moving)])
    print()
    print(f"  CSV con los cinco puntos crudos: {path.relative_to(ROOT)}")
    print("  Mándale ESE archivo a Datos, no la pendiente sola — solo los puntos")
    print("  distinguen un acoplamiento no lineal, y solo ellos delatan un")
    print("  mecanismo mixto que el ajuste global promediaria hasta desaparecer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
