"""Experiment playlist — a queue of test items run ONE AT A TIME, with a manual
gate between them.

Why the gate matters: between experiments the operator has to read the graduated
cylinder, empty it, and often swap the specimen. Auto-advancing would either lose
that volume or pressurise a membrane nobody is standing next to. So the queue
never advances on its own — an item ends, the rig returns to its safe state
(valve closed, diverter to waste), and the next item starts only when the
operator presses play.

The playlist is persisted next to the config so it survives a restart, and it
carries the specimen pressure limit: that limit belongs to the mesh currently
clamped in the vessel, not to the hardware, so it lives with the queue and is
editable without touching config.yaml.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

TERMINAL = (DONE, FAILED, SKIPPED)


@dataclass
class Experiment:
    """One queued experiment. `setpoints_kpa` is usually a single pressure, but
    a multi-point item is allowed (it runs its points back-to-back, unattended)."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    label: str = ""
    setpoints_kpa: List[float] = field(default_factory=list)
    collection_s: float = 60.0
    dwell_s: float = 5.0
    tolerance_pct: float = 10.0
    stabilize_timeout_s: float = 180.0
    status: str = PENDING
    run_name: str = ""
    note: str = ""
    results: List[dict] = field(default_factory=list)

    def points(self) -> List[tuple]:
        """(mean pressure kPa, flow m^3/s) for successful points with a volume."""
        return [(r.get("mean_kpa", 0.0), r.get("flow_m3s", 0.0))
                for r in self.results
                if r.get("success") and (r.get("flow_m3s") or 0.0) > 0]

    def needs_volume(self) -> bool:
        """A finished item whose points have no measured volume yet."""
        return self.status == DONE and any(
            r.get("success") and not (r.get("volume_ml") or 0.0) > 0
            for r in self.results)


class Playlist:
    def __init__(self, path: Path, membrane_limit_kpa: float = 0.0) -> None:
        self.path = Path(path)
        self.items: List[Experiment] = []
        self.membrane_limit_kpa = float(membrane_limit_kpa or 0.0)
        self.load()

    # --- queue operations ----------------------------------------------------
    def add(self, item: Experiment, index: Optional[int] = None) -> Experiment:
        if index is None or index >= len(self.items):
            self.items.append(item)
        else:
            self.items.insert(max(0, index), item)
        self.save()
        return item

    def get(self, item_id: str) -> Optional[Experiment]:
        return next((i for i in self.items if i.id == item_id), None)

    def remove(self, item_id: str) -> bool:
        n = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        self.save()
        return len(self.items) < n

    def move(self, item_id: str, delta: int) -> bool:
        idx = next((n for n, i in enumerate(self.items) if i.id == item_id), None)
        if idx is None:
            return False
        new = max(0, min(len(self.items) - 1, idx + delta))
        if new == idx:
            return False
        self.items.insert(new, self.items.pop(idx))
        self.save()
        return True

    def update(self, item_id: str, **fields) -> Optional[Experiment]:
        item = self.get(item_id)
        if item is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)
        self.save()
        return item

    def clear(self) -> None:
        self.items = []
        self.save()

    def reset(self) -> None:
        """Re-queue everything (keeps the items, drops their results)."""
        for i in self.items:
            i.status = PENDING
            i.run_name = ""
            i.note = ""
            i.results = []
        self.save()

    # --- cursor --------------------------------------------------------------
    def next_pending(self) -> Optional[Experiment]:
        return next((i for i in self.items if i.status == PENDING), None)

    def running(self) -> Optional[Experiment]:
        return next((i for i in self.items if i.status == RUNNING), None)

    def last_finished(self) -> Optional[Experiment]:
        done = [i for i in self.items if i.status in TERMINAL]
        return done[-1] if done else None

    def collected_points(self) -> List[tuple]:
        """Every measured (pressure, flow) point across finished items — the
        combined Q-vs-dP dataset for the specimen."""
        pts: List[tuple] = []
        for i in self.items:
            if i.status == DONE:
                pts.extend(i.points())
        return pts

    def counts(self) -> dict:
        c = {PENDING: 0, RUNNING: 0, DONE: 0, FAILED: 0, SKIPPED: 0}
        for i in self.items:
            c[i.status] = c.get(i.status, 0) + 1
        c["total"] = len(self.items)
        return c

    # --- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "membrane_limit_kpa": self.membrane_limit_kpa,
            "items": [asdict(i) for i in self.items],
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_dict(), indent=2))
            tmp.replace(self.path)          # atomic: never leave a half-written queue
        except Exception:
            pass                            # a queue that can't persist must not stop a run

    def load(self) -> None:
        try:
            if not self.path.exists():
                return
            raw = json.loads(self.path.read_text())
        except Exception:
            return
        limit = raw.get("membrane_limit_kpa")
        if limit:
            self.membrane_limit_kpa = float(limit)
        self.items = []
        for d in raw.get("items", []):
            try:
                known = {k: v for k, v in d.items()
                         if k in Experiment.__dataclass_fields__}
                item = Experiment(**known)
                # a run interrupted by a restart is not still running
                if item.status == RUNNING:
                    item.status = FAILED
                    item.note = item.note or "interrupted (server restarted)"
                self.items.append(item)
            except Exception:
                continue
