"""Render the Q-vs-ΔP permeability plot (matches the Excel chart style).

Scatter of every replicate point + linear trendline, annotated with the fit
equation, R², Darcy k and mean hydraulic pore size. Uses the Agg backend so it
works headless on the Raspberry Pi. matplotlib is an optional dependency: if it
isn't installed the numeric analysis still runs; only the PNG is skipped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def plot_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def plot_permeability(result, out_path, *, title: str = "Q vs ΔP",
                      units: str = "kPa", excluded_points=None,
                      flagged_points=None) -> Optional[str]:
    """Write a PNG for a PermeabilityResult. Returns the path, or None if
    matplotlib is missing or there aren't enough points.

    excluded_points / flagged_points are (ΔP kPa, Q m³/s) pairs from runs whose
    ceiling was raised mid-test — the two ways that can land:

      * excluded_points: dropped from the fit (the playlist path drops them).
        Drawn hollow grey so they are visibly absent-on-purpose. A point that
        just vanishes looks like it was never measured.
      * flagged_points: still IN the fit (the single-run path excludes nothing),
        so this k is partly derived from them. Ringed amber — the loudest case,
        because the number on the chart depends on those points.

    Both default to None, which renders exactly the plain plot.
    """
    if result.n < 2 or not out_path:
        # No path means no run is open (RunLogger.plot_path() -> None). Bail
        # instead of str(None), which silently writes a file called "None.png"
        # into the cwd and returns it as if it were a real artefact.
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [p for p, _ in result.points_kpa_m3s]
    ys = [q for _, q in result.points_kpa_m3s]
    excluded = list(excluded_points or [])
    flagged = list(flagged_points or [])
    # excluded points are outside the fit, so they don't constrain the axes —
    # scale to them anyway or they'd be drawn off-canvas and silently lost
    xmax = max(xs + [p for p, _ in excluded]) * 1.15
    ymax = max(ys + [q for _, q in excluded]) * 1.15
    x0, x1 = 0.0, xmax
    b, a = result.slope_per_kpa, result.intercept_m3s

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=130)
    ax.plot([x0, x1], [a + b * x0, a + b * x1], ":", color="#2f6fdb",
            linewidth=1.6, zorder=1)
    ax.scatter(xs, ys, s=42, color="#2f6fdb", alpha=0.75,
               edgecolors="#173a70", linewidths=0.5, zorder=2,
               label="Q (in fit)" if (excluded or flagged) else None)
    if flagged:
        ax.scatter([p for p, _ in flagged], [q for _, q in flagged], s=132,
                   facecolors="none", edgecolors="#c77700", linewidths=1.8,
                   zorder=3, label="ceiling raised — in fit")
    if excluded:
        ax.scatter([p for p, _ in excluded], [q for _, q in excluded], s=42,
                   facecolors="none", edgecolors="#8a929a", linewidths=1.2,
                   zorder=2, label="ceiling raised — excluded")
    if excluded or flagged:
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.9)

    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.set_xlabel(f"ΔP ({units})")
    ax.set_ylabel("flow rate  Q  (m³/s)")
    ttl = f"{title} — {result.label}" if result.label else title
    ax.set_title(ttl, loc="left", fontsize=12)
    ax.grid(True, color="#e2e6ea", linewidth=0.8)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    eq = (f"y = {b:.3e}·x + {a:.3e}\n"
          f"R² = {result.r2:.6f}")
    ax.text(0.97, 0.06, eq, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, color="#333",
            bbox=dict(boxstyle="round,pad=0.4", fc="#f4f6f8", ec="#cfd6dd"))

    verdict = "follows Darcy's law" if result.follows_darcy else "low R² — check linearity"
    tpart = f"{result.water_temp_c:.1f} °C, µ={result.viscosity_pa_s:.2e} · " if result.water_temp_c else ""
    # k's error bar, kept to a short "± x.xx%" so the caption stays one line.
    # Omitted when n < 3 (unknown, not zero) and when k <= 0, where a relative
    # error would come out negative — same guard the workbook uses.
    kse = getattr(result, "k_stderr_m2", 0.0)
    kpart = (f" ± {kse / result.k_darcy_m2 * 100:.2f}%"
             if kse > 0 and result.k_darcy_m2 > 0 else "")
    cap = (f"{tpart}k = {result.k_darcy_m2:.3e} m²{kpart}   ·   "
           f"pore d = {result.pore_size_m*1e6:.3f} µm   ·   {verdict}")
    fig.subplots_adjust(bottom=0.2)
    fig.text(0.5, 0.035, cap, ha="center", fontsize=10.5, color="#222")

    out_path = str(out_path)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
