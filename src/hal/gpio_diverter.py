"""Real diverter driver: a single GPIO through a relay/MOSFET to the 3-way coil.

De-energised (GPIO inactive) routes flow to WASTE — the fail-safe, and the one
place in this rig where a power cut genuinely helps: the coil drops out on its
own and the permeate goes to waste rather than into the measuring cylinder.

Energising routes to the MEASURED container. The coil is 12 V and draws
hundreds of mA, so a GPIO cannot drive it — 3.3 V and ~16 mA is four times too
little voltage and thirty times too little current. Something has to switch:
an IRLZ44N (logic-level, 470 R in series to the gate, 10 k gate-to-ground), or a
relay module, which brings its own transistor and flyback diode. With the bare
MOSFET the 1N5819 across the coil is yours to fit, band to the +12 V side.

The 10 k gate pull-down is not optional: while the Pi boots, GPIO23 is still an
INPUT, and without it the gate floats and the diverter can energise itself
before any software runs.

Backend: gpiozero picks lgpio on Trixie (pigpio is gone from Debian 13). That is
fine here and unrelated to the servo's move to the kernel PWM — an on/off line
needs no timing precision, only guaranteed cleanup so the coil drops on exit.
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
