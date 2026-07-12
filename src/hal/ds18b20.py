"""Real water-temperature probe: a DS18B20 on the Pi's 1-Wire bus.

Why this probe: temperature is a test variable here (you vary the water bath),
and water viscosity mu depends on it, which feeds straight into k = slope*mu*L/A.
The DS18B20 is a cheap, waterproof, 12-bit digital probe the Pi reads natively
over 1-Wire — no ADC, no calibration curve.

WIRING
------
    DS18B20 data (yellow) -> GPIO4 (BCM 4, the default 1-Wire pin)
    DS18B20 VDD (red)     -> 3.3V
    DS18B20 GND (black)   -> GND
    4.7k pull-up resistor between data and 3.3V   (from the resistor kit)

Enable 1-Wire once on the Pi:  sudo raspi-config  (Interface Options -> 1-Wire),
or add `dtoverlay=w1-gpio` to /boot/config.txt, then reboot. The probe shows up
as /sys/bus/w1/devices/28-xxxxxxxx/w1_slave.

Reads are pure file I/O, so this imports fine on a laptop; a missing bus just
returns NaN (the controller then falls back to the configured manual temp).
"""
from __future__ import annotations

import glob
import os

from .interfaces import TemperatureSensor


class Ds18b20Sensor(TemperatureSensor):
    def __init__(self, cfg) -> None:
        self._device = None
        w1_id = cfg.temperature.w1_id
        base = "/sys/bus/w1/devices"
        if w1_id:
            path = os.path.join(base, w1_id, "w1_slave")
            if os.path.exists(path):
                self._device = path
        else:
            matches = glob.glob(os.path.join(base, "28-*", "w1_slave"))
            if matches:
                self._device = matches[0]

    def read_c(self) -> float:
        if not self._device:
            return float("nan")
        try:
            lines = open(self._device).read().splitlines()
            # line 1 ends in "YES" when the CRC is good; line 2 has "t=<milli°C>"
            if len(lines) < 2 or not lines[0].strip().endswith("YES"):
                return float("nan")
            key = "t="
            i = lines[1].find(key)
            if i < 0:
                return float("nan")
            return int(lines[1][i + len(key):]) / 1000.0
        except Exception:
            return float("nan")
