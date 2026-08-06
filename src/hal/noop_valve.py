"""A valve driver that does nothing, on purpose, so sensor bring-up can proceed.

WHY THIS EXISTS
---------------
`build_hal` constructs the valve *before* the sensor, and `ServoValve.__init__`
raises when pigpiod is not running. On Raspberry Pi OS Trixie pigpiod does not
exist at all (the package was dropped upstream), so on that OS the whole app
refused to start — and the pressure sensor could not be read even though the
ADS1115 answers `i2cdetect` perfectly. The actuator was blocking the sensor.

That is the wrong dependency order for commissioning: reading the ADC, measuring
the real `divider_ratio` and enumerating the temperature probe are all Stage 2-4
work that needs no actuator at all, and none of it energises 12 V or moves
anything.

WHY IT IS OPT-IN AND NEVER A FALLBACK
-------------------------------------
`build_hal` does NOT substitute this driver automatically when the servo fails.
It is selected only by writing `valve.type: none` in config.yaml, because the
dangerous version of this idea is the one that degrades silently: a rig that
quietly starts with no pressure control, while the operator believes the
software can still close the valve, is worse than a rig that refuses to start.
A missing actuator must be a decision, not an accident.

WHAT IT DOES AND DOES NOT PROTECT
---------------------------------
`to_safe()` and `full_close()` do nothing here, so **no software action closes
anything while this driver is selected**. That is not a new hazard — with no
working actuator nothing can open the valve either, so this driver cannot create
pressure. But it means the standing rule is the only rule: the air valve on the
lab panel is closed BY HAND, and that is the whole failsafe.

Commanding pressure with this driver selected will not reach a setpoint. That is
handled correctly upstream and needs no special case: the controller's
plant-response watchdog aborts with "plant unresponsive: valve at N% for 8 s but
pressure held near X kPa", which is the literal truth here, and the sequencer
times out on stabilisation. Sensor bring-up reads `status["pressure_kpa"]` while
idle and never starts a run, so neither fires.
"""
from __future__ import annotations

from .interfaces import ProportionalValve


class NoOpValve(ProportionalValve):
    #: Surfaced so the UI and the run metadata can say "no actuator" rather than
    #: showing a command value that means nothing. Same reasoning as
    #: TemperatureSensor.source: a number whose provenance is invisible is worse
    #: than no number.
    source = "none"

    def __init__(self, cfg) -> None:
        self.cfg = cfg.valve
        self._command = 0.0

    def set_command(self, command: float) -> None:
        # Remembered only so the UI reflects what was asked; nothing is driven.
        self._command = max(0.0, min(100.0, float(command)))

    def to_safe(self) -> None:
        """Does nothing — there is no actuator. Close the panel valve by hand."""

    def full_close(self) -> None:
        """Does nothing — see to_safe()."""

    def close(self) -> None:
        pass
