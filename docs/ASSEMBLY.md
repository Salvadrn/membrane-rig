# Assembly guide

Air-over-water rig: compressed air (lab panel, yellow line) pressurises the
stainless vessel through a **90° quarter-turn ball valve** (lever handle removed;
a servo turns the stem). Water permeates the membrane; the 3-way solenoid routes
permeate to waste or the graduated cylinder. See the BOM (`BOM.xlsx`) for parts.

> **Verdict on servo-driving the ball valve** (researched): precision is *not*
> the limit — the DS3218 holds ~0.5–1° (≈0.2° with a 2:1 reduction), far finer
> than needed, and a ball valve is *least* twitchy near-closed where this rig
> operates. **Torque is the question.** With the handle off the servo has zero
> leverage, so it must match the stem breakaway torque 1:1. **Measure it first**
> (§ "Measure before designing").

## Parts YOU design (3D-printed)

### 1. Servo↔ball-valve coupling (the critical part)
Handle off → the exposed stem is a square or double-D flat. Couple the servo to
it; **add a ~2:1 reduction** (servo swings ~180° → valve turns 90°) — this buys
both **torque margin** and **finer resolution near the seat**, and costs only a
slightly slower quarter-turn.
- **Broach the stem's flat** into a 100%-infill coupler + an M3 **set screw on
  the flat** (never rely on friction).
- Use a **metal horn / metal coupler** on the servo output — the plastic servo
  horn twists and strips under valve torque.
- Reduction: a **preloaded spur-gear pair or a single tight crank**, NOT a loose
  4-bar linkage (its ratio varies with angle and its slop eats the resolution
  gain). Anti-backlash (split gear or light return spring) keeps the fine step.
- **Do NOT use a self-locking worm**: the digital servo already holds while
  powered, and a self-locking ratio (≥~20:1) would let a 270° servo reach only
  ~13° at the valve — it can't make the full 90°.
- Print in PETG/ABS (PLA creeps under sustained torque).

### 2. Servo mount (reacts the torque)
The #1 failure mode of DIY servo-valve actuators is the printed part twisting.
- **React torque into a rigid metal frame** (aluminium plate / bracket bolted to
  the vessel or baseplate), never into the printed housing.
- Keep the servo axis coaxial with the valve stem (misalignment = binding); slot
  the DS3218 ear holes (~40×20×40.5 mm, 4 holes) for alignment.
- **Servo supply: 6 V**, off a supply that can source ~2 A peaks — a brownout at
  stall is the classic failure. 6 V because that is what the UBEC in the BOM
  (Hobbywing UBEC-3A, `B07T2CKC8G`) actually delivers: its jumper selects **5 V
  or 6 V only**, there is no 6.8 V position. The DS3218's *rated* range is
  4.8–6.8 V, so 6 V is valid — just not the top of it, which is where the
  datasheet quotes the headline torque. See `wiring_ubec.html`. If breakaway is
  high, use a higher-torque servo (e.g. DS3240MG ~40 kg·cm ≈ 3.9 N·m) instead.

### 3. Pi / electronics enclosure
- Fits: Pi 4 + half breadboard + UBEC + fuse holder. Mount the Pi on **M2.5**
  standoffs — its mounting holes are ~2.7 mm, so M3 does not pass through them.
  M3/M4 are for the baseplate and the servo bracket, not the Pi.
- Ventilation slots (Pi 4 runs warm); cable entry through bottom/side notches or
  glands so splashes can't run down wires into the box; splash lid on top.

### Where the transducer goes is a measurement decision, not a convenience

The rig is not one vessel with a membrane in it. It is a **chain of separate
pieces**, confirmed first-hand by Adrián:

> air line → **water tank** (dip tube reaching its floor) → line carrying the
> **existing manometer**, with a **tee whose other leg takes the transducer** →
> **membrane holder** (cylindrical, ~1 cm² specimen) → **3-way diverter** →
> waste while pressure stabilises, graduated cylinder while collecting.

That chain has a consequence worth getting right the first time. Everything
between the tank and the membrane — dip tube, fittings, tubing — carries the
full permeate flow and drops pressure doing it, and that drop **grows with Q**:

| Dip tube ID | 5 mL/s | 15 mL/s | 30 mL/s |
|---|---|---|---|
| 3 mm | 0.7 kPa | 7.9 kPa | **26.6 kPa** |
| 4 mm | 0.2 | 2.0 | 6.8 |
| 6 mm | 0.05 | 0.3 | 1.0 |

Against a 35 kPa setpoint, and in turbulent flow it scales as roughly Q^1.75 —
so it is **not** a constant offset. It bends the Darcy line exactly the way the
diverter's orifice does (§ Stage 10.5 in `COMMISSIONING.md`), and `R² ≥ 0.98`
will not catch it.

**The rig already has this right.** The tee sits in the line between tank and
holder, so the transducer measures downstream of the dip tube: every loss above
is *upstream* of the reading and simply means the tank runs a little higher,
while the sensor still reports the pressure the membrane actually sees. Mounted
on the **tank** instead, all of it would land between sensor and specimen and
bias `k` with a curvature nobody sees in the fit.

What *does* still count is whatever line remains **between the tee and the
holder inlet** — that stretch is inside the measurement. It is small if kept
short:

| Run from tee to holder | 15 mL/s | 30 mL/s |
|---|---|---|
| 5 cm of 1/4" tube | 0.23 kPa | 0.76 kPa |
| 30 cm of 1/4" tube | 1.36 kPa | 4.56 kPa |

So: **tee as close to the holder as the fittings allow.** A few centimetres is
noise against 35 kPa; a third of a metre of narrow tube is not.

This retroactively settles the BOM's "or mount at the existing manometer port"
option: it is not merely the cheaper choice, it is the correct one.

### The specimen mounts at the BASE flange — and the permeate line runs down

Confirmed from a photo of the bench: the membrane is clamped in the **bolted
flange at the bottom of the vessel**, and permeate leaves **beneath it**. (An
earlier description of a "mid-plane flange" was wrong; it survived a long time
because no amount of reading the code can tell you where a mesh is bolted.)

Two consequences for the plumbing:

- **Route the permeate line downhill** to the diverter and the container. Every
  metre of vertical rise is `ρgh` = **9.81 kPa** of back pressure, and at a
  35 kPa setpoint even half a metre eats 14 % of the driving pressure.
- **But be precise about what that costs.** A static column is a *constant*
  offset — it does not depend on Q — so it shifts the intercept of the Q-vs-ΔP
  fit and **does not bias `k`**. This is the opposite of the diverter's orifice,
  whose drop goes as Q² and therefore *bends* the line (see § Stage 10.5 in
  `COMMISSIONING.md`). The risk from a rising permeate line is operability, not
  accuracy: enough rise and there is no flow left to measure at the low
  setpoints.

### 4. (optional) DS18B20 probe clip
Holds the waterproof probe in the permeate stream inside the waste container
(fresh permeate = the water temperature you want). A simple printed clip on the
beaker rim works.

### 5. (optional) Baseplate
One board (printed or plywood) carrying enclosure + strain reliefs, so the
assembly moves as a unit.

## Measure before designing/buying (caliper on the bench)
1. **Valve stem breakaway torque** — the make-or-break number. Handle off, turn
   the stem with a torque wrench (or a luggage scale on a known lever arm:
   torque = force × arm). Read the peak to *start* moving.

   **Do NOT do this at "0.5–1 bar in the vessel", as this document used to say.**
   That is 50–100 kPa: above the 65 kPa specimen limit, at or above the 80 kPa
   global cutoff, on a vessel whose pressure rating is written nowhere in this
   repo, with **no relief valve fitted** and no software running to abort. It also
   measured the wrong thing. What loads the ball is the **ΔP across it**, which
   the regulator sets — not the pressure sitting in the vessel.

   Instead: measure at **the regulator's own setting**, and record which ΔP the
   number was taken at, because the torque only means something paired with it.
   Start dry (0 kPa) to get a floor; seal friction adds on top of that, so a dry
   reading already tells you whether you are near a threshold.
   Thresholds are stated **at 6 V**, the rig's actual servo supply (see §2).
   The DS3218 datasheet gives stall torque 19 kg·cm at 5.0 V and 21.5 kg·cm at
   6.8 V; stall torque tracks supply voltage (I_stall = V/R_winding), so 6 V
   interpolates to ~20.4 kg·cm ≈ **2.00 N·m**. The bands below keep the same
   ~47 % derate of stall that the original 6.8 V numbers used.
   - **≤ ~0.95 N·m** → a bare DS3218 at 6 V is fine.
   - **0.95–1.42 N·m** → add the 2:1 reduction (№1).
   - **> ~1.42 N·m** → reduction *and* a bigger servo (DS3240MG) or a
     smaller-bore / lower-friction valve; work the valve in first.

   The 5 % shift from the old 6.8 V bands is smaller than the uncertainty of
   measuring breakaway with a luggage scale — that is not the point. The point
   is the **0.95–1.05 N·m** band, where the old numbers said "bare servo" and
   the physics at 6 V says "add the reduction". Land in it and fit the
   reduction; it is the cheap side of the mistake.
2. Valve **stem** flat: square vs double-D, across-flats size, height → coupling (№1)
3. Valve body / mounting surface + free space around it → mount (№2)
4. **Swagelok tube OD** on the rig (likely 1/4") → the green BOM fittings
5. Existing manometer port thread → transducer adapter

## Wiring (all grounds common)

> **Visual build guide** (colour-coded by what's on hand vs still missing, with
> the do-NOT-do rules and the staged build order): [`wiring_diagram.png`](wiring_diagram.png).
> Close-up of the divider — it is not a purchasable part, it is two resistors
> from the kit: [`wiring_divider.png`](wiring_divider.png).
> ADS1115 pin-by-pin hookup (which pin goes where, and why R2 must reach the
> same ground the ADC measures against): [`wiring_ads1115.png`](wiring_ads1115.png).
> Regenerate all three with `./.venv/bin/python tools/gen_wiring.py` — keep them
> in sync with the table below.

| From (Pi) | To | Notes |
|---|---|---|
| 5V (pin 2) | transducer V+ (**red**) | ratiometric 0.5–4.5 V sensor |
| GPIO2/GPIO3 (SDA/SCL) | ADS1115 | ADS powered at **3.3 V** |
| — sensor signal (**green**) | 10k/22k divider → ADS A0 | never feed 4.5 V straight in |
| GPIO4 | DS18B20 data | + 4.7k pull-up to 3.3 V; enable 1-Wire |
| GPIO18 | servo signal | servo power from **UBEC 6 V**, not the Pi |
| GPIO23 | IRLZ44N gate via **470 Ω** | + 10k gate pull-down; drain → solenoid−; flyback across coil |
| 12 V PSU | fuse 3 A → solenoid+ and UBEC in | 1000 µF at UBEC out, 470–1000 µF at 12 V in |
| GND | everything | Pi + 12 V + UBEC + sensors + servo |
| — diverter coil pair | through the **V1738 3-pole plug** | poles 1–2 = coil+/coil−; pole 3 stays DEAD on the header (anti-reversal key) |

### The transducer's three leads — and the two things that go wrong

The unit that arrived has **red / black / green**: red `V+`, black `GND`, green
signal. That is a colour variant — the same part ships with yellow signal — so
**the colours are a starting hypothesis, not the confirmation.** Confirm by
measurement, and the measurement is one you already have to do:

> Power red and black from the Pi's 5 V (pin 2) and GND, then **measure green
> against black**. At atmosphere it must read **~0.500 V**. That single reading
> confirms the pinout *and* is the bench zero check — it is one test, not two.
> Measure again after the divider for **0.3438 V** and the whole chain is
> validated.

Two ways to get this wrong:

- **Red and black cannot be swapped.** These sensors carry no reverse-polarity
  protection; backwards supply can destroy the unit outright. If the colours are
  ambiguous, meter before powering, not after.
- **The pressure side has no inlet and outlet.** It is a *single* port — a blind
  tap. The transducer does **not** go in-line in the feed; it goes on a **tee**
  (or in the existing manometer port) and reads the pressure of whatever it is
  screwed into. Plumbing it in series is a real mistake people make with a
  two-terminal-looking part; there is nothing to pass through it.

### Why the gate resistor is 470 Ω

Peak current into the gate is just V/R at the instant the gate capacitance
starts charging:

| R | peak | vs BCM283x (16 mA) | vs **BCM2711 / Pi 4 (8 mA)** |
|---|---|---|---|
| 150 Ω | 22 mA | over | over |
| 220 Ω | 15 mA | ok | **over** |
| 330 Ω | 10 mA | ok | **over** |
| **470 Ω** | **7 mA** | ok | **ok** |

This doc previously justified 220 Ω against a **16 mA** pin limit. That figure
is from the BCM283x used on earlier Pis; the Pi 4's BCM2711 is documented at
**8 mA** max drive (I_OH 7 mA @ 2.6 V), which puts 220 Ω and 330 Ω out of spec
too. Rather than adjudicate the datasheets, take the value that is inside both:
**470 Ω**.

It costs nothing here. The diverter switches about six times per run, so edge
speed is worth nothing and there is no reason to spend pin current on it.

**Do not carry this value over to the unbuilt `valve.type: pwm` topology, and do
not carry the reasoning either.** That circuit has the opposite constraint —
continuous 1 kHz against 1 µs duty steps — and it cannot be fixed with a
resistor. What sets the edge is not the RC but the **Miller plateau**, and a
3.3 V GPIO driving a gate whose plateau sits near 2.5 V has only ~0.8 V of
overdrive, so the plateau current is small whatever R you pick:

| R | plateau current | rough edge |
|---|---|---|
| 220 Ω | 3.6 mA | ~3 µs |
| 470 Ω | 1.7 mA | ~7 µs |
| 1 kΩ | 0.8 mA | ~15 µs |

Every one of those is longer than the 1 µs duty step, so **no resistor value
gives that topology usable duty resolution from a bare GPIO** — it would need a
gate driver. (Edge figures are estimates: Qgd is taken as ~12 nC at 12 V, since
the datasheet quotes 25 nC at 44 V. The ordering is robust even if the
microseconds are not.) The rig runs `type: servo`, so none of this is built.

None of this would destroy a pad — the output self-limits and the transient is
sub-microsecond. It is about staying inside spec when doing so is free.

Caveat worth knowing either way: the IRLZ44N datasheet characterises R_DS(on) at
V_GS = 5 V and 4 V. Driven from a 3.3 V GPIO the part runs **off the table**, so
the 0.022 Ω figure does not apply here. At ~1 A of coil current it does not
matter, but do not quote that number as if it did.

### Coil current does cross the breadboard — mind the two clips

The 12 V rail stays off the breadboard, but the IRLZ44N itself sits in it, so
its **drain and source legs carry the full coil current through their clips**
(rows 38 and 39 of the proposed layout).

The coil current is no longer a guess: the ESValves listing for the
231Y-6-12VDC gives **13 W at 12 V ≈ 1.08 A** (listing figure, not measured).
That is *above* the ~1 A a breadboard contact is rated for, so this is not a
thin margin — it is over the limit.

Fix, now mandatory rather than advisable: solder the 22 AWG runs **directly to
the D and S legs** of the MOSFET instead of letting the current pass through
breadboard contacts. The gate side stays on the board, where it carries
microamps.

Same number closes the fuse budget: 1.08 A of coil plus ~0.95 A drawn by the
UBEC ≈ **2.03 A**, against the 3 A fuse. That fits, with the honest caveat that
both figures are catalogue values and neither has been measured on the rig.

### Pluggable break — V1738 3-pole plug + header (in hand 2026-07-27)

One pluggable terminal block, so the legs that cross to the **wet or moving**
side can be unplugged without tearing down the breadboard. Only one is on hand,
so it buys exactly one break. Ranked by what a plug pushed in backwards costs:

| Candidate | Conductors | A reversed plug does | Verdict |
|---|---|---|---|
| 3-way diverter coil | 2 (+1 spare pole) | destroys parts — see the warning — **unless** the spare pole is used as a key | **best use** |
| DS18B20 probe | 3 (GND · VDD · DQ) | swaps GND↔DQ, both legs current-limited by the 4.7k pull-up → probe reads nothing, nothing dies | good second |
| Pressure transducer | 3 (V+ · sig · GND) | sensor return goes through the 10k/22k divider: A0 sits ≈3.4 V (abs max is VDD+0.3 = 3.6 V) and the rig reads >100 kPa → aborts | detectable, not free |
| Servo DS3218 | 3 (GND · V+ · sig) | the servo's return current (~2 A peaks) flows through **GPIO18**, rated 8 mA on the Pi 4 → dead GPIO, likely dead Pi | do NOT, unless keyed |

**Recommended: coil on poles 1 and 2, pole 3 left dead on the header.** A 3-pole
plug flipped 180° maps 1→3, 2→2, 3→1. With the coil on poles 1–2 and *nothing*
landed on header pole 3, a backwards plug leaves coil+ dangling: the circuit
opens, the coil stays de-energised, permeate keeps going to waste — the same
direction as the designed failsafe. The third pole is not spare, it is the key.
Label it `NC` on the header so nobody repurposes it later.

Before soldering:
- **Measure the pitch.** 5.08 mm straddles alternating breadboard columns and
  works; 3.81 mm / 3.5 mm does not fit a 0.1" breadboard at all and needs a scrap
  of perfboard. Not specified anywhere for this block — measure it.
- **Check the current rating** on the block against the coil current (the ESValves
  3-way coil draw is not recorded in this repo — read it off the valve).
- **Do not tin** the stranded ends that go under a screw clamp: solder creeps and
  the joint loosens. Bare stranded or ferrules.

> **Polarity — read this before soldering.** The 1N5819 flyback sits across the
> coil (banded end = cathode → coil+, anode → coil− = MOSFET drain), at the coil,
> not at the board. If the plug goes in backwards with all poles landed, that
> diode ends up **forward-biased between +12 V and the drain**. The first time
> GPIO23 goes high the coil is bypassed by a dead short limited only by the PSU:
> the 1N5819 (1 A part) blows, and takes the 3 A fuse or the IRLZ44N with it.
> Mark pole 1 on the plug **and** on the header — paint pen or a heat-shrink flag
> — before any solder, and dry-fit the plug once with the rail de-energised.

## Build order
1. **Electronics first, on the bench** (no valves): 12 V → fuse → rail, UBEC,
   MOSFET, ADS1115 + divider, DS18B20. Run `mode: hardware`; check the sensor
   reads ~0 kPa at atmosphere and the probe reads a glass of water.
2. **Transducer** onto the manometer port (adapter). Two-point calibration —
   atmosphere plus one pressurised point.

   **Calibrate against the Keller LEX1, not the dial gauge.** The bench already
   has one (`−1…2 bar rel`, part `303030.0026`): a calibration-grade digital
   instrument that covers the 35–40 kPa working range with 5× headroom and reads
   without parallax. It is a better standard than anything in the BOM. Its output
   is RS-485 (pins 1 GND / 3 +Supply / 4 A / 5 B), not 4–20 mA, so it cannot
   serve as the loop sensor — but for calibration you read its display, which is
   all this step needs. Fall back to the dial gauge only if the LEX1 is
   unavailable.

   Before this step, verify the electrical chain on the bench with nothing
   plumbed: powered from the Pi's 5 V, at atmosphere the transducer gives 0.500 V,
   the divider puts **0.3438 V** on A0, and the driver must report **0.000 kPa**.
   That clears sensor, divider, ADC and conversion in one shot, so anything wrong
   afterwards is mechanical.

   **Where to mount it — check the LEX1's fitting before buying an adapter.**
   The transducer is G1/4 male and the rig is Swagelok/compression, which is why
   the BOM carries a G1/4 → Swagelok adapter. But the LEX1 is *already mounted on
   this rig*, and Keller's LEX1 commonly ships with a **G1/4 male** process
   connection too. If that is the case here, whatever fitting is holding the LEX1
   already accepts G1/4 — and the transducer threads into the same place with no
   new part at all. **Verify on the bench, not from this note:** back the LEX1 out
   and read its thread. Two outcomes worth having either way — if they match, the
   adapter stops being a blocker; if they do not, you now know the real thread
   instead of guessing, which is item 5 of "Measure before designing".

   Note the trade if you do borrow the LEX1's port: the transducer takes the spot
   the calibration reference occupies, so calibrate first, or tee it.

   ### Water temperature is not room temperature

   `k = b·µ·L/A`, and µ comes from the water temperature, so a temperature error
   lands **directly** on k with no dilution. Measured against `water_viscosity_pa_s`:
   µ changes **−2.39 % per °C** near 20 °C, and falls **28 %** between 20 and
   35 °C. A raw Q-vs-ΔP slope taken at 35 °C and interpreted as 20 °C is wrong by
   roughly 39 %; only the viscosity correction cancels it.

   Two separate things, and it is worth keeping them apart:
   - **The viscosity correction is mandatory.** There is no version of this
     experiment where it is optional.
   - **The DS18B20 is the convenient way to obtain it**, not the only way —
     `temperature.source: manual` exists.

   But if you run `manual`, measure **the water**, not the room. They are not the
   same, and the gap is not small: the vessel is pressurised with **compressed
   air, which heats as it compresses**, so the headspace — and eventually the
   water — sits above ambient by an amount nobody here has measured. A wall
   thermometer reading 21 °C while the water is at 24 °C is a **7 % error in k**
   that nothing in the fit will reveal.
3. **Print & fit coupling + mount**; servo onto the ball valve. Run the
   **static valve-authority sweep** (servo 0→100 %, log pressure) — this maps
   the useful travel; set `servo_min_us`/`servo_max_us` to that sub-range.
4. **3-way solenoid** into the permeate line (barbs + clamps); probe clipped in
   the waste stream. Land the coil through the **V1738** (poles 1–2, pole 3 dead)
   so the valve can come back out for plumbing work without touching the board.
5. Tune the PID (see README), then run a full sequence end-to-end.

## First safety checks

> **These checks live in sequence in [`COMMISSIONING.md`](COMMISSIONING.md)** —
> twelve staged energy boundaries, each closed before the next supply is
> connected, with the expected number at every step. Use that to actually
> commission; this section is the reference for what each check means.
>
> The two calibrations it depends on now have runnable procedures:
> `tools/valve_calib.py --sweep` for the authority sweep and `--close` for
> `servo_close_us`. Read that script's safety notes before either.

> ### ⚠ The relief valve is on order — which is not the same as fitted
>
> It was dropped, then **reinstated** when the rig became something operated
> remotely: with nobody standing in front of it, "shut the supply by hand" stops
> being a procedure and becomes a sentence with no one to execute it. It is on
> the order to Roxanne, status being confirmed.
>
> **Until it is physically mounted and set, everything below is still true.**
> Ordered is not installed. Do not let the line item on a purchase order read as
> a layer of protection.
>
> Today the rig has **no layer that acts with no software and no power**:
>
> | Layer | Fails if |
> |---|---|
> | Global cutoff 80 kPa + sensor faults | the Pi is hung or unpowered |
> | Frozen-signal + plant watchdog | same |
> | **Air-line regulator** | — passive, but its setting is **still unrecorded** |
>
> So the regulator's setting is not a nice-to-have: until the relief is fitted,
> **the supply pressure is the only thing that bounds a runaway**, exactly as
> `config.yaml` says. Find that number before pressurising, and keep the panel
> valve within reach — with the ball valve's handle removed, that panel valve is
> the only thing a human can shut.
>
> **When it arrives:** set it below the vessel's limit and above the max test
> point, and **check the part before fitting** — a relief that cracks below the
> working point does not merely fail to protect, it stops you pressurising at
> all, which is what gets it removed. Tests run at 35–40 kPa, so a fixed 5 psi
> (34.5 kPa) unit is useless here; it must be adjustable. Record the setting;
> it is one of the numbers `COMMISSIONING.md` asks for.

- **Kill test** (sustained fault): unplug the sensor mid-run → the rig must
  vent/abort. With the sensor pin at 0 V the front end reads **−12.93 kPa**,
  below `safety.min_plausible` (−5.0), so `SENSOR_FAULT` fires after
  `fault_grace_reads: 3` reads (~150 ms at 20 Hz).
- **Glitch test** (transient fault) — *different failure, different mechanism,
  run both*: force a single isolated NaN reading, i.e. fewer than
  `fault_grace_reads`, so no fault is declared. Pressure must **not** excursion
  and the valve must **not** stick open; the loop holds its last good command
  and resumes when good reads return. Guarded in `pid.py` (commit `867ba6d`) —
  before that guard, one I²C hiccup poisoned the PID integrator and pinned the
  valve at 100 % until overpressure aborted the run.
- **Noise-floor check — do this before trusting the frozen-sensor detector.**
  Safety declares a fault when `Reading.raw` comes back bit-identical for ~10
  consecutive samples, on the principle that a live analog chain always jitters.
  That rests on a number nobody has measured yet: the sim assumes 0.15 kPa of
  sensor noise against 0.0047 kPa per ADC count, i.e. **~32 counts of movement
  between samples**, which makes bit-identical readings impossible when healthy.
  Once the ADS1115 is wired, run this on the Pi with the rig at rest:

  ```
  ./.venv/bin/python tools/noise_floor.py
  ```

  It builds only the sensor (never the full HAL, so it does not construct
  ServoValve and never drives the servo to 700 µs), samples `raw` for a minute,
  and reports the number safety actually uses: **the longest run of
  bit-identical values**, against `safety.frozen_raw_reads`. The CSV logger has
  no `raw` column, so this script is the only way to run this step.
  **The risk runs the quiet way:** if the real front end is quieter than
  modelled, a healthy sensor can repeat a value and trip a spurious fault. If
  that happens, **raise N** — the script tells you to what — rather than
  removing the check.
- Servo power loss: the valve **holds position**, it does not spring shut. With
  no relief valve, nothing covers this case automatically — the bound is the
  regulator setting, and the remedy is shutting the panel valve by hand. This is
  also what `close_warning` is telling you when it fires.
- V1738 dry-fit, rail de-energised: meter continuity from header pole 1 to the
  fused +12 V and pole 2 to the MOSFET drain, and confirm pole 3 reaches nothing.
  Then plug it in backwards on purpose once and confirm the coil stays silent.
