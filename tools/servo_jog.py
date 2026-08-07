#!/usr/bin/env python3
"""Move the servo to an ABSOLUTE angle and hold it — find the endpoints by eye.

    ./.venv/bin/python tools/servo_jog.py 135        # go to 135 deg, hold 6 s
    ./.venv/bin/python tools/servo_jog.py 135 --hold 20

Exists because calibrating servo_min_us / servo_max_us by editing config.yaml and
re-running a sweep is a slow guessing loop: the operator can see where the valve
handle actually is, and the software cannot. This inverts it — the operator names
an angle, the servo goes there, and the two angles that turn out to be CLOSED and
OPEN are read straight off the valve.

Angles are in the servo's own frame, with 0 deg at 500 us, using the DS3218's
270 deg / 500-2500 us spec: 7.41 us per degree. So the number you pass is the
number to hand back for the config, and no arithmetic happens in anyone's head.

It does NOT touch config.yaml. Nothing here is persistent — it drives the servo
and releases. Set the endpoints deliberately once they are known.

SAFETY
  * Shut the air at the panel first. This moves the valve with no pressure
    control and no setpoint; it is a positioning aid, not a controlled run.
  * If the servo buzzes without moving it is stalled against a stop — CUT ITS
    POWER. A stalled servo overheats in seconds and this tool holds position
    for as long as you asked.
  * The tool refuses angles outside the CALIBRATED travel in config.yaml. That
    is the valve's limit, not the servo's 0-270. Use --beyond only when you are
    deliberately recalibrating, and watch it while it moves.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402

US_PER_DEG = 2000.0 / 270.0      # DS3218: 270 deg spans 500-2500 us
US_AT_ZERO = 500.0
HIS_OFFSET = 90.0                # the servo's 0 deg reads as 90 on the valve dial


def us_for(deg: float) -> int:
    return int(round(US_AT_ZERO + deg * US_PER_DEG))


def deg_for(us: float) -> float:
    return (us - US_AT_ZERO) / US_PER_DEG


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("angle", type=float, help="angulo absoluto en grados")
    ap.add_argument("--dial", action="store_true",
                    help="el angulo va en TU marco (el que lees en la manija), no en el del servo")
    ap.add_argument("--hold", type=float, default=6.0, help="segundos a sostener")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--beyond", action="store_true",
                    help="permitir salir del recorrido calibrado (solo para recalibrar)")
    args = ap.parse_args()

    # --dial lets the operator type the number painted on the valve instead of
    # the servo's own. Mixing the two frames has caused three wrong calibrations
    # on this rig, every one of them because a human did the +90 in their head
    # and one of us used the other frame. The tool does the arithmetic now.
    deg = args.angle - HIS_OFFSET if args.dial else args.angle
    if not 0.0 <= deg <= 270.0:
        lo_d, hi_d = (HIS_OFFSET, 270.0 + HIS_OFFSET) if args.dial else (0.0, 270.0)
        print(f"angulo fuera del rango del servo: {args.angle} "
              f"(permitido {lo_d:.0f}-{hi_d:.0f} en este marco)")
        return 2

    cfg = Config.load(args.config)
    us = us_for(deg)

    # Refuse to leave the calibrated travel unless the operator says so out loud.
    # This tool is how the endpoints were FOUND, so it cannot simply clamp — but
    # it is also the easiest way to drive the stem past its seat by fat-fingering
    # an angle, and the standing instruction is that the servo never leaves the
    # band. So: inside the band is free, outside needs --beyond and prints why.
    lo, hi = sorted((int(cfg.valve.servo_min_us), int(cfg.valve.servo_max_us)))
    if not lo <= us <= hi and not args.beyond:
        print(f"  {args.angle:.0f} grados = {us} us — FUERA del recorrido calibrado "
              f"({lo}-{hi} us = tus {deg_for(lo) + HIS_OFFSET:.0f}-{deg_for(hi) + HIS_OFFSET:.0f} grados).")
        print("  Ahi el vastago topa contra el asiento o el servo contra su tope, y")
        print("  un servo calado se calienta en segundos. Para recalibrar a proposito:")
        print(f"      --beyond   (y vigilalo: si zumba sin moverse, CORTA LA CORRIENTE)")
        return 2

    import pigpio  # noqa: E402
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpiod no responde — arrancalo con: sudo pigpiod")
        return 1

    pin = cfg.valve.servo_pin
    marco = "tuyos (manija)" if args.dial else "del servo"
    print(f"  {args.angle:.0f} grados {marco}  =  {deg + HIS_OFFSET:.0f} en tu marco "
          f"/ {deg:.0f} en el del servo  =  {us} us   (GPIO{pin})")
    print(f"  sosteniendo {args.hold:.0f} s — MIRA la manija de la valvula")
    try:
        pi.set_servo_pulsewidth(pin, us)
        time.sleep(args.hold)
    finally:
        # Release rather than hold: a servo left commanded is a servo that can
        # cook if it is pressed against a stop and nobody is watching.
        pi.set_servo_pulsewidth(pin, 0)
        pi.stop()
        print("  liberado (sin pulsos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
