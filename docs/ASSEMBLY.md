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
- **Servo supply:** run at 6.8 V off a supply that can source ~2 A peaks — a
  brownout at stall is the classic failure. If breakaway is high, use a
  higher-torque servo (e.g. DS3240MG ~40 kg·cm ≈ 3.9 N·m) instead of the DS3218.

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
   - **≤ ~1.0 N·m** → a bare DS3218 at 6.8 V is fine.
   - **1.0–1.5 N·m** → add the 2:1 reduction (№1).
   - **> ~1.5 N·m** → reduction *and* a bigger servo (DS3240MG) or a
     smaller-bore / lower-friction valve; work the valve in first.
2. Valve **stem** flat: square vs double-D, across-flats size, height → coupling (№1)
3. Valve body / mounting surface + free space around it → mount (№2)
4. **Swagelok tube OD** on the rig (likely 1/4") → the green BOM fittings
5. Existing manometer port thread → transducer adapter

## Wiring (all grounds common)

> **Visual build guide** (colour-coded by what's on hand vs still missing, with
> the do-NOT-do rules and the staged build order): [`wiring_diagram.png`](wiring_diagram.png).
> Close-up of the divider — it is not a purchasable part, it is two resistors
> from the kit: [`wiring_divider.png`](wiring_divider.png).
> Regenerate both with `./.venv/bin/python tools/gen_wiring.py` — keep them in
> sync with the table below.

| From (Pi) | To | Notes |
|---|---|---|
| 5V (pin 2) | transducer V+ | ratiometric 0.5–4.5 V sensor |
| GPIO2/GPIO3 (SDA/SCL) | ADS1115 | ADS powered at **3.3 V** |
| — sensor signal | 10k/20k divider → ADS A0 | never feed 4.5 V straight in |
| GPIO4 | DS18B20 data | + 4.7k pull-up to 3.3 V; enable 1-Wire |
| GPIO18 | servo signal | servo power from **UBEC 6 V**, not the Pi |
| GPIO23 | IRLZ44N gate via 150–330 Ω | + 10k gate pull-down; drain → solenoid−; flyback across coil |
| 12 V PSU | fuse 3 A → solenoid+ and UBEC in | 1000 µF at UBEC out, 470–1000 µF at 12 V in |
| GND | everything | Pi + 12 V + UBEC + sensors + servo |

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
   the waste stream.
5. Tune the PID (see README), then run a full sequence end-to-end.

## First safety checks
- Relief valve set below the vessel's limit and above your max test point.
- Kill test: unplug the sensor mid-run → the rig must vent/abort (sensor fault).
- Servo power loss: valve holds position — confirm the relief covers that case.
