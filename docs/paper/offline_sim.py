"""Accelerated (no-sleep) simulation runs to regenerate the paper's validation
numbers with the CURRENT code and config, plus a trace CSV for the timeline
figure and the instrument's own Q-vs-dP plot."""
import os
import csv
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.config import Config, water_viscosity_pa_s
from src.control.pid import PID
from src.control.plant_sim import MockPlant
from src.sequencer import Sequencer, Phase
from src.analysis import fit_permeability
from src.plotting import plot_permeability
from dataclasses import replace

OUT = os.path.dirname(os.path.abspath(__file__))
CFG = Config.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"))
DT = 1.0 / CFG.pid.sample_hz


def run_sequence(temp_c, seed, trace_path=None):
    """One full 20/40/60 kPa sequence at the given water temperature.
    Mirrors app.py's tick: sensor read -> sequencer -> ramped PID -> plant."""
    random.seed(seed)
    plant = MockPlant(CFG)
    plant.set_viscosity(water_viscosity_pa_s(temp_c))
    pid = PID(CFG.pid.kp, CFG.pid.ki, CFG.pid.kd,
              CFG.pid.output_min, CFG.pid.output_max)
    seq = Sequencer(CFG)
    now = 0.0
    seq.start(list(CFG.test.setpoints_kpa), now)

    ramp_sp = None
    ramp_for = None
    collect_vol = {}
    trace = []

    while not seq.finished:
        meas = plant.pressure + random.gauss(0.0, CFG.sim.sensor_noise_kpa)
        st = seq.update(now, meas)
        if st.phase == Phase.DONE:
            break
        sp = st.setpoint_kpa
        # setpoint ramp, replicated from app._pid_target
        rate = CFG.test.ramp_kpa_s
        if rate <= 0:
            target = sp
        else:
            if ramp_for != sp:
                ramp_for, ramp_sp = sp, meas
            step = rate * DT
            ramp_sp = min(sp, ramp_sp + step) if ramp_sp < sp else max(sp, ramp_sp - step)
            target = ramp_sp
        cmd = pid.update(target, meas, DT)
        plant.set_command(cmd)
        if st.phase == Phase.COLLECTING:
            collect_vol[st.index] = collect_vol.get(st.index, 0.0) + plant.flow_m3s() * DT
        if trace_path:
            trace.append((round(now, 2), round(meas, 3), round(sp, 1),
                          round(cmd, 2), st.phase.value, int(st.diverter_measured),
                          int(st.in_band)))
        plant.step(DT)
        now += DT
        if now > 3600:
            raise RuntimeError("sim did not converge")

    results = seq.results
    for r in results:
        idx = results.index(r)
        v = collect_vol.get(idx, 0.0)
        r.volume_ml = v * 1e6
        r.flow_m3s = v / r.collection_s if r.collection_s > 0 else 0.0

    if trace_path:
        with open(trace_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "pressure_kpa", "setpoint_kpa", "valve_pct",
                        "phase", "diverter", "in_band"])
            w.writerows(trace)

    mu = water_viscosity_pa_s(temp_c)
    mb = replace(CFG.membrane, viscosity_pa_s=mu, water_temp_c=temp_c)
    pts = [(r.mean_kpa, r.flow_m3s) for r in results if r.success and r.flow_m3s > 0]
    fit = fit_permeability(pts, mb)
    return results, fit, now


# --- Run A: nominal 21 C with wobble, trace saved --------------------------
resA, fitA, dur = run_sequence(21.0, seed=7, trace_path=f"{OUT}/trace.csv")
print(f"RUN A (21 C, wobble +-{CFG.sim.supply_wobble_kpa} kPa / {CFG.sim.supply_wobble_period_s} s), duration {dur:.0f} s sim time")
for r in resA:
    print(f"  sp {r.setpoint_kpa:5.1f}  mean {r.mean_kpa:6.2f}  std {r.std_kpa:5.2f}  "
          f"min {r.min_kpa:6.2f}  max {r.max_kpa:6.2f}  in-band {r.in_band_fraction*100:5.1f}%  "
          f"n {r.n_samples}  V {r.volume_ml:7.1f} mL  Q {r.flow_m3s:.4e}")
print(f"  fit: slope {fitA.slope_per_kpa:.4e} (m3/s)/kPa  R2 {fitA.r2:.5f}  "
      f"k {fitA.k_darcy_m2:.4e} m2  pore {fitA.pore_size_m*1e6:.3f} um  darcy={fitA.follows_darcy}")

p = plot_permeability(fitA, f"{OUT}/fig5_fit.png", title="Q vs ΔP", units="kPa")
print("  plot:", p)

# valve counter-modulation during collection windows
import statistics
rows = list(csv.DictReader(open(f"{OUT}/trace.csv")))
for spv in (20.0, 40.0, 60.0):
    cmds = [float(r["valve_pct"]) for r in rows
            if r["phase"] == "collecting" and float(r["setpoint_kpa"]) == spv]
    if cmds:
        print(f"  valve @ sp {spv:.0f}: mean {statistics.mean(cmds):5.2f}%  "
              f"span {max(cmds)-min(cmds):5.2f}%  min {min(cmds):5.2f}  max {max(cmds):5.2f}")

# --- Runs B: temperature sweep --------------------------------------------
print("\nTEMPERATURE SWEEP (same specimen, same seed)")
ks = {}
for t in (20.0, 25.0, 30.0, 35.0):
    _, fit, _ = run_sequence(t, seed=11)
    ks[t] = fit
    print(f"  {t:4.1f} C  mu {water_viscosity_pa_s(t):.4e}  "
          f"slope {fit.slope_per_kpa:.4e}  k {fit.k_darcy_m2:.4e}  R2 {fit.r2:.5f}")
vals = [f.k_darcy_m2 for f in ks.values()]
spread = (max(vals) - min(vals)) / (sum(vals) / len(vals)) * 100
print(f"  k spread: {spread:.3f}%")
