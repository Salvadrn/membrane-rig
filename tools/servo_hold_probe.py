#!/usr/bin/env python3
"""Hold the servo and watch the 5 V rail through the pressure sensor.

    ./.venv/bin/python tools/servo_hold_probe.py --deg 46 --hold 25

Answers one question that a person watching the valve cannot answer reliably:
when the servo misbehaves during a long hold, is it FIGHTING A STOP or is it
BROWNING OUT?

The trick is that the pressure transducer is ratiometric — its output is a fixed
fraction of its supply, so its zero moves when the rail moves. With no pressure
applied it is therefore a voltmeter pointed at the 5 V rail, already wired,
already calibrated, and sampled at 20 Hz. If holding the servo drags the rail
down, the "pressure" reading walks and its noise floor opens up, even though
nothing pneumatic happened at all.

Three phases, so the hold is compared against its own before and after rather
than against a remembered number:

    idle (released) -> HOLD at --deg -> idle (released)

Read it like this:
  * noise and mean unchanged through all three  -> the rail is steady. Whatever
    the servo is doing, it is not a supply problem. Suspect the mechanical stop:
    re-run at an angle away from the seat and compare.
  * noise opens up / mean walks during the hold  -> the rail is sagging under
    holding current. No angle fixes that; the servo's supply does.
  * mean shifts and STAYS shifted after release  -> not the rail: something
    actually moved pneumatically, or the sensor drifted. Different problem.

CAVEAT, stated because it decides how much the result is worth: this only sees
the rail the TRANSDUCER is on. If the servo runs from its own UBEC and shares
only ground with the sensor, a servo brownout may not show here at all — a quiet
trace is then weak evidence, while a noisy one is still strong evidence. Check
which supply feeds the transducer before trusting a null result.

SAFETY
  * Shut the air at the panel. This moves the valve with no pressure control.
  * Releases the servo at the end, and on Ctrl+C.
  * If the servo buzzes audibly, stop and cut its power — this tool will keep
    commanding for as long as you asked.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402

US_PER_DEG = 2000.0 / 270.0
US_AT_ZERO = 500.0
HIS_OFFSET = 90.0


def sample(sensor, seconds: float, hz: float = 20.0):
    out = []
    period = 1.0 / hz
    nxt = t0 = time.time()
    while time.time() - t0 < seconds:
        r = sensor.read()
        out.append((r.raw, r.pressure_kpa))
        nxt += period
        time.sleep(max(0.0, nxt - time.time()))
    return out


def report(name: str, rows) -> tuple[float, float]:
    vs = [r[0] for r in rows]
    ps = [r[1] for r in rows]
    v_mean, v_p2p = statistics.fmean(vs), max(vs) - min(vs)
    print(f"  {name:<22} V {v_mean:.4f}  p2p {v_p2p:.4f}   "
          f"P {statistics.fmean(ps):+7.2f} kPa  p2p {max(ps) - min(ps):.3f}")
    return v_mean, v_p2p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deg", type=float, default=46.0,
                    help="angulo en el marco del SERVO (46 = tus 136, medio recorrido)")
    ap.add_argument("--hold", type=float, default=25.0)
    ap.add_argument("--idle", type=float, default=6.0, help="segundos de reposo antes y despues")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    cfg = Config.load(args.config)
    us = int(round(US_AT_ZERO + args.deg * US_PER_DEG))
    lo, hi = sorted((int(cfg.valve.servo_min_us), int(cfg.valve.servo_max_us)))
    if not lo <= us <= hi:
        print(f"  {us} us esta fuera del recorrido calibrado ({lo}-{hi}). No lo hago.")
        return 2

    from src.hal.ads1115_sensor import Ads1115Sensor  # noqa: E402
    import pigpio  # noqa: E402

    sensor = Ads1115Sensor(cfg)
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpiod no responde — arrancalo con: sudo pigpiod")
        return 1
    pin = cfg.valve.servo_pin

    print(f"\n  sosteniendo {args.deg:.0f} deg del servo = tus "
          f"{args.deg + HIS_OFFSET:.0f} deg = {us} us   (GPIO{pin})")
    print(f"  el transductor mira el riel de 5 V: si se hunde, su cero se mueve\n")

    try:
        pi.set_servo_pulsewidth(pin, 0)
        a = sample(sensor, args.idle)
        va, pa = report("reposo (antes)", a)

        pi.set_servo_pulsewidth(pin, us)
        b = sample(sensor, args.hold)
        vb, pb = report(f"SOSTENIENDO {args.hold:.0f}s", b)

        pi.set_servo_pulsewidth(pin, 0)
        c = sample(sensor, args.idle)
        vc, pc = report("reposo (despues)", c)
    finally:
        pi.set_servo_pulsewidth(pin, 0)
        pi.stop()

    print()
    d_mean = (vb - va) * 1000.0
    ratio = pb / pa if pa > 1e-9 else float("inf")
    print(f"  corrimiento del cero durante el sostenimiento : {d_mean:+.1f} mV")
    print(f"  ruido durante / ruido en reposo               : {ratio:.1f}x")
    print()
    # Thresholds are deliberately loose: this separates "obviously sagging" from
    # "obviously steady" and refuses to adjudicate the middle, because a marginal
    # call here would send someone to buy a UBEC they may not need.
    if ratio > 3.0 or abs(d_mean) > 10.0:
        print("  >>> EL RIEL SE MUEVE bajo la corriente de sostenimiento.")
        print("      Ningun angulo arregla esto: es la alimentacion del servo.")
    elif ratio < 1.8 and abs(d_mean) < 4.0:
        print("  >>> EL RIEL ESTA FIRME. El sostenimiento no lo esta cargando.")
        print("      Si aun asi el servo se agita, sospecha del tope mecanico:")
        print("      repite este mismo comando cerca del cierre y compara.")
    else:
        print("  >>> RESULTADO INTERMEDIO — no alcanza para decidir.")
        print("      Repitelo con --hold mas largo, y mide el voltaje en el servo")
        print("      con el multimetro MIENTRAS sostiene. Debe mantenerse >= 5 V.")
    print()
    print("  OJO: esto solo ve el riel del TRANSDUCTOR. Si el servo cuelga de su")
    print("  propio UBEC y solo comparten tierra, un hundimiento del servo puede")
    print("  no aparecer aqui — una traza limpia es evidencia debil, una sucia no.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
