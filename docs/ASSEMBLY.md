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
- Fits: Pi 4 + half breadboard + UBEC + fuse holder. Mount on M3 standoffs.
- Ventilation slots (Pi 4 runs warm); cable entry through bottom/side notches or
  glands so splashes can't run down wires into the box; splash lid on top.

### 4. (optional) DS18B20 probe clip
Holds the waterproof probe in the permeate stream inside the waste container
(fresh permeate = the water temperature you want). A simple printed clip on the
beaker rim works.

### 5. (optional) Baseplate
One board (printed or plywood) carrying enclosure + strain reliefs, so the
assembly moves as a unit.

## Measure before designing/buying (caliper on the bench)
1. **Valve stem breakaway torque** — the make-or-break number. Handle off, ~0.5–1
   bar in the vessel, turn the stem with a torque wrench (or a luggage scale on a
   known lever arm: torque = force × arm). Read the peak to *start* moving:
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
| 5V (pin 2) | transducer V+ | ratiometric 0.5–4.5 V sensor |
| GPIO2/GPIO3 (SDA/SCL) | ADS1115 | ADS powered at **3.3 V** |
| — sensor signal | 10k/22k divider → ADS A0 | never feed 4.5 V straight in |
| GPIO4 | DS18B20 data | + 4.7k pull-up to 3.3 V; enable 1-Wire |
| GPIO18 | servo signal | servo power from **UBEC 6 V**, not the Pi |
| GPIO23 | IRLZ44N gate via **470 Ω** | + 10k gate pull-down; drain → solenoid−; flyback across coil |
| 12 V PSU | fuse 3 A → solenoid+ and UBEC in | 1000 µF at UBEC out, 470–1000 µF at 12 V in |
| GND | everything | Pi + 12 V + UBEC + sensors + servo |
| — diverter coil pair | through the **V1738 3-pole plug** | poles 1–2 = coil+/coil−; pole 3 stays DEAD on the header (anti-reversal key) |

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

It costs nothing. Edge time is τ = R·Ciss = 0.8 µs at 470 Ω versus 0.37 µs at
220 Ω, on a diverter that switches about six times per run — the speed is worth
nothing here, so there is no reason to spend pin current on it. (The unbuilt
`valve.type: pwm` topology on GPIO18 is the opposite case: it switches
continuously at 1 kHz against 1 µs duty steps, so it wants the *fast* end. It
does not exist in this rig.)

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
| Servo DS3218 | 3 (GND · V+ · sig) | the servo's return current (~2 A peaks) flows through **GPIO18**, rated 16 mA → dead GPIO, likely dead Pi | do NOT, unless keyed |

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
2. **Transducer** onto the manometer port (adapter). Two-point calibration
   against the dial gauge (atmosphere + one pressurised point).
3. **Print & fit coupling + mount**; servo onto the ball valve. Run the
   **static valve-authority sweep** (servo 0→100 %, log pressure) — this maps
   the useful travel; set `servo_min_us`/`servo_max_us` to that sub-range.
4. **3-way solenoid** into the permeate line (barbs + clamps); probe clipped in
   the waste stream. Land the coil through the **V1738** (poles 1–2, pole 3 dead)
   so the valve can come back out for plumbing work without touching the board.
5. Tune the PID (see README), then run a full sequence end-to-end.

## First safety checks
- Relief valve set below the vessel's limit and above your max test point.
  **Check the part before ordering:** a relief that cracks below the working
  point does not merely fail to protect — it stops you pressurising at all,
  which is what gets it removed. Tests run at 35–40 kPa, so a fixed 5 psi
  (34.5 kPa) unit is useless here; it must be adjustable.
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
- Servo power loss: valve holds position — confirm the relief covers that case.
- V1738 dry-fit, rail de-energised: meter continuity from header pole 1 to the
  fused +12 V and pole 2 to the MOSFET drain, and confirm pole 3 reaches nothing.
  Then plug it in backwards on purpose once and confirm the coil stays silent.
