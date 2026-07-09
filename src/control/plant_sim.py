"""First-order hydraulic plant model for simulation mode.

Pressure is driven up toward the supply (compressor) pressure and bled down
through the proportional valve:

    dP/dt = k_fill * (P_supply - P)  -  k_bleed * bleed_opening * P

where bleed_opening = 1 - command/100  (command 100 == valve closed).

Equilibrium for a given command:  P_eq = k_fill*P_supply / (k_fill + k_bleed*opening)
With the default gains: command 0 -> ~6 kPa (vented), command 100 -> P_supply.
This is intentionally simple — enough to exercise the PID, the stabilisation
band logic and the state machine, not a CFD model.
"""
from __future__ import annotations

import math
import random


class MockPlant:
    def __init__(self, cfg) -> None:
        self.supply = cfg.sim.supply_pressure_kpa
        self.k_fill = cfg.sim.k_fill
        self.k_bleed = cfg.sim.k_bleed
        self.noise = cfg.sim.process_noise_kpa
        self.pressure = 0.0
        self._command = 0.0  # 0..100, 100 == fully closed
        # simulated permeate flow so sim runs auto-produce a Darcy Q-vs-dP line
        self._flow_slope = cfg.sim.flow_per_kpa_m3s
        self._flow_intercept = cfg.sim.flow_intercept_m3s
        self._flow_noise = cfg.sim.flow_noise_frac

    def set_command(self, command: float) -> None:
        self._command = max(0.0, min(100.0, command))

    def flow_m3s(self) -> float:
        """Simulated instantaneous permeate flow at the current pressure."""
        q = self._flow_slope * self.pressure + self._flow_intercept
        if self._flow_noise:
            q *= 1.0 + random.gauss(0.0, self._flow_noise)
        return max(0.0, q)

    def step(self, dt: float) -> None:
        if dt <= 0:
            return
        opening = 1.0 - self._command / 100.0
        dP = self.k_fill * (self.supply - self.pressure) - self.k_bleed * opening * self.pressure
        self.pressure += dP * dt
        if self.noise:
            self.pressure += random.gauss(0.0, self.noise) * math.sqrt(dt)
        if self.pressure < 0.0:
            self.pressure = 0.0
