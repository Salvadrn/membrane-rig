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

        # Setpoint ramp: the plant is asymmetric (rises fast, falls slowly —
        # overshoot is expensive to undo), so the PID chases a target that ramps
        # from the current pressure toward each setpoint instead of a step.
        self._ramp_sp: Optional[float] = None
        self._ramp_for: Optional[float] = None  # which true setpoint the ramp tracks

        # water temperature (a test variable): polled slowly off the fast loop.
        # mu is derived from it; the run-mean temp feeds the permeability calc.
        self._water_temp_c = cfg.temperature.manual_c
        self._temp_sum = 0.0
        self._temp_n = 0
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
            "viscosity_pa_s": cfg.membrane.viscosity_pa_s,
            "units": cfg.units,
            "playlist_analysis": None,
            "item_id": None,
            "item_label": "",
            "run_ceiling_kpa": cfg.safety.max_pressure_kpa,
            "run_ceiling_disp": round(cfg.disp(cfg.safety.max_pressure_kpa), 2),
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
            self.playlist.membrane_limit_kpa = min(kpa, self.cfg.safety.max_pressure_kpa)
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
            ceiling = self.safety.arm_for_run(setpoints_kpa)
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
            self._temp_sum = 0.0
            self._temp_n = 0
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
            self.status["run_name"] = run_name
            self.status["run_ceiling_kpa"] = round(ceiling, 2)
            self.status["run_ceiling_disp"] = round(self.cfg.disp(ceiling), 2)
            if item_id:
                self.playlist.update(item_id, status=RUNNING, run_name=run_name)
            return {"ok": True, "run_name": run_name,
                    "ceiling": round(self.cfg.disp(ceiling), 2)}

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
                "results": i.results,
            })
        nxt = self.playlist.next_pending()
        return {
            "items": items,
            "counts": self.playlist.counts(),
            "next_id": nxt.id if nxt else None,
            "units": self.cfg.units,
            "limit": round(self.cfg.disp(limit_kpa), 2),
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
        # mu from the run-mean water temperature (distilled/pure water)
        mu = water_viscosity_pa_s(run_temp_c)
        membrane = dataclasses.replace(self.cfg.membrane, viscosity_pa_s=mu, water_temp_c=run_temp_c)
        points = [(r.mean_kpa, r.flow_m3s) for r in results if r.success and r.flow_m3s > 0]
        result = fit_permeability(points, membrane)
        self.analysis_result = result
        json_path = self.logger.save_analysis(result.as_dict())
        plot_path = None
        if self.cfg.analysis.auto_plot and plot_available() and result.n >= 2:
            try:
                plot_path = plot_permeability(result, self.logger.plot_path(),
                                              title=title, units="kPa")
            except Exception:
                plot_path = None
        xlsx_path = None
        if xlsx_available() and result.n >= 1:
            try:
                detail = [dict(r.__dict__) for r in results]
                xlsx_path = export_permeability_xlsx(
                    result, self.logger.xlsx_path(), title=title, units="kPa",
                    points_detail=detail)
            except Exception:
                xlsx_path = None
        summary = {
            "n": result.n,
            "slope_per_kpa": result.slope_per_kpa,
            "intercept_m3s": result.intercept_m3s,
            "r2": result.r2,
            "k_darcy_m2": result.k_darcy_m2,
            "pore_size_um": result.pore_size_m * 1e6,
            "follows_darcy": result.follows_darcy,
            "label": result.label,
            "note": result.note,
            "water_temp_c": round(run_temp_c, 2),
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
        with self._lock:
            run_temp_c = (self._temp_sum / self._temp_n) if self._temp_n else self._water_temp_c
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
                    title=self.cfg.analysis.title, units="kPa")).name
            except Exception:
                pass
        if xlsx_available() and result.n >= 1:
            try:
                detail = [r for i in self.playlist.items if i.status == DONE
                          for r in i.results]
                files["xlsx_file"] = Path(export_permeability_xlsx(
                    result, base.with_name("playlist_latest_results.xlsx"),
                    title=self.cfg.analysis.title, units="kPa",
                    points_detail=detail)).name
            except Exception:
                pass
        summary = {
            "n": result.n,
            "slope_per_kpa": result.slope_per_kpa,
            "intercept_m3s": result.intercept_m3s,
            "r2": result.r2,
            "k_darcy_m2": result.k_darcy_m2,
            "pore_size_um": result.pore_size_m * 1e6,
            "follows_darcy": result.follows_darcy,
            "label": result.label,
            "note": result.note,
            "water_temp_c": round(run_temp_c, 2),
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

    def _temp_loop(self) -> None:
        """Poll the water-temperature probe slowly (blocking reads are fine here,
        off the fast control loop). Cache the latest good reading + its viscosity."""
        while not self._stop_evt.is_set():
            try:
                t = self.temp.read_c()
                if t == t:  # not NaN
                    mu = water_viscosity_pa_s(t)
                    with self._lock:
                        self._water_temp_c = t
                        self.status["water_temp_c"] = round(t, 2)
                        self.status["viscosity_pa_s"] = mu
                    if self.plant is not None and hasattr(self.plant, "set_viscosity"):
                        self.plant.set_viscosity(mu)
            except Exception:
                pass
            self._stop_evt.wait(self.cfg.temperature.read_period_s)

    def _safe_all(self) -> None:
        try:
            self.valve.to_safe()
        except Exception:
            pass
        try:
            self.diverter.to_safe()
        except Exception:
            pass

    def _end_run(self, reason: str) -> None:
        """Must be called with the lock held."""
        self._safe_all()
        self.safety.disarm()          # idle again: back to the global cutoff
        try:
            self.logger.finish_run(self.sequencer.results, status_note=reason)
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
                self.playlist.update(
                    self._current_item_id,
                    status=DONE if reason == "completed" else FAILED,
                    note="" if reason == "completed" else reason,
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

            if state != SafetyState.OK:
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
                self._accumulate_volume(seq, prev_n)
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
                    self.diverter.set_measured(seq.diverter_measured)
                    elapsed = now - self._run_start
                    self._temp_sum += self._water_temp_c
                    self._temp_n += 1
                    self.logger.log(
                        elapsed_s=elapsed, phase=seq.phase.value,
                        setpoint_kpa=seq.setpoint_kpa, pressure_kpa=pressure,
                        valve_command=command, diverter_measured=seq.diverter_measured,
                        in_band=seq.in_band, water_temp_c=self._water_temp_c,
                    )
                    self.history.append((round(elapsed, 2),
                                         round(self.cfg.disp(pressure), 3),
                                         round(self.cfg.disp(seq.setpoint_kpa), 3)))
                    self._update_status(pressure, seq.setpoint_kpa, command,
                                        seq.diverter_measured, seq.phase, seq.index,
                                        seq.total, elapsed, seq.collect_remaining_s,
                                        in_band=seq.in_band)
            elif self._finished:
                # a run ended (completed/aborted); hold safe but keep reporting
                # the terminal state so a slow UI poll always sees it.
                self.valve.to_safe()
                self.diverter.to_safe()
                self._update_status(pressure, None, 0.0, False, Phase.DONE,
                                    self._final_index, self._final_total,
                                    self._final_elapsed, 0.0, in_band=False)
            else:
                # idle: hold safe/vented
                self.valve.to_safe()
                self.diverter.to_safe()
                self._update_status(pressure, None, 0.0, False, Phase.IDLE, 0, 0,
                                    0.0, 0.0, in_band=False)

            if self.plant is not None:
                self.plant.step(self._dt)

    def _update_status(self, pressure_kpa, setpoint_kpa, command, measured, phase,
                       index, total, elapsed, collect_remaining, *, in_band) -> None:
        s = self.status
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
