<!--
ENLACE 8-minute talk — slide content (canonical source).
Direction: "Pizarra" (dark, high-contrast, one idea per slide). Gamma theme: default-dark ("Basic Dark").
Fed to Gamma verbatim (textMode: preserve, cardSplit: inputTextBreaks, "---" = card break). 10 cards (Gamma's max).
Figures are NOT in Gamma (it can't pull local PNGs) — insert fig5/fig1/fig4 in the editor; see script.md for which slide.
All numbers are from the paper (simulation). Keep in sync with docs/paper/ if the paper changes.
Language: English (matches the paper and the UCSD venue). Ask Adrián if he'll present in Spanish.
-->

# Automating a Membrane Permeability Test Rig

A closed-loop instrument for constant-pressure permeability testing

Salvador Adrián Martínez García
ENLACE Research Program · TEMP Lab · UC San Diego · Summer 2026

Verified in simulation — not yet run on hardware

---

# Why this measurement is hard

Two-phase cooling devices move heat by boiling a liquid through a woven-mesh wick, and the mesh's **pore size** trades flow against capillary pumping.

The property that governs it is **permeability, k** — and it lives in the tiny **10⁻¹³–10⁻¹² m²** range.

The meshes you compare differ by **less than a factor of ten**, so the result has to be **repeatable**, not just roughly right.

---

# The manual method hides two errors

An operator holds the pressure by hand and times the collection with a stopwatch.

**Pressure:** a ±3 kPa hand-wander at a 20 kPa setpoint is **±15%** on the independent variable — and it is **never recorded**.

**Timing:** every hose transfer spills a little, the same way each time — that is **bias, not noise**.

---

# Two errors. Two different fixes.

**Timing → give the clock to the computer.** A solenoid switches collection on the same 20 Hz loop that samples the pressure. *Eliminated.*

**Pressure → make it honest.** Analyze against the **measured mean** of each window, not the nominal setpoint.

Regression averages out **scatter**. It can never undo **bias**.

---

# Darcy's law, read as a slope

Flow is proportional to pressure: **Q ∝ ΔP** — a straight line through the origin.

The **slope is the permeability.**

**R² ≥ 0.98** is a built-in physics check: is it really a line?

Why the slope and not an average of point-by-point k? The fitted intercept absorbs zero-offsets and small leaks that would poison every single-point estimate.

---

# The instrument checks itself

Warmer water is thinner, so it flows faster and the raw slope **rises**.

But permeability multiplies that slope by viscosity again — and the two cancel.

**k must not change with temperature.** It is geometry, not fluid.

If k drifts with temperature, the measurement chain is broken — not the membrane.

---

# The system

The existing pressure vessel stays **untouched**.

A servo turns the air-inlet **ball valve**, driven by a **20 Hz PID** loop.

Transducer → divider → **ADS1115** (16-bit); a **DS18B20** reads water temperature.

A solenoid **diverter** times the permeate collection.

A mechanical **relief valve sits deliberately outside** the control system.

---

# Validation — in simulation

Against a **±8 kPa** oscillating supply disturbance, the loop held every setpoint to **0.21–0.69 kPa**.

Across a 15 °C sweep, k stayed constant to **five significant figures** while the raw slope moved **39%** — exactly as theory demands.

It reproduced a real, manually-taken dataset: **k = 1.44 × 10⁻¹² m², mean pore 6.78 µm, R² = 0.994.**

Every number on this slide is from **simulation**.

---

# Trusted before it was built — and honest about it

**~US$300** in commodity parts, and **non-invasive** — the existing vessel, plumbing, and gauge are left alone.

**Hardware-free verifiability was a design goal** — every line of control and analysis ran end-to-end before a single part was bought.

**Nothing has been tested on hardware yet:** the Raspberry Pi boots, but not one cable is connected — every number here is simulation.

**Next:** commission on the rig, retune the PID; the simulation stays on as a permanent regression harness.

---

# One idea to take away

One error was **eliminated**; the other was made **honest**.

That is the difference between automation and "a Raspberry Pi bolted onto an experiment."

Thank you — TEMP Lab, ENLACE, Kwangsoo Cho, and Prof. Renkun Chen.
