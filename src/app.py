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
from .plotting import plot_available, plot_permeability
from .safety import SafetyMonitor, SafetyState
from .sequencer import Phase, Sequencer


class RigController:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.sensor, self.valve, self.diverter, self.temp, self.plant = build_hal(cfg)
        self.pid = PID(cfg.pid.kp, cfg.pid.ki, cfg.pid.kd,
                       cfg.pid.output_min, cfg.pid.output_max)
        self.safety = SafetyMonitor(cfg)
        self.sequencer = Sequencer(cfg)
        self.logger = RunLogger(cfg)

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

    # --- public API ----------------------------------------------------------
    def start_sequence(self, setpoints_display: List[float], *, tolerance_pct=None,
                       dwell_s=None, collection_s=None, stabilize_timeout_s=None,
                       kp=None, ki=None, kd=None) -> dict:
        with self._lock:
            if self._active:
                return {"ok": False, "error": "a test is already running"}
            setpoints_kpa = [self.cfg.to_internal(v) for v in setpoints_display]
            if not setpoints_kpa:
                return {"ok": False, "error": "no setpoints provided"}
            for sp in setpoints_kpa:
                if sp > self.cfg.safety.max_pressure_kpa:
                    return {"ok": False, "error": (
                        f"setpoint {self.cfg.disp(sp):.1f} {self.cfg.units} exceeds "
                        f"safety cutoff {self.cfg.disp(self.cfg.safety.max_pressure_kpa):.1f}"
                    )}
            if any(x is not None for x in (kp, ki, kd)):
                self.pid.set_gains(
                    kp if kp is not None else self.pid.kp,
                    ki if ki is not None else self.pid.ki,
                    kd if kd is not None else self.pid.kd,
                )
            self.pid.reset()
            self.safety.reset()
            self.history.clear()
            self._fault_reason = ""
            self._finished = False
            self._collect_idx = None
            self._collect_vol_m3 = 0.0
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
            return {"ok": True, "run_name": run_name}

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
        try:
            self.logger.finish_run(self.sequencer.results, status_note=reason)
        except Exception:
            pass
        self.logger.close()
        self._active = False
        self._finished = True
        self.status["running"] = False
        self.status["finished"] = True
        self.status["phase"] = self.sequencer.phase.value
        self.status["valve_command"] = 0.0
        self.status["diverter_measured"] = False
        self.status["results"] = [r.__dict__ for r in self.sequencer.results]

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
                    command = self.pid.update(seq.setpoint_kpa, pressure, self._dt)
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
