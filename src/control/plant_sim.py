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

from ..config import water_viscosity_pa_s


class MockPlant:
    def __init__(self, cfg) -> None:
        self.supply = cfg.sim.supply_pressure_kpa
        self.k_fill = cfg.sim.k_fill
        self.k_bleed = cfg.sim.k_bleed
        self.noise = cfg.sim.process_noise_kpa
        self.pressure = 0.0
        self._command = 0.0  # 0..100, 100 == fully closed
        # Compressor cycling: the real supply is NOT constant (the compressor
        # kicks on/off), so the sim can wobble the supply pressure sinusoidally.
        # The PID must reject this disturbance — that's the whole point of
        # closed-loop control. Set sim.supply_wobble to 0 to disable.
        self._wobble = cfg.sim.supply_wobble_kpa
        self._wobble_period = max(1.0, cfg.sim.supply_wobble_period_s)
        self._t = 0.0
        # simulated permeate flow so sim runs auto-produce a Darcy Q-vs-dP line
        self._flow_slope = cfg.sim.flow_per_kpa_m3s
        self._flow_intercept = cfg.sim.flow_intercept_m3s
        self._flow_noise = cfg.sim.flow_noise_frac
        # Darcy flow scales as 1/mu: warmer (thinner) water permeates faster. The
        # flow constants above were tuned near 20 C, so scale by mu_ref/mu. This
        # makes the derived k come out ~constant across temperature, as it should.
        self._mu_ref = water_viscosity_pa_s(20.0)
        self._mu = self._mu_ref

    def set_viscosity(self, mu_pa_s: float) -> None:
        if mu_pa_s and mu_pa_s > 0:
            self._mu = mu_pa_s

    def set_command(self, command: float) -> None:
        self._command = max(0.0, min(100.0, command))

    def flow_m3s(self) -> float:
        """Simulated instantaneous permeate flow at the current pressure.
        Scales as 1/mu (Darcy): warmer, thinner water flows faster."""
        q = self._flow_slope * self.pressure + self._flow_intercept
        q *= self._mu_ref / self._mu
        if self._flow_noise:
            q *= 1.0 + random.gauss(0.0, self._flow_noise)
        return max(0.0, q)

    def step(self, dt: float) -> None:
        if dt <= 0:
            return
        self._t += dt
        supply = self.supply
        if self._wobble:
            supply += self._wobble * math.sin(2.0 * math.pi * self._t / self._wobble_period)
        opening = 1.0 - self._command / 100.0
        dP = self.k_fill * (supply - self.pressure) - self.k_bleed * opening * self.pressure
        self.pressure += dP * dt
        if self.noise:
            self.pressure += random.gauss(0.0, self.noise) * math.sqrt(dt)
        if self.pressure < 0.0:
            self.pressure = 0.0
