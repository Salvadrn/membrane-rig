<!--
ENLACE 8-minute talk — slide content (canonical source).
Direction: "Pizarra" (dark, high-contrast, one idea per slide). Gamma theme: onyx (b&w, bold, high contrast).
Fed to Gamma verbatim (textMode: preserve, cardSplit: inputTextBreaks, "---" = card break). 10 cards (Gamma's max).

DELIBERATELY SPARSE: Gamma scales type to fit, so fewer words = bigger, bolder text and room for a figure.
The full argument lives in script.md (what Adrián says) — slides are the backdrop, not the script.
If you add text here, the type shrinks. Cut instead.

Generated with imageOptions.source: placeholder — Gamma reserves an image area; Adrián drops the paper
figures in (fig5 → Darcy slide, fig1 → system slide, fig4 → validation slide). Delete unused placeholders.
All numbers are from the paper (simulation). Keep in sync with docs/paper/.
-->

# Automating a Membrane Permeability Test Rig

Closed-loop pressure control for constant-pressure permeability testing

Salvador Adrián Martínez García
ENLACE · TEMP Lab · UC San Diego · Summer 2026

Verified in simulation — not yet run on hardware

---

# Why this is hard to measure

Two-phase cooling wicks live or die by **pore size** — flow versus capillary pumping.

Permeability **k** is tiny: **10⁻¹³–10⁻¹² m²**.

Competing meshes differ by **less than 10×**, so it must be **repeatable**.

---

# The manual method hides two errors

**Pressure:** ±3 kPa by hand at a 20 kPa setpoint = **±15%** — and never recorded.

**Timing:** each hose transfer spills the same way — **bias, not noise**.

---

# Two errors. Two different fixes.

**Timing → eliminated.** The computer takes the clock: a solenoid switches on the same 20 Hz loop that samples pressure.

**Pressure → made honest.** Analyze against the **measured mean**, not the setpoint.

Regression averages out **scatter**. It can never undo **bias**.

---

# Darcy's law, read as a slope

**Q ∝ ΔP** — a straight line through the origin.

The **slope is the permeability**.

**R² ≥ 0.98** — a built-in check that it really is a line.

---

# The instrument checks itself

Warm water is thinner → the raw slope **rises**.

Permeability multiplies it back by viscosity — the two **cancel**.

**k must not change with temperature.** If it drifts, the chain is broken, not the membrane.

---

# The system

Existing vessel **untouched**.

Servo on the air-inlet **ball valve** · **20 Hz PID**.

Transducer → divider → **ADS1115** · **DS18B20** for temperature.

Solenoid **diverter** times collection.

Mechanical relief **outside the control system**.

---

# Validation — in simulation

**±8 kPa** supply disturbance → held to **0.21–0.69 kPa**.

15 °C sweep → k constant to **5 significant figures** while the raw slope moved **39%**.

Reproduced a real manual dataset: **k = 1.44 × 10⁻¹² m²**, pore **6.78 µm**, **R² = 0.994**.

---

# Trusted before it was built

**~US$300** · non-invasive · **verifiable with no hardware attached** — by design.

Every line ran end-to-end before a part was bought.

**Nothing has run on hardware yet.** The Pi boots; no cable is connected.

Next: commission and retune on the real rig.

---

# One idea to take away

One error **eliminated**. The other made **honest**.

That is the difference between automation and a Raspberry Pi bolted onto an experiment.

Thank you — TEMP Lab, ENLACE, Kwangsoo Cho, Prof. Renkun Chen.
