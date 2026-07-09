"""Mock drivers — implement the HAL against the simulated plant.

All three share a single MockPlant. The valve pushes its command into the
plant; the sensor reads the plant's pressure (with measurement noise). The
controller steps the plant once per loop, so the closed loop is exercised
exactly as it would be on real hardware — just with no GPIO.
"""
from __future__ import annotations

import random

from .interfaces import DiverterValve, PressureSensor, ProportionalValve, Reading
from ..control.plant_sim import MockPlant


class MockSensor(PressureSensor):
    def __init__(self, plant: MockPlant, cfg) -> None:
        self.plant = plant
        self.noise = cfg.sim.sensor_noise_kpa

    def read(self) -> Reading:
        p = self.plant.pressure + (random.gauss(0.0, self.noise) if self.noise else 0.0)
        return Reading(pressure_kpa=p, raw=p, healthy=True)


class MockValve(ProportionalValve):
    def __init__(self, plant: MockPlant, cfg) -> None:
        self.plant = plant
        self.command = 0.0

    def set_command(self, command: float) -> None:
        self.command = max(0.0, min(100.0, command))
        self.plant.set_command(self.command)

    def to_safe(self) -> None:
        self.set_command(0.0)


class MockDiverter(DiverterValve):
    def __init__(self, cfg) -> None:
        self.measured = False

    def set_measured(self, on: bool) -> None:
        self.measured = bool(on)

    def to_safe(self) -> None:
        self.measured = False
