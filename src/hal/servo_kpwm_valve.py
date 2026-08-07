"""Servo valve driven by the KERNEL's hardware PWM instead of pigpio.

WHY THIS EXISTS
---------------
On this rig (Pi 4, Raspberry Pi OS Trixie, pigpio built from source) the servo
misbehaves on every pulse pigpio generates. Measured on the bench 2026-08-06,
with the servo UNCOUPLED and unloaded, so no mechanical explanation survives:
it is still whenever GPIO18 is held low and erratic whenever pigpio drives it,
at any angle, with either pigpio clock peripheral (-t 0 and -t 1 both tried).

pigpio times its waveform in software and paints it onto the pin with DMA.
GPIO18 is a genuine hardware-PWM output, so the silicon can emit the pulse train
itself and there is no software timing left to get wrong. The project's notes
named this port before any of that debugging began.

SETUP, once, in /boot/firmware/config.txt followed by a reboot:

    dtoverlay=pwm,pin=18,func=2      # func=2 == ALT5 == PWM0 on GPIO18

And **remove any `gpio=18=...` line**: it forces the pin to a plain output and
wins over the overlay, so the PWM runs but never reaches the wire. That exact
collision cost an afternoon here — the first kernel-PWM test moved nothing while
the pulse was being generated perfectly.

PERMISSIONS
-----------
Writing /sys/class/pwm needs root unless a udev rule hands the group access
(install.sh adds one). The driver says which of the two is missing rather than
raising a bare PermissionError, because "run it with sudo" and "the overlay is
absent" are different problems with the same symptom of nothing moving.

VALVE SENSE
-----------
Identical to ServoValve: `command` is 0..100 pressure authority, 0 == lowest
pressure == SAFE. `valve.invert` flips which end of the calibrated travel 0%
lands on. Every pulse is clamped to servo_min_us..servo_max_us — same reasoning
as ServoValve._write_us(): the clamp sits at the write so no caller can escape
it, and a servo held against a stop overheats.

The pulse train PERSISTS after the process exits — the kernel keeps driving it.
That is deliberate and is the same property close() needs: released, this servo
drifts off the commanded angle rather than holding by friction (measured
2026-08-06), so a valve left un-driven does not stay shut.
"""
from __future__ import annotations

import time
from pathlib import Path

from .interfaces import ProportionalValve

PWM_ROOT = Path("/sys/class/pwm")
PERIOD_NS = 20_000_000          # 50 Hz servo frame


class ServoKernelPwmValve(ProportionalValve):
    #: Surfaced so run metadata records which generator produced the pulses.
    #: The rig has two, they behave differently on this board, and a trace that
    #: does not say which one it used cannot be compared against another.
    source = "servo_kpwm"

    def __init__(self, cfg) -> None:
        self.cfg = cfg.valve
        self._ch = self._open_channel()
        self.to_safe()

    # ---- sysfs plumbing ----------------------------------------------------

    def _open_channel(self) -> Path:
        chips = sorted(PWM_ROOT.glob("pwmchip*"))
        if not chips:
            raise RuntimeError(
                "no PWM chip in /sys/class/pwm — add 'dtoverlay=pwm,pin=18,func=2' "
                "to /boot/firmware/config.txt and reboot")
        # The chip number moves between kernels once other controllers register
        # first, so this looks instead of hardcoding pwmchip0; a hardcoded path
        # fails with a bare ENOENT that reads like a missing overlay.
        chip = next((c for c in chips
                     if (c / "npwm").exists()
                     and int((c / "npwm").read_text().strip()) >= 1), None)
        if chip is None:
            raise RuntimeError(f"PWM chips present ({[c.name for c in chips]}) but none usable")

        ch = chip / "pwm0"
        try:
            if not ch.exists():
                (chip / "export").write_text("0")
                for _ in range(50):          # udev needs a moment to chmod it
                    if ch.exists():
                        break
                    time.sleep(0.02)
            (ch / "period").write_text(str(PERIOD_NS))
        except PermissionError as e:
            raise RuntimeError(
                f"no permission to drive {chip.name} ({e}). Run as root, or let "
                f"install.sh add the udev rule that gives the gpio group access."
            ) from e
        return ch

    def _travel_us(self) -> tuple[int, int]:
        lo, hi = int(self.cfg.servo_min_us), int(self.cfg.servo_max_us)
        return (lo, hi) if lo <= hi else (hi, lo)

    def _write_us(self, us: float) -> None:
        """Every pulse goes through here, clamped to the calibrated travel.

        Same placement and same reason as ServoValve._write_us(): a rule enforced
        at each caller is a rule the next caller forgets, and what it guards is a
        stall — a servo pinned against a stop overheats in seconds unattended.
        """
        lo, hi = self._travel_us()
        duty_ns = int(round(max(lo, min(hi, us)) * 1000))
        (self._ch / "duty_cycle").write_text(str(duty_ns))
        (self._ch / "enable").write_text("1")

    # ---- ProportionalValve -------------------------------------------------

    def _apply(self, command: float) -> None:
        command = max(self.cfg.min_command, min(self.cfg.max_command, command))
        frac = command / 100.0
        if self.cfg.invert:
            frac = 1.0 - frac
        self._write_us(self.cfg.servo_min_us
                       + frac * (self.cfg.servo_max_us - self.cfg.servo_min_us))

    def _shut_pulse_us(self) -> int:
        if self.cfg.servo_close_us:
            return int(self.cfg.servo_close_us)
        return int(self.cfg.servo_max_us if self.cfg.invert else self.cfg.servo_min_us)

    def set_command(self, command: float) -> None:
        self._apply(command)

    def to_safe(self) -> None:
        self._apply(0.0)

    def full_close(self) -> None:
        self._write_us(self._shut_pulse_us())

    def close(self) -> None:
        try:
            self.full_close()
            time.sleep(max(0.0, float(self.cfg.close_hold_s)))
            # Deliberately does NOT disable the channel. The kernel keeps
            # emitting, which is what holds the valve shut after the process is
            # gone — this servo drifts when it stops being driven, so releasing
            # here would undo the close it just performed.
        except Exception:
            pass
