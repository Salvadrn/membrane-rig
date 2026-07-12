"""Permeability analysis — the slope method (matches lab.divid.site).

Fit permeate flow rate Q against transmembrane pressure ΔP:

    Q = a + b·ΔP

and derive Darcy permeability from the slope:

    k = b_Pa · μ · L / A          (b_Pa = dQ/dΔP in (m³/s)/Pa)
    mean hydraulic pore size  d = √(32 · k)

Averaging per-point k is wrong (each point carries experimental error); the
slope over all replicate points is the robust estimate, and R² tells you how
well the data obeys Darcy's law. Everything here is SI (Pa, m³/s, m², m).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class PermeabilityResult:
    points_kpa_m3s: List[Tuple[float, float]] = field(default_factory=list)
    n: int = 0
    slope_per_kpa: float = 0.0     # dQ/dP with P in kPa (matches the sheet's y=..x)
    intercept_m3s: float = 0.0
    r2: float = 0.0
    slope_per_pa: float = 0.0
    k_darcy_m2: float = 0.0
    pore_size_m: float = 0.0
    follows_darcy: bool = False
    area_m2: float = 0.0
    thickness_m: float = 0.0
    viscosity_pa_s: float = 0.0
    water_temp_c: float = 0.0
    label: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["pore_size_um"] = self.pore_size_m * 1e6
        return d


def _linfit(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """Ordinary least squares. Returns (slope, intercept, r2)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return slope, intercept, r2


def fit_permeability(points_kpa_m3s, membrane, *, r2_darcy: float = 0.98) -> PermeabilityResult:
    """points_kpa_m3s: iterable of (pressure_kPa, flow_m3s). Needs >= 2 points."""
    pts = [(float(p), float(q)) for p, q in points_kpa_m3s if q is not None]
    res = PermeabilityResult(
        points_kpa_m3s=pts, n=len(pts),
        area_m2=membrane.area_m2, thickness_m=membrane.thickness_m,
        viscosity_pa_s=membrane.viscosity_pa_s,
        water_temp_c=getattr(membrane, "water_temp_c", 0.0),
        label=membrane.label,
    )
    if len(pts) < 2:
        res.note = "need >= 2 flow points to fit a slope"
        return res

    xs = [p for p, _ in pts]
    ys = [q for _, q in pts]
    slope_kpa, intercept, r2 = _linfit(xs, ys)
    res.slope_per_kpa = slope_kpa
    res.intercept_m3s = intercept
    res.r2 = r2
    res.slope_per_pa = slope_kpa / 1000.0  # (m^3/s)/kPa -> (m^3/s)/Pa
    res.k_darcy_m2 = res.slope_per_pa * membrane.viscosity_pa_s * membrane.thickness_m / membrane.area_m2
    res.pore_size_m = math.sqrt(32.0 * res.k_darcy_m2) if res.k_darcy_m2 > 0 else 0.0
    res.follows_darcy = r2 >= r2_darcy
    return res
