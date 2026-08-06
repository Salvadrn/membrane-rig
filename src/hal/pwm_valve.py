"""Real proportional-valve driver: PWM via pigpio (DMA hardware-timed).

DRIVER CIRCUIT ASSUMPTIONS
--------------------------
The Pi's 3.3V GPIO cannot drive a solenoid directly. Assumed circuit:

    GPIO(pwm_pin) --[1k]--> gate of a logic-level N-MOSFET (e.g. IRLZ44N)
    valve coil between +12V and the MOSFET drain; source to GND
    flyback diode (e.g. 1N5819 / SB560) across the coil, cathode to +12V
    common ground between the Pi and the 12V supply
    (optionally use a ready-made "MOSFET driver module" that packages this)

PWM duty cycle sets the average coil current, which sets the valve position.
A 1 kHz carrier is a good starting point; some proportional valves prefer a
"dither" frequency — see the valve datasheet.

VALVE SENSE
-----------
`command` is 0..100 pressure authority (0 = lowest pressure = SAFE, 100 = max).
Not "vent": this driver serves either topology. The RECOMMENDED wiring below does
vent at 0%, but an inverted one does not, and naming the mechanism here would
promise an escape path that half the configurations lack.
For the recommended NORMALLY-OPEN bleed valve, energising it CLOSES it and
raises pressure, so duty == command. If your valve is wired/behaves the other
way, set `valve.invert: true` and the mapping flips.

pigpio is imported lazily so this file imports fine on a laptop.
"""
from __future__ import annotations

from .interfaces import ProportionalValve


class PwmValve(ProportionalValve):
    def __init__(self, cfg) -> None:
        import pigpio  # type: ignore

        self.cfg = cfg.valve
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError("pigpio daemon not running (start it: sudo pigpiod)")
        self._pi.set_PWM_frequency(self.cfg.pwm_pin, self.cfg.pwm_freq_hz)
        self._pi.set_PWM_range(self.cfg.pwm_pin, 1000)  # 0..1000 for finer resolution
        self.to_safe()

    def _apply(self, command: float) -> None:
        command = max(self.cfg.min_command, min(self.cfg.max_command, command))
        duty = command if not self.cfg.invert else (100.0 - command)
        self._pi.set_PWM_dutycycle(self.cfg.pwm_pin, int(duty / 100.0 * 1000))

    def set_command(self, command: float) -> None:
        self._apply(command)

    def to_safe(self) -> None:
        # command 0 == lowest pressure. With invert this still maps to the safe
        # duty — which vents only on the normally-open bleed wiring.
        self._apply(0.0)

    def full_close(self) -> None:
        # A solenoid has no travel to over-drive: 0% already drives it to its
        # LOWEST-PRESSURE state, so seating it is the same action as going safe.
        # Not "its shut position" — on the recommended normally-open bleed valve
        # the safe state is the valve OPEN, venting. What is shut is the path to
        # pressure, not the valve.
        self._apply(0.0)

    def close(self) -> None:
        try:
            self.full_close()
            self._pi.stop()
        except Exception:
            pass
