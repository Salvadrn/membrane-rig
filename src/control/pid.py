"""PID controller.

Design choices that matter for a pressure loop:
  * Derivative on measurement (not error) -> no derivative kick when the
    setpoint changes between test points.
  * LOW-PASS FILTERED derivative -> without it, sensor noise through kd shakes
    the valve and can destabilise the loop entirely (a raw derivative at 20 Hz
    turns +/-0.15 kPa of noise into +/-3 kPa/s of phantom rate). First-order
    filter with time constant d_filter_s (~0.3 s) on the rate estimate.
  * Back-calculation anti-windup -> the integral term is corrected whenever the
    output saturates, so it can't wind up while the valve is at a limit
    (important here: while pressurising, the valve sits at 100% for a while).
  * Output clamped to [output_min, output_max] (0..100 valve command).
"""
from __future__ import annotations


class PID:
    def __init__(self, kp: float, ki: float, kd: float,
                 out_min: float = 0.0, out_max: float = 100.0,
                 d_filter_s: float = 0.3) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self.d_filter_s = d_filter_s
        self.reset()

    def set_gains(self, kp: float, ki: float, kd: float) -> None:
        self.kp, self.ki, self.kd = kp, ki, kd

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_measurement = None
        self._rate = 0.0  # filtered d(measurement)/dt
        self.last_output = 0.0
        self.last_terms = (0.0, 0.0, 0.0)  # (p, i, d) for logging/tuning

    def update(self, setpoint: float, measurement: float, dt: float) -> float:
        if dt <= 0:
            return self.last_output

        error = setpoint - measurement
        p = self.kp * error
        self._integral += self.ki * error * dt

        if self._prev_measurement is None:
            d = 0.0
        else:
            raw_rate = (measurement - self._prev_measurement) / dt
            alpha = dt / (self.d_filter_s + dt)
            self._rate += alpha * (raw_rate - self._rate)
            d = -self.kd * self._rate
        self._prev_measurement = measurement

        raw = p + self._integral + d
        out = max(self.out_min, min(self.out_max, raw))

        # Back-calculation anti-windup: keep the integral consistent with the
        # clamped output so it stops accumulating once saturated.
        if raw != out:
            self._integral += (out - raw)

        self.last_output = out
        self.last_terms = (p, self._integral, d)
        return out
