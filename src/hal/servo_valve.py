"""Real proportional-valve driver: a hobby servo turning a quarter-turn ball valve.

Chosen for LOW-pressure work (10-60 kPa): true water proportional solenoids are
expensive and most won't actuate below ~0.5 bar. A servo turning the existing
quarter-turn ball valve gives cheap, position-based restriction — coarse, but
usable near-closed where this rig runs (see docs/ASSEMBLY.md).

DRIVER / MECHANICAL ASSUMPTIONS
-------------------------------
    GPIO(servo_pin) --> servo signal wire      (pin 12/13/18/19 = hardware PWM)
    servo V+  <-- separate 5-6V supply (NOT the Pi 3.3V/5V rail; servos draw
                  stall currents that brown-out the Pi)
    common ground between the Pi and the servo supply
    servo horn --[coupler/bracket]--> ball-valve stem

pigpio drives the servo with clean DMA-timed pulses via set_servo_pulsewidth().

VALVE SENSE
-----------
`command` is 0..100 pressure authority (0 = lowest pressure = SAFE state,
100 = highest). What 0% means physically depends on the plumbing topology:
  * INLINE feed throttle (this rig): 0% = valve CLOSED (feed shut; the cell
    drains through the membrane), 100% = fully open toward supply pressure.
  * BLEED-to-waste: 0% = valve fully OPEN (vent), 100% = closed.
Calibrate servo_min_us/servo_max_us to the ends of the useful CONTROL range;
`valve.invert` flips the direction if the linkage turns the other way.

`servo_close_us` is separate and matters when a test ends: 0% is the bottom of
the control range, which is where regulation stops, not necessarily where the
valve seals — with backlash in a printed coupling it can sit slightly cracked.
Set servo_close_us a little past 0% so the end of a run SEATS the valve. Find it
by hand: step the pulse down until flow stops with the supply on, then add a
small margin. Do NOT jam it into the mechanical stop — the controller holds this
position for as long as the rig sits idle, and a stalled servo overheats.

Note: a servo HOLDS position on power loss (it does not spring to safe), so it
is not a fail-safe by itself — the mechanical relief valve is the hardware
failsafe. `to_safe()` actively drives to the lowest-pressure stop while powered.

pigpio is imported lazily so this file imports fine on a laptop.
"""
from __future__ import annotations

import time

from .interfaces import ProportionalValve


class ServoValve(ProportionalValve):
    def __init__(self, cfg) -> None:
        import pigpio  # type: ignore

        self.cfg = cfg.valve
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError("pigpio daemon not running (start it: sudo pigpiod)")
        self.to_safe()

    def _apply(self, command: float) -> None:
        command = max(self.cfg.min_command, min(self.cfg.max_command, command))
        frac = command / 100.0
        if self.cfg.invert:
            frac = 1.0 - frac
        us = self.cfg.servo_min_us + frac * (self.cfg.servo_max_us - self.cfg.servo_min_us)
        self._pi.set_servo_pulsewidth(self.cfg.servo_pin, int(us))

    def _shut_pulse_us(self) -> int:
        """Pulse width that SEATS the valve. `servo_close_us` overrides the end
        of the control range so the valve can be driven a little past where
        regulation stops — 0 (unset) keeps the old behaviour exactly."""
        if self.cfg.servo_close_us:
            return int(self.cfg.servo_close_us)
        return int(self.cfg.servo_max_us if self.cfg.invert else self.cfg.servo_min_us)

    def set_command(self, command: float) -> None:
        self._apply(command)

    def to_safe(self) -> None:
        # command 0 == lowest pressure (inline: feed shut / bleed: vented)
        self._apply(0.0)

    def full_close(self) -> None:
        self._pi.set_servo_pulsewidth(self.cfg.servo_pin, self._shut_pulse_us())

    def close(self) -> None:
        try:
            self.full_close()
            # Hold the shut position long enough for the stem to actually get
            # there before the process exits — a servo travels ~0.15 s/60°, and
            # releasing the instant we command it would leave it mid-travel.
            time.sleep(max(0.0, float(self.cfg.close_hold_s)))
            # 0 pulse width releases the servo (stops sending pulses). It keeps
            # its position by friction: a servo does NOT spring shut on power
            # loss, which is why the mechanical relief valve is the real
            # failsafe and why the supply valve gets closed by hand at the end
            # of a session.
            self._pi.set_servo_pulsewidth(self.cfg.servo_pin, 0)
            self._pi.stop()
        except Exception:
            pass
