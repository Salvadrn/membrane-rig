"""Configuration loading, validation and unit handling.

Pressures live in the YAML in whatever `units` the user picked (kPa or psi).
Everything is converted to kPa on load; the rest of the codebase is kPa-only.
Fields that hold a pressure carry a `_kpa` suffix so the unit is unambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

PSI_TO_KPA = 6.894757293168361


def water_viscosity_pa_s(temp_c: float) -> float:
    """Dynamic viscosity of liquid water vs temperature (0-100 C), in Pa·s.
    μ = A·10^(B/(T-C)) with A=2.414e-5 Pa·s, B=247.8 K, C=140 K, T in Kelvin.
    Checks: 20 C -> 1.00e-3, 25 C -> 8.9e-4. Use this when the rig runs at
    ambient temperature (no controlled bath) so k tracks the real water temp."""
    t_k = temp_c + 273.15
    return 2.414e-5 * 10 ** (247.8 / (t_k - 140.0))


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
    type: str = "servo"          # "servo" (servo-driven quarter-turn ball valve) or "pwm" (MOSFET proportional solenoid)
    invert: bool = False
    min_command: float = 0.0
    max_command: float = 100.0
    # --- pwm proportional-solenoid driver ---
    pwm_pin: int = 18
    pwm_freq_hz: int = 1000
    # --- servo-driven quarter-turn ball valve ---
    servo_pin: int = 18          # hardware-PWM pin (12/13/18/19); pigpio servo pulses
    servo_min_us: int = 700      # pulse width (µs) at 0% command = valve CLOSED (inline: lowest pressure = SAFE)
    servo_max_us: int = 2300     # pulse width (µs) at 100% command = valve OPEN (inline: highest pressure)
    # Pulse that SEATS the valve when a test ends — a little past the 0% end of
    # the control range, because 0% is where regulation stops, not necessarily
    # where the valve seals. 0 = unset (use the 0% endpoint, i.e. old behaviour).
    servo_close_us: int = 0
    close_hold_s: float = 1.5    # keep driving shut this long before releasing


@dataclass
class DiverterConfig:
    pin: int = 23
    active_high: bool = True


@dataclass
class PidConfig:
    kp: float = 4.0
    ki: float = 0.4
    kd: float = 1.0
    output_min: float = 0.0
    output_max: float = 100.0
    sample_hz: float = 20.0


@dataclass
class SafetyConfig:
    max_pressure_kpa: float = 80.0
    min_plausible_kpa: float = -5.0
    max_plausible_kpa: float = 105.0
    fault_grace_reads: int = 3
    # Per-run ceiling. While a test is running the effective cutoff drops to
    # max(setpoints) + this margin. Without it, a 20 kPa test could drift all the
    # way to the 80 kPa global cutoff before aborting — enough to destroy a
    # delicate mesh. 0 disables it (global cutoff governs).
    overshoot_margin_kpa: float = 10.0
    # After a run ends the feed is shut, so pressure MUST start falling. If it
    # hasn't dropped by close_check_min_drop_kpa within close_check_s, the valve
    # did not actually seat — raise it as a warning instead of leaving a
    # pressurised specimen sitting there unnoticed. 0 disables the check.
    close_check_s: float = 20.0
    close_check_min_drop_kpa: float = 1.0


@dataclass
class TestConfig:
    tolerance_pct: float = 2.0
    dwell_s: float = 5.0
    collection_s: float = 60.0
    stabilize_timeout_s: float = 120.0
    setpoints_kpa: List[float] = field(default_factory=list)
    # The plant is ASYMMETRIC: pressure rises fast (open the air valve) but falls
    # slowly (only by permeation once the valve is closed). Two mitigations:
    sort_ascending: bool = True   # run setpoints low->high so we never wait on a slow fall
    ramp_kpa_s: float = 3.0       # ramp the PID target toward each setpoint (0 = off)
                                  # so the loop approaches from below without overshoot


@dataclass
class SimConfig:
    supply_pressure_kpa: float = 100.0
    # compressor cycling: sinusoidal supply-pressure disturbance the PID must reject
    supply_wobble_kpa: float = 0.0
    supply_wobble_period_s: float = 30.0
    # Asymmetric inline-throttle plant (matches the real rig): opening the valve
    # fills FAST (k_in), closing it only lets pressure decay SLOWLY through the
    # membrane (k_drain << k_in effect). Real observation: rise ~seconds, fall
    # ~tens of seconds and never immediate.
    k_in: float = 0.3      # inflow gain at full open (fast rise)
    k_drain: float = 0.05  # permeation decay rate (slow fall; tau ~ 1/k_drain)
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
    viscosity_pa_s: float = 1.0e-3  # effective mu, derived from the water temperature
    water_temp_c: float = 21.0     # temperature that viscosity_pa_s corresponds to
    label: str = ""
    # Specimen pressure limit — meshes are delicate, and this is usually well
    # below what the vessel and the safety cutoff would allow. No setpoint above
    # it can be queued or started. 0 = unset (the safety cutoff governs).
    max_pressure_kpa: float = 0.0


@dataclass
class TemperatureConfig:
    """Water temperature = a test variable (you vary the bath). mu depends on it.
    source 'probe' reads a DS18B20; 'manual' uses manual_c (or the last-known temp
    if a probe read fails). read_period_s is the (slow) polling rate off the fast
    control loop."""
    source: str = "manual"     # "probe" (DS18B20 on 1-Wire) or "manual"
    manual_c: float = 21.0     # used when source=manual, or as probe fallback
    w1_id: str = ""            # DS18B20 device id, e.g. "28-01234"; empty = auto-detect
    read_period_s: float = 3.0


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
    temperature: TemperatureConfig = field(default_factory=TemperatureConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # --- unit conversion helpers used by the UI/logging ----------------------
    def disp(self, value_kpa: float) -> float:
        """kPa -> display units."""
        return from_kpa(value_kpa, self.units)

    def to_internal(self, value_display: float) -> float:
        """display units -> kPa."""
        return to_kpa(value_display, self.units)

    def specimen_limit_kpa(self) -> float:
        """Highest pressure any setpoint may request: the specimen's own limit
        when one is set, otherwise the safety cutoff. Never above the cutoff."""
        m = self.membrane.max_pressure_kpa
        if m and m > 0:
            return min(m, self.safety.max_pressure_kpa)
        return self.safety.max_pressure_kpa

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
            servo_close_us=int(v.get("servo_close_us", 0) or 0),
            close_hold_s=float(v.get("close_hold_s", 1.5)),
        )

        d = raw.get("diverter", {})
        diverter = DiverterConfig(
            pin=int(d.get("pin", 23)),
            active_high=bool(d.get("active_high", True)),
        )

        p = raw.get("pid", {})
        pid = PidConfig(
            kp=float(p.get("kp", 4.0)),
            ki=float(p.get("ki", 0.4)),
            kd=float(p.get("kd", 1.0)),
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
            overshoot_margin_kpa=k(sf.get("overshoot_margin", 10.0)),
            close_check_s=float(sf.get("close_check_s", 20.0)),
            close_check_min_drop_kpa=k(sf.get("close_check_min_drop", 1.0)),
        )

        t = raw.get("test", {})
        test = TestConfig(
            tolerance_pct=float(t.get("tolerance_pct", 2.0)),
            dwell_s=float(t.get("dwell_s", 5.0)),
            collection_s=float(t.get("collection_s", 60.0)),
            stabilize_timeout_s=float(t.get("stabilize_timeout_s", 120.0)),
            setpoints_kpa=[k(x) for x in t.get("setpoints", [])],
            sort_ascending=bool(t.get("sort_ascending", True)),
            ramp_kpa_s=k(t.get("ramp_kpa_s", 3.0)),
        )

        sm = raw.get("sim", {})
        sim = SimConfig(
            supply_pressure_kpa=k(sm.get("supply_pressure", 100.0)),
            supply_wobble_kpa=k(sm.get("supply_wobble", 0.0)),
            supply_wobble_period_s=float(sm.get("supply_wobble_period_s", 30.0)),
            k_in=float(sm.get("k_in", 0.3)),
            k_drain=float(sm.get("k_drain", 0.05)),
            process_noise_kpa=k(sm.get("process_noise", 0.05)),
            sensor_noise_kpa=k(sm.get("sensor_noise", 0.15)),
            flow_per_kpa_m3s=float(sm.get("flow_per_kpa_m3s", 7.86e-7)),
            flow_intercept_m3s=float(sm.get("flow_intercept_m3s", 1.3072e-5)),
            flow_noise_frac=float(sm.get("flow_noise_frac", 0.02)),
        )

        mb = raw.get("membrane", {})
        tc = raw.get("temperature", {})
        # temperature is the source of truth for mu. back-compat: old configs put
        # the temp under membrane.water_temp_c.
        manual_c = float(tc.get("manual_c", mb.get("water_temp_c", 21.0)))
        temperature = TemperatureConfig(
            source=str(tc.get("source", "manual")),
            manual_c=manual_c,
            w1_id=str(tc.get("w1_id", "")),
            read_period_s=float(tc.get("read_period_s", 3.0)),
        )
        # mu at the (manual/bath) temperature; the controller overrides this with
        # the live probe reading during a run (for distilled/pure water).
        viscosity = water_viscosity_pa_s(manual_c)
        membrane = MembraneConfig(
            area_m2=float(mb["area_cm2"]) * 1e-4 if "area_cm2" in mb else float(mb.get("area_m2", 6.4e-5)),
            thickness_m=float(mb["thickness_mm"]) * 1e-3 if "thickness_mm" in mb else float(mb.get("thickness_m", 1.17e-4)),
            viscosity_pa_s=viscosity,
            water_temp_c=manual_c,
            label=str(mb.get("label", "")),
            max_pressure_kpa=k(mb["max_pressure"]) if mb.get("max_pressure") else 0.0,
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
            temperature=temperature,
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
        if self.temperature.source not in ("manual", "probe"):
            errs.append(f"temperature.source must be manual or probe, got {self.temperature.source!r}")
        if self.sensor.range_max_kpa <= self.sensor.range_min_kpa:
            errs.append("sensor range_max must be > range_min")
        if self.safety.max_pressure_kpa > self.sensor.range_max_kpa:
            errs.append("safety.max_pressure exceeds the sensor's full-scale range")
        if self.membrane.max_pressure_kpa > self.safety.max_pressure_kpa:
            errs.append("membrane.max_pressure exceeds safety.max_pressure")
        limit = self.specimen_limit_kpa()
        for sp in self.test.setpoints_kpa:
            if sp > limit:
                errs.append(f"setpoint {sp:.1f} kPa exceeds the pressure limit ({limit:.1f} kPa)")
        if self.pid.output_max <= self.pid.output_min:
            errs.append("pid.output_max must be > output_min")
        if errs:
            raise ValueError("Invalid config:\n  - " + "\n  - ".join(errs))
