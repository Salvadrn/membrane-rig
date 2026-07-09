"""Configuration loading, validation and unit handling.

Pressures live in the YAML in whatever `units` the user picked (kPa or psi).
Everything is converted to kPa on load; the rest of the codebase is kPa-only.
Fields that hold a pressure carry a `_kpa` suffix so the unit is unambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

PSI_TO_KPA = 6.894757293168361


def to_kpa(value: float, units: str) -> float:
    return float(value) * PSI_TO_KPA if units.lower() == "psi" else float(value)


def from_kpa(value_kpa: float, units: str) -> float:
    return float(value_kpa) / PSI_TO_KPA if units.lower() == "psi" else float(value_kpa)


@dataclass
class SensorConfig:
    type: str = "current_loop"
    range_min_kpa: float = 0.0
    range_max_kpa: float = 100.0
    ads_channel: int = 0
    ads_gain: int = 1
    read_hz: float = 20.0
    shunt_ohms: float = 150.0
    signal_min: float = 0.004
    signal_max: float = 0.020
    divider_ratio: float = 0.667
    v_signal_min: float = 0.5
    v_signal_max: float = 4.5


@dataclass
class ValveConfig:
    type: str = "servo"          # "servo" (servo-driven needle valve) or "pwm" (MOSFET proportional solenoid)
    invert: bool = False
    min_command: float = 0.0
    max_command: float = 100.0
    # --- pwm proportional-solenoid driver ---
    pwm_pin: int = 18
    pwm_freq_hz: int = 1000
    # --- servo-driven needle/metering valve ---
    servo_pin: int = 18          # hardware-PWM pin (12/13/18/19); pigpio servo pulses
    servo_min_us: int = 700      # pulse width (µs) at 0% command = valve fully OPEN (vent)
    servo_max_us: int = 2300     # pulse width (µs) at 100% command = valve fully CLOSED (max pressure)


@dataclass
class DiverterConfig:
    pin: int = 23
    active_high: bool = True


@dataclass
class PidConfig:
    kp: float = 3.0
    ki: float = 1.2
    kd: float = 0.15
    output_min: float = 0.0
    output_max: float = 100.0
    sample_hz: float = 20.0


@dataclass
class SafetyConfig:
    max_pressure_kpa: float = 80.0
    min_plausible_kpa: float = -5.0
    max_plausible_kpa: float = 105.0
    fault_grace_reads: int = 3


@dataclass
class TestConfig:
    tolerance_pct: float = 2.0
    dwell_s: float = 5.0
    collection_s: float = 60.0
    stabilize_timeout_s: float = 120.0
    setpoints_kpa: List[float] = field(default_factory=list)


@dataclass
class SimConfig:
    supply_pressure_kpa: float = 100.0
    k_fill: float = 0.4
    k_bleed: float = 6.0
    process_noise_kpa: float = 0.05
    sensor_noise_kpa: float = 0.15
    # Simulated permeate flow so sim mode reproduces a Darcy Q-vs-dP line:
    #   Q(P) = flow_per_kpa * P_kPa + flow_intercept   (+/- flow_noise_frac)
    flow_per_kpa_m3s: float = 7.86e-7
    flow_intercept_m3s: float = 1.3072e-5
    flow_noise_frac: float = 0.02


@dataclass
class MembraneConfig:
    """Geometry + fluid props for the Darcy permeability calc (slope method).
    k = slope * mu * L / A, with slope = dQ/dP in (m^3/s)/Pa. All SI internally."""
    area_m2: float = 6.4e-5        # 0.64 cm^2
    thickness_m: float = 1.17e-4   # 0.117 mm
    viscosity_pa_s: float = 1.0e-3  # water ~20 C
    label: str = ""


@dataclass
class AnalysisConfig:
    auto_plot: bool = True
    title: str = "Q vs ΔP"


@dataclass
class LoggingConfig:
    dir: str = "runs"


@dataclass
class Config:
    units: str = "kPa"
    mode: str = "sim"
    sensor: SensorConfig = field(default_factory=SensorConfig)
    valve: ValveConfig = field(default_factory=ValveConfig)
    diverter: DiverterConfig = field(default_factory=DiverterConfig)
    pid: PidConfig = field(default_factory=PidConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    test: TestConfig = field(default_factory=TestConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    membrane: MembraneConfig = field(default_factory=MembraneConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # --- unit conversion helpers used by the UI/logging ----------------------
    def disp(self, value_kpa: float) -> float:
        """kPa -> display units."""
        return from_kpa(value_kpa, self.units)

    def to_internal(self, value_display: float) -> float:
        """display units -> kPa."""
        return to_kpa(value_display, self.units)

    # --- loading -------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        units = str(raw.get("units", "kPa"))
        k = lambda v: to_kpa(v, units)

        s = raw.get("sensor", {})
        sensor = SensorConfig(
            type=s.get("type", "current_loop"),
            range_min_kpa=k(s.get("range_min", 0.0)),
            range_max_kpa=k(s.get("range_max", 100.0)),
            ads_channel=int(s.get("ads_channel", 0)),
            ads_gain=int(s.get("ads_gain", 1)),
            read_hz=float(s.get("read_hz", 20.0)),
            shunt_ohms=float(s.get("shunt_ohms", 150.0)),
            signal_min=float(s.get("signal_min", 0.004)),
            signal_max=float(s.get("signal_max", 0.020)),
            divider_ratio=float(s.get("divider_ratio", 0.667)),
            v_signal_min=float(s.get("v_signal_min", 0.5)),
            v_signal_max=float(s.get("v_signal_max", 4.5)),
        )

        v = raw.get("valve", {})
        valve = ValveConfig(
            type=str(v.get("type", "servo")),
            invert=bool(v.get("invert", False)),
            min_command=float(v.get("min_command", 0.0)),
            max_command=float(v.get("max_command", 100.0)),
            pwm_pin=int(v.get("pwm_pin", 18)),
            pwm_freq_hz=int(v.get("pwm_freq_hz", 1000)),
            servo_pin=int(v.get("servo_pin", 18)),
            servo_min_us=int(v.get("servo_min_us", 700)),
            servo_max_us=int(v.get("servo_max_us", 2300)),
        )

        d = raw.get("diverter", {})
        diverter = DiverterConfig(
            pin=int(d.get("pin", 23)),
            active_high=bool(d.get("active_high", True)),
        )

        p = raw.get("pid", {})
        pid = PidConfig(
            kp=float(p.get("kp", 3.0)),
            ki=float(p.get("ki", 1.2)),
            kd=float(p.get("kd", 0.15)),
            output_min=float(p.get("output_min", 0.0)),
            output_max=float(p.get("output_max", 100.0)),
            sample_hz=float(p.get("sample_hz", 20.0)),
        )

        sf = raw.get("safety", {})
        safety = SafetyConfig(
            max_pressure_kpa=k(sf.get("max_pressure", 80.0)),
            min_plausible_kpa=k(sf.get("min_plausible", -5.0)),
            max_plausible_kpa=k(sf.get("max_plausible", 105.0)),
            fault_grace_reads=int(sf.get("fault_grace_reads", 3)),
        )

        t = raw.get("test", {})
        test = TestConfig(
            tolerance_pct=float(t.get("tolerance_pct", 2.0)),
            dwell_s=float(t.get("dwell_s", 5.0)),
            collection_s=float(t.get("collection_s", 60.0)),
            stabilize_timeout_s=float(t.get("stabilize_timeout_s", 120.0)),
            setpoints_kpa=[k(x) for x in t.get("setpoints", [])],
        )

        sm = raw.get("sim", {})
        sim = SimConfig(
            supply_pressure_kpa=k(sm.get("supply_pressure", 100.0)),
            k_fill=float(sm.get("k_fill", 0.4)),
            k_bleed=float(sm.get("k_bleed", 6.0)),
            process_noise_kpa=k(sm.get("process_noise", 0.05)),
            sensor_noise_kpa=k(sm.get("sensor_noise", 0.15)),
            flow_per_kpa_m3s=float(sm.get("flow_per_kpa_m3s", 7.86e-7)),
            flow_intercept_m3s=float(sm.get("flow_intercept_m3s", 1.3072e-5)),
            flow_noise_frac=float(sm.get("flow_noise_frac", 0.02)),
        )

        mb = raw.get("membrane", {})
        membrane = MembraneConfig(
            area_m2=float(mb["area_cm2"]) * 1e-4 if "area_cm2" in mb else float(mb.get("area_m2", 6.4e-5)),
            thickness_m=float(mb["thickness_mm"]) * 1e-3 if "thickness_mm" in mb else float(mb.get("thickness_m", 1.17e-4)),
            viscosity_pa_s=float(mb.get("viscosity_pa_s", 1.0e-3)),
            label=str(mb.get("label", "")),
        )

        an = raw.get("analysis", {})
        analysis = AnalysisConfig(
            auto_plot=bool(an.get("auto_plot", True)),
            title=str(an.get("title", "Q vs ΔP")),
        )

        lg = raw.get("logging", {})
        logging_cfg = LoggingConfig(dir=str(lg.get("dir", "runs")))

        cfg = cls(
            units=units,
            mode=str(raw.get("mode", "sim")),
            sensor=sensor,
            valve=valve,
            diverter=diverter,
            pid=pid,
            safety=safety,
            test=test,
            sim=sim,
            membrane=membrane,
            analysis=analysis,
            logging=logging_cfg,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        errs = []
        if self.units.lower() not in ("kpa", "psi"):
            errs.append(f"units must be kPa or psi, got {self.units!r}")
        if self.mode not in ("sim", "hardware"):
            errs.append(f"mode must be sim or hardware, got {self.mode!r}")
        if self.sensor.type not in ("current_loop", "voltage_divider"):
            errs.append(f"sensor.type must be current_loop or voltage_divider")
        if self.valve.type not in ("servo", "pwm"):
            errs.append(f"valve.type must be servo or pwm, got {self.valve.type!r}")
        if self.sensor.range_max_kpa <= self.sensor.range_min_kpa:
            errs.append("sensor range_max must be > range_min")
        if self.safety.max_pressure_kpa > self.sensor.range_max_kpa:
            errs.append("safety.max_pressure exceeds the sensor's full-scale range")
        for sp in self.test.setpoints_kpa:
            if sp > self.safety.max_pressure_kpa:
                errs.append(f"setpoint {sp:.1f} kPa exceeds safety.max_pressure")
        if self.pid.output_max <= self.pid.output_min:
            errs.append("pid.output_max must be > output_min")
        if errs:
            raise ValueError("Invalid config:\n  - " + "\n  - ".join(errs))
