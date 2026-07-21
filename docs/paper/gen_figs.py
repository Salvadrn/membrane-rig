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
box(ax, 37, 25, 18, 8, "voltage divider 10 k / 20 k\n↓\nADS1115  16-bit ADC",
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

print("figures written")
