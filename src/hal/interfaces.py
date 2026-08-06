"""Hardware Abstraction Layer — the contracts every driver must satisfy.

The controller, PID, sequencer and safety code only ever talk to these three
abstract types. Swapping a physical sensor or valve = writing a new subclass;
nothing above the HAL changes. The mock drivers implement the same contracts,
which is what makes full-logic simulation on a laptop possible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Reading:
    """A single pressure measurement."""
    pressure_kpa: float
    raw: float          # raw electrical signal: amps (current loop) or volts
    healthy: bool = True  # False if the driver itself detected a fault


class PressureSensor(ABC):
    @abstractmethod
    def read(self) -> Reading:
        """Return the current pressure. Never raises for a transient glitch —
        signal an unrecoverable read by returning healthy=False so the safety
        layer (not the sensor) decides what to do."""

    def close(self) -> None:  # optional cleanup
        pass


class ProportionalValve(ABC):
    """Pressure-control valve. `command` is 0..100 'pressure authority':
    0 == lowest pressure (SAFE), 100 == driving toward maximum pressure.

    Deliberately not "vented": this interface covers both plumbing topologies,
    and only one of them vents. A bleed-to-waste valve really does open an
    escape at 0%; the inline feed throttle this rig uses merely shuts the
    supply, and the vessel then falls by permeation through the membrane — or
    does not fall at all, if the mesh is blocked. Naming a mechanism here would
    promise the servo topology an escape path it does not have."""

    @abstractmethod
    def set_command(self, command: float) -> None:
        ...

    @abstractmethod
    def to_safe(self) -> None:
        """Drive the valve to its fail-safe state."""

    def full_close(self) -> None:
        """Seat the valve SHUT, past the regulating range.

        0% command is the bottom of the *control* range, calibrated for smooth
        regulation — it is not necessarily a sealed valve, and backlash in the
        coupling can leave it cracked. When a test ends the feed must be properly
        shut, not merely turned down, so drivers that can over-travel do it here.
        Falls back to to_safe() for drivers that cannot."""
        self.to_safe()

    def close(self) -> None:
        pass


class DiverterValve(ABC):
    """3-way diverter. Safe/de-energised state routes flow to waste."""

    @abstractmethod
    def set_measured(self, on: bool) -> None:
        """True -> route to the measured container; False -> route to waste."""

    @abstractmethod
    def to_safe(self) -> None:
        ...

    def close(self) -> None:
        pass


class TemperatureSensor(ABC):
    """Water temperature probe. Read is allowed to be slow/blocking (e.g. a
    DS18B20 takes ~750 ms), so the controller polls it in its own slow thread,
    never in the fast PID loop."""

    #: Where the number came from: "probe" (measured), "manual" (configured by
    #: hand) or "sim" (generated). µ is derived from this reading and k from µ,
    #: so a configured value must never be presented as a measured one — and the
    #: value itself cannot carry that distinction. Consumers should surface it.
    source: str = "unknown"

    @abstractmethod
    def read_c(self) -> float:
        """Water temperature in °C, or NaN if the read failed."""

    def close(self) -> None:
        pass
