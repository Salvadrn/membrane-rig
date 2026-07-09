"""Real pressure sensor driver: ADS1115 (I2C, 16-bit ADC) front-end.

Two front-ends are supported (config `sensor.type`):

  current_loop   4-20 mA sensor. Wire the loop so the current returns through a
                 precision shunt resistor to GND; the ADS1115 measures the
                 voltage across it.  V = I * shunt_ohms.
                 e.g. 150 ohm -> 4mA=0.60V, 20mA=3.00V (safe at gain=1, +/-4.096V).

  voltage_divider  0.5-4.5V (or 0-5V) sensor. The signal exceeds the ADS1115's
                 input at a 3.3V supply, so scale it with a resistor divider:
                 Vadc = Vsensor * divider_ratio,  ratio = R2/(R1+R2).

The Adafruit libraries are imported lazily inside __init__ so this module can
be imported on a laptop (sim mode) without the hardware libs installed.
"""
from __future__ import annotations

from .interfaces import PressureSensor, Reading


class Ads1115Sensor(PressureSensor):
    def __init__(self, cfg) -> None:
        import board  # type: ignore
        import busio  # type: ignore
        import adafruit_ads1x15.ads1115 as ADS  # type: ignore
        from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore

        self.cfg = cfg.sensor
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = self.cfg.ads_gain
        channel = {0: ADS.P0, 1: ADS.P1, 2: ADS.P2, 3: ADS.P3}[self.cfg.ads_channel]
        self._chan = AnalogIn(ads, channel)

    def _signal_to_pressure(self) -> tuple[float, float]:
        """Return (pressure_kpa, raw_signal). raw_signal is amps or volts."""
        v_adc = self._chan.voltage  # volts at the ADC pin
        c = self.cfg
        if c.type == "current_loop":
            current = v_adc / c.shunt_ohms  # A
            frac = (current - c.signal_min) / (c.signal_max - c.signal_min)
            raw = current
        else:  # voltage_divider
            v_sensor = v_adc / c.divider_ratio
            frac = (v_sensor - c.v_signal_min) / (c.v_signal_max - c.v_signal_min)
            raw = v_sensor
        pressure = c.range_min_kpa + frac * (c.range_max_kpa - c.range_min_kpa)
        return pressure, raw

    def read(self) -> Reading:
        try:
            pressure, raw = self._signal_to_pressure()
            return Reading(pressure_kpa=pressure, raw=raw, healthy=True)
        except Exception:
            # I2C hiccup / disconnected ADC — report unhealthy, let safety decide.
            return Reading(pressure_kpa=float("nan"), raw=float("nan"), healthy=False)
