"""RigController — owns the control loop, HAL, PID, sequencer, safety, logging.

A single background thread runs at `pid.sample_hz`. Every tick it:
  1. reads the sensor
  2. runs the safety check (independent of test state) -> vent+abort on fault
  3. if a test sequence is active: steps the sequencer, runs the PID, drives the
     valve + diverter, logs the row
  4. if idle: holds everything in the safe/vented state
  5. in sim mode: steps the plant model

The UI (web or CLI) only calls start_sequence / stop / get_status / shutdown and
reads the shared, lock-protected `status` snapshot.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from typing import List, Optional

from pathlib import Path

import dataclasses

from .analysis import fit_permeability
from .config import Config, water_viscosity_pa_s
from .control.pid import PID
from .export_excel import export_permeability_xlsx, xlsx_available
from .hal import build_hal
from .logging_csv import RunLogger
from .playlist import DONE, FAILED, PENDING, RUNNING, Experiment, Playlist
from .plotting import plot_available, plot_permeability
from .safety import SafetyMonitor, SafetyState
from .sequencer import Phase, Sequencer


class RigController:
    def __init__(self, cfg: Config, playlist_path: str = "playlist.json") -> None:
        self.cfg = cfg
        self.sensor, self.valve, self.diverter, self.temp, self.plant = build_hal(cfg)
        self.pid = PID(cfg.pid.kp, cfg.pid.ki, cfg.pid.kd,
                       cfg.pid.output_min, cfg.pid.output_max)
        self.safety = SafetyMonitor(cfg)
        self.sequencer = Sequencer(cfg)
        self.logger = RunLogger(cfg)
        # queue of experiments; runs one item then waits for the operator
        self.playlist = Playlist(Path(playlist_path), cfg.membrane.max_pressure_kpa)
        self._current_item_id: Optional[str] = None

        self._dt = 1.0 / cfg.pid.sample_hz
        self._lock = threading.Lock()
        self._active = False
        self._run_start = 0.0
        self._fault_reason = ""
        # `_finished` is sticky: it stays True from the moment a run ends
        # (completed OR aborted) until the next start_sequence, so a slow UI
        # poll can't miss the terminal state between control-loop ticks.
        self._finished = False
        self._final_elapsed = 0.0
        self._final_index = 0
        self._final_total = 0

        # permeate volume accumulation for the current collection window
        self._collect_idx: Optional[int] = None
        self._collect_vol_m3 = 0.0
        self.analysis_result = None

        # post-run verification that the feed valve actually seated
        self._close_check_until = 0.0
        self._close_check_p0 = 0.0
        self._close_warning = ""

        # Setpoint ramp: the plant is asymmetric (rises fast, falls slowly —
        # overshoot is expensive to undo), so the PID chases a target that ramps
        # from the current pressure toward each setpoint instead of a step.
        self._ramp_sp: Optional[float] = None
        self._ramp_for: Optional[float] = None  # which true setpoint the ramp tracks

        # Plant-response watchdog (detector B): the valve command is here, not in
        # the SafetyMonitor, so this lives in the controller. See _plant_watchdog.
        self._wd_valve_pct = cfg.safety.watchdog_valve_pct
        self._wd_hold_ticks = int(cfg.safety.watchdog_hold_s / self._dt) if cfg.safety.watchdog_hold_s > 0 else 0
        self._wd_min_rise = cfg.safety.watchdog_min_rise_kpa
        self._wd_open_p: Optional[float] = None
        self._wd_ticks = 0
        self._wd_rose = False

        # Ceiling recovery (HELD). Hitting a RUN ceiling stops to safe and waits
        # for the operator instead of ending the run; the global cutoff and sensor
        # faults are never recoverable. See _enter_held.
        self._held = False
        self._held_alarm: Optional[dict] = None
        # Between-point pause: the feed is SHUT COMPLETELY and the run waits for
        # the operator to weigh the permeate. Distinct from HELD, which is an
        # alarm — this one is a planned stop and nothing is wrong.
        self._awaiting_operator = False
        self._pause_between_points = cfg.test.pause_between_points
        self._hold_count = 0             # consecutive holds on the current point
        self._hold_point_idx: Optional[int] = None
        self._retry_max = cfg.safety.ceiling_retry_max
        self._ceiling_raised = False     # provenance: was this run's ceiling raised?
        self._raise_note = ""
        # filtered dP/dt, used to tell a normal overshoot from a runaway
        self._prev_p: Optional[float] = None
        self._p_rate = 0.0

        # water temperature (a test variable): polled slowly off the fast loop.
        # mu is derived from it; the run-mean temp feeds the permeability calc.
        self._water_temp_c = cfg.temperature.manual_c
        # How that number was obtained. The HAL exposes it (TemperatureSensor.source)
        # precisely because the value cannot carry the distinction itself, and µ —
        # hence k — is derived from it: a configured constant must never reach the
        # evidence trail looking like a measurement. Refined at runtime to flag a
        # probe that has stopped answering.
        self._temp_source = getattr(self.temp, "source", "unknown")
        self._temp_last_good = 0.0   # monotonic of the last successful read; 0 = never
        self._temp_sum = 0.0
        self._temp_n = 0
        # Provenance of the temperature ACROSS the run: "mixed" if it changed
        # mid-run, because a single run-level label would then misdescribe every
        # sample on one side of that moment. The per-row CSV stays the record of
        # truth; this is the honest scalar for the run summary.
        self._run_temp_source: Optional[str] = None
        # in sim, tell the plant the viscosity so its flow scales as 1/mu
        if self.plant is not None and hasattr(self.plant, "set_viscosity"):
            self.plant.set_viscosity(water_viscosity_pa_s(cfg.temperature.manual_c))

        # shared status snapshot (read by the UI)
        self.status = {
            "running": False,
            "finished": False,
            "phase": Phase.IDLE.value,
            "fault": "",
            "pressure_kpa": 0.0,
            "pressure_disp": 0.0,
            "setpoint_kpa": None,
            "setpoint_disp": None,
            "valve_command": 0.0,
            "diverter_measured": False,
            "index": 0,
            "total": 0,
            "elapsed_s": 0.0,
            "collect_remaining_s": 0.0,
            "run_name": None,
            "results": [],
            "analysis": None,
            "water_temp_c": round(cfg.temperature.manual_c, 2),
            "water_temp_source": getattr(self.temp, "source", "unknown"),
            "viscosity_pa_s": cfg.membrane.viscosity_pa_s,
            "units": cfg.units,
            "playlist_analysis": None,
            "item_id": None,
            "item_label": "",
            "run_ceiling_kpa": cfg.safety.max_pressure_kpa,
            "run_ceiling_disp": round(cfg.disp(cfg.safety.max_pressure_kpa), 2),
            "run_ceiling_source": "safety cutoff",
            "close_warning": "",
            # Ceiling recovery: `held` = stopped at the ceiling, feed shut, waiting
            # for the operator. `held_alarm` carries everything the UI needs (all
            # pressures in DISPLAY units) including the machine-readable severity /
            # retry_advised the Retry button keys off — never parse the prose.
            "held": False,
            "held_alarm": None,
            # planned pause between points (weigh the permeate), NOT an alarm
            "awaiting_operator": False,
            "awaiting_point": None,
        }
        # rolling history for the live chart: (elapsed_s, pressure_disp, setpoint_disp)
        self.history = deque(maxlen=4000)

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="rig-control", daemon=True)
        self._thread.start()
        # slow temperature poller (a DS18B20 read blocks ~750 ms, so keep it off
        # the fast control loop)
        self._temp_thread = threading.Thread(target=self._temp_loop, name="rig-temp", daemon=True)
        self._temp_thread.start()

    # --- pressure limits -----------------------------------------------------
    def pressure_limit_kpa(self) -> float:
        """Highest setpoint anything may request right now: the tightest of the
        safety cutoff, the configured specimen limit, and the limit the operator
        set for the mesh currently in the vessel."""
        limit = self.cfg.specimen_limit_kpa()
        pl = self.playlist.membrane_limit_kpa
        if pl and pl > 0:
            limit = min(limit, pl)
        return limit

    def setpoint_bounds(self) -> dict:
        """The bounds a setpoint must satisfy, in DISPLAY units — the same rule
        check_setpoints() enforces, published as DATA so a client can warn while
        the operator types instead of hard-coding the policy and drifting from it.
        `min` is EXCLUSIVE (a setpoint must be strictly above it); `max` is
        INCLUSIVE. Both are stated so neither side has to guess at the edge.
        `max` is live: it tracks the specimen limit, which the operator can tighten
        mid-session. check_setpoints() remains the authority — this is the
        preview, not a second gate."""
        # Round the max DOWN, never to nearest: the published bound has to be a
        # value check_setpoints() actually accepts. In psi a 65 kPa limit is
        # 9.4274… and round() lifts it to 9.43, which converts back to 65.0035 and
        # gets rejected — so the UI would offer a maximum the server refuses. A
        # floored bound is at worst a hundredth conservative, which is the right
        # direction for a pressure limit.
        max_disp = math.floor(self.cfg.disp(self.pressure_limit_kpa()) * 100.0) / 100.0
        return {
            "min": 0.0,
            "min_inclusive": False,
            "max": max_disp,
            "max_inclusive": True,
            "units": self.cfg.units,
        }

    def check_setpoints(self, setpoints_kpa: List[float]) -> Optional[str]:
        """None if every setpoint is safe to run, else the reason it is not."""
        if not setpoints_kpa:
            return "no setpoints provided"
        limit = self.pressure_limit_kpa()
        u = self.cfg.units
        for sp in setpoints_kpa:
            if sp <= 0:
                return f"setpoint {self.cfg.disp(sp):.1f} {u} must be above zero"
            if sp > limit:
                return (f"setpoint {self.cfg.disp(sp):.1f} {u} exceeds the pressure "
                        f"limit of {self.cfg.disp(limit):.1f} {u}")
        return None

    def set_membrane_limit(self, limit_display: Optional[float]) -> dict:
        """Operator-set pressure limit for the specimen now in the vessel.
        Clamped by the safety cutoff — the UI can only ever tighten, never
        loosen, what the hardware layer allows."""
        with self._lock:
            if self._active:
                return {"ok": False, "error": "cannot change the limit mid-run"}
        if limit_display is None or float(limit_display) <= 0:
            self.playlist.membrane_limit_kpa = 0.0
        else:
            kpa = self.cfg.to_internal(float(limit_display))
            # Clamp to the CONFIGURED specimen limit, not just the global cutoff:
            # otherwise a value above it was accepted and stored while
            # pressure_limit_kpa() quietly kept using the smaller configured one,
            # so what the queue persisted was not what applied. Storing only what
            # actually binds keeps "the UI can only tighten" true of the stored
            # state too, not just of its effect.
            self.playlist.membrane_limit_kpa = min(kpa, self.cfg.specimen_limit_kpa())
        self.playlist.save()
        return {"ok": True, "limit": round(self.cfg.disp(self.pressure_limit_kpa()), 2)}

    # --- public API ----------------------------------------------------------
    def start_sequence(self, setpoints_display: List[float], *, tolerance_pct=None,
                       dwell_s=None, collection_s=None, stabilize_timeout_s=None,
                       kp=None, ki=None, kd=None) -> dict:
        setpoints_kpa = [self.cfg.to_internal(v) for v in setpoints_display]
        return self._begin(setpoints_kpa, tolerance_pct=tolerance_pct, dwell_s=dwell_s,
                           collection_s=collection_s,
                           stabilize_timeout_s=stabilize_timeout_s,
                           kp=kp, ki=ki, kd=kd)

    def _begin(self, setpoints_kpa: List[float], *, tolerance_pct=None,
               dwell_s=None, collection_s=None, stabilize_timeout_s=None,
               kp=None, ki=None, kd=None, item_id: Optional[str] = None) -> dict:
        with self._lock:
            if self._active:
                return {"ok": False, "error": "a test is already running"}
            problem = self.check_setpoints(setpoints_kpa)
            if problem:
                return {"ok": False, "error": problem}
            # Tighten the overpressure cutoff to what THIS run needs, so a low
            # test can never coast up to the global limit on a delicate mesh.
            # The specimen limit clamps it too (a fault must not exceed the mesh's
            # declared limit), so pass the live limit (config + playlist).
            ceiling = self.safety.arm_for_run(
                setpoints_kpa, specimen_limit_kpa=self.pressure_limit_kpa())
            if any(x is not None for x in (kp, ki, kd)):
                self.pid.set_gains(
                    kp if kp is not None else self.pid.kp,
                    ki if ki is not None else self.pid.ki,
                    kd if kd is not None else self.pid.kd,
                )
            self.pid.reset()
            self.safety.reset()
            self.history.clear()
            self._current_item_id = item_id
            self._fault_reason = ""
            self._finished = False
            self._collect_idx = None
            self._collect_vol_m3 = 0.0
            self._ramp_sp = None
            self._ramp_for = None
            self._wd_open_p = None
            self._wd_ticks = 0
            self._wd_rose = False
            self._held = False
            self._held_alarm = None
            self._awaiting_operator = False
            self.status["awaiting_operator"] = False
            self.status["awaiting_point"] = None
            self._hold_count = 0
            # A run always starts on point 0. Leaving this None meant a run that
            # holds on its FIRST tick (residual pressure from the previous item
            # already above the new ceiling) never recorded which point the hold
            # belonged to, so the first OK tick after a retry saw index != None and
            # zeroed the budget — the operator silently got an extra retry before
            # the three-strike backstop began counting.
            self._hold_point_idx = 0
            self._ceiling_raised = False
            self._raise_note = ""
            self._prev_p = None
            self._p_rate = 0.0
            self.status["ceiling_raised"] = False
            self.status["held"] = False
            self.status["held_alarm"] = None
            self._temp_sum = 0.0
            self._temp_n = 0
            self._run_temp_source = None
            self._close_check_until = 0.0
            self._close_warning = ""
            self.status["close_warning"] = ""
            self.analysis_result = None
            self.status["finished"] = False
            self.status["fault"] = ""
            self.status["analysis"] = None
            now = time.monotonic()
            self.sequencer.start(setpoints_kpa, now,
                                 tolerance_pct=tolerance_pct, dwell_s=dwell_s,
                                 collection_s=collection_s,
                                 stabilize_timeout_s=stabilize_timeout_s)
            run_name = self.logger.start_run(setpoints_kpa)
            self._run_start = now
            self._active = True
            # Publish immediately instead of waiting for the next tick, so a UI
            # that polls right after pressing play never sees a stale "idle".
            self.status["running"] = True
            self.status["phase"] = Phase.STABILIZING.value
            self.status["run_name"] = run_name
            self.status["run_ceiling_kpa"] = round(ceiling, 2)
            self.status["run_ceiling_disp"] = round(self.cfg.disp(ceiling), 2)
            # Which bound set the ceiling ("run ceiling" vs "specimen limit" vs
            # "safety cutoff"), so the operator sees when a run's real margin was
            # clamped below setpoint+overshoot instead of it happening silently.
            self.status["run_ceiling_source"] = self.safety.limit_name
            if item_id:
                self.playlist.update(item_id, status=RUNNING, run_name=run_name)
            return {"ok": True, "run_name": run_name,
                    "ceiling": round(self.cfg.disp(ceiling), 2),
                    "ceiling_source": self.safety.limit_name}

    # --- playlist ------------------------------------------------------------
    def play_next(self) -> dict:
        """Start the next pending experiment. Never called automatically — the
        queue only advances when the operator presses play, because between
        experiments they have to read and empty the graduated cylinder."""
        with self._lock:
            if self._active:
                return {"ok": False, "error": "a test is already running"}
        item = self.playlist.next_pending()
        if item is None:
            return {"ok": False, "error": "nothing pending in the playlist"}
        res = self._begin(list(item.setpoints_kpa),
                          tolerance_pct=item.tolerance_pct, dwell_s=item.dwell_s,
                          collection_s=item.collection_s,
                          stabilize_timeout_s=item.stabilize_timeout_s,
                          item_id=item.id)
        if res.get("ok"):
            res["item"] = item.id
            res["label"] = item.label
        return res

    def add_experiment(self, *, label: str, setpoints_display: List[float],
                       collection_s=None, dwell_s=None, tolerance_pct=None,
                       stabilize_timeout_s=None) -> dict:
        setpoints_kpa = [self.cfg.to_internal(float(v)) for v in setpoints_display]
        problem = self.check_setpoints(setpoints_kpa)
        if problem:
            return {"ok": False, "error": problem}
        t = self.cfg.test
        item = Experiment(
            label=label or "",
            setpoints_kpa=setpoints_kpa,
            collection_s=float(collection_s if collection_s is not None else t.collection_s),
            dwell_s=float(dwell_s if dwell_s is not None else t.dwell_s),
            tolerance_pct=float(tolerance_pct if tolerance_pct is not None else t.tolerance_pct),
            stabilize_timeout_s=float(stabilize_timeout_s if stabilize_timeout_s is not None
                                      else t.stabilize_timeout_s),
        )
        self.playlist.add(item)
        return {"ok": True, "id": item.id}

    def update_experiment(self, item_id: str, *, setpoints_display=None, **fields) -> dict:
        item = self.playlist.get(item_id)
        if item is None:
            return {"ok": False, "error": "no such experiment"}
        if item.status == RUNNING:
            return {"ok": False, "error": "that experiment is running"}
        if setpoints_display is not None:
            setpoints_kpa = [self.cfg.to_internal(float(v)) for v in setpoints_display]
            problem = self.check_setpoints(setpoints_kpa)
            if problem:
                return {"ok": False, "error": problem}
            fields["setpoints_kpa"] = setpoints_kpa
        self.playlist.update(item_id, **fields)
        return {"ok": True}

    def playlist_state(self) -> dict:
        limit_kpa = self.pressure_limit_kpa()
        items = []
        for i in self.playlist.items:
            items.append({
                "id": i.id, "label": i.label, "status": i.status,
                "setpoints": [round(self.cfg.disp(x), 2) for x in i.setpoints_kpa],
                "collection_s": i.collection_s, "dwell_s": i.dwell_s,
                "tolerance_pct": i.tolerance_pct,
                "stabilize_timeout_s": i.stabilize_timeout_s,
                "run_name": i.run_name, "note": i.note,
                "needs_volume": i.needs_volume(),
                # provenance: this run's ceiling was raised mid-test, so it is
                # excluded from the combined fit — the queue view needs to be able
                # to say which rows are out and why.
                "ceiling_raised": bool(i.ceiling_raised),
                "results": i.results,
            })
        nxt = self.playlist.next_pending()
        return {
            "items": items,
            "counts": self.playlist.counts(),
            "next_id": nxt.id if nxt else None,
            "units": self.cfg.units,
            "limit": round(self.cfg.disp(limit_kpa), 2),
            # the same rule check_setpoints() enforces, as data (see setpoint_bounds)
            "setpoint_bounds": self.setpoint_bounds(),
            "membrane_limit": (round(self.cfg.disp(self.playlist.membrane_limit_kpa), 2)
                               if self.playlist.membrane_limit_kpa else None),
            "safety_cutoff": round(self.cfg.disp(self.cfg.safety.max_pressure_kpa), 2),
            "overshoot_margin": round(self.cfg.disp(self.cfg.safety.overshoot_margin_kpa), 2),
            "points": len(self.playlist.collected_points()),
        }

    def set_item_volumes(self, item_id: str, volumes_ml) -> dict:
        """Attach measured volumes to a finished playlist item and recompute its
        flow rates. Works after the run has ended, which is the whole point of
        the pause between experiments."""
        item = self.playlist.get(item_id)
        if item is None:
            return {"ok": False, "error": "no such experiment"}
        entries = volumes_ml.items() if isinstance(volumes_ml, dict) else enumerate(volumes_ml)
        for i, v in entries:
            i = int(i)
            if not (0 <= i < len(item.results)):
                continue
            v = float(v)
            r = item.results[i]
            r["volume_ml"] = v
            cs = r.get("collection_s") or 0.0
            r["flow_m3s"] = (v * 1e-6 / cs) if cs > 0 else 0.0
        self.playlist.save()
        # keep the live sequencer results in step when it's the current item
        with self._lock:
            if self._current_item_id == item_id:
                live = self.sequencer.results
                for i, r in enumerate(item.results):
                    if i < len(live):
                        live[i].volume_ml = r.get("volume_ml", 0.0)
                        live[i].flow_m3s = r.get("flow_m3s", 0.0)
                self.status["results"] = [x.__dict__ for x in live]
        return {"ok": True}

    def stop(self, reason: str = "stopped by operator") -> dict:
        with self._lock:
            if not self._active:
                return {"ok": False, "error": "no test running"}
            self._end_run(reason)
            return {"ok": True}

    def get_status(self) -> dict:
        with self._lock:
            snap = dict(self.status)
            snap["history"] = list(self.history)
            item_id = self._current_item_id
        item = self.playlist.get(item_id) if item_id else None
        snap["item_id"] = item_id
        snap["item_label"] = item.label if item else ""
        snap["item_status"] = item.status if item else None
        snap["item_needs_volume"] = bool(item and item.needs_volume())
        snap["playlist"] = self.playlist.counts()
        nxt = self.playlist.next_pending()
        snap["next_label"] = nxt.label if nxt else None
        snap["next_setpoints"] = ([round(self.cfg.disp(x), 2) for x in nxt.setpoints_kpa]
                                  if nxt else None)
        snap["pressure_limit"] = round(self.cfg.disp(self.pressure_limit_kpa()), 2)
        return snap

    def set_volumes(self, volumes_ml) -> None:
        """Attach measured permeate volumes (mL) to completed points, keyed by
        point index. Used on hardware where the operator reads the graduated
        cylinder. dict{index: mL} or a list aligned to results order."""
        with self._lock:
            results = self.sequencer.results
            items = volumes_ml.items() if isinstance(volumes_ml, dict) else enumerate(volumes_ml)
            for i, v in items:
                i, v = int(i), float(v)
                if 0 <= i < len(results):
                    results[i].volume_ml = v
                    cs = results[i].collection_s
                    results[i].flow_m3s = (v * 1e-6 / cs) if cs > 0 else 0.0

    def compute_and_save_analysis(self) -> dict:
        """Fit Q vs ΔP over the collected points, derive Darcy k + pore size,
        and save runs/<run>_analysis.json (+ a PNG plot if matplotlib is
        present). Safe to call after a run, or after set_volumes() on hardware."""
        with self._lock:
            results = list(self.sequencer.results)
            title = self.cfg.analysis.title
            run_temp_c = (self._temp_sum / self._temp_n) if self._temp_n else self._water_temp_c
            temp_source = self._run_temp_source or self._temp_source
        # mu from the run-mean water temperature (distilled/pure water)
        mu = water_viscosity_pa_s(run_temp_c)
        membrane = dataclasses.replace(self.cfg.membrane, viscosity_pa_s=mu, water_temp_c=run_temp_c)
        points = [(r.mean_kpa, r.flow_m3s) for r in results if r.success and r.flow_m3s > 0]
        # Single-run provenance: this fit does NOT drop raised-ceiling points (it
        # never consults the queue), so any that exist are INSIDE the published k —
        # the worst case. Flag them so the plot says so. Same float objects as
        # `points` above, never recomputed: the export derives in/out by membership.
        flagged = [(r.mean_kpa, r.flow_m3s) for r in results
                   if r.success and r.flow_m3s > 0 and r.collected_under_raised_ceiling]
        result = fit_permeability(points, membrane)
        self.analysis_result = result
        json_path = self.logger.save_analysis(result.as_dict())
        plot_path = None
        # logger.plot_path()/xlsx_path() are None when no run is open (reachable on
        # hardware: set_volumes + analyse after a server restart). Don't ask for an
        # artefact we have nowhere to put — the callees now refuse too, but the
        # path that gets here is ours.
        have_run = self.logger.plot_path() is not None
        if have_run and self.cfg.analysis.auto_plot and plot_available() and result.n >= 2:
            try:
                plot_path = plot_permeability(result, self.logger.plot_path(),
                                              title=title, units="kPa",
                                              flagged_points=flagged or None)
            except Exception:
                plot_path = None
        xlsx_path = None
        if self.logger.xlsx_path() is not None and xlsx_available() and result.n >= 1:
            try:
                # per-row provenance for the export (single-run path: the flag comes
                # from runtime state, not the playlist — nothing is excluded here,
                # the single-run fit doesn't consult the queue)
                item = self.playlist.get(self._current_item_id) if self._current_item_id else None
                detail = []
                for r in results:
                    row = dict(r.__dict__)
                    row["ceiling_raised"] = self._ceiling_raised
                    row["experiment_id"] = item.id if item else ""
                    row["experiment_label"] = item.label if item else ""
                    detail.append(row)
                xlsx_path = export_permeability_xlsx(
                    result, self.logger.xlsx_path(), title=title, units="kPa",
                    points_detail=detail, water_temp_source=temp_source)
            except Exception:
                xlsx_path = None
        summary = {
            "n": result.n,
            "slope_per_kpa": result.slope_per_kpa,
            "intercept_m3s": result.intercept_m3s,
            "r2": result.r2,
            "k_darcy_m2": result.k_darcy_m2,
            # Uncertainty of k, from the standard error of the fitted slope. R^2
            # says the points lie on a line; it does NOT say how well pinned that
            # line's slope is, and k is only worth what the slope is worth.
            # None (not 0.0) when n < 3: with no residual degrees of freedom the
            # error is UNKNOWN, and rendering it as "+/- 0" would claim a precision
            # that was never measured.
            "k_stderr_m2": result.k_stderr_m2 if result.n >= 3 else None,
            # `> 0`, not just truthy: k CAN come out negative (a leak that opens up
            # with pressure gives Q falling with dP -> negative slope). k_stderr_m2
            # is always >= 0, so se/k would report a negative standard error —
            # nonsense to render. The absolute error still stands; only the
            # percentage loses meaning. Same k > 0 guard pore_size_m already uses.
            "k_stderr_pct": (result.k_stderr_m2 / result.k_darcy_m2 * 100.0
                             if result.n >= 3 and result.k_darcy_m2 > 0 else None),
            "pore_size_um": result.pore_size_m * 1e6,
            "follows_darcy": result.follows_darcy,
            "label": result.label,
            "note": result.note,
            "water_temp_c": round(run_temp_c, 2),
            # k = b*mu*L/A and mu comes from this temperature, so the k inherits
            # however the temperature was obtained. Carry that with it: a k whose
            # mu came from a configured constant is not the same evidence as one
            # from a probe reading, and the number alone cannot say which.
            "water_temp_source": temp_source,
            "viscosity_pa_s": mu,
            "json_file": Path(json_path).name if json_path else None,
            "plot_file": Path(plot_path).name if plot_path else None,
            "xlsx_file": Path(xlsx_path).name if xlsx_path else None,
        }
        with self._lock:
            self.status["analysis"] = summary
        return summary

    def analyze_playlist(self) -> dict:
        """Fit Q vs ΔP across every completed experiment in the queue.

        The queue is normally one specimen measured at several pressures, split
        into separately-gated runs, so the combined fit — not the per-run one —
        is the deliverable. Points come from items marked done that have a
        measured volume."""
        points = self.playlist.collected_points()
        # The pairs the fit dropped, so the plot can DRAW them greyed instead of
        # letting them vanish silently. Built from the same Experiment.points() the
        # fit uses, so the values are identical floats.
        excluded = [p for i in self.playlist.items
                    if i.status == DONE and i.ceiling_raised for p in i.points()]
        with self._lock:
            run_temp_c = (self._temp_sum / self._temp_n) if self._temp_n else self._water_temp_c
            temp_source = self._run_temp_source or self._temp_source
        mu = water_viscosity_pa_s(run_temp_c)
        membrane = dataclasses.replace(self.cfg.membrane, viscosity_pa_s=mu,
                                       water_temp_c=run_temp_c)
        result = fit_permeability(points, membrane)
        base = Path(self.cfg.logging.dir) / "playlist_latest"
        base.parent.mkdir(parents=True, exist_ok=True)
        files = {}
        try:
            p = base.with_name("playlist_latest_analysis.json")
            p.write_text(json.dumps(result.as_dict(), indent=2))
            files["json_file"] = p.name
        except Exception:
            pass
        if self.cfg.analysis.auto_plot and plot_available() and result.n >= 2:
            try:
                files["plot_file"] = Path(plot_permeability(
                    result, base.with_name("playlist_latest_plot.png"),
                    title=self.cfg.analysis.title, units="kPa",
                    excluded_points=excluded or None)).name
            except Exception:
                pass
        if xlsx_available() and result.n >= 1:
            try:
                # Per-ROW provenance: this sheet mixes points from several runs, so
                # a scalar can't label it. Every row carries its run's
                # ceiling_raised flag (+ id/label to group by), which is how a k
                # from a raised-ceiling run stays visible in Excel instead of just
                # silently missing from the fit.
                detail = []
                for i in self.playlist.items:
                    if i.status != DONE:
                        continue
                    for r in i.results:
                        row = dict(r)
                        row["ceiling_raised"] = bool(i.ceiling_raised)
                        row["experiment_id"] = i.id
                        row["experiment_label"] = i.label
                        detail.append(row)
                files["xlsx_file"] = Path(export_permeability_xlsx(
                    result, base.with_name("playlist_latest_results.xlsx"),
                    title=self.cfg.analysis.title, units="kPa",
                    points_detail=detail, water_temp_source=temp_source)).name
            except Exception:
                pass
        summary = {
            "n": result.n,
            "slope_per_kpa": result.slope_per_kpa,
            "intercept_m3s": result.intercept_m3s,
            "r2": result.r2,
            "k_darcy_m2": result.k_darcy_m2,
            # Uncertainty of k, from the standard error of the fitted slope. R^2
            # says the points lie on a line; it does NOT say how well pinned that
            # line's slope is, and k is only worth what the slope is worth.
            # None (not 0.0) when n < 3: with no residual degrees of freedom the
            # error is UNKNOWN, and rendering it as "+/- 0" would claim a precision
            # that was never measured.
            "k_stderr_m2": result.k_stderr_m2 if result.n >= 3 else None,
            # `> 0`, not just truthy: k CAN come out negative (a leak that opens up
            # with pressure gives Q falling with dP -> negative slope). k_stderr_m2
            # is always >= 0, so se/k would report a negative standard error —
            # nonsense to render. The absolute error still stands; only the
            # percentage loses meaning. Same k > 0 guard pore_size_m already uses.
            "k_stderr_pct": (result.k_stderr_m2 / result.k_darcy_m2 * 100.0
                             if result.n >= 3 and result.k_darcy_m2 > 0 else None),
            "pore_size_um": result.pore_size_m * 1e6,
            "follows_darcy": result.follows_darcy,
            "label": result.label,
            "note": result.note,
            "water_temp_c": round(run_temp_c, 2),
            # k = b*mu*L/A and mu comes from this temperature, so the k inherits
            # however the temperature was obtained. Carry that with it: a k whose
            # mu came from a configured constant is not the same evidence as one
            # from a probe reading, and the number alone cannot say which.
            "water_temp_source": temp_source,
            "viscosity_pa_s": mu,
            **files,
        }
        with self._lock:
            self.status["playlist_analysis"] = summary
        return summary

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=2.0)
        self._temp_thread.join(timeout=2.0)
        self._safe_all()
        for dev in (self.valve, self.diverter, self.sensor, self.temp):
            try:
                dev.close()
            except Exception:
                pass

    # --- internals -----------------------------------------------------------
    def _flow_increment(self) -> float:
        """Permeate volume (m^3) collected this tick. Sim integrates the plant's
        flow; on hardware there's no flow sensor so this is 0 (volume entered
        manually afterwards)."""
        if self.plant is not None and hasattr(self.plant, "flow_m3s"):
            return self.plant.flow_m3s() * self._dt
        return 0.0

    def _accumulate_volume(self, seq, prev_n: int) -> None:
        """Integrate permeate volume over the collection window and attach it to
        the point's result the moment the sequencer finalises that collection."""
        if seq.phase == Phase.COLLECTING:
            if self._collect_idx != seq.index:
                self._collect_idx = seq.index
                self._collect_vol_m3 = 0.0
            self._collect_vol_m3 += self._flow_increment()
        # stamp per-point provenance on every result the moment it is finalised
        if len(self.sequencer.results) > prev_n:
            self.sequencer.results[-1].collected_under_raised_ceiling = self._ceiling_raised
        # a result was just finalised AND we were mid-collection -> attach volume
        if len(self.sequencer.results) > prev_n and self._collect_idx is not None:
            r = self.sequencer.results[-1]
            r.volume_ml = self._collect_vol_m3 * 1e6  # m^3 -> mL
            if r.collection_s > 0:
                r.flow_m3s = self._collect_vol_m3 / r.collection_s
            self._collect_idx = None
            self._collect_vol_m3 = 0.0

    def _pid_target(self, setpoint_kpa: float, pressure_kpa: float) -> float:
        """Ramped PID target. Approaching each setpoint from the current pressure
        at test.ramp_kpa_s keeps the integrator calm and avoids overshoot — which
        matters because the plant can't shed pressure quickly (permeation-only
        fall). The sequencer's in-band/dwell logic still uses the TRUE setpoint."""
        rate = self.cfg.test.ramp_kpa_s
        if rate <= 0:
            return setpoint_kpa
        if self._ramp_for != setpoint_kpa:
            self._ramp_for = setpoint_kpa
            self._ramp_sp = pressure_kpa  # start the ramp where the plant is now
        step = rate * self._dt
        if self._ramp_sp < setpoint_kpa:
            self._ramp_sp = min(setpoint_kpa, self._ramp_sp + step)
        else:
            self._ramp_sp = max(setpoint_kpa, self._ramp_sp - step)
        return self._ramp_sp

    def _plant_watchdog(self, command: float, pressure: float) -> Optional[str]:
        """Detector B: has the loop LOST authority over pressure? If the valve is
        pinned open (>= watchdog_valve_pct) for watchdog_hold_s and pressure never
        rose watchdog_min_rise from where it sat when the valve pinned, the loop is
        commanding pressure up and nothing is happening — a stuck valve, a shut
        supply, or a sensor stuck LOW while the real cell climbs (the frozen-signal
        detector catches the *frozen* variant; this catches a stuck-low reading
        that still carries noise). Integrated, not dP/dt: a legitimate plateau
        below an unreachable setpoint ROSE first, so it sets _wd_rose and is left
        to stabilize_timeout; only a plant that never responded fires. Returns a
        fault reason or None. It is safe on any *measurable* specimen — to hold
        even the lowest setpoint a sample must build far more than min_rise, so the
        only things that fire are a real fault or an unmeasurable (super-permeable)
        sample that could not be tested anyway. Lock held."""
        if self._wd_hold_ticks <= 0:
            return None
        # A non-finite reading is a GAP, not a sample: without this, one NaN taken
        # as the baseline makes every later `pressure - baseline` comparison NaN
        # (never >= min_rise), so _wd_rose can never latch and the watchdog
        # false-fires "plant unresponsive" for the rest of the run — even while
        # pressure is climbing perfectly well. Same contract as pid.update and
        # _Accum.add: an unusable read advances nothing.
        if not math.isfinite(pressure):
            return None
        if command >= self._wd_valve_pct:
            if self._wd_open_p is None:
                self._wd_open_p = pressure
                self._wd_ticks = 0
                self._wd_rose = False
            self._wd_ticks += 1
            if pressure - self._wd_open_p >= self._wd_min_rise:
                self._wd_rose = True
            if self._wd_ticks >= self._wd_hold_ticks and not self._wd_rose:
                return (
                    f"plant unresponsive: valve at {command:.0f}% for "
                    f"{self._wd_ticks * self._dt:.0f} s but pressure held near "
                    f"{pressure:.1f} kPa (stuck valve / shut supply / sensor stuck low)"
                )
        else:
            self._wd_open_p = None
            self._wd_ticks = 0
            self._wd_rose = False
        return None

    def _abort_fault(self, reason: str, now: float, pressure: float,
                     index: int = 0, total: int = 0) -> None:
        """Hard fault: vent-safe, abort the sequencer, end the run. NOT
        recoverable — used for plant/sensor faults where retrying can't help.
        Lock held."""
        self._fault_reason = reason
        self._safe_all()
        if self._active:
            self.sequencer.abort(reason, now)
            self._end_run(reason)
        self.status["fault"] = reason
        self._update_status(pressure, None, 0.0, False, Phase.DONE, index, total,
                            now - self._run_start, 0.0, in_band=False)

    # A hit is classified "runaway" (retry is the WRONG move) when pressure is
    # still climbing while the loop is already commanding the valve (near) shut —
    # the signature of a stuck valve or a lying sensor. Anything else is a plain
    # overshoot, where retrying the point is reasonable. Advisory only: it drives
    # the alarm text and the Retry button, never an abort.
    _RUNAWAY_RISE_KPA_S = 0.5
    _RUNAWAY_VALVE_PCT = 20.0

    # Missed poll periods before a probe stops being reported as "measured".
    # A label, not a safety threshold — it gates nothing, so it lives here rather
    # than adding config surface. 3 periods = 9 s at the default read_period_s.
    _TEMP_STALE_PERIODS = 3

    def _track_rate(self, pressure: float) -> None:
        """Filtered dP/dt, used only to tell a normal overshoot from a runaway when
        a ceiling is hit. Same filter constant as the PID's derivative. Lock held."""
        if pressure != pressure:            # NaN: no information, keep the estimate
            return
        if self._prev_p is not None:
            raw = (pressure - self._prev_p) / self._dt
            alpha = self._dt / (0.3 + self._dt)
            self._p_rate += alpha * (raw - self._p_rate)
        self._prev_p = pressure

    def _raise_cap_kpa(self) -> float:
        """Highest ceiling the operator may raise to. 0 in config = raising is
        DISABLED (the born-inert default), signalled by returning the current
        ceiling: the UI sees raise_max <= ceiling and greys the button out. A
        positive cap is still clamped to the specimen limit and the global cutoff,
        so a raise can never exceed what the mesh was declared to tolerate."""
        configured = self.cfg.safety.operator_raise_max_kpa
        if not configured or configured <= 0:
            return self.safety.max_pressure          # no raise possible
        return min(configured, self.pressure_limit_kpa(), self.cfg.safety.max_pressure_kpa)

    def _retry_possible(self, severity: Optional[str] = None,
                        pressure: Optional[float] = None) -> tuple:
        """SINGLE SOURCE OF TRUTH for the alarm's `retry_advised`: "would the Retry
        button do anything if it were tapped?". The UI keys the button off this
        flag alone and must never re-derive the policy in JS — if it looks alive,
        tapping it works. Returns (possible, why_not).

        Note the asymmetry, which is deliberate: a "runaway" classification makes
        retry NOT advised (the UI disables the button), but recover_retry() itself
        still honours an explicit call, because that classification is a heuristic
        and an operator who has physically gone and fixed the rig must not be
        hard-blocked by it. What must never happen is the reverse — advised=True
        and the call rejecting."""
        if not self._held:
            return False, "the rig is not waiting at a ceiling"
        if self._hold_count >= self._retry_max:
            return False, (f"no retries left ({self._hold_count}/{self._retry_max}) — "
                           f"something physical needs checking")
        if severity == "runaway":
            return False, ("pressure is still rising with the valve commanded shut — "
                           "check the rig instead of retrying")
        # Retrying while pressure is STILL above the ceiling cannot work: the very
        # next tick re-trips OVERPRESSURE, burns a retry, and re-holds — the button
        # appears to do nothing, and three taps end the run for "a physical
        # problem" when nothing physical is wrong. The cell only bleeds down
        # through the membrane (~0.05 kPa/s), so this can take tens of seconds.
        # Gate it, and let it come alive on its own as pressure falls.
        if pressure is not None:
            if not math.isfinite(pressure):
                return False, "the sensor reading is not usable right now"
            if pressure >= self.safety.max_pressure:
                u = self.cfg.units
                return False, (f"pressure is still at {self.cfg.disp(pressure):.1f} {u}, "
                               f"at or above the {self.cfg.disp(self.safety.max_pressure):.1f} "
                               f"{u} ceiling — wait for it to bleed down")
        return True, ""

    def _refresh_held_alarm(self, pressure: float) -> None:
        """Re-evaluate the DYNAMIC parts of a live alarm each held tick. Pressure
        bleeds down while the rig waits, so the Retry button has to come alive by
        itself once retrying could actually succeed — a frozen alarm would either
        block retry forever or invite a tap that cannot work. `severity` stays
        frozen on purpose: it describes the moment of the hit. Lock held."""
        if not self._held_alarm:
            return
        ok, why = self._retry_possible(self._held_alarm.get("severity"), pressure)
        self._held_alarm["retry_advised"] = ok
        self._held_alarm["retry_blocked_reason"] = why
        self._held_alarm["pressure_now"] = round(self.cfg.disp(pressure), 2)

    def _enter_held(self, now: float, pressure: float, reason: str) -> None:
        """Stop to safe at the run ceiling and wait for the operator instead of
        ending the run. The feed is SHUT here and stays shut every held tick — the
        rig is safe while it waits, which is why waiting forever is acceptable and
        why nothing auto-retries or auto-raises: deciding at a safety boundary with
        nobody watching is exactly what we don't want. Lock held."""
        self._safe_all()
        self._held = True
        runaway = (self._p_rate > self._RUNAWAY_RISE_KPA_S
                   and self.pid.last_output <= self._RUNAWAY_VALVE_PCT)
        severity = "runaway" if runaway else "overshoot"
        if runaway:
            advice = ("Pressure is still RISING while the valve is being commanded shut. "
                      "Do NOT retry — that would repeat the excursion. Check the rig "
                      "physically: a stuck valve, a stuck sensor, or supply that isn't "
                      "shutting off.")
        else:
            advice = ("Normal overshoot past the ceiling. Retrying this point is "
                      "reasonable; the feed is shut and pressure is bleeding down.")
        cap = self._raise_cap_kpa()
        d = self.cfg.disp
        # every field is populated here, under the lock, at the same time as
        # status["held"] — the UI is guaranteed a COMPLETE alarm whenever held is
        # true, so a missing field can safely be treated as "assume the worst".
        sp_kpa = self.sequencer.current_setpoint_kpa()
        retry_ok, retry_why = self._retry_possible(severity, pressure)
        if not retry_ok and retry_why and not runaway:
            advice = f"{advice} {retry_why.capitalize()}."
        self._held_alarm = {
            "setpoint": round(d(sp_kpa), 2) if sp_kpa is not None
                        else self.status.get("setpoint_disp"),
            "ceiling": round(d(self.safety.max_pressure), 2),
            "ceiling_source": self.safety.limit_name,
            "pressure_reached": round(d(pressure), 2),
            "layer": reason,
            "retry_n": self._hold_count,
            "retry_max": self._retry_max,
            "raise_max": round(d(cap), 2),
            "severity": severity,          # tone of the screen (frozen at the hit)
            "retry_advised": retry_ok,     # the Retry button keys off THIS alone
            "retry_blocked_reason": retry_why,   # why it is off, refreshed each tick
            "pressure_now": round(d(pressure), 2),
            "recommendation": advice,
            "units": self.cfg.units,
        }
        self.status["held"] = True
        self.status["held_alarm"] = self._held_alarm

    def _exit_held(self) -> None:
        """Leave the held state (retry / raise / stop / hard abort). Lock held."""
        self._held = False
        self._held_alarm = None
        self.status["held"] = False
        self.status["held_alarm"] = None

    def _resume_point(self, now: float) -> None:
        """Common tail of retry and raise: restart the CURRENT point from scratch.
        The partial collection is discarded (it carries the excursion, and that
        pressure record is what produces k), and the PID + ramp are reset so the
        loop re-approaches from wherever the cell is now instead of resuming with a
        wound-up integrator. Lock held."""
        self.sequencer.restart_current_point(now)
        self.pid.reset()
        self.safety.reset()
        self._ramp_sp = None
        self._ramp_for = None
        self._wd_open_p = None
        self._wd_ticks = 0
        self._wd_rose = False
        self._collect_idx = None
        self._collect_vol_m3 = 0.0
        self._prev_p = None
        self._p_rate = 0.0
        self._exit_held()

    def _enter_point_pause(self, now: float, pressure: float, done_points: int) -> None:
        """Seal the feed and wait for the operator between points. NOT an alarm:
        nothing is wrong, the permeate simply cannot be weighed while flow is still
        arriving. Uses _safe_all (full_close, not to_safe) because a seat is what
        is wanted here, and re-asserts it every paused tick. Lock held."""
        self._safe_all()
        self._awaiting_operator = True
        self.status["awaiting_operator"] = True
        self.status["awaiting_point"] = done_points   # 1-based: which point to weigh

    def resume_next_point(self) -> dict:
        """Operator has weighed the permeate; carry on with the next point."""
        with self._lock:
            if not self._awaiting_operator:
                return {"ok": False, "error": "the rig is not waiting between points"}
            # restart the (already advanced) point so its stabilisation clock
            # starts now, not when the previous point ended
            self._resume_point(time.monotonic())
            self._awaiting_operator = False
            self.status["awaiting_operator"] = False
            self.status["awaiting_point"] = None
            return {"ok": True, "action": "resume"}

    # --- operator recovery actions -------------------------------------------
    def recover_retry(self) -> dict:
        """Re-run the point that hit the ceiling, same ceiling."""
        with self._lock:
            if not self._held:
                return {"ok": False, "error": "the rig is not waiting at a ceiling"}
            if self._hold_count >= self._retry_max:
                return {"ok": False, "error": f"no retries left "
                                              f"({self._hold_count}/{self._retry_max})"}
            # Refuse while pressure is still at/above the ceiling: the retry would
            # re-trip on the next tick and burn the budget for nothing. This one IS
            # enforced (unlike the runaway advisory) because no operator action can
            # make it work — only time.
            p_now = self.status.get("pressure_kpa")
            if p_now is not None and math.isfinite(p_now) and p_now >= self.safety.max_pressure:
                u = self.cfg.units
                return {"ok": False,
                        "error": (f"pressure is still {self.cfg.disp(p_now):.1f} {u}, at or "
                                  f"above the {self.cfg.disp(self.safety.max_pressure):.1f} {u} "
                                  f"ceiling — wait for it to bleed down before retrying")}
            # NOTE: a "runaway" classification is not rejected here on purpose —
            # see _retry_possible. The UI hides the button; an operator who went
            # and fixed the rig is not hard-blocked by a heuristic.
            self._resume_point(time.monotonic())
            return {"ok": True, "action": "retry"}

    def recover_raise(self, new_ceiling_display: float) -> dict:
        """Raise this run's ceiling (never above the cap) and re-run the point.
        Marks the run as ceiling-raised: it saw pressure the mesh was not declared
        to tolerate, so its k is provenance-tagged and excluded from the combined
        fit."""
        with self._lock:
            if not self._held:
                return {"ok": False, "error": "the rig is not waiting at a ceiling"}
            cap = self._raise_cap_kpa()
            if not self.cfg.safety.operator_raise_max_kpa > 0:
                return {"ok": False, "error": "raising the ceiling is disabled in config "
                                              "(safety.operator_raise_max = 0)"}
            new_kpa = self.cfg.to_internal(float(new_ceiling_display))
            u = self.cfg.units
            if new_kpa <= self.safety.max_pressure:
                return {"ok": False, "error": f"{self.cfg.disp(new_kpa):.1f} {u} is not above "
                                              f"the current ceiling"}
            if new_kpa > cap:
                return {"ok": False, "error": f"{self.cfg.disp(new_kpa):.1f} {u} exceeds the "
                                              f"maximum allowed raise of {self.cfg.disp(cap):.1f} {u}"}
            old = self.safety.max_pressure
            self.safety.max_pressure = new_kpa
            self.safety.limit_name = "raised ceiling"
            self._ceiling_raised = True
            self.status["run_ceiling_kpa"] = round(new_kpa, 2)
            self.status["run_ceiling_disp"] = round(self.cfg.disp(new_kpa), 2)
            self.status["run_ceiling_source"] = "raised ceiling"
            self.status["ceiling_raised"] = True
            # Provenance, through the channels this module owns: the playlist item
            # flag (which excludes the run from the combined fit and reaches the
            # export), plus a note that lands in the run's CSV footer via
            # _end_run -> logger.finish_run(status_note=...).
            self._raise_note = (f"ceiling raised by operator {self.cfg.disp(old):.1f} -> "
                                f"{self.cfg.disp(new_kpa):.1f} {u}")
            if self._current_item_id:
                try:
                    self.playlist.update(self._current_item_id, ceiling_raised=True,
                                         note=self._raise_note)
                except Exception:
                    pass
            self._resume_point(time.monotonic())
            return {"ok": True, "action": "raise",
                    "ceiling": round(self.cfg.disp(new_kpa), 2)}

    def recover_stop(self) -> dict:
        """End the run from the held state."""
        with self._lock:
            if not self._held:
                return {"ok": False, "error": "the rig is not waiting at a ceiling"}
            self._exit_held()
            self._end_run("stopped by operator at the ceiling")
            return {"ok": True, "action": "stop"}

    def _temp_loop(self) -> None:
        """Poll the water-temperature probe slowly (blocking reads are fine here,
        off the fast control loop). Cache the latest good reading + its viscosity."""
        base = getattr(self.temp, "source", "unknown")
        while not self._stop_evt.is_set():
            ok = False
            try:
                t = self.temp.read_c()
                if t == t:  # not NaN
                    mu = water_viscosity_pa_s(t)
                    ok = True
                    with self._lock:
                        self._water_temp_c = t
                        self.status["water_temp_c"] = round(t, 2)
                        self.status["viscosity_pa_s"] = mu
                    if self.plant is not None and hasattr(self.plant, "set_viscosity"):
                        self.plant.set_viscosity(mu)
            except Exception:
                pass
            # A probe that stops answering is swallowed here by design (one bad
            # read must not disturb a run), but then water_temp_c silently keeps
            # its last value — and µ, hence k, would still be presented as
            # measured. Say so instead: the number stays, its provenance changes.
            #
            # Only after a GRACE, though: `source` is a static class attribute, so
            # staleness can only be judged here, and flipping on the first missed
            # read would paint the screen red for an isolated 1-Wire CRC error —
            # a noisy warning is one that gets ignored. Water temperature moves
            # slowly (µ shifts ~2.4 %/°C), so a few seconds of holding the last
            # good value is honest as long as we stop calling it "measured" once
            # it really has gone quiet. NOT a fault: unlike pressure, a stale
            # temperature must never abort a run — it is a provenance problem.
            now_m = time.monotonic()
            if ok:
                self._temp_last_good = now_m
            stale_after = self._TEMP_STALE_PERIODS * max(0.1, self.cfg.temperature.read_period_s)
            age = (now_m - self._temp_last_good) if self._temp_last_good else float("inf")
            with self._lock:
                self._temp_source = base if (base != "probe" or age <= stale_after) \
                    else "probe (no recent reading)"
                self.status["water_temp_source"] = self._temp_source
            self._stop_evt.wait(self.cfg.temperature.read_period_s)

    def _safe_all(self) -> None:
        """Shut the feed and route permeate to waste.

        Uses full_close(), not to_safe(): 0% command is the bottom of the
        regulating range, which is not necessarily a sealed valve. When a test
        ends — or faults — the feed has to be properly shut, otherwise the
        specimen sits pressurised with nobody watching."""
        try:
            self.valve.full_close()
        except Exception:
            try:
                self.valve.to_safe()
            except Exception:
                pass
        try:
            self.diverter.to_safe()
        except Exception:
            pass

    def _start_close_check(self, pressure_kpa: float) -> None:
        """Arm the post-run check that the valve actually seated. Lock held."""
        self._close_warning = ""
        self.status["close_warning"] = ""
        if self.cfg.safety.close_check_s <= 0 or pressure_kpa < 5.0:
            self._close_check_until = 0.0     # nothing meaningful to verify
            return
        self._close_check_p0 = pressure_kpa
        self._close_check_until = time.monotonic() + self.cfg.safety.close_check_s

    def _run_close_check(self, now: float, pressure_kpa: float) -> None:
        """With the feed shut, pressure must fall (it bleeds through the
        membrane). If it hasn't, the valve did not seat. Lock held."""
        if not self._close_check_until or now < self._close_check_until:
            return
        self._close_check_until = 0.0
        drop = self._close_check_p0 - pressure_kpa
        if drop < self.cfg.safety.close_check_min_drop_kpa:
            u = self.cfg.units
            self._close_warning = (
                f"valve may not have closed: pressure only fell "
                f"{self.cfg.disp(drop):.2f} {u} in "
                f"{self.cfg.safety.close_check_s:.0f} s "
                f"(now {self.cfg.disp(pressure_kpa):.1f} {u}). "
                f"Check the valve and shut the supply by hand."
            )
            self.status["close_warning"] = self._close_warning

    def _end_run(self, reason: str) -> None:
        """Must be called with the lock held."""
        self._safe_all()              # feed fully shut, diverter to waste
        self.safety.disarm()          # idle again: back to the global cutoff
        self._exit_held()             # a run can't stay 'held' once it has ended
        self._awaiting_operator = False
        self.status["awaiting_operator"] = False
        self.status["awaiting_point"] = None
        self._start_close_check(self.status.get("pressure_kpa", 0.0))
        # Provenance rides along into the run's CSV footer: a k from a run whose
        # ceiling was raised must be traceable in the artefacts, not just in RAM.
        note = f"{reason}; {self._raise_note}" if self._raise_note else reason
        try:
            # Pass the parameters THIS run resolved, not config's: a playlist item
            # carries its own, so quoting the defaults would put a meta beside its
            # own results contradicting them. (collection_s the logger derives from
            # the results; these two no TestResult carries.)
            self.logger.finish_run(self.sequencer.results, status_note=note,
                                   tolerance_pct=self.sequencer.tolerance_pct,
                                   dwell_s=self.sequencer.dwell_s)
        except Exception:
            pass
        self.logger.close()
        self._active = False
        self._finished = True
        results = [r.__dict__ for r in self.sequencer.results]
        # Record the outcome on the playlist item and STOP. The queue never
        # advances by itself — the operator has a cylinder to read and empty.
        if self._current_item_id:
            try:
                # keep the raise note even on a clean finish — it is provenance,
                # not an error message, so "completed" must not erase it.
                item_note = "" if reason == "completed" else reason
                # A stopped/failed item keeps whatever points it already measured,
                # but collected_points() only counts DONE items — so those good
                # points sit outside the combined fit until someone says so. Tell
                # the operator how to get them back, right where they'll see it:
                # re-queueing RE-RUNS the experiment, marking it done recovers it.
                kept = sum(1 for r in results if r.get("success"))
                if reason != "completed" and kept:
                    item_note = (f"{item_note}; {kept} measured point(s) kept — mark this "
                                 f"item done to include them in the combined fit "
                                 f"(re-queueing re-runs it instead)")
                if self._raise_note:
                    item_note = f"{item_note}; {self._raise_note}" if item_note else self._raise_note
                self.playlist.update(
                    self._current_item_id,
                    status=DONE if reason == "completed" else FAILED,
                    note=item_note,
                    results=[dict(r) for r in results],
                )
            except Exception:
                pass
        self.status["running"] = False
        self.status["finished"] = True
        self.status["phase"] = self.sequencer.phase.value
        self.status["valve_command"] = 0.0
        self.status["diverter_measured"] = False
        self.status["results"] = results

    def _loop(self) -> None:
        next_t = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            try:
                self._tick(now)
            except Exception as exc:  # never let the loop die silently
                with self._lock:
                    self._fault_reason = f"control loop exception: {exc!r}"
                    self._safe_all()
                    if self._active:
                        self.sequencer.abort(self._fault_reason, now)
                        self._end_run(self._fault_reason)
                    self.status["fault"] = self._fault_reason
            next_t += self._dt
            sleep = next_t - time.monotonic()
            if sleep > 0:
                self._stop_evt.wait(sleep)
            else:
                next_t = time.monotonic()  # we fell behind; resync

    def _tick(self, now: float) -> None:
        reading = self.sensor.read()
        state, reason = self.safety.check(reading)

        with self._lock:
            pressure = reading.pressure_kpa
            self._track_rate(pressure)

            # --- held at a ceiling: feed already shut, waiting for the operator ---
            if self._held:
                self._safe_all()      # keep it shut for as long as we wait
                # A runaway must NEVER hide behind a screen waiting for a human:
                # while held we still watch the layers that are not recoverable —
                # the GLOBAL cutoff and sensor faults. Reaching either here is a
                # hard vent-abort with no recovery offered. (The run-ceiling
                # OVERPRESSURE that put us here keeps repeating as pressure bleeds
                # down; that one is already answered, so it is ignored.)
                if state == SafetyState.SENSOR_FAULT:
                    self._exit_held()
                    self._abort_fault(f"{state.value}: {reason}", now, pressure)
                elif pressure >= self.safety.hard_max:
                    self._exit_held()
                    self._abort_fault(
                        f"overpressure: {pressure:.1f} kPa reached the global cutoff "
                        f"{self.safety.hard_max:.1f} kPa while held", now, pressure)
                else:
                    self._refresh_held_alarm(pressure)
                    self._update_status(pressure, None, 0.0, False,
                                        self.sequencer.phase, self._final_index,
                                        self._final_total, now - self._run_start, 0.0,
                                        in_band=False)
                if self.plant is not None:
                    self.plant.step(self._dt)
                return

            # --- paused between points: feed sealed, waiting to be weighed ---
            if self._awaiting_operator:
                self._safe_all()      # keep it SHUT for as long as we wait
                self._update_status(pressure, None, 0.0, False,
                                    self.sequencer.phase, self.status.get("index", 0),
                                    self.status.get("total", 0), now - self._run_start,
                                    0.0, in_band=False)
                if self.plant is not None:
                    self.plant.step(self._dt)
                return

            if state != SafetyState.OK:
                # A RUN-ceiling overpressure is recoverable: stop to safe, alarm,
                # and let the operator decide. The global cutoff and sensor faults
                # are not — those always vent and end the run.
                ceiling_bound = self.safety.max_pressure < self.safety.hard_max
                if (self._active and state == SafetyState.OVERPRESSURE
                        and ceiling_bound and pressure < self.safety.hard_max):
                    self._hold_count += 1
                    if self._hold_count < self._retry_max:
                        self._enter_held(now, pressure, reason)
                        self._update_status(pressure, None, 0.0, False,
                                            self.sequencer.phase, 0, 0,
                                            now - self._run_start, 0.0, in_band=False)
                        if self.plant is not None:
                            self.plant.step(self._dt)
                        return
                    # repeated hits on the same point: something physical is wrong
                    reason = (f"{reason} — hit {self._hold_count} times on this point; "
                              f"stopping instead of retrying. Check the rig.")
                self._fault_reason = f"{state.value}: {reason}"
                self._safe_all()
                if self._active:
                    self.sequencer.abort(self._fault_reason, now)
                    self._end_run(self._fault_reason)
                self.status["fault"] = self._fault_reason
                self._update_status(pressure, None, 0.0, False,
                                    Phase.IDLE if not self._active else self.sequencer.phase,
                                    0, 0, 0.0, 0.0, in_band=False)
                if self.plant is not None:
                    self.plant.step(self._dt)
                return

            if self._active:
                prev_n = len(self.sequencer.results)
                seq = self.sequencer.update(now, pressure)
                # The retry budget is per POINT: moving on to a new setpoint gets a
                # fresh count (a retry restarts the same point, so it does not).
                if seq.index != self._hold_point_idx:
                    self._hold_point_idx = seq.index
                    self._hold_count = 0
                self._accumulate_volume(seq, prev_n)
                # A point just finished and more remain: seal the feed and wait
                # for the operator to weigh this point's permeate. The sequencer
                # has already advanced, so the resume restarts the NEW point's
                # stabilisation clock — a long weighing pause cannot time it out.
                if (self._pause_between_points and len(self.sequencer.results) > prev_n
                        and seq.phase != Phase.DONE):
                    self._enter_point_pause(now, pressure, len(self.sequencer.results))
                    # publish immediately: the feed is sealed NOW, so the screen
                    # must not keep showing the command from the tick before
                    self._update_status(pressure, None, 0.0, False, seq.phase,
                                        seq.index, seq.total, now - self._run_start,
                                        0.0, in_band=False)
                    if self.plant is not None:
                        self.plant.step(self._dt)
                    return
                if seq.phase == Phase.DONE:
                    self._final_elapsed = now - self._run_start
                    self._final_index, self._final_total = seq.index, seq.total
                    self._end_run("completed")
                    self._update_status(pressure, None, 0.0, False, Phase.DONE,
                                        seq.index, seq.total, self._final_elapsed,
                                        0.0, in_band=False)
                else:
                    command = self.pid.update(self._pid_target(seq.setpoint_kpa, pressure),
                                              pressure, self._dt)
                    self.valve.set_command(command)
                    # Detector B: if the loop has lost authority over pressure
                    # (valve pinned, nothing happening), vent-abort — not
                    # recoverable, retrying can't unstick a valve or a dead sensor.
                    wd_reason = self._plant_watchdog(command, pressure)
                    if wd_reason:
                        self._abort_fault(wd_reason, now, pressure, seq.index, seq.total)
                        if self.plant is not None:
                            self.plant.step(self._dt)
                        return
                    self.diverter.set_measured(seq.diverter_measured)
                    elapsed = now - self._run_start
                    self._temp_sum += self._water_temp_c
                    self._temp_n += 1
                    # run-level provenance: constant, or honestly "mixed"
                    if self._run_temp_source is None:
                        self._run_temp_source = self._temp_source
                    elif self._run_temp_source != self._temp_source:
                        self._run_temp_source = "mixed"
                    self.logger.log(
                        elapsed_s=elapsed, phase=seq.phase.value,
                        setpoint_kpa=seq.setpoint_kpa, pressure_kpa=pressure,
                        valve_command=command, diverter_measured=seq.diverter_measured,
                        in_band=seq.in_band, water_temp_c=self._water_temp_c,
                        # per ROW, not once per run: a probe that stops answering
                        # keeps its last value, so the pair (value, origin) can
                        # change meaning mid-run and one label would misdescribe
                        # every row on one side of that moment
                        water_temp_source=self._temp_source,
                    )
                    self.history.append((round(elapsed, 2),
                                         round(self.cfg.disp(pressure), 3),
                                         round(self.cfg.disp(seq.setpoint_kpa), 3)))
                    self._update_status(pressure, seq.setpoint_kpa, command,
                                        seq.diverter_measured, seq.phase, seq.index,
                                        seq.total, elapsed, seq.collect_remaining_s,
                                        in_band=seq.in_band)
            elif self._finished:
                # a run ended (completed/aborted); the feed stays FULLY SHUT and
                # we keep reporting the terminal state so a slow UI poll always
                # sees it.
                self._safe_all()
                self._run_close_check(now, pressure)
                self._update_status(pressure, None, 0.0, False, Phase.DONE,
                                    self._final_index, self._final_total,
                                    self._final_elapsed, 0.0, in_band=False)
            else:
                # idle: feed shut, permeate to waste
                self._safe_all()
                self._run_close_check(now, pressure)
                self._update_status(pressure, None, 0.0, False, Phase.IDLE, 0, 0,
                                    0.0, 0.0, in_band=False)

            if self.plant is not None:
                self.plant.step(self._dt)

    def _update_status(self, pressure_kpa, setpoint_kpa, command, measured, phase,
                       index, total, elapsed, collect_remaining, *, in_band) -> None:
        s = self.status
        # Heartbeat: wall-clock stamp of the last control tick. A remote screen
        # can serve a perfectly fine 200 with stale data if the loop has stalled,
        # so the UI needs to see staleness rather than trust freshness.
        s["ts"] = time.time()
        s["running"] = self._active
        s["phase"] = phase.value if hasattr(phase, "value") else str(phase)
        s["fault"] = self._fault_reason
        s["pressure_kpa"] = round(pressure_kpa, 3)
        s["pressure_disp"] = round(self.cfg.disp(pressure_kpa), 3)
        s["setpoint_kpa"] = None if setpoint_kpa is None else round(setpoint_kpa, 3)
        s["setpoint_disp"] = None if setpoint_kpa is None else round(self.cfg.disp(setpoint_kpa), 3)
        s["valve_command"] = round(command, 2)
        s["diverter_measured"] = bool(measured)
        s["in_band"] = bool(in_band)
        s["index"] = index
        s["total"] = total
        s["elapsed_s"] = round(elapsed, 2)
        s["collect_remaining_s"] = round(collect_remaining, 1)
        s["results"] = [r.__dict__ for r in self.sequencer.results]
