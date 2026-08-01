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
    """The real flow path, per Adrián at the bench:

        air hose -> water TANK, air injected above the water
                    a dip tube runs from the top down to the tank floor
                 -> line with the pressure GAUGE
                 -> CYLINDRICAL mesh holder; the specimen is only ~1 cm square
                 -> graduated cylinder

    The tank and the holder are separate pieces joined by tubing. The specimen
    gets a zoom callout because at holder scale it is nearly invisible — and how
    small it is, is part of why the measurement is delicate."""
    from matplotlib.patches import Ellipse

    FIGW, FIGH = 9.6, 5.4
    fig, ax = plt.subplots(figsize=(FIGW, FIGH))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ASPECT = FIGW / FIGH          # to make round things round on unequal axes

    def cylinder(x, w, y0, y1, ec=INK, lw=2.2, cap=0.19):
        """Vertical cylinder seen from the side: body + elliptical caps."""
        eh = w * (FIGW / (FIGH * 100)) * 100 * cap     # cap height in data units
        ax.plot([x, x], [y0, y1], color=ec, lw=lw)
        ax.plot([x + w, x + w], [y0, y1], color=ec, lw=lw)
        ax.add_patch(Ellipse((x + w / 2, y1), w, eh, fill=False, ec=ec, lw=lw))
        ax.add_patch(Ellipse((x + w / 2, y0), w, eh, fill=False, ec=ec, lw=lw,
                             alpha=0.45))
        return eh

    LINE_Y = 90

    # ---------------- water tank ----------------
    TX, TW, TY0, TY1 = 6, 21, 34, 74
    cylinder(TX, TW, TY0, TY1)
    ax.add_patch(plt.Rectangle((TX, TY0), TW, 26, fc=DATA, alpha=0.18, lw=0))
    ax.add_patch(Ellipse((TX + TW / 2, TY0 + 26), TW, TW * 0.055 * 100 * 0.30 / 100 * 100 * 0,
                         fill=False, lw=0))                      # (no cap on the water line)
    ax.plot([TX, TX + TW], [TY0 + 26, TY0 + 26], color=DATA, lw=1.8, alpha=0.9)
    ax.text(TX + TW / 2, 63.5, "air", fontsize=13.5, color=DIM, ha="center")
    ax.text(TX + TW / 2, 46, "water", fontsize=15, color=DATA, ha="center")
    ax.text(TX + TW / 2, 25, "tank", fontsize=15.5, color=INK, ha="center")

    ax.annotate("", xy=(TX + TW - 4, TY1 + 1), xytext=(TX + TW - 4, 98),
                arrowprops=dict(arrowstyle="-|>", color=WARN, lw=3.0,
                                shrinkA=0, shrinkB=0, mutation_scale=19))
    ax.text(TX + TW - 1.5, 97, "compressed air", fontsize=15.5, color=WARN,
            fontweight="bold", va="center")

    # dip tube: reaches the floor, so the air pushes water up and out
    DIP = TX + 5
    ax.plot([DIP, DIP], [LINE_Y, TY0 + 4], color=DATA, lw=2.2)
    ax.annotate("", xy=(DIP, TY0 + 11), xytext=(DIP, TY0 + 4),
                arrowprops=dict(arrowstyle="-|>", color=DATA, lw=2.2,
                                shrinkA=0, shrinkB=0, mutation_scale=14))
    ax.text(TX + TW / 2, 19, "tube reaches the floor", fontsize=11.5,
            color=DIM, ha="center")

    # ---------------- line + gauge ----------------
    HX, HW = 52, 15                                   # holder geometry
    ax.plot([DIP, HX + HW / 2], [LINE_Y, LINE_Y], color=INK, lw=2.3)
    GR = 4.6
    ax.add_patch(Ellipse((36, LINE_Y), GR * 2, GR * 2 * ASPECT,
                         fc="none", ec=INK, lw=2.2))
    ax.plot([36, 37.4], [LINE_Y, LINE_Y + 5.4], color=INK, lw=1.8)
    ax.add_patch(Ellipse((36, LINE_Y), 1.1, 1.1 * ASPECT, fc=INK, lw=0))
    ax.text(36, LINE_Y - 12, "pressure gauge", fontsize=14.5, color=INK,
            ha="center")

    # ---------------- cylindrical mesh holder ----------------
    HY0, HY1 = 52, 70
    ax.plot([HX + HW / 2, HX + HW / 2], [LINE_Y, HY1], color=INK, lw=2.3)
    cylinder(HX, HW, HY0, HY1)
    MESH_Y = 60.5
    ax.plot([HX, HX + HW], [MESH_Y, MESH_Y], color=WARN, lw=3.4)
    ax.text(HX - 2.5, 66, "mesh\nholder", fontsize=15, color=INK,
            ha="right", va="center", linespacing=1.3)

    # ---------------- zoom callout: the specimen is tiny ----------------
    ZX, ZY, ZR = 84, 62, 10.5
    ax.plot([HX + HW, ZX - ZR * 0.86], [MESH_Y + 0.6, ZY + ZR * 0.5],
            color=DIM, lw=1.1, ls=(0, (4, 3)))
    ax.plot([HX + HW, ZX - ZR * 0.86], [MESH_Y - 0.6, ZY - ZR * 0.5],
            color=DIM, lw=1.1, ls=(0, (4, 3)))
    zoom = Ellipse((ZX, ZY), ZR * 2, ZR * 2 * ASPECT, fc="none", ec=WARN, lw=2.4)
    ax.add_patch(zoom)
    for i in range(-4, 5):                            # the weave, magnified
        off = i * 2.05
        h, = ax.plot([ZX - ZR, ZX + ZR], [ZY + off * ASPECT, ZY + off * ASPECT],
                     color=WARN, lw=1.5, alpha=0.85)
        v, = ax.plot([ZX + off, ZX + off], [ZY - ZR * ASPECT, ZY + ZR * ASPECT],
                     color=WARN, lw=1.5, alpha=0.85)
        h.set_clip_path(zoom)
        v.set_clip_path(zoom)
    ax.text(ZX, ZY - ZR * ASPECT - 5, "the membrane", fontsize=15.5, color=WARN,
            fontweight="bold", ha="center")
    ax.text(ZX, ZY - ZR * ASPECT - 11, "about 1 cm square", fontsize=13,
            color=DIM, ha="center")

    # ---------------- graduated cylinder ----------------
    ax.annotate("", xy=(HX + HW / 2, 42), xytext=(HX + HW / 2, 51),
                arrowprops=dict(arrowstyle="-|>", color=DATA, lw=2.8,
                                shrinkA=0, shrinkB=0, mutation_scale=18))
    CX, CW = HX - 2, 19
    ax.add_patch(plt.Rectangle((CX, 16), CW, 25, fill=False, ec=INK, lw=2.3))
    ax.add_patch(plt.Rectangle((CX + 0.9, 16), CW - 1.8, 11, fc=DATA,
                               alpha=0.35, lw=0))
    for y in (20, 24, 28, 32, 36):
        ax.plot([CX, CX + 3.6], [y, y], color=DIM, lw=1.3)
    ax.text(CX + CW / 2, 11, "how much water,\nand for how long", fontsize=14.5,
            color=INK, ha="center", va="top", linespacing=1.35)

    ax.text(30, 8, "repeat at a\nfew pressures", fontsize=14, color=DIM,
            ha="center", va="top", style="italic", linespacing=1.3)
    save(fig, "talk_test_concept.png")


# ==================================================== 6. what R2 is checking ==
# Schematic, not rig data: Darcy predicts a straight line, so R2 is a free
# physics check. The bad panel bends the way a pressure drop that GROWS with
# flow bends it (turbulence, the diverter orifice, dip-tube losses) — the
# failure the rig is actually exposed to. R2 values are computed from the
# plotted points, not invented.
def fig_darcy_check():
    def ols_r2(xs, ys):
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        a = my - b * mx
        ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
        ss_tot = sum((y - my) ** 2 for y in ys)
        return a, b, 1 - ss_res / ss_tot

    P = [20, 30, 40, 50, 60]
    good = [1.02 * p + 0.6 for p in P]                    # a line, faint noise
    good = [g + d for g, d in zip(good, (0.5, -0.4, 0.3, -0.5, 0.4))]
    # Flow that stops keeping up: the mesh blinding, or turbulence setting in.
    # A GENTLE bend is not enough — with five points a mild curve still fits a
    # line at R2 > 0.99, which is exactly why R2 alone is a coarse check.
    bad = [21.0, 31.5, 40.0, 45.0, 47.0]

    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.8))
    for ax, ys, title, colour, verdict in (
        (axes[0], good, "Follows Darcy's law", GOOD, "the slope is the permeability"),
        (axes[1], bad, "Something is wrong", WARN, "below 0.98 — flagged, don't report a k"),
    ):
        a, b, r2 = ols_r2(P, ys)
        fx = [14, 66]
        ax.plot(fx, [a + b * x for x in fx], color=DIM, lw=2.2, ls="--",
                alpha=0.9, zorder=1)
        ax.scatter(P, ys, s=200, color=colour, edgecolor="white",
                   linewidth=2.0, zorder=3)
        ax.set_title(title, color=colour, fontsize=19, fontweight="bold", pad=10)
        ax.text(0.05, 0.93, f"R² = {r2:.3f}", transform=ax.transAxes,
                fontsize=19, color=colour, fontweight="bold", va="top")
        ax.text(0.5, -0.155, verdict, transform=ax.transAxes, fontsize=14.5,
                color=INK, ha="center")
        ax.set_xlim(14, 66)
        ax.set_ylim(0, 72)
        ax.set_xlabel("pressure", fontsize=13.5, color=DIM)
        bare(ax, keep_ticks=False)
    axes[0].set_ylabel("flow", fontsize=13.5, color=DIM)
    axes[1].annotate("flow stops\nkeeping up",
                     xy=(56, bad[4] - 2), xytext=(34, 16), fontsize=14.5,
                     color=WARN, linespacing=1.3,
                     arrowprops=dict(arrowstyle="-|>", color=WARN, lw=1.8,
                                     shrinkA=4, shrinkB=6, mutation_scale=14))
    fig.subplots_adjust(wspace=0.16)
    save(fig, "talk_darcy_check.png")


if __name__ == "__main__":
    print("talk figures ->")
    fig_test_concept()
    fig_darcy_check()
    fig_fit()
    fig_temperature()
    fig_scatter_vs_bias()
    fig_system()
    print("done")
