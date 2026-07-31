# ENLACE talk — presenter script (8:00)

**Audience:** undergraduate summer-research program, mixed background (area mentors + peers from other disciplines). Assume no one knows membranes; Darcy and the slope must land on their own.
**Total:** 8:00, 10 slides. Times are cumulative — if you pass the mark, cut a sentence, don't rush the next slide.
**Gamma deck:** https://gamma.app/docs/rguwb2l0i0i88fn
**The one rule:** say "in simulation" out loud on the title and again on slide 8. Never let a number be heard without it. It's a strength, not an apology.

**The slides are deliberately sparse** — big, heavy type, a few words each. The argument lives here, in what you say. Don't read the slides; they're the backdrop.

**On the day, don't hold this file — hold [`cue-card.html`](cue-card.html).** One page, printable, readable on a phone: the clock, the opening line of every slide, and the numbers you can't invent. This file is for rehearsing; that one is for standing up.

**Figures** — use the talk versions in this folder, *not* the paper's (those are black-on-white and glare on a dark slide). Gamma reserved an image area on each card:

| Slide | Figure |
|---|---|
| 4 · the core idea | `talk_scatter_vs_bias.png` |
| 5 · Darcy as a slope | `talk_fit.png` |
| 6 · it checks itself | `talk_temperature.png` |
| 7 · the system | `talk_system.png` |

Slides 1–3 and 8–10 are text only — delete their placeholders. Regenerate with `./.venv/bin/python docs/talk/gen_talk_figs.py`.

---

### 1 · Title — 0:00–0:20
"This summer I built an instrument that automates a membrane-permeability test. One line before I start: everything I'll show is **verified in simulation** — the rig itself hasn't run on hardware yet. I'll come back to why that's deliberate."

### 2 · Why it's hard — 0:20–1:15
"The lab builds two-phase cooling devices — they move heat by boiling a liquid through a porous mesh wick. The mesh's **pore size** is the whole game: wide pores flow more, fine pores pump harder by capillary action. The property that governs it is **permeability, k** — and it's hard to measure two ways: it's tiny, around 10⁻¹³ to 10⁻¹² square meters, and the meshes you compare differ by **less than a factor of ten**. So 'roughly right' is useless — it has to be **repeatable**."
> _Enrich once Adrián sends Kwangsoo's specifics: which device, the research question, where his measurement fits._

### 3 · The two errors — 1:15–2:10
"Today it's done by hand: hold the pressure with a valve, time the collection with a stopwatch. Two errors sneak in. Pressure: a hand wanders ±3 kPa, and at the lowest setpoint, 20 kPa, that's **±15%** on your independent variable — and it's **never written down**, so the analysis trusts a pressure that was never true. Timing: every time you move the hose you spill a little, the **same way every time**. That's not noise that averages out — it's **bias**."

### 4 · The core idea — 2:10–3:05  ← the heart, don't cut this
> _FIGURE: talk_scatter_vs_bias.png_
"Here's the idea the whole project turns on: two different errors need two different fixes. The **timing** error you can just **delete** — give the clock to the computer. A solenoid switches collection on the very same 20 Hz loop that samples pressure, so timing is exact. The **pressure** error you *can't* delete with cheap hardware — so you make it **honest**: analyze against the **measured average** pressure of each window, not the setpoint you aimed for. Regression averages out **scatter**; it can never undo **bias**. We turned hidden bias into visible scatter."

### 5 · Darcy as a slope — 3:05–4:05
> _FIGURE: talk_fit.png_
"The physics is Darcy's law, and you don't need membranes to read it: flow is proportional to pressure — a straight line through the origin. The **slope of that line is the permeability**. Two nice consequences. The R-squared is a free physics check — if it's not a straight line the sample isn't behaving, and the software flags anything under 0.98. And taking the slope, instead of averaging a k at each point, means a constant offset — a zero error, a small leak — lands in the intercept and never touches the answer."

### 6 · It checks itself — 4:05–4:45
> _FIGURE: talk_temperature.png_
"There's a built-in sanity check. Warm water is thinner, so it flows faster and the raw slope goes up. But to get permeability you multiply the slope by viscosity again — and the two exactly cancel. So **k must not change with temperature**; it's geometry, not fluid. If it ever does drift with temperature, you know the instrument is broken, not the membrane."

### 7 · The system — 4:45–5:45
> _FIGURE: talk_system.png_
"Here's the build. The existing vessel is left untouched — everything attaches around it. A hobby servo turns the air-inlet ball valve, driven by a PID loop at 20 Hz. Pressure goes through a divider into a 16-bit ADC; a digital probe reads water temperature for the viscosity correction. A three-way solenoid is the diverter that times collection. And notice the relief valve — **deliberately outside** the control system, a pure-mechanical backstop that vents even if all the software is dead. About three hundred dollars in parts."

### 8 · Validation, in simulation — 5:45–6:55
"Now the results — and these are all from **simulation**, running the exact production code against a modeled plant. Against a ±8 kPa oscillating supply — worse than the real bench should be — the loop held each setpoint to **two-tenths to seven-tenths of a kPa**. Across a 15 °C sweep the derived k held constant to **five significant figures** while the raw slope moved **39%** — the cancellation you just saw, proven end to end. And it reproduced a real, hand-taken dataset: k of 1.44e-12, pore size 6.8 microns, R-squared 0.994."

### 9 · Trusted before built, and honest — 6:55–7:45
"A word on discipline. It's ~$300 and non-invasive — vessel, plumbing, and gauge left alone. And **being verifiable without hardware was a design goal**: every line ran end-to-end before a part was bought. The honest flip side, plainly: **nothing has been tested on hardware yet** — the Pi boots, but not one cable is connected. Every number today is simulation; the point is the *logic* is already proven. Next is commissioning on the real rig and retuning the PID — and the simulation stays on as a regression harness."

### 10 · Take-away — 7:45–8:00
"So — one error eliminated, the other made honest. That's the line between real automation and a Raspberry Pi bolted onto an experiment. Thank you — to the TEMP Lab, ENLACE, Kwangsoo Cho, and Professor Renkun Chen."

---

## If you're long (cut in this order)
1. Slide 2 — drop the "factor of ten" clause; keep pore size and "repeatable".
2. Slide 6 — leave the figure up and say only: "k comes out independent of temperature — which is also how the rig proves itself." The picture does the rest in two seconds.
3. Slide 9 — compress the discipline points, but **never** the "nothing has run on hardware yet" line.
**Never cut slide 4.** It's the idea a mentor will remember.

## If you're short
- Slide 5 — walk the fit: point at one dot, "each dot is one 60-second collection."
- Slide 6 — trace the two curves with your hand: "this one climbs 39%, this one doesn't move at all."
- Slide 9 — the upgrade path: a stepper-driven needle valve if finer holding is ever needed.
