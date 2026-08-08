"""Safety monitor — runs on every control-loop tick, independent of test state.

Failure modes handled:
  * OVERPRESSURE   pressure above the effective cutoff -> immediate abort (no
                   grace). The cutoff is not fixed: `arm_for_run` tightens it to
                   max(setpoint) + margin for the duration of a run, so a 20 kPa
                   test aborts near 30 kPa instead of coasting to the global
                   cutoff. Meshes are delicate; the ceiling should track
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
        # Frozen-signal detector state (see check()). Only armed during a run.
        self.frozen_reads = cfg.safety.frozen_raw_reads
        self._armed = False
        self._last_raw = None
        self._raw_repeat = 0

    def arm_for_run(self, setpoints_kpa, specimen_limit_kpa=None) -> float:
        """Tighten the cutoff to what THIS run actually needs.

        A test at 20 kPa has no business ever reaching the global cutoff;
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
        # Arm the frozen-signal detector for the run and start it fresh.
        self._armed = True
        self._last_raw = None
        self._raw_repeat = 0
        self.max_pressure = self.hard_max
        self.limit_name = "safety cutoff"
        ceiling = None
        name = None
        if self.overshoot_margin > 0 and setpoints_kpa:
            ceiling = max(setpoints_kpa) + self.overshoot_margin
            name = "run ceiling"
        # The specimen limit clamps INDEPENDENTLY of the margin. Setting
        # overshoot_margin = 0 disables the per-run ceiling, but the mesh's
        # declared limit is not the run's to waive — folding this into the branch
        # above meant margin = 0 silently dropped it and let the cutoff sit at 80
        # on the mounted specimen, contradicting this docstring.
        if specimen_limit_kpa and specimen_limit_kpa > 0:
            if ceiling is None or specimen_limit_kpa < ceiling:
                ceiling = specimen_limit_kpa
                name = "specimen limit"
        if ceiling is not None and ceiling < self.hard_max:
            self.max_pressure = ceiling
            self.limit_name = name
        return self.max_pressure

    def disarm(self) -> None:
        """Back to the global cutoff (idle: no run ceiling applies).

        DELIBERATE, NOT AN OVERSIGHT — Adrián's decision, 2026-07-31. The idle
        cutoff returns to the GLOBAL cutoff and is *not* clamped to the mounted
        specimen's limit, so an idle overpressure does not alarm until the global
        cutoff even with a lower specimen limit declared. The trade-off he
        accepted: the alarm fires above what the mesh was declared to tolerate
        (the gap is safety.max_pressure - the specimen limit, whatever they are).

        Do not "fix" this. It looks like the arm_for_run bug that WAS fixed (an
        audit found the specimen clamp being dropped when overshoot_margin = 0, and
        that one was a real defect), so it gets re-reported by every fresh reader.
        It was raised, analysed and decided against on purpose. Reopening it needs
        Adrián, not a patch."""
        self._armed = False
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

        # Frozen signal (only while a run is armed). A live electrical signal is
        # ALWAYS noisy, so the raw ADC value being bit-identical for N consecutive
        # reads is impossible with a healthy sensor even when pressure is dead
        # still. It is the signature of a dead transducer / frozen I2C — and it
        # catches the WORST failure: a sensor stuck LOW at a plausible value, which
        # the plausibility band and the global cutoff both miss (they read the same
        # lying number) while the PID opens the valve MORE chasing a setpoint the
        # cell already passed. The question is "is the signal still ALIVE?", not
        # "is the number credible?" — a stuck sensor wins the second by lying but
        # cannot fake noise. Plant-independent, so it survives plant changes that
        # rot pressure thresholds. If it ever false-fires the fix is to RAISE
        # frozen_raw_reads, never to remove the check.
        raw = getattr(reading, "raw", None)
        raw_live = raw is not None and not math.isnan(raw)
        if self._armed and self.frozen_reads > 0 and raw_live:
            if self._last_raw is not None and raw == self._last_raw:
                self._raw_repeat += 1
            else:
                self._raw_repeat = 0
            self._last_raw = raw
            if self._raw_repeat >= self.frozen_reads:
                return SafetyState.SENSOR_FAULT, (
                    f"sensor signal frozen: raw {raw!r} identical for "
                    f"{self._raw_repeat + 1} reads (dead transducer / frozen I2C)"
                )
        # A non-live read (NaN/None — e.g. an interspersed dead read) is a GAP, not
        # a fresh sample: leave _raw_repeat and _last_raw untouched. Otherwise a
        # sensor alternating frozen<->dead would reset the frozen counter on every
        # NaN and evade this detector, while each frozen read still nudges the PID.

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
        self._raw_repeat = 0
        self._last_raw = None
