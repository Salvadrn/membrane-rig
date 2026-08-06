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
  * Do not exceed the travel you have already confirmed by eye. The tool clamps
    to 0-270 deg, which is the SERVO's limit, not your valve's.
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


def us_for(deg: float) -> int:
    return int(round(US_AT_ZERO + deg * US_PER_DEG))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("angle", type=float, help="angulo absoluto en grados (0-270)")
    ap.add_argument("--hold", type=float, default=6.0, help="segundos a sostener")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    if not 0.0 <= args.angle <= 270.0:
        print(f"angulo fuera del rango del servo (0-270): {args.angle}")
        return 2

    cfg = Config.load(args.config)
    us = us_for(args.angle)

    import pigpio  # noqa: E402
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpiod no responde — arrancalo con: sudo pigpiod")
        return 1

    pin = cfg.valve.servo_pin
    print(f"  {args.angle:.0f} grados  =  {us} us   (GPIO{pin})")
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
