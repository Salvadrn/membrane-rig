"""Export a permeability run to a native .xlsx (mirrors the lab spreadsheet).

Builds a real Excel workbook with:
  * the (pressure, flow rate) data table (all replicate points)
  * a native scatter chart with a linear trendline that shows the equation and
    R² — Excel recomputes these itself, so the chart stays editable
  * the Darcy permeability (slope method) and mean hydraulic pore size cells

openpyxl is optional: if it isn't installed, the CSV/JSON/PNG still export and
this is skipped.
"""
from __future__ import annotations

from typing import Optional

SCI = "0.000E+00"


def xlsx_available() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except Exception:
        return False


def export_permeability_xlsx(result, out_path, *, title: str = "Q vs ΔP",
                             units: str = "kPa", points_detail=None) -> Optional[str]:
    if result.n < 1:
        return None
    from openpyxl import Workbook
    from openpyxl.chart import Reference, ScatterChart, Series
    from openpyxl.chart.marker import Marker
    from openpyxl.chart.trendline import Trendline
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Permeability"
    bold = Font(bold=True)

    # --- membrane header ------------------------------------------------------
    meta = [
        ("membrane", result.label or "—"),
        ("area (cm²)", result.area_m2 * 1e4),
        ("thickness (mm)", result.thickness_m * 1e3),
        ("water temp (°C)", result.water_temp_c),
        ("viscosity (Pa·s)", result.viscosity_pa_s),
    ]
    for i, (k, v) in enumerate(meta, start=1):
        ws.cell(row=i, column=1, value=k).font = bold
        ws.cell(row=i, column=2, value=v)

    # --- data table -----------------------------------------------------------
    head_row = 6
    ws.cell(row=head_row, column=2, value=f"pressure ({units})").font = bold
    ws.cell(row=head_row, column=3, value="flow rate (m³/s)").font = bold
    first = head_row + 1
    for j, (p, q) in enumerate(result.points_kpa_m3s):
        ws.cell(row=first + j, column=2, value=round(p, 4))
        c = ws.cell(row=first + j, column=3, value=q)
        c.number_format = SCI
    last = first + result.n - 1

    # --- native scatter chart + linear trendline ------------------------------
    chart = ScatterChart()
    chart.title = f"{title} — {result.label}" if result.label else title
    chart.x_axis.title = f"ΔP ({units})"
    chart.y_axis.title = "flow rate  Q  (m³/s)"
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.x_axis.scaling.min = 0
    chart.y_axis.scaling.min = 0
    chart.height = 9
    chart.width = 16
    xref = Reference(ws, min_col=2, min_row=first, max_row=last)
    yref = Reference(ws, min_col=3, min_row=first, max_row=last)
    series = Series(yref, xref, title="Q")
    series.marker = Marker(symbol="circle", size=6)
    series.graphicalProperties.line.noFill = True  # markers only (scatter)
    series.trendline = Trendline(trendlineType="linear", dispEq=True, dispRSqr=True)
    chart.series.append(series)
    ws.add_chart(chart, "E6")

    # --- results block --------------------------------------------------------
    r = last + 2
    verdict = "follows Darcy's law" if result.follows_darcy else "low R² — check linearity"
    rows = [
        ("slope (m³/s per kPa)", result.slope_per_kpa, SCI),
        ("intercept (m³/s)", result.intercept_m3s, SCI),
        ("R²", round(result.r2, 6), None),
        ("Darcy permeability using the slope (m²)", result.k_darcy_m2, SCI),
        ("Mean hydraulic pore size (m)", result.pore_size_m, SCI),
        ("Mean hydraulic pore size (µm)", round(result.pore_size_m * 1e6, 4), None),
        ("verdict", verdict, None),
    ]
    for i, (label, val, fmt) in enumerate(rows):
        ws.cell(row=r + i, column=1, value=label).font = bold
        cell = ws.cell(row=r + i, column=2, value=val)
        if fmt:
            cell.number_format = fmt

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16

    # --- optional per-point summary sheet ------------------------------------
    if points_detail:
        ps = wb.create_sheet("Per point")
        cols = ["setpoint_kpa", "mean_kpa", "std_kpa", "min_kpa", "max_kpa",
                "in_band_fraction", "n_samples", "collection_s", "volume_ml", "flow_m3s"]
        for c, name in enumerate(cols, start=1):
            ps.cell(row=1, column=c, value=name).font = bold
        for ri, d in enumerate(points_detail, start=2):
            for c, name in enumerate(cols, start=1):
                cell = ps.cell(row=ri, column=c, value=d.get(name))
                if name == "flow_m3s":
                    cell.number_format = SCI

    out_path = str(out_path)
    wb.save(out_path)
    return out_path
