"""Configured water temperature — a number someone typed, reported as such.

`temperature.source: manual` is how the rig runs when no DS18B20 is fitted: the
operator measures the water by hand and writes it into `config.yaml`. That value
still matters as much as a probe reading would, because µ comes from it and
`k = b·µ·L/A` comes from µ.

Which is why this class exists instead of reusing `MockTemperature`. The mock
adds ±0.02 °C of gaussian noise, which is right for **sim** — it is simulating a
bath that really does drift — and wrong for **hardware**, where the same wobble
would arrive in the CSV under the same field name as a probe reading, refreshed
every 3 s, indistinguishable from a measurement by anyone looking at the data.
Nobody typed a number that moves. Reporting one asserts a precision that was
never observed.

So: return exactly what was configured, and say where it came from. `source`
lets the UI and the logs mark this value as *configured, not measured* — the
distinction the number itself cannot carry.
"""
from __future__ import annotations

from .interfaces import TemperatureSensor


class ManualTemperature(TemperatureSensor):
    """Reports `temperature.manual_c` verbatim. No noise, no drift, no pretence."""

    source = "manual"

    def __init__(self, cfg) -> None:
        self._t = float(cfg.temperature.manual_c)

    def read_c(self) -> float:
        return self._t
