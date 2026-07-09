"""Real diverter driver: a single GPIO through a relay/MOSFET to the 3-way coil.

De-energised (GPIO inactive) routes flow to WASTE — the fail-safe. Energising
the coil routes to the MEASURED container. Same MOSFET+flyback assumptions as
the proportional valve, or use a relay module. gpiozero (pigpio backend) gives
guaranteed pin cleanup so the coil de-energises on exit.
"""
from __future__ import annotations

from .interfaces import DiverterValve


class GpioDiverter(DiverterValve):
    def __init__(self, cfg) -> None:
        from gpiozero import OutputDevice  # type: ignore

        self._dev = OutputDevice(
            cfg.diverter.pin,
            active_high=cfg.diverter.active_high,
            initial_value=False,  # start at waste
        )

    def set_measured(self, on: bool) -> None:
        if on:
            self._dev.on()
        else:
            self._dev.off()

    def to_safe(self) -> None:
        self._dev.off()

    def close(self) -> None:
        try:
            self._dev.off()
            self._dev.close()
        except Exception:
            pass
