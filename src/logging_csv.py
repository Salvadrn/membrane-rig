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
        base = self._start_dt.strftime("run_%Y%m%d_%H%M%S")
        # Two runs started inside the same clock second would share every
        # artefact name (csv, meta, plot, xlsx) and the first one's data would be
        # overwritten with no error. Suffix instead of widening the timestamp, so
        # the ordinary name — which the operator reads and the meta quotes —
        # keeps its familiar shape.
        self.name = base
        n = 2
        while (self.dir / f"{self.name}.csv").exists():
            self.name = f"{base}_{n}"
            n += 1
        self.ts_path = self.dir / f"{self.name}.csv"
        self.meta_path = self.dir / f"{self.name}_meta.json"
        self._fh = self.ts_path.open("w", newline="")
        self._writer = csv.writer(self._fh)
        self._writer.writerow([
            "iso_time", "elapsed_s", "phase",
            f"setpoint_{self.cfg.units}", "setpoint_kpa",
            f"pressure_{self.cfg.units}", "pressure_kpa",
            "valve_command", "diverter_measured", "in_band", "water_temp_c",
            # How that temperature was obtained ("probe" / "manual" / "sim" /
            # "probe (no recent reading)"). k = b·µ·L/A and µ comes from this
            # temperature, so k inherits its provenance: a k whose µ came from a
            # typed-in number is not the same evidence as one from a live probe,
            # and the value alone cannot carry that. Logged per ROW, not per run,
            # because it can change mid-run — a probe that stops answering keeps
            # the last value but is no longer measuring, and a single label for
            # the whole run would misdescribe every row on one side of that.
            "water_temp_source",
        ])
        self._fh.flush()
        return self.name

    def log(self, *, elapsed_s, phase, setpoint_kpa, pressure_kpa,
            valve_command, diverter_measured, in_band, water_temp_c=None,
            water_temp_source=None) -> None:
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
            "" if water_temp_source is None else str(water_temp_source),
        ])
        self._fh.flush()

    def finish_run(self, results, status_note: str = "completed", *,
                   tolerance_pct=None, dwell_s=None) -> Optional[str]:
        """Write runs/<name>_meta.json.

        The test parameters must describe THIS run, not config.yaml: a playlist
        item carries its own tolerance/dwell/collection, so quoting the config
        defaults produced a meta that contradicted the results sitting beside it
        in the same file. collection_s is taken from the results themselves, so
        it is right whether or not the caller passes anything; the two that no
        TestResult carries are accepted as arguments, and whatever still falls
        back to config is named in `params_from_config_defaults` rather than
        being asserted as if it had been used.
        """
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

        # collection_s comes from the points that actually ran; a list if they
        # differed, so the meta never flattens a varied run into one number
        seen = sorted({round(r.collection_s, 3) for r in results
                       if getattr(r, "collection_s", 0)})
        fell_back = []
        if seen:
            coll = seen[0] if len(seen) == 1 else seen
        else:
            coll = self.cfg.test.collection_s
            fell_back.append("collection_s")
        tol, dwl = tolerance_pct, dwell_s
        if tol is None:
            tol = self.cfg.test.tolerance_pct
            fell_back.append("tolerance_pct")
        if dwl is None:
            dwl = self.cfg.test.dwell_s
            fell_back.append("dwell_s")

        meta = {
            "run": self.name,
            "units": u,
            "mode": self.cfg.mode,
            "started": self._start_dt.isoformat(),
            "ended": end_dt.isoformat(),
            "duration_s": round((end_dt - self._start_dt).total_seconds(), 1),
            "status": status_note,
            "pid": {"kp": self.cfg.pid.kp, "ki": self.cfg.pid.ki, "kd": self.cfg.pid.kd},
            "tolerance_pct": tol,
            "dwell_s": dwl,
            "collection_s": coll,
            "timeseries_csv": self.ts_path.name if self.ts_path else None,
            "results": [result_row(r) for r in results],
        }
        if fell_back:
            meta["params_from_config_defaults"] = fell_back
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
