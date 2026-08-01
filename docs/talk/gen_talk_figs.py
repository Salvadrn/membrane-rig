"""Talk figures — presentation versions, NOT the paper's figures shrunk.

A paper figure is read at 30 cm with time; a talk figure is read from the back of
the room in the ~8 seconds the audience spares while also listening to you. So:
one idea per figure, large type, few elements, transparent background with light
ink for the dark "Pizarra" deck (a white rectangle on a dark slide glares).

This is deliberately SEPARATE from ../paper/gen_figs.py: that one feeds the .docx
and must keep its white background. Do not merge them.

Numbers come from offline_sim.py's own stdout (the paper's RUN A and temperature
sweep), so the talk cannot contradict the paper. Re-run offline_sim.py and update
the constants below if the control code ever changes.

    ./.venv/bin/python docs/talk/gen_talk_figs.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.dirname(os.path.abspath(__file__))

# --- palette for a dark slide (transparent background, light ink) ------------
INK = "#ECEFF2"      # primary text / axes
DIM = "#98A0A8"      # secondary text, gridlines
DATA = "#7FD1FF"     # the measurement (cool, calm)
WARN = "#FFB454"     # the thing that moves / the error (warm, alarming)
GOOD = "#8BE6A8"     # the thing that stays put

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": DIM,
    "xtick.color": INK,
    "ytick.color": INK,
    "font.size": 15,
    "axes.labelsize": 16,
    "axes.titlesize": 18,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
    "figure.dpi": 200,
})


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, transparent=True, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print("  ", name)


def bare(ax, keep_ticks=True):
    """Strip the frame down to two axes — fewer lines, more signal."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(1.2)
    if not keep_ticks:
        ax.set_xticks([])
        ax.set_yticks([])


# =============================================================== 1. the fit ==
# RUN A, straight from offline_sim.py stdout. The evidence slide: the line, the
# points, and R² — nothing else competes.
FIT_PTS = [(20.09, 2.9570e-05), (40.08, 4.5662e-05), (60.06, 6.1688e-05)]
FIT_SLOPE, FIT_INTERCEPT = 8.0361e-07, 1.3419e-05      # Q = a + b·ΔP
FIT_R2, FIT_K, FIT_PORE = 1.00000, 1.4365e-12, 6.780


def fig_fit():
    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    xs = [p[0] for p in FIT_PTS]
    ys = [p[1] * 1e6 for p in FIT_PTS]                  # m³/s → mL/s (×1e6)
    line_x = [0, 68]
    line_y = [(FIT_INTERCEPT + FIT_SLOPE * x) * 1e6 for x in line_x]

    ax.plot(line_x, line_y, color=DATA, lw=2.6, alpha=0.85, zorder=1)
    ax.scatter(xs, ys, s=260, color=DATA, edgecolor="white", linewidth=2.2, zorder=3)

    ax.set_xlabel("measured pressure  ΔP  (kPa)")
    ax.set_ylabel("flow  Q  (mL/s)")
    ax.set_xlim(0, 68)
    ax.set_ylim(0, 72)
    ax.grid(True, color=DIM, alpha=0.18, lw=0.9)
    bare(ax)

    # The two things worth saying, said big.
    ax.text(0.04, 0.95, "slope = permeability", transform=ax.transAxes,
            fontsize=17, color=DATA, va="top", fontweight="bold")
    ax.text(0.04, 0.855, "k = 1.44 × 10⁻¹² m²\nR² = 1.000",
            transform=ax.transAxes, fontsize=16, color=INK, va="top",
            linespacing=1.5)
    ax.text(0.97, 0.06, "each point = one 60 s collection", transform=ax.transAxes,
            fontsize=12.5, color=DIM, ha="right")
    save(fig, "talk_fit.png")


# ====================================================== 2. temperature check ==
# The best visual argument in the whole talk: the raw slope climbs 39% while the
# derived k does not move at all. Two lines, one flat, one not.
T_C = [20, 25, 30, 35]
T_SLOPE = [7.8591e-07, 8.8415e-07, 9.8752e-07, 1.0957e-06]
T_K = [1.4392e-12] * 4


def fig_temperature():
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    base_s = T_SLOPE[0]
    slope_rel = [s / base_s * 100 for s in T_SLOPE]
    k_rel = [k / T_K[0] * 100 for k in T_K]

    ax.plot(T_C, slope_rel, "-o", color=WARN, lw=3.2, ms=13,
            markeredgecolor="white", markeredgewidth=1.8, zorder=3)
    ax.plot(T_C, k_rel, "-o", color=GOOD, lw=3.2, ms=13,
            markeredgecolor="white", markeredgewidth=1.8, zorder=3)

    ax.annotate("raw slope  +39%", xy=(35, slope_rel[-1]), xytext=(-10, 13),
                textcoords="offset points", ha="right", va="bottom",
                fontsize=17, color=WARN, fontweight="bold")
    ax.annotate("permeability k\nunchanged", xy=(35, 100), xytext=(-8, 14),
                textcoords="offset points", ha="right", va="bottom",
                fontsize=17, color=GOOD, fontweight="bold", linespacing=1.35)

    ax.set_xlabel("water temperature  (°C)")
    ax.set_ylabel("relative to 20 °C  (%)")
    ax.set_xticks(T_C)
    ax.set_ylim(88, 152)
    ax.grid(True, color=DIM, alpha=0.18, lw=0.9)
    bare(ax)
    ax.text(0.5, -0.235, "warmer water flows faster — but permeability is geometry, not fluid",
            transform=ax.transAxes, fontsize=13.5, color=DIM, ha="center")
    save(fig, "talk_temperature.png")


# ========================================================= 3. scatter vs bias ==
# Schematic, not data: why one error is survivable and the other is not.
def fig_scatter_vs_bias():
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.6))
    xs = [1, 2, 3, 4, 5]
    truth = [1.0, 2.0, 3.0, 4.0, 5.0]
    scattered = [1.35, 1.72, 3.28, 3.71, 5.22]        # noisy about the true line
    biased = [1.75, 2.75, 3.75, 4.75, 5.75]           # displaced, same slope

    for ax, pts, title, colour, verdict in (
        (axes[0], scattered, "Scatter", DATA, "the fit averages it out"),
        (axes[1], biased, "Bias", WARN, "the fit cannot undo it"),
    ):
        ax.plot([0.4, 5.6], [0.4, 5.6], color=DIM, lw=2.0, ls="--", alpha=0.75, zorder=1)
        ax.scatter(xs, pts, s=185, color=colour, edgecolor="white",
                   linewidth=1.9, zorder=3)
        ax.set_title(title, color=colour, fontsize=21, fontweight="bold", pad=12)
        ax.text(0.5, -0.13, verdict, transform=ax.transAxes, fontsize=15,
                color=INK, ha="center")
        ax.set_xlim(0.2, 6.0)
        ax.set_ylim(0.2, 6.6)
        bare(ax, keep_ticks=False)
        ax.set_xlabel("pressure", fontsize=13, color=DIM)
    axes[0].set_ylabel("flow", fontsize=13, color=DIM)
    axes[0].text(0.05, 0.93, "true line", transform=axes[0].transAxes,
                 fontsize=12.5, color=DIM, style="italic")
    fig.subplots_adjust(wspace=0.18)
    save(fig, "talk_scatter_vs_bias.png")


# ============================================================== 4. the system ==
# Radically simplified vs the paper's fig. 1: the audience needs the two loops,
# not the full block diagram.
def fig_system():
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 58)
    ax.axis("off")

    def box(x, y, w, h, text, colour=INK, fs=14.5, lw=2.0):
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=False, ec=colour,
                                   lw=lw, joinstyle="round"))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=INK, linespacing=1.35)

    def arrow(p0, p1, colour, lw=2.2, ls="-"):
        ax.annotate("", xy=p1, xytext=p0,
                    arrowprops=dict(arrowstyle="-|>", color=colour, lw=lw,
                                    linestyle=ls, shrinkA=0, shrinkB=0,
                                    mutation_scale=18))

    box(37, 30, 26, 13, "pressure vessel\n+ membrane")
    box(4, 30, 22, 13, "valve\n+ servo", colour=DATA)
    box(37, 6, 26, 12, "PID  20 Hz", colour=DATA)
    box(75, 30, 21, 13, "diverter", colour=WARN)
    box(75, 6, 21, 12, "collection\ntimer", colour=WARN)

    # pressure loop
    arrow((26, 36.5), (37, 36.5), DATA)
    arrow((50, 30), (50, 18), DATA)
    arrow((37, 12), (15, 12), DATA)
    arrow((15, 12), (15, 30), DATA)
    ax.text(15, 25.5, "measure", ha="center", fontsize=12.5, color=DATA)
    # collection loop
    arrow((63, 36.5), (75, 36.5), INK)
    arrow((85.5, 18), (85.5, 30), WARN)
    ax.text(33, 51, "pressure loop", ha="center",
            fontsize=17, color=DATA, fontweight="bold")
    ax.text(33, 46, "holds the setpoint", ha="center", fontsize=13, color=DIM)
    ax.text(85.5, 51, "collection loop", ha="center",
            fontsize=17, color=WARN, fontweight="bold")
    ax.text(85.5, 46, "exact timing", ha="center", fontsize=13, color=DIM)
    ax.text(85.5, 1.5, "same 20 Hz clock", ha="center", fontsize=12.5, color=DIM)
    save(fig, "talk_system.png")


# ========================================================= 5. what the test is ==
# Slide 2, for the half of the room that has never seen this experiment. Concept
# only — no electronics, no PID (that is the system figure's job): pressure in,
# membrane, water out, measured over a known time.
def fig_test_concept():
    """THIS rig, not a generic filter cartoon: air-over-water in a stainless
    vessel, with the specimen clamped in the BOLTED FLANGE AT THE BASE (Adrián
    confirmed from the bench — the paper's "mid-plane" wording was wrong).
    Compressed air presses on the water column; permeate leaves underneath."""
    fig, ax = plt.subplots(figsize=(7.0, 5.8))
    ax.set_xlim(0, 100)
    ax.set_ylim(-4, 100)
    ax.axis("off")

    VX0, VX1 = 22, 54          # vessel walls
    BASE = 30                  # the bolted base flange

    # --- compressed air in ---
    ax.annotate("", xy=(38, 86), xytext=(38, 99),
                arrowprops=dict(arrowstyle="-|>", color=WARN, lw=3.2,
                                shrinkA=0, shrinkB=0, mutation_scale=20))
    ax.text(43, 95, "compressed air", fontsize=16, color=WARN,
            fontweight="bold", va="center")

    # --- vessel: air pressing on the water column ---
    ax.add_patch(plt.Rectangle((VX0, BASE + 4), VX1 - VX0, 56,
                               fill=False, ec=INK, lw=2.4))
    ax.add_patch(plt.Rectangle((VX0 + 0.9, BASE + 4), VX1 - VX0 - 1.8, 30,
                               fc=DATA, alpha=0.22, lw=0))
    ax.plot([VX0 + 0.9, VX1 - 0.9], [BASE + 34, BASE + 34], color=DATA,
            lw=1.8, alpha=0.85)
    ax.text(38, 78, "air", fontsize=15, color=DIM, ha="center")
    ax.text(38, 48, "water", fontsize=15.5, color=DATA, ha="center")

    # --- bolted base flange, with the specimen clamped in it ---
    for x in (VX0 - 4.6, VX1 + 0.6):                       # flange ears
        ax.add_patch(plt.Rectangle((x, BASE - 0.8), 4.0, 5.2,
                                   fc="none", ec=DIM, lw=1.8))
    ax.add_patch(plt.Rectangle((VX0, BASE + 0.6), VX1 - VX0, 3.4,
                               fc="none", ec=WARN, lw=2.0, hatch="xx"))
    ax.annotate("the membrane,\nbolted in at the base",
                xy=(VX1 + 5.0, BASE + 2.2), xytext=(63, BASE + 2.2),
                textcoords="data", fontsize=16, color=WARN, fontweight="bold",
                va="center", linespacing=1.3,
                arrowprops=dict(arrowstyle="-", color=WARN, lw=1.6,
                                shrinkA=2, shrinkB=4))

    # --- permeate falls straight through ---
    ax.annotate("", xy=(38, 22), xytext=(38, 29),
                arrowprops=dict(arrowstyle="-|>", color=DATA, lw=2.8,
                                shrinkA=0, shrinkB=0, mutation_scale=18))

    # --- graduated cylinder ---
    ax.add_patch(plt.Rectangle((28, -1), 20, 23, fill=False, ec=INK, lw=2.4))
    ax.add_patch(plt.Rectangle((28.9, -1), 18.2, 11, fc=DATA, alpha=0.35, lw=0))
    for y in (3, 7, 11, 15, 19):
        ax.plot([28, 31.5], [y, y], color=DIM, lw=1.3)
    ax.annotate("how much water,\nand for how long",
                xy=(48, 9), xytext=(53, 9), textcoords="data",
                fontsize=16, color=INK, va="center", linespacing=1.35,
                arrowprops=dict(arrowstyle="-", color=DIM, lw=1.6,
                                shrinkA=2, shrinkB=4))

    ax.text(11, 62, "repeat at\na few\npressures", fontsize=14.5, color=DIM,
            ha="center", style="italic", linespacing=1.35)
    save(fig, "talk_test_concept.png")


if __name__ == "__main__":
    print("talk figures ->")
    fig_test_concept()
    fig_fit()
    fig_temperature()
    fig_scatter_vs_bias()
    fig_system()
    print("done")
