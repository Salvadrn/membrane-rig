import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.dirname(os.path.abspath(__file__))

INK = "#1a1a1a"
FLUID = "#2f5597"
SIG = "#8a6d00"
CTRL = "#7a2f2f"


def box(ax, x, y, w, h, text, fc="white", ec=INK, fs=8.5, lw=1.1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                                fc=fc, ec=ec, lw=lw))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=INK, linespacing=1.35)


def arrow(ax, p0, p1, color=INK, ls="-", lw=1.3):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=11,
                                 color=color, ls=ls, lw=lw, shrinkA=0, shrinkB=0))


def line(ax, p0, p1, color=INK, ls="-", lw=1.3):
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=color, ls=ls, lw=lw,
            solid_capstyle="butt")


DASH = (0, (4, 2))
DOT = (0, (1, 2.2))

# ================================================================ Figure 1
fig, ax = plt.subplots(figsize=(9.4, 5.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 72)
ax.axis("off")

# --- relief valve (vents upward, above the air line) ---
box(ax, 17, 64, 16, 6.5, "relief valve  ~90 kPa", fc="#fdecec", ec="#a33", fs=8)
ax.text(34.5, 67.2, "mechanical — vents regardless of software",
        fontsize=7.5, color="#a33", va="center")

# --- process row ---
box(ax, 1, 52, 13, 7, "compressed\nair supply", fc="#eef3fb", ec=FLUID)
box(ax, 18, 51, 15, 9, "ball valve\n+ servo\n(quarter turn)", fc="#eef3fb", ec=FLUID)
box(ax, 37, 49, 18, 12, "pressure vessel\nair over water\n———\nmembrane specimen",
    fc="#eef3fb", ec=FLUID)
box(ax, 59, 51, 13, 8, "3-way\ndiverter", fc="#eef3fb", ec=FLUID)
box(ax, 76, 55.5, 22, 6, "waste", fc="#f7f7f7", ec=FLUID)
box(ax, 76, 46, 22, 7, "graduated\ncontainer", fc="#f7f7f7", ec=FLUID)

arrow(ax, (14, 55.5), (18, 55.5), FLUID)
arrow(ax, (33, 55.5), (37, 55.5), FLUID)
arrow(ax, (55, 55), (59, 55), FLUID)
arrow(ax, (72, 56.5), (76, 58.5), FLUID)
arrow(ax, (72, 53.5), (76, 49.5), FLUID)
arrow(ax, (25, 60), (25, 64), "#a33")

# --- measurement chain ---
box(ax, 37, 36, 18, 8, "pressure transducer\n0–103 kPa, 0.5–4.5 V",
    fc="#fffbe8", ec=SIG, fs=8)
box(ax, 37, 25, 18, 8, "voltage divider 10 k / 22 k\n↓\nADS1115  16-bit ADC",
    fc="#fffbe8", ec=SIG, fs=8)
box(ax, 76, 34, 22, 8, "DS18B20\nwater temperature", fc="#fffbe8", ec=SIG, fs=8)

arrow(ax, (46, 49), (46, 44), SIG, ls=DASH)
arrow(ax, (46, 36), (46, 33), SIG, ls=DASH)
line(ax, (46, 25), (46, 23), SIG, ls=DASH)
arrow(ax, (87, 46), (87, 42), SIG, ls=DASH)
line(ax, (87, 34), (87, 23), SIG, ls=DASH)
line(ax, (87, 23), (46, 23), SIG, ls=DASH)
arrow(ax, (46, 23), (30, 23), SIG, ls=DASH)
ax.text(35.5, 24.2, "I²C", fontsize=7.5, color=SIG, ha="center")
ax.text(89, 28, "1-Wire", fontsize=7.5, color=SIG, ha="left", va="center")

# --- controller and command paths ---
box(ax, 4, 6, 26, 18,
    "Raspberry Pi 4\n———\nPID control loop, 20 Hz\ntest sequencer\nsafety supervisor\ndata logging + web UI",
    fc="#f2ecec", ec=CTRL, lw=1.6)
box(ax, 58, 13, 16, 7, "MOSFET driver\n12 V", fc="#f2ecec", ec=CTRL, fs=8)
box(ax, 78, 4, 20, 13, "browser\nlaptop / phone\n———\nlive data, setpoints,\nrun history",
    fc="#f7f7f7", ec=CTRL, fs=8)

arrow(ax, (25, 24), (25, 51), CTRL)
ax.text(23.5, 40, "servo pulse\n(pigpio)", fontsize=7.5, color=CTRL,
        ha="right", va="center")
arrow(ax, (30, 16.5), (58, 16.5), CTRL)
ax.text(44, 17.8, "GPIO", fontsize=7.5, color=CTRL, ha="center")
arrow(ax, (66, 20), (66, 51), CTRL)
ax.text(67.5, 32, "solenoid\ndrive", fontsize=7.5, color=CTRL, ha="left", va="center")
arrow(ax, (30, 10), (78, 10), CTRL, ls=DOT)
ax.text(54, 8.2, "HTTP  (LAN or authenticated tunnel)", fontsize=7.5,
        color=CTRL, ha="center")

# --- legend ---
line(ax, (1, 48), (5, 48), FLUID)
ax.text(6, 48, "air / water", fontsize=7.5, va="center", color=FLUID)
line(ax, (1, 45), (5, 45), SIG, ls=DASH)
ax.text(6, 45, "measurement", fontsize=7.5, va="center", color=SIG)
line(ax, (1, 42), (5, 42), CTRL)
ax.text(6, 42, "command", fontsize=7.5, va="center", color=CTRL)

fig.savefig(f"{OUT}/fig1_system.png", dpi=200, bbox_inches="tight",
            facecolor="white", pad_inches=0.08)
plt.close(fig)

# ================================================================ Figure 2
fig, ax = plt.subplots(figsize=(9.4, 5.4))
ax.set_xlim(0, 100)
ax.set_ylim(0, 66)
ax.axis("off")

box(ax, 2, 57, 96, 8,
    "User interface layer      ui/web.py  (browser: live data, parameters, run history)      ·      ui/cli.py",
    fc="#eef3fb", ec=FLUID)

box(ax, 2, 36, 96, 16, "", fc="#fbfbfd", ec=INK, lw=0.9)
ax.text(4, 51, "Application layer      app.py  —  RigController", fontsize=8.5, va="top")
box(ax, 5, 37.5, 20, 9.5, "control/pid.py\nanti-windup,\nderivative on\nmeasurement", fs=7.6)
box(ax, 27.5, 37.5, 20, 9.5, "sequencer.py\nstabilize →\ncollect →\nadvance", fs=7.6)
box(ax, 50, 37.5, 20, 9.5, "safety.py\noverpressure,\nsensor-fault\ndetection", fs=7.6)
box(ax, 72.5, 37.5, 23, 9.5, "logging_csv.py\n20 Hz CSV +\nmetadata JSON", fs=7.6)

box(ax, 2, 21.5, 96, 12, "", fc="#fbfbfd", ec=INK, lw=0.9)
ax.text(4, 32.5, "Analysis layer      (post-run, automatic)", fontsize=8.5, va="top")
box(ax, 5, 22.8, 27, 5.8, "analysis.py — least-squares fit,\nk, pore size, R²", fs=7.6)
box(ax, 34.5, 22.8, 27, 5.8, "plotting.py — Q vs ΔP chart\nwith trendline", fs=7.6)
box(ax, 64, 22.8, 31.5, 5.8, "export_excel.py — workbook with\nnative editable chart", fs=7.6)

box(ax, 2, 7, 96, 12, "", fc="#fbfbfd", ec=INK, lw=0.9)
ax.text(4, 18, "Hardware abstraction layer      hal/interfaces.py  —  four abstract interfaces",
        fontsize=8.5, va="top")
box(ax, 5, 8.3, 42, 5.8, "REAL   ADS1115 · servo (pigpio) ·\nGPIO diverter · DS18B20",
    fc="#f2ecec", ec=CTRL, fs=7.6)
box(ax, 53, 8.3, 42.5, 5.8, "MOCK   plant_sim.py — first-order\npressure + Darcy flow model",
    fc="#eef7ee", ec="#2f6b2f", fs=7.6)

ax.text(50, 5.6, "one line in config.yaml selects which implementation is loaded",
        ha="center", fontsize=7.8, style="italic", color="#555")

box(ax, 2, 0.5, 96, 4,
    "config.py / config.yaml      every parameter — setpoints, gains, timings, limits, geometry — without touching code",
    fc="#f7f7f7", ec=INK, fs=8.2)

for y0, y1 in [(57, 52), (36, 33.5), (21.5, 19)]:
    arrow(ax, (50, y0), (50, y1), "#888", lw=1.0)

fig.savefig(f"{OUT}/fig2_software.png", dpi=200, bbox_inches="tight",
            facecolor="white", pad_inches=0.08)
plt.close(fig)

# ================================================================ Figure 3
# Closed-loop control block diagram
fig, ax = plt.subplots(figsize=(9.6, 4.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 50)
ax.axis("off")

def circle(ax, x, y, r, text):
    ax.add_patch(plt.Circle((x, y), r, fc="white", ec=INK, lw=1.2))
    ax.text(x, y, text, ha="center", va="center", fontsize=10)

box(ax, 1, 34, 12, 8, "setpoint\nsequence\n20/40/60 kPa", fs=7.8)
box(ax, 17, 34, 13, 8, "ramp limiter\n3 kPa/s\n(starts at\ncurrent P)", fs=7.6)
circle(ax, 36.5, 38, 2.3, "Σ")
ax.text(34.2, 41.6, "+", fontsize=9)
ax.text(33.6, 34.6, "−", fontsize=11)

# PID box with internals
box(ax, 42, 27, 24, 21, "", fc="#fbfbfd", ec=CTRL, lw=1.4)
ax.text(54, 45.7, "PID  (20 Hz)", ha="center", fontsize=8.6, color=CTRL)
box(ax, 44, 39.5, 20, 4.2, "P:  Kp·e     (Kp = 4.0)", fs=7.4)
box(ax, 44, 34.3, 20, 4.2, "I:  I += Ki·e·Δt   (Ki = 0.4)", fs=7.4)
box(ax, 44, 29.1, 20, 4.2, "D:  −Kd·(filtered dŷ/dt)", fs=7.4)
box(ax, 70, 34, 11, 8, "clamp\n0–100 %", fs=7.8)
arrow(ax, (38.8, 38), (42, 38), INK)
arrow(ax, (66, 38), (70, 38), INK)
# anti-windup feedback
line(ax, (75.5, 34), (75.5, 26), "#a33", ls=DASH)
line(ax, (75.5, 26), (54, 26), "#a33", ls=DASH)
arrow(ax, (54, 26), (54, 27), "#a33", ls=DASH)

box(ax, 85, 34, 13, 8, "servo\n700–2300 µs\n→ ball valve", fs=7.6)
arrow(ax, (81, 38), (85, 38), CTRL)
ax.text(83, 39.4, "u", fontsize=8.5, style="italic", color=CTRL)

# anti-windup label (left of the wobble box, clear of it)
ax.text(46, 24.6, "anti-windup:  I += (u − u_raw)\nwhen the clamp is active",
        fontsize=7.2, color="#a33", ha="center", va="center")

# disturbance
box(ax, 62, 19, 33, 4.6, "supply wobble   P_s(t) = 100 + 8·sin(2πt / 25 s)",
    fc="#fdecec", ec="#a33", fs=7.2)
arrow(ax, (78, 19), (78, 15.4), "#a33")

# plant
box(ax, 56, 4, 42, 11.4,
    "vessel plant\ndP/dt = k_in·(u/100)·(P_s(t) − P)  −  k_drain·P",
    fc="#eef3fb", ec=FLUID, fs=7.8)
arrow(ax, (91.5, 34), (91.5, 15.4), CTRL)

# sensor feedback
box(ax, 14, 4, 34, 11.4,
    "transducer 0.5–4.5 V  →  divider ×0.6875  →\nADS1115 (16-bit)  →  pressure",
    fc="#fffbe8", ec=SIG, fs=7.6)
arrow(ax, (56, 9.7), (48, 9.7), SIG, ls=DASH)
line(ax, (14, 9.7), (7, 9.7), SIG, ls=DASH)
line(ax, (7, 9.7), (7, 30.5), SIG, ls=DASH)
line(ax, (7, 30.5), (36.5, 30.5), SIG, ls=DASH)
arrow(ax, (36.5, 30.5), (36.5, 35.7), SIG, ls=DASH)
ax.text(9, 32, "measurement ŷ  (also feeds the D term)", fontsize=7.4, color=SIG)
arrow(ax, (13, 38), (17, 38), INK)
arrow(ax, (30, 38), (34.2, 38), INK)

fig.savefig(f"{OUT}/fig3_control.png", dpi=200, bbox_inches="tight",
            facecolor="white", pad_inches=0.08)
plt.close(fig)

# ================================================================ Figure 4
# Annotated timeline from the accelerated simulation trace
import csv

rows = list(csv.DictReader(open(f"{OUT}/trace.csv")))
t = [float(r["t_s"]) for r in rows]
p = [float(r["pressure_kpa"]) for r in rows]
sp = [float(r["setpoint_kpa"]) for r in rows]
u = [float(r["valve_pct"]) for r in rows]
coll = [int(r["diverter"]) for r in rows]

fig, (a1, a2) = plt.subplots(2, 1, figsize=(9.6, 5.4), sharex=True,
                             height_ratios=[2.1, 1.0],
                             gridspec_kw={"hspace": 0.12})
# collection windows
spans = []
start = None
for i, c in enumerate(coll):
    if c and start is None:
        start = t[i]
    elif not c and start is not None:
        spans.append((start, t[i - 1]))
        start = None
if start is not None:
    spans.append((start, t[-1]))
for (x0, x1) in spans:
    for a in (a1, a2):
        a.axvspan(x0, x1, color="#e4f0e4", zorder=0)

# tolerance bands around each setpoint segment
seg_start = 0
for i in range(1, len(t) + 1):
    if i == len(t) or sp[i] != sp[seg_start]:
        s = sp[seg_start]
        a1.fill_between([t[seg_start], t[i - 1]], s * 0.9, s * 1.1,
                        color="#dbe6f5", zorder=0.5)
        seg_start = i if i < len(t) else seg_start

a1.plot(t, sp, color="#888", lw=1.0, ls=(0, (4, 2)), label="setpoint")
a1.plot(t, p, color=FLUID, lw=1.1, label="measured pressure")
a1.set_ylabel("pressure (kPa)", fontsize=9)
a1.set_ylim(0, 70)
a1.legend(loc="upper left", fontsize=8, frameon=False)
for (x0, x1) in spans:
    a1.text((x0 + x1) / 2, 3.5, "COLLECT 60 s", ha="center", fontsize=7.3,
            color="#2f6b2f")
a1.text(spans[0][0] - 9 if spans else 10, 3.5, "stabilize", ha="right",
        fontsize=7.3, color="#666")
a1.text(2, 47, "band = setpoint ± 10 %\nshaded = diverter → measurement container",
        fontsize=7.6, color="#555", va="top")

a2.plot(t, u, color=CTRL, lw=1.0)
a2.set_ylabel("valve command (%)", fontsize=9)
a2.set_xlabel("time (s)", fontsize=9)
a2.set_ylim(0, 45)
a2.text(0.02, 0.94, "PID counter-modulates against the ±8 kPa / 25 s supply wobble",
        transform=a2.transAxes, ha="left", va="top", fontsize=7.6, color=CTRL)
for a in (a1, a2):
    a.grid(color="#eceff2", lw=0.7)
    a.spines["top"].set_visible(False)
    a.spines["right"].set_visible(False)

fig.savefig(f"{OUT}/fig4_sequence.png", dpi=200, bbox_inches="tight",
            facecolor="white", pad_inches=0.08)
plt.close(fig)

print("figures written")
