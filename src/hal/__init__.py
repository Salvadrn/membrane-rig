"""HAL factory: build the right drivers for the configured mode."""
from __future__ import annotations

from .interfaces import DiverterValve, PressureSensor, ProportionalValve, Reading


def build_hal(cfg):
    """Return (sensor, valve, diverter, temperature, plant_or_None).

    In sim mode the plant is returned so the controller can step it each loop.
    In hardware mode plant is None.
    """
    if cfg.mode == "sim":
        from .mock import MockDiverter, MockSensor, MockTemperature, MockValve
        from ..control.plant_sim import MockPlant

        plant = MockPlant(cfg)
        return (MockSensor(plant, cfg), MockValve(plant, cfg), MockDiverter(cfg),
                MockTemperature(cfg), plant)

    from .ads1115_sensor import Ads1115Sensor
    from .gpio_diverter import GpioDiverter

    if cfg.valve.type == "none":
        # Opt-in ONLY, never a fallback: see noop_valve.py. Lets sensor bring-up
        # proceed on a board where the actuator cannot be built (e.g. no pigpiod
        # on Trixie) without the actuator blocking the ADC and the probe.
        from .noop_valve import NoOpValve
        valve = NoOpValve(cfg)
    elif cfg.valve.type == "servo":
        from .servo_valve import ServoValve
        valve = ServoValve(cfg)
    else:
        from .pwm_valve import PwmValve
        valve = PwmValve(cfg)

    if cfg.temperature.source == "probe":
        from .ds18b20 import Ds18b20Sensor
        temp = Ds18b20Sensor(cfg)
    else:
        # NOT MockTemperature: its ±0.02 °C of noise is right for sim and wrong
        # here, where it would reach the CSV under the same field name as a probe
        # reading and feed µ — and therefore k — while looking measured.
        from .manual_temp import ManualTemperature
        temp = ManualTemperature(cfg)

    return Ads1115Sensor(cfg), valve, GpioDiverter(cfg), temp, None


__all__ = [
    "build_hal",
    "PressureSensor",
    "ProportionalValve",
    "DiverterValve",
    "Reading",
]
