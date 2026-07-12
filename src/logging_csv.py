"""Per-run logging: a timeseries CSV plus a metadata/summary JSON.

One "run" == one start->finish of a setpoint sequence (a whole session).
  runs/run_YYYYMMDD_HHMMSS.csv        timestamped pressure trace (for plotting)
  runs/run_YYYYMMDD_HHMMSS_meta.json  setpoints, per-setpoint stats, timings

Pressure is logged in BOTH the display unit (for eyeballing) and kPa (canonical).
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional


class RunLogger:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.dir = Path(cfg.logging.dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._writer = None
        self.name: Optional[str] = None
        self.ts_path: Optional[Path] = None
        self.meta_path: Optional[Path] = None
        self._start_dt: Optional[datetime] = None

    def start_run(self, setpoints_kpa: List[float]) -> str:
        self._start_dt = datetime.now()
        self.name = self._start_dt.strftime("run_%Y%m%d_%H%M%S")
        self.ts_path = self.dir / f"{self.name}.csv"
        self.meta_path = self.dir / f"{self.name}_meta.json"
        self._fh = self.ts_path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self._writer.writerow([
            "iso_time", "elapsed_s", "phase",
            f"setpoint_{self.cfg.units}", "setpoint_kpa",
            f"pressure_{self.cfg.units}", "pressure_kpa",
            "valve_command", "diverter_measured", "in_band", "water_temp_c",
        ])
        self._fh.flush()
        return self.name

    def log(self, *, elapsed_s, phase, setpoint_kpa, pressure_kpa,
            valve_command, diverter_measured, in_band, water_temp_c=None) -> None:
        if self._writer is None:
            return
        sp_disp = "" if setpoint_kpa is None else round(self.cfg.disp(setpoint_kpa), 4)
        sp_kpa = "" if setpoint_kpa is None else round(setpoint_kpa, 4)
        self._writer.writerow([
            datetime.now().isoformat(timespec="milliseconds"),
            round(elapsed_s, 3), phase, sp_disp, sp_kpa,
            round(self.cfg.disp(pressure_kpa), 4), round(pressure_kpa, 4),
            round(valve_command, 3), int(bool(diverter_measured)), int(bool(in_band)),
            "" if water_temp_c is None else round(water_temp_c, 3),
        ])
        self._fh.flush()

    def finish_run(self, results, status_note: str = "completed") -> Optional[str]:
        if self.meta_path is None or self._start_dt is None:
            return None
        end_dt = datetime.now()
        u = self.cfg.units

        def result_row(r):
            d = asdict(r)
            # add display-unit copies of every pressure field
            for key in ("setpoint", "mean", "std", "min", "max"):
                d[f"{key}_{u}"] = round(self.cfg.disp(d[f"{key}_kpa"]), 4)
            return d

        meta = {
            "run": self.name,
            "units": u,
            "mode": self.cfg.mode,
            "started": self._start_dt.isoformat(),
            "ended": end_dt.isoformat(),
            "duration_s": round((end_dt - self._start_dt).total_seconds(), 1),
            "status": status_note,
            "pid": {"kp": self.cfg.pid.kp, "ki": self.cfg.pid.ki, "kd": self.cfg.pid.kd},
            "tolerance_pct": self.cfg.test.tolerance_pct,
            "dwell_s": self.cfg.test.dwell_s,
            "collection_s": self.cfg.test.collection_s,
            "timeseries_csv": self.ts_path.name if self.ts_path else None,
            "results": [result_row(r) for r in results],
        }
        self.meta_path.write_text(json.dumps(meta, indent=2))
        return str(self.meta_path)

    def plot_path(self) -> Optional[Path]:
        return self.dir / f"{self.name}_plot.png" if self.name else None

    def xlsx_path(self) -> Optional[Path]:
        return self.dir / f"{self.name}_results.xlsx" if self.name else None

    def save_analysis(self, analysis: dict) -> Optional[Path]:
        """Write runs/<name>_analysis.json (slope, R², Darcy k, pore size)."""
        if self.name is None:
            return None
        path = self.dir / f"{self.name}_analysis.json"
        path.write_text(json.dumps(analysis, indent=2))
        return path

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None
                self._writer = None
