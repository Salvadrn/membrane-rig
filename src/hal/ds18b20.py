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


# The DS18B20's scratchpad powers up holding 85.000 °C. Read it before the first
# conversion completes — or after a brown-out reset the driver never saw — and the
# bus hands back exactly that, WITH a valid CRC, because the value is genuinely
# what the chip is storing. It is indistinguishable from a real reading by every
# check the kernel does.
#
# It is not a small error. mu(85 °C) is 0.338x mu(21 °C), and k = b*mu*L/A, so a
# run that swallows one comes out ~66 % low with nothing in the fit to show for
# it. Water in this rig cannot be at 85 °C — the vessel is at room temperature and
# the probe sits in the permeate stream — so the value is rejected outright.
#
# Rejecting a genuine 85.000 is the harmless direction: it returns NaN, the temp
# loop keeps the previous value, and nobody is running this experiment at 85 °C.
_POR_C = 85.0
_POR_RAW = 85000  # milli-°C, exact


class Ds18b20Sensor(TemperatureSensor):
    def __init__(self, cfg) -> None:
        self._device = None
        self._w1_id = cfg.temperature.w1_id
        self._base = "/sys/bus/w1/devices"
        self._resolve()

    def _resolve(self) -> bool:
        """Find the probe's sysfs path. Called from __init__ AND retried on every
        failed read.

        The original version resolved once at construction. That is a boot race
        waiting to happen: systemd starts the app as soon as the network is up,
        which can easily beat the kernel's 1-Wire enumeration, and the probe would
        then stay dead for the WHOLE session with no retry — reported as NaN,
        silently swallowed by the temp loop, leaving a stale temperature on screen
        and a wrong mu in every k. Retrying costs one glob per 3 s poll.
        """
        if self._w1_id:
            path = os.path.join(self._base, self._w1_id, "w1_slave")
            self._device = path if os.path.exists(path) else None
        else:
            matches = sorted(glob.glob(os.path.join(self._base, "28-*", "w1_slave")))
            self._device = matches[0] if matches else None
        return self._device is not None

    def read_c(self) -> float:
        if not self._device and not self._resolve():
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
            raw = int(lines[1][i + len(key):])
            if raw == _POR_RAW:  # power-on-reset value, not a measurement
                return float("nan")
            return raw / 1000.0
        except Exception:
            # The probe may have been unplugged; force a re-resolve next time
            # rather than reading a stale path forever.
            self._device = None
            return float("nan")
