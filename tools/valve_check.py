#!/usr/bin/env python3
"""Prove the valve's two safety properties on the bench: DIRECTION and HOLD.

    ./.venv/bin/python tools/valve_check.py              # the check (moves the valve)
    ./.venv/bin/python tools/valve_check.py --readback   # read-only, moves nothing

Two claims this rig depends on had never been tested against hardware, and one
of them turned out to be false:

  DIRECTION — command 0 % is the state the rig drives to on startup, on every
  abort, and on sensor fault. If `valve.invert` is set wrong, that state is
  fully OPEN and every safety layer in the software is pointed backwards. No
  amount of code review catches this; only a person looking at the handle does.

  HOLD — `close()` used to release the servo, on the documented assumption that
  friction would hold the stem. On this rig it does not: released, the servo
  drifts off the commanded angle (Adrián, 2026-08-06). `close()` now keeps
  driving the shut position, and `--readback` proves that from a SEPARATE
  process, which is the only way to show the hold survives the app exiting.

`--readback` is the objective half. Both drivers keep driving after the process
that commanded them exits — pigpio because the DAEMON generates the train, the
kernel PWM because the SILICON does — so a fresh process can ask what is still
being emitted. A number out of a process that never wrote anything is evidence;
"it looked like it stayed" is not.

Angles are printed in ADRIÁN'S frame (his 90 deg = the servo's 0 deg), because
that is the frame the valve handle is read in and mixing the two has already
cost this rig three wrong calibrations.

SAFETY
  * SHUT THE AIR AT THE PANEL FIRST. This moves the valve with no pressure
    control and no setpoint. It is a bench check, not a run.
  * If the servo buzzes without moving it is stalled against a stop — CUT ITS
    POWER. The endpoints are wrong, and a stalled servo overheats in seconds.
  * This check leaves the valve SHUT AND POWERED, which is the point. The panel
    valve closed by hand is still the only failsafe: the mechanical relief is in
    hand but NOT FITTED.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402

US_PER_DEG = 2000.0 / 270.0   # DS3218: 270 deg spans 500-2500 us
US_AT_ZERO = 500.0
HIS_OFFSET = 90.0             # servo 0 deg reads as 90 deg on Adrián's dial


def his_angle(us: float) -> float:
    return (us - US_AT_ZERO) / US_PER_DEG + HIS_OFFSET


def ends(v) -> tuple[int, int]:
    """(pulse at 0 % = SAFE, pulse at 100 %) after applying `invert`."""
    lo, hi = int(v.servo_min_us), int(v.servo_max_us)
    return (hi, lo) if v.invert else (lo, hi)


def _emitted_us(cfg) -> float:
    """What is being emitted RIGHT NOW, asked of whichever generator is in use.

    Both drivers keep driving after the commanding process exits — that is the
    property this whole check exists to prove — but they are asked differently:
    pigpio answers over its daemon socket, the kernel PWM answers from sysfs.
    """
    if cfg.valve.type == "servo_kpwm":
        from pathlib import Path as _P
        for chip in sorted(_P("/sys/class/pwm").glob("pwmchip*")):
            ch = chip / "pwm0"
            if not ch.exists():
                continue
            if (ch / "enable").read_text().strip() != "1":
                return 0.0
            return int((ch / "duty_cycle").read_text().strip()) / 1000.0
        raise RuntimeError("no hay canal PWM exportado — corre el chequeo primero")

    import pigpio  # noqa: E402
    pi = pigpio.pi()
    if not pi.connected:
        raise RuntimeError("pigpiod no responde — arrancalo con: sudo pigpiod")
    try:
        return float(pi.get_servo_pulsewidth(cfg.valve.servo_pin))
    finally:
        pi.stop()


def readback(cfg) -> int:
    try:
        us = _emitted_us(cfg)
    except Exception as e:
        print(f"  {e}")
        return 1

    safe_us, open_us = ends(cfg.valve)
    if not us:
        print("\n  NO se estan emitiendo pulsos (0 us) — el servo esta SUELTO.")
        print("  >>> NO se esta sosteniendo la posicion.")
        return 1
    print(f"\n  se esta emitiendo AHORA : {us:.0f} us   (tus {his_angle(us):.0f} grados)"
          f"   [{cfg.valve.type}]")
    if abs(us - safe_us) <= 2:
        print(f"  >>> SOSTENIENDO el cierre ({safe_us} us). Correcto.")
        return 0
    print(f"  >>> esta en {us} us, pero el cierre es {safe_us} us"
          f" (tus {his_angle(safe_us):.0f} grados). Revisa.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readback", action="store_true",
                    help="solo leer que pulso emite pigpiod; no mueve nada")
    ap.add_argument("--dwell", type=float, default=8.0,
                    help="segundos en cada posicion para que la mires")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()

    cfg = Config.load(args.config)
    if args.readback:
        return readback(cfg)

    if cfg.valve.type not in ("servo", "servo_kpwm"):
        print(f"valve.type es '{cfg.valve.type}' — esta prueba es para el servo.")
        return 2

    v = cfg.valve
    safe_us, open_us = ends(v)
    print()
    print(f"  invert            : {v.invert}")
    print(f"  0 %  = SEGURO/CERRADO -> {safe_us} us  = tus {his_angle(safe_us):.0f} grados")
    print(f"  100 % = ABIERTO        -> {open_us} us  = tus {his_angle(open_us):.0f} grados")
    print(f"  cierre al terminar     -> "
          f"{int(v.servo_close_us) if v.servo_close_us else safe_us} us")
    print()
    print("  CIERRA EL AIRE EN EL PANEL. Esto mueve la valvula sin control de presion.")
    for s in range(5, 0, -1):
        print(f"    empezando en {s}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")

    # Built through the same branch build_hal uses, so this checks the driver the
    # RIG will actually construct — not a stand-in that happens to move the same
    # servo. The two differ in exactly the thing this check is about.
    if cfg.valve.type == "servo_kpwm":
        from src.hal.servo_kpwm_valve import ServoKernelPwmValve as _Valve  # noqa: E402
    else:
        from src.hal.servo_valve import ServoValve as _Valve  # noqa: E402

    # __init__ calls to_safe(), so building the driver IS test 1: whatever the
    # rig does the instant it starts is what it will do on every abort.
    print(f"\n  [1/3] arrancando el driver ({cfg.valve.type}) -> 0 % (SEGURO)")
    valve = _Valve(cfg)
    print(f"        MIRA LA MANIJA. Debe quedar CERRADA (tus {his_angle(safe_us):.0f} grados).")
    time.sleep(args.dwell)

    print(f"\n  [2/3] 100 % -> ABIERTO (tus {his_angle(open_us):.0f} grados)")
    valve.set_command(100.0)
    print("        la manija debe girar al otro extremo.")
    time.sleep(args.dwell)

    print(f"\n  [3/3] close() -> sella y SOSTIENE (ya no se suelta)")
    valve.close()
    print("        la manija debe volver a CERRADA y QUEDARSE ahi.")

    print()
    print("  Ahora comprueba que el sostenimiento sobrevive a que el programa muera:")
    print("      ./.venv/bin/python tools/valve_check.py --readback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
