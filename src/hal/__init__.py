"""HAL factory: build the right drivers for the configured mode."""
from __future__ import annotations

from .interfaces import DiverterValve, PressureSensor, ProportionalValve, Reading


def build_hal(cfg):
    """Return (sensor, valve, diverter, plant_or_None).

    In sim mode the plant is returned so the controller can step it each loop.
    In hardware mode plant is None.
    """
    if cfg.mode == "sim":
        from .mock import MockDiverter, MockSensor, MockValve
        from ..control.plant_sim import MockPlant

        plant = MockPlant(cfg)
        return MockSensor(plant, cfg), MockValve(plant, cfg), MockDiverter(cfg), plant

    from .ads1115_sensor import Ads1115Sensor
    from .gpio_diverter import GpioDiverter

    if cfg.valve.type == "servo":
        from .servo_valve import ServoValve
        valve = ServoValve(cfg)
    else:
        from .pwm_valve import PwmValve
        valve = PwmValve(cfg)

    return Ads1115Sensor(cfg), valve, GpioDiverter(cfg), None


__all__ = [
    "build_hal",
    "PressureSensor",
    "ProportionalValve",
    "DiverterValve",
    "Reading",
]
