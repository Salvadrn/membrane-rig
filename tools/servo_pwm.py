#!/usr/bin/env python3
"""Drive the servo from the KERNEL's hardware PWM, bypassing pigpio entirely.

    sudo ./.venv/bin/python tools/servo_pwm.py 190 --dial
    sudo ./.venv/bin/python tools/servo_pwm.py --release

Why this exists: on this Pi (Trixie, pigpio built from source) the servo moves
badly on every pulse pigpio generates — uncoupled, unloaded, at any angle, with
either clock peripheral (-t 0 and -t 1 both). The one constant across a long
afternoon of wrong hypotheses is that the servo is still whenever the pin is
held low and misbehaves whenever pigpio drives it. pigpio times its waveform in
software via DMA; GPIO18 is a real hardware-PWM output, so the silicon can
generate the pulse train itself and there is nothing left to get the timing
wrong. The project's own notes named this as the correct port before any of
today's debugging started.

REQUIRES, once, in /boot/firmware/config.txt followed by a reboot:

    dtoverlay=pwm,pin=18,func=2

func=2 is ALT5, which is what routes PWM0 to GPIO18 on a Pi 4. Without the
overlay there is no pwmchip to write to and this tool says so rather than
failing obscurely.

Servo signalling, for the record: a 20 ms period (50 Hz) with the pulse width
carrying the position. Period and duty go to the kernel in NANOSECONDS, so a
1500 us pulse is a duty of 1_500_000 ns inside a period of 20_000_000 ns.

Angles are in Adrián's dial frame with --dial (the number read off the valve),
or the servo's own frame without it. The servo's zero reads as 90 on the dial.

SAFETY
  * Shut the air at the panel. This moves the valve with no pressure control.
  * The pulse train PERSISTS after this program exits — that is the point, it is
    what stops the valve drifting. Use --release to stop driving.
  * If the servo buzzes without moving it is against a stop. Stop and cut its
    power; a stalled servo overheats in seconds.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

US_PER_DEG = 2000.0 / 270.0
US_AT_ZERO = 500.0
HIS_OFFSET = 90.0
PERIOD_NS = 20_000_000        # 50 Hz, the standard servo frame


def find_channel() -> Path:
    """The pwmchip that the overlay created, and channel 0 within it.

    The chip number moves between kernels (pwmchip0 on older Pi OS, pwmchip2 on
    newer ones once the RP1/other controllers register first), so this looks
    rather than assuming — a hardcoded pwmchip0 fails with a bare ENOENT that
    reads like the overlay is missing when it is merely numbered differently.
    """
    chips = sorted(Path("/sys/class/pwm").glob("pwmchip*"))
    if not chips:
        raise SystemExit(
            "No hay ningun pwmchip. Falta el overlay: agrega a "
            "/boot/firmware/config.txt la linea\n"
            "    dtoverlay=pwm,pin=18,func=2\n"
            "y reinicia.")
    for chip in chips:
        try:
            if int((chip / "npwm").read_text().strip()) >= 1:
                return chip
        except OSError:
            continue
    raise SystemExit(f"pwmchips presentes ({[c.name for c in chips]}) pero ninguno usable.")


def channel_dir(chip: Path, ch: int = 0) -> Path:
    d = chip / f"pwm{ch}"
    if not d.exists():
        (chip / "export").write_text(str(ch))
        for _ in range(50):                   # udev needs a moment to chmod it
            if d.exists():
                break
            time.sleep(0.02)
    return d


def write(p: Path, value) -> None:
    p.write_text(str(value))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("angle", type=float, nargs="?", help="angulo absoluto")
    ap.add_argument("--dial", action="store_true",
                    help="el angulo va en TU marco (el de la manija)")
    ap.add_argument("--release", action="store_true",
                    help="dejar de manejar el servo (se soltara y puede derivar)")
    args = ap.parse_args()

    chip = find_channel()
    ch = channel_dir(chip)

    if args.release:
        try:
            write(ch / "enable", 0)
        except OSError:
            pass
        print(f"  liberado ({chip.name}/pwm0 apagado) — el servo puede derivar")
        return 0

    if args.angle is None:
        ap.error("dame un angulo, o --release")

    deg = args.angle - HIS_OFFSET if args.dial else args.angle
    if not 0.0 <= deg <= 270.0:
        print(f"  fuera del rango del servo (0-270 en su marco): {args.angle}")
        return 2
    us = US_AT_ZERO + deg * US_PER_DEG

    # Order matters: period before duty, or the kernel rejects a duty that is
    # momentarily larger than the period it still has from a previous run.
    write(ch / "period", PERIOD_NS)
    write(ch / "duty_cycle", int(round(us * 1000)))
    write(ch / "enable", 1)

    print(f"  {args.angle:.0f} grados {'tuyos' if args.dial else 'del servo'}"
          f"  =  {deg + HIS_OFFSET:.0f} en tu marco / {deg:.0f} en el del servo"
          f"  =  {us:.0f} us     ({chip.name}/pwm0)")
    print("  el kernel sigue generando el pulso despues de que esto termine.")
    print("  para soltarlo:  sudo ./.venv/bin/python tools/servo_pwm.py --release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
