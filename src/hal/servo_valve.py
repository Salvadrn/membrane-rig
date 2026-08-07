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
small margin. It is CLAMPED to the calibrated travel by `_write_us()`, so a value
outside servo_min_us..servo_max_us seats at the band edge rather than jamming the
stem into the mechanical stop — the controller holds this position for as long as
the rig sits idle, and a stalled servo overheats. If seating needs a pulse the
band does not contain, the ENDPOINTS are wrong; recalibrate them rather than
widening the clamp.

Note: a servo is not a fail-safe by itself. It does not spring to safe — and
on this rig it does not even stay put: measured 2026-08-06, released, it DRIFTS
off the commanded angle, so losing power leaves the valve at an angle nobody
chose and nobody has yet measured (COMMISSIONING 10.7 records it). That is why
`close()` keeps driving the shut pulse instead of releasing. The mechanical
relief valve is meant to cover the power-loss case — it is now IN HAND but
**not fitted**, and it protects nothing until it is mounted and its crack
pressure is set. Until then the panel valve is the only human shutoff and the
regulator setting is the only bound. `to_safe()` actively drives to the
lowest-pressure stop while powered.

pigpio is imported lazily so this file imports fine on a laptop.
"""
from __future__ import annotations

import time

from .interfaces import ProportionalValve


class ServoValve(ProportionalValve):
    def __init__(self, cfg) -> None:
        try:
            import pigpio  # type: ignore
        except ImportError as e:
            # install.sh stopped building pigpio by default on 2026-08-07 — the
            # rig drives the servo from the kernel PWM now. Say that here rather
            # than letting a bare ImportError look like a broken install.
            raise RuntimeError(
                "pigpio no esta instalado. El rig usa valve.type: servo_kpwm "
                "(PWM del kernel) desde 2026-08-07; en esta Pi el servo se "
                "comporta mal con cada pulso que pigpio genera. Si de verdad "
                "quieres el camino de pigpio, re-corre install.sh con "
                "MEMBRANE_RIG_BUILD_PIGPIO=1."
            ) from e

        self.cfg = cfg.valve
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError("pigpio daemon not running (start it: sudo pigpiod)")
        self.to_safe()

    def _travel_us(self) -> tuple[int, int]:
        """The ONLY pulse widths this driver may ever emit, low..high.

        Calibrated by hand at the valve: the operator drove the servo until the
        stem reached each end of the quarter turn and read the angle off the
        handle. Outside that band the horn is pushing the ball against a seat or
        the servo against its own stop — which stalls it, and a stalled servo
        overheats in seconds with nobody watching.
        """
        lo, hi = int(self.cfg.servo_min_us), int(self.cfg.servo_max_us)
        return (lo, hi) if lo <= hi else (hi, lo)

    def _write_us(self, us: float) -> None:
        """Every pulse this driver emits goes through here, clamped.

        The clamp is deliberately at the WRITE, not at the callers. Adrián's
        instruction was that the servo must never leave the calibrated band "por
        nada del mundo", and a rule enforced at each caller is a rule that the
        next caller forgets. Two live holes it closes today:
          * `servo_close_us` is a raw microsecond override, so a typo there used
            to drive the stem straight past the seat.
          * `min_command`/`max_command` bound the COMMAND, not the pulse, so they
            cannot protect a path that writes microseconds directly.
        Clamping silently is right here: refusing to move is not safer than
        moving to the nearest legal position, and this runs in the control loop
        where raising would abort a healthy run over an arithmetic edge.
        """
        lo, hi = self._travel_us()
        self._pi.set_servo_pulsewidth(self.cfg.servo_pin, int(max(lo, min(hi, us))))

    def _apply(self, command: float) -> None:
        command = max(self.cfg.min_command, min(self.cfg.max_command, command))
        frac = command / 100.0
        if self.cfg.invert:
            frac = 1.0 - frac
        self._write_us(self.cfg.servo_min_us
                       + frac * (self.cfg.servo_max_us - self.cfg.servo_min_us))

    def _shut_pulse_us(self) -> int:
        """Pulse width that SEATS the valve. `servo_close_us` overrides the end
        of the control range so the valve can be driven a little past where
        regulation stops — 0 (unset) means "use the 0% end". Whatever it says,
        `_write_us` still clamps it into the calibrated travel: seating a little
        harder is a legitimate ask, leaving the band is not."""
        if self.cfg.servo_close_us:
            return int(self.cfg.servo_close_us)
        return int(self.cfg.servo_max_us if self.cfg.invert else self.cfg.servo_min_us)

    def set_command(self, command: float) -> None:
        self._apply(command)

    def to_safe(self) -> None:
        # command 0 == lowest pressure (inline: feed shut / bleed: vented)
        self._apply(0.0)

    def full_close(self) -> None:
        self._write_us(self._shut_pulse_us())

    def close(self) -> None:
        try:
            self.full_close()
            # Hold the shut position long enough for the stem to actually get
            # there before the process exits — a servo travels ~0.15 s/60°, and
            # releasing the instant we command it would leave it mid-travel.
            time.sleep(max(0.0, float(self.cfg.close_hold_s)))
            # KEEP DRIVING the shut position. This used to release the servo
            # (pulse width 0) on the assumption that friction would hold the
            # stem — the old comment said so outright. Adrián's bench disproved
            # it on 2026-08-06: released, the servo drifts off the commanded
            # angle, so "close and release" did NOT leave the valve shut.
            #
            # That matters because close() is what runs when a test ends or the
            # process exits, and a valve that drifts open afterwards is the one
            # failure this driver exists to prevent. Holding costs a powered
            # servo; drifting costs an unattended open feed.
            #
            # Holding is only safe because the endpoints are now calibrated to
            # the stem's real travel (servo_min_us/max_us), so shut is a
            # position the servo can reach rather than a stop it grinds against.
            # A servo held against a hard stop overheats — if this ever buzzes
            # at rest, the endpoints are wrong, not this choice.
            #
            # Unchanged: the mechanical relief is in hand and NOT FITTED, so
            # closing the PANEL valve by hand at the end of a session is still
            # the whole failsafe, not a backup to one.
            self._pi.stop()
        except Exception:
            pass
