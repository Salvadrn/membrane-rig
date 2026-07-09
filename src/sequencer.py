"""Test sequencer — the state machine that runs a sequence of setpoints.

Per setpoint:

  STABILIZING  PID holds the setpoint, diverter -> waste. Once the pressure
               stays inside +/- tolerance band continuously for `dwell_s`,
               advance to COLLECTING. If it can't stabilise within
               `stabilize_timeout_s`, the setpoint is recorded as failed and
               skipped.
  COLLECTING   diverter -> measured container, collect for `collection_s` while
               the PID keeps holding pressure. Pressure stats are accumulated
               over the collection window only (that's the number that matters
               for the permeability calc). Then diverter -> waste, record the
               result and move to the next setpoint.

DONE when all setpoints are processed.

`update()` is pure w.r.t. hardware — it takes (now, pressure) and returns what
the controller should do (target setpoint + diverter position). The controller
owns the PID and the actual I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Phase(str, Enum):
    IDLE = "idle"
    STABILIZING = "stabilizing"
    COLLECTING = "collecting"
    DONE = "done"


@dataclass
class TestResult:
    setpoint_kpa: float
    success: bool
    mean_kpa: float = 0.0
    std_kpa: float = 0.0
    min_kpa: float = 0.0
    max_kpa: float = 0.0
    in_band_fraction: float = 0.0
    n_samples: int = 0
    collection_s: float = 0.0
    note: str = ""
    # permeate volume collected in this point's collection window, and the
    # resulting flow rate Q = volume / collection_s. In sim these are filled
    # from the simulated plant; on hardware the operator enters the volume.
    volume_ml: float = 0.0
    flow_m3s: float = 0.0


@dataclass
class SeqStatus:
    phase: Phase
    setpoint_kpa: Optional[float]
    diverter_measured: bool
    index: int
    total: int
    in_band: bool = False
    phase_elapsed_s: float = 0.0
    collect_remaining_s: float = 0.0


@dataclass
class _Accum:
    n: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    lo: float = math.inf
    hi: float = -math.inf
    in_band: int = 0

    def add(self, x: float, in_band: bool) -> None:
        self.n += 1
        self.total += x
        self.total_sq += x * x
        self.lo = min(self.lo, x)
        self.hi = max(self.hi, x)
        if in_band:
            self.in_band += 1


class Sequencer:
    def __init__(self, cfg) -> None:
        self.tolerance_pct = cfg.test.tolerance_pct
        self.dwell_s = cfg.test.dwell_s
        self.collection_s = cfg.test.collection_s
        self.stabilize_timeout_s = cfg.test.stabilize_timeout_s
        self._setpoints: List[float] = []
        self._idx = 0
        self.phase = Phase.IDLE
        self.results: List[TestResult] = []
        self._phase_start = 0.0
        self._band_since: Optional[float] = None
        self._collect_start = 0.0
        self._acc = _Accum()

    # --- lifecycle -----------------------------------------------------------
    def start(self, setpoints_kpa: List[float], now: float,
              tolerance_pct=None, dwell_s=None, collection_s=None,
              stabilize_timeout_s=None) -> None:
        if tolerance_pct is not None:
            self.tolerance_pct = tolerance_pct
        if dwell_s is not None:
            self.dwell_s = dwell_s
        if collection_s is not None:
            self.collection_s = collection_s
        if stabilize_timeout_s is not None:
            self.stabilize_timeout_s = stabilize_timeout_s
        self._setpoints = list(setpoints_kpa)
        self._idx = 0
        self.results = []
        self._enter_stabilizing(now)

    def abort(self, note: str, now: float) -> None:
        """Called by the controller on a safety fault."""
        if self.phase in (Phase.STABILIZING, Phase.COLLECTING) and self._idx < len(self._setpoints):
            self._finalize(success=False, note=note)
        self.phase = Phase.DONE

    @property
    def finished(self) -> bool:
        return self.phase in (Phase.DONE, Phase.IDLE)

    # --- internal transitions ------------------------------------------------
    def _enter_stabilizing(self, now: float) -> None:
        self.phase = Phase.STABILIZING
        self._phase_start = now
        self._band_since = None

    def _enter_collecting(self, now: float) -> None:
        self.phase = Phase.COLLECTING
        self._phase_start = now
        self._collect_start = now
        self._acc = _Accum()

    def _current(self) -> float:
        return self._setpoints[self._idx]

    def _tol(self) -> float:
        return abs(self._current()) * self.tolerance_pct / 100.0

    def _finalize(self, success: bool, note: str) -> None:
        sp = self._current()
        a = self._acc
        if a.n > 0:
            mean = a.total / a.n
            var = max(0.0, a.total_sq / a.n - mean * mean)
            res = TestResult(
                setpoint_kpa=sp, success=success, mean_kpa=mean,
                std_kpa=math.sqrt(var), min_kpa=a.lo, max_kpa=a.hi,
                in_band_fraction=a.in_band / a.n, n_samples=a.n,
                collection_s=self.collection_s, note=note,
            )
        else:
            res = TestResult(setpoint_kpa=sp, success=success, note=note)
        self.results.append(res)

    def _advance(self, now: float) -> None:
        self._idx += 1
        if self._idx >= len(self._setpoints):
            self.phase = Phase.DONE
        else:
            self._enter_stabilizing(now)

    # --- main tick -----------------------------------------------------------
    def update(self, now: float, pressure_kpa: float) -> SeqStatus:
        if self.finished:
            return SeqStatus(Phase.DONE, None, False, self._idx, len(self._setpoints))

        sp = self._current()
        tol = self._tol()
        in_band = abs(pressure_kpa - sp) <= tol

        if self.phase == Phase.STABILIZING:
            if in_band:
                if self._band_since is None:
                    self._band_since = now
                elif now - self._band_since >= self.dwell_s:
                    self._enter_collecting(now)
            else:
                self._band_since = None

            if self.phase == Phase.STABILIZING and now - self._phase_start >= self.stabilize_timeout_s:
                self._finalize(success=False, note="stabilize_timeout")
                self._advance(now)
                return self.update(now, pressure_kpa)  # re-evaluate next setpoint

            return SeqStatus(
                Phase.STABILIZING, sp, False, self._idx, len(self._setpoints),
                in_band=in_band, phase_elapsed_s=now - self._phase_start,
            )

        # COLLECTING
        self._acc.add(pressure_kpa, in_band)
        remaining = self.collection_s - (now - self._collect_start)
        if remaining <= 0:
            self._finalize(success=True, note="")
            self._advance(now)
            if self.finished:
                return SeqStatus(Phase.DONE, None, False, self._idx, len(self._setpoints))
            nsp = self._current()
            return SeqStatus(
                Phase.STABILIZING, nsp, False, self._idx, len(self._setpoints),
                phase_elapsed_s=0.0,
            )

        return SeqStatus(
            Phase.COLLECTING, sp, True, self._idx, len(self._setpoints),
            in_band=in_band, phase_elapsed_s=now - self._phase_start,
            collect_remaining_s=remaining,
        )
