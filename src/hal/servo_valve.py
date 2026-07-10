"""Real proportional-valve driver: a hobby servo turning a needle/metering valve.

Chosen for LOW-pressure work (10-60 kPa): true water proportional solenoids are
expensive and most won't actuate below ~0.5 bar. A servo turning a brass needle
valve gives smooth, cheap, position-based restriction at any pressure.

DRIVER / MECHANICAL ASSUMPTIONS
-------------------------------
    GPIO(servo_pin) --> servo signal wire      (pin 12/13/18/19 = hardware PWM)
    servo V+  <-- separate 5-6V supply (NOT the Pi 3.3V/5V rail; servos draw
                  stall currents that brown-out the Pi)
    common ground between the Pi and the servo supply
    servo horn --[coupler/bracket]--> needle-valve stem

pigpio drives the servo with clean DMA-timed pulses via set_servo_pulsewidth().

VALVE SENSE
-----------
`command` is 0..100 pressure authority (0 = lowest pressure = SAFE state,
100 = highest). What 0% means physically depends on the plumbing topology:
  * INLINE feed throttle (this rig): 0% = valve CLOSED (feed shut; the cell
    drains through the membrane), 100% = fully open toward supply pressure.
  * BLEED-to-waste: 0% = valve fully OPEN (vent), 100% = closed.
Calibrate servo_min_us/servo_max_us so 0/100% land exactly on the valve's stops
(over-driving past a hard stop stalls and cooks the servo); `valve.invert`
flips the direction if the linkage turns the other way.

Note: a servo HOLDS position on power loss (it does not spring to safe), so it
is not a fail-safe by itself — the mechanical relief valve is the hardware
failsafe. `to_safe()` actively drives to the lowest-pressure stop while powered.

pigpio is imported lazily so this file imports fine on a laptop.
"""
from __future__ import annotations

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

    def set_command(self, command: float) -> None:
        self._apply(command)

    def to_safe(self) -> None:
        # command 0 == lowest pressure (inline: feed shut / bleed: vented)
        self._apply(0.0)

    def close(self) -> None:
        try:
            self.to_safe()
            # 0 pulse width releases the servo (stops sending pulses)
            self._pi.set_servo_pulsewidth(self.cfg.servo_pin, 0)
            self._pi.stop()
        except Exception:
            pass
