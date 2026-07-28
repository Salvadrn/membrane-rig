"""Safety monitor — runs on every control-loop tick, independent of test state.

Failure modes handled:
  * OVERPRESSURE   pressure above the effective cutoff -> immediate abort (no
                   grace). The cutoff is not fixed: `arm_for_run` tightens it to
                   max(setpoint) + margin for the duration of a run, so a 20 kPa
                   test aborts near 30 kPa instead of coasting to the 80 kPa
                   global limit. Meshes are delicate; the ceiling should track
                   what the test actually asked for.
  * SENSOR_FAULT   driver reported unhealthy, or the reading is outside the
                   physically plausible range (e.g. a disconnected 4-20mA loop
                   reads ~0 -> below min_plausible). Requires N consecutive bad
                   reads so a single glitch doesn't abort a run.

The critical case: a disconnected sensor reading "0 kPa" must NOT be trusted as
"low pressure" — otherwise the PID would slam the valve fully closed. Treating
implausible readings as a fault (vent + abort) is the safe response.
"""
from __future__ import annotations

import math
from enum import Enum


class SafetyState(Enum):
    OK = "ok"
    OVERPRESSURE = "overpressure"
    SENSOR_FAULT = "sensor_fault"


class SafetyMonitor:
    def __init__(self, cfg) -> None:
        self.hard_max = cfg.safety.max_pressure_kpa
        self.overshoot_margin = cfg.safety.overshoot_margin_kpa
        # effective cutoff: equals hard_max when idle, tightens per run
        self.max_pressure = self.hard_max
        self.limit_name = "safety cutoff"
        self.min_plausible = cfg.safety.min_plausible_kpa
        self.max_plausible = cfg.safety.max_plausible_kpa
        self.grace = cfg.safety.fault_grace_reads
        self._bad_reads = 0

    def arm_for_run(self, setpoints_kpa, specimen_limit_kpa=None) -> float:
        """Tighten the cutoff to what THIS run actually needs.

        A test at 20 kPa has no business ever reaching the 80 kPa global cutoff;
        letting it get there before aborting would destroy a delicate specimen.
        The run ceiling is max(setpoint) + overshoot margin, clamped to BOTH the
        global cutoff and the specimen limit — so a fault can never push the mesh
        past the pressure we declared it tolerates. Returns the effective ceiling.

        The margin is absolute (not a % of setpoint): mesh damage and the specimen
        limit are both absolute, so an absolute margin bounds the worst-case
        over-stress consistently — see the overshoot_margin rationale in
        config.yaml. `specimen_limit_kpa` is always defined by the caller
        (RigController.pressure_limit_kpa() falls back to the safety cutoff, it is
        never None); the guard below only skips the clamp if it is explicitly
        passed None/0. `limit_name` names whichever bound is binding, so an
        OVERPRESSURE abort message tells the operator what it hit."""
        self.max_pressure = self.hard_max
        self.limit_name = "safety cutoff"
        if self.overshoot_margin > 0 and setpoints_kpa:
            ceiling = max(setpoints_kpa) + self.overshoot_margin
            name = "run ceiling"
            # A fault must never push the mesh past its declared limit, so the
            # specimen limit clamps the ceiling too (not just the global cutoff).
            if specimen_limit_kpa and specimen_limit_kpa > 0 and specimen_limit_kpa < ceiling:
                ceiling = specimen_limit_kpa
                name = "specimen limit"
            if ceiling < self.hard_max:
                self.max_pressure = ceiling
                self.limit_name = name
        return self.max_pressure

    def disarm(self) -> None:
        """Back to the global cutoff (idle: no run ceiling applies)."""
        self.max_pressure = self.hard_max
        self.limit_name = "safety cutoff"

    def check(self, reading) -> tuple[SafetyState, str]:
        p = reading.pressure_kpa

        # Overpressure is immediate and takes priority.
        if not (reading.healthy is False) and not math.isnan(p) and p > self.max_pressure:
            return SafetyState.OVERPRESSURE, (
                f"pressure {p:.1f} kPa exceeded {self.limit_name} "
                f"{self.max_pressure:.1f} kPa"
            )

        bad = (
            reading.healthy is False
            or math.isnan(p)
            or p < self.min_plausible
            or p > self.max_plausible
        )
        if bad:
            self._bad_reads += 1
            if self._bad_reads >= self.grace:
                return SafetyState.SENSOR_FAULT, (
                    f"sensor implausible/unhealthy for {self._bad_reads} reads "
                    f"(last={p!r})"
                )
            return SafetyState.OK, ""

        self._bad_reads = 0
        return SafetyState.OK, ""

    def reset(self) -> None:
        self._bad_reads = 0
