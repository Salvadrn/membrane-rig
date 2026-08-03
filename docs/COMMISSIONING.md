# Commissioning checklist

The rig is wired the day the parts land. This is the sequence that turns "it looks
right" into **evidence that it is right**: one pass, top to bottom, nothing to
decide, an expected number at every step.

It does **not** replace [`ASSEMBLY.md`](ASSEMBLY.md) — that is where the wiring
table, the pinout and the reasoning live, and it is the source this file defers to.
This file is the order of operations and the acceptance numbers, collected in one
place instead of spread across `ASSEMBLY.md`, `INVENTORY.md` and the wiring sheets.

Nothing below has been run. Every "expected" value is derived from the config, the
drivers or a datasheet, and is marked where it is an assumption rather than a
measurement.

## How to use it

- **Top to bottom.** A stage is a *power boundary*: every box in a stage is ticked
  before the next stage's supply is connected. That is the whole point — a wrong
  rail found with a multimeter costs two minutes; found by a component, it costs
  the component and, worse, it can bias a measurement nobody re-checks.
- **Write the number you actually got** into [Numbers to record](#numbers-to-record).
  Several of them are not decoration: they go into `config.yaml` and they change
  the published `k`.
- **A box that cannot be ticked stops the stage.** "It probably reads fine" is the
  failure mode this document exists to prevent.

Tags on each check:

| Tag | Meaning |
|---|---|
| `[bench]` | doable today with a multimeter, no Pi |
| `[Pi]` | needs `install.sh` to have run on the Raspberry Pi |
| `[part]` | blocked: a part named in `INVENTORY.md` has not arrived |

---

## The four interlocks that override everything else

1. **No 12 V rail without the 3 A fuse — and the fuse is not the only missing
   piece.** The barrel-jack → screw-terminal adapter (`INVENTORY.md` item #6) is a
   *second, independent* blocker: without it there is nowhere to land 12 V on a
   screw, so the star point does not exist and the bulk capacitors cannot be
   placed. **Two parts, not one.**
2. **No diverter energisation without the 1N5819 fitted across the coil**, banded
   end (cathode) to coil+. Without it the inductive kick at turn-off kills the
   IRLZ44N.
3. **No servo power and no coupling until Stage 6.** `ServoValve.__init__` calls
   `to_safe()` *while constructing*, so the instant anything starts in
   `mode: hardware` the servo slams to 700 µs. If the coupler is already on the
   stem, it drives into whatever it finds there.
4. **There is no mechanical relief valve.** `config.yaml` states it plainly in the
   `operator_raise_max` note: *"with no mechanical relief the supply pressure is
   the only thing that bounds a runaway"*. So the ladder has two layers, not
   three, and one of them is a number nobody has measured yet:

| Layer | Pressure | Status |
|---|---|---|
| Normal tests | 35 kPa (≤ 60 kPa configured) | — |
| Specimen limit `membrane.max_pressure` | 65 kPa | software, admission-time |
| Run ceiling `max(setpoint) + 10` | e.g. 30 kPa for a 20 kPa point | software, abort |
| Global cutoff `safety.max_pressure` | 80 kPa | software, abort |
| ~~Mechanical relief~~ | ~~90 kPa~~ | **not bought — this layer does not exist** |
| Line regulator | **unknown** | the only non-software bound. See Stage 8 |
| Transducer saturation | 103.4 kPa | — |

> **Everything pressurised in this document is gated on Stage 8.3** — measuring and
> setting the regulator. Until that number exists, the only thing standing between
> the lab panel and a 0.117 mm mesh is a servo the software has not yet calibrated.

---

## Stage 0 — Bench, nothing powered

Everything here is `[bench]` and can be done today.

- [ ] **Tools on the table.** Multimeter and soldering iron confirmed 2026-07-29.
      `BOM.csv` lists **no tools at all** and no solid-core wire, so the solid tails
      of check 0.5 come from sacrificing kit jumpers.
- [ ] **0.1 Breadboard rails — are they split at the midpoint?** Many 830-point
      boards are. Probe both ends of the *same* rail.
      **Expected: continuity (beep, < 1 Ω).**
      If it reads open, the rail is split: bridge the two halves and measure again.
      A missing bridge means half your grounds are not grounds.
- [ ] **0.2 Rail + against rail −. Expected: open circuit (OL).**
      Any reading here is a short across a Pi regulator before anything is even
      connected.
- [ ] **0.3 Ohmmeter on every resistor *before* planting it.** The kit is 1 %.
      | Resistor | Role | Expected |
      |---|---|---|
      | R1 | divider top (signal side) | 10 kΩ ± 1 % |
      | R2 | divider bottom (to GND) | 22 kΩ ± 1 % |
      | pull-up | DS18B20 data → 3.3 V | 4.7 kΩ ± 1 % |
      | gate series | GPIO23 → IRLZ44N gate | 470 Ω ± 1 % |
      | gate pull-down | gate → GND | 10 kΩ ± 1 % |
      Record R1 and R2 to four digits: they give the divider ratio independently of
      any voltage measurement (Stage 2.2).
- [ ] **0.4 Diode-test the IRLZ44N before planting it** — confirm G·D·S rather than
      trusting the silkscreen orientation. Hold the TO-220 upright with the printing
      facing you; the repo's wiring sheets say **G · D · S, left to right**, tab tied
      to drain. Verify it:

      1. Short all three legs together for a second (a charged gate makes the part
         behave like a dead short in both directions — this is the confusing result
         people get and misread as a blown MOSFET).
      2. **Ohmmeter, metal tab ↔ centre leg. Expected: ~0 Ω.** That confirms the
         centre leg is the **drain**.
      3. **Diode mode, red probe on the right leg, black on the centre leg.
         Expected: it conducts** — the body diode's anode is the source, cathode the
         drain. Typical DMM reading ~0.4–0.6 V at its ~1 mA test current; the
         IRLZ44N datasheet only fixes V_SD ≤ 1.0 V at rated current, so **the exact
         number is not fixed by this repo — the direction is what matters.**
      4. **Reverse the probes. Expected: OL.**
      5. **Gate to either other leg, both directions. Expected: OL** (it is a
         capacitor; a brief drifting reading while it charges is normal, a stable
         low reading is a punched-through gate — discard that part, you have ten).

      If step 3 conducts in *both* directions, go back to step 1: the gate is
      charged, not the part dead.
- [ ] **0.5 Solid tails on every stranded end** that enters the breadboard (DS18B20
      probe, 22 AWG, and — confirm on the part — the transducer pigtail). A
      breadboard clip is a spring made for 0.4–0.7 mm solid wire; stranded splays and
      gives an intermittent that moves when the bench moves. Do this **before**
      planting anything, or you will pull it all back out.
      **Never tin a stranded end that goes under a screw clamp (V1738)** — solder
      creeps and the joint loosens.
- [ ] **0.6 V1738: measure the pitch and read the current rating.** 5.08 mm
      straddles alternating breadboard columns and works; 3.81 / 3.5 mm does not fit
      0.1" at all and needs perfboard. Neither the pitch nor the rating is recorded
      anywhere in this repo.

**Gate:** do not connect the Pi's header to anything until 0.1–0.3 are ticked.

---

## Stage 1 — The Pi's own rails, header unloaded

`[bench]`. Pi powered by its USB-C, **nothing** connected to the header.

- [ ] **1.1** pin 2 → pin 6: **5.0 V ± 5 %**
- [ ] **1.2** pin 1 → pin 6: **3.3 V ± 5 %**
- [ ] **1.3** pin 1 ↔ pin 17: **continuity** (same 3.3 V — also proves you are
      counting pins correctly)
- [ ] **1.4** pin 2 ↔ pin 4: **continuity** (same 5 V)
- [ ] **1.5 Write down the actual 5 V number.** This is not cosmetic: the transducer
      is **ratiometric**, so its zero is `0.1 × V_supply` and the voltage after the
      divider is `0.06875 × V_supply`. Stage 2 is judged against *your* rail, not
      against 5.000 V.

| Your rail | Transducer zero | At A0 |
|---|---|---|
| 5.00 V | 0.500 V | 0.3438 V |
| 4.90 V | 0.490 V | 0.3369 V |
| 5.10 V | 0.510 V | 0.3506 V |

A Pi that boots but does not appear on the network still delivers both rails
normally — the header knows nothing about Ethernet. A Pi that is genuinely dead
loses 3.3 V (the board generates it); 5 V usually survives because it comes from
the USB-C input, but that has not been verified on this board.

**Gate:** if either rail is missing, stop. Everything downstream is referenced to
them.

---

## Stage 2 — Sensing chain, on 3.3 V and 5 V only

`[bench]`. **No 12 V anywhere near this stage.** The whole low-voltage sensing
chain is independent of the 12 V rail, which is why it can be finished long before
the fuse arrives.

- [ ] **2.1 ADS1115 planted, ADDR to GND, VDD to 3.3 V** (not 5 V — the divider is
      sized for a 3.3 V ADC). Compare the 10-pin strip against the module's silkscreen
      before planting: if your board's order is reversed, VDD lands in the wrong row
      and the whole table inverts.
- [ ] **2.2 Measure the divider ratio and write it into `config.yaml`.**
      This is the single check with the largest effect on the published result.

      **Primary (per `.claude/roles/hardware.md`): measure Vout/Vin on the soldered
      divider with the same meter and divide.** Meter gain error cancels in the
      quotient; meter *input impedance* does not, because it sits in parallel with
      R2 and always biases the answer **low**:

      | Meter input Z | Reads | Bias |
      |---|---|---|
      | 10 MΩ | 0.6868 | −0.11 % |
      | 1 MΩ | 0.6828 | −0.68 % |

      **Cross-check with the resistances from 0.3:** `R2/(R1+R2)`. A pure ohmmeter
      gain error cancels in that quotient too, and it is immune to input impedance.
      **Expected: the two agree to within the bias in the table above, with the
      voltage method low.** A larger gap means a bad joint in the built divider —
      which is exactly what the voltage method is good at catching and the loose-part
      method is not.
      **Nominal is 0.6875** (10 k / 22 k). Write the *measured* number.

      Why this is gating for a publishable `k`: leaving `0.667` on a physical 0.6875
      divider reports 60 kPa as **62.24 kPa** and biases `k` by **−2.98 %**, with
      **R² = 1.000000** and `follows_darcy = True`. Nothing in the plot reveals it.
      Safe for the mesh (it over-reports, so it aborts early); silently wrong for the
      result.
- [ ] **2.3 Transducer zero.** Power **red = V+ from the Pi's 5 V (pin 2), black =
      GND**, and measure **green against black at atmosphere**.
      **Expected: 0.500 V** (scaled to your rail — table in 1.5).
      That one reading confirms the lead colours *and* is the bench zero: one test,
      not two. The colours here are a variant (the same part ships with a yellow
      signal lead), so they are a hypothesis until this reading agrees.
      > **Red and black cannot be swapped. These sensors carry no reverse-polarity
      > protection; backwards supply can destroy the unit outright.** If the colours
      > are ambiguous, meter before powering, not after.
- [ ] **2.4 After the divider, at A0. Expected: 0.3438 V** (= 0.06875 × your rail).
      Sensor, divider, ADC input and wiring all validated at once — anything that
      goes wrong after this is mechanical.
- [ ] **2.5 Sanity you get for free:** if R1 and R2 are swapped, the ratio becomes
      0.3125, A0 sits at 0.156 V and the driver will report **−7.1 kPa** — below
      `safety.min_plausible = −5.0`, so it faults. **That error announces itself and
      damages nothing**, unlike a mis-recorded ratio, which never announces itself.

**Gate:** the transducer's pressure port is a **single blind tap**, not an in-line
fitting — it goes on a tee, never in series with the feed. Do not plumb it yet
(Stage 8).

---

## Stage 3 — Pi software, I²C and the noise floor

`[Pi]`. Blocked today: `install.sh` has never run on the Pi, so `i2cdetect` does not
even exist yet. Provisioning belongs to the General session.

- [ ] **3.1** `bash install.sh` completed (installs `i2c-tools`, enables I²C and
      1-Wire, starts `pigpiod`, builds the venv). **Reboot** after the first run —
      1-Wire needs it.
- [ ] **3.2** `i2cdetect -y 1` → **`0x48`**, and only that. A different address means
      ADDR is not at GND; the driver looks for 0x48 and nothing else.
- [ ] **3.3 The driver's own zero.** Do **not** start the app for this: in
      `mode: hardware`, `build_hal()` constructs `ServoValve` **before** the sensor,
      so launching the UI drives the servo to 700 µs. Build only the sensor:

      ```sh
      ./.venv/bin/python -c "from src.config import Config; \
      from src.hal.ads1115_sensor import Ads1115Sensor; \
      c=Config.load('config.yaml'); print(Ads1115Sensor(c).read())"
      ```

      **Expected: `pressure_kpa` = 0.000 ± 0.05, `healthy=True`.** This is the
      conversion half of the check whose electrical half was 2.3/2.4.
- [ ] **3.4 Noise floor** — the number the frozen-signal detector rests on, and the
      only way to get it (the CSV logger has no `raw` column). Rig at rest:

      ```sh
      ./.venv/bin/python tools/noise_floor.py
      ```

      **Expected: `longest identical run` ≤ 3, i.e. PASS with ≥ 3× margin against
      `safety.frozen_raw_reads: 10`.** 1 LSB is 0.0047 kPa and the modelled noise is
      0.15 kPa (~32 counts), so a healthy chain should essentially never repeat a
      value — but that model has never been measured.
      **If the longest run approaches or exceeds 10, RAISE `frozen_raw_reads` to what
      the script tells you. Never remove the check.** It is the only guard against a
      sensor stuck at a *plausible* value, and there is no mechanical relief behind it.
- [ ] **3.5** `systemctl status pigpiod` → **active**. `ServoValve.__init__` raises
      `RuntimeError("pigpio daemon not running")` otherwise, and the app will not
      start at all.

**Gate:** 3.4 must pass before any run is trusted; a detector that false-fires gets
switched off, which is worse than not having it.

---

## Stage 4 — Water temperature (1-Wire)

`[Pi]`, probe in hand.

- [ ] **4.1** `sudo raspi-config nonint do_onewire 0`, then **reboot** (first time
      only).
- [ ] **4.2** `ls /sys/bus/w1/devices/` → **one `28-…` entry**. Nothing there means
      the pull-up, the data line or the reboot is missing.
- [ ] **4.3** Pin it: put that id in `temperature.w1_id`. With two probes on the bus
      the driver takes `matches[0]` arbitrarily.
- [ ] **4.4** Set `temperature.source: probe`. Today it is `manual`, and in hardware
      mode `manual` builds `MockTemperature`, which reports `manual_c` ± 0.02 °C of
      **simulated** noise. That wobble on screen is not a measurement — it is the
      single most convincing-looking fake number in the whole system.
- [ ] **4.5** Restart the app after plugging the probe in. `Ds18b20Sensor` resolves
      the `/sys/bus/w1/devices/28-*` path **once, in `__init__`**; connecting the probe
      with the app running does nothing.
- [ ] **4.6 Sanity check against something known.** Expected: room-temperature water
      within a degree of a reference thermometer, and a clear move when you put it in
      cold water. **There is no reference thermometer in `BOM.csv`** — if the lab has
      none, this check degrades to "it reads plausibly and it moves", and the
      absolute accuracy stays unverified.
- [ ] **4.7 Know the silent failure before it bites.** `read_c()` returns NaN on any
      fault (bad CRC, missing bus) and `_temp_loop` **discards NaN silently**, leaving
      the last good value on screen — and that µ goes straight into `k = b·µ·L/A`.
      **If the temperature does not move at all during a whole run, suspect the
      probe**, not a very stable lab.

---

## Stage 5 — The 12 V rail

`[part]`: blocked on the 3 A fuse + holder (item #7) **and** the barrel-jack → screw
terminal adapter (item #6). Order matters here more than anywhere else.

- [ ] **5.1 Grounds first, before any supply is plugged in.** From one point on the
      ground bar, check continuity to: **Pi GND (pin 6), UBEC IN−, UBEC OUT−, and the
      12 V supply negative. All four must beep.** If one does not, stop. Two grounds
      that never meet is one of the two ways components die on this bench.
- [ ] **5.2** Rail + against rail −: **open**, again, now that more is planted.
- [ ] **5.3 Fuse in, all receivers disconnected.** Measure:
      - UBEC input: **12 V** (12.3–13 V unloaded on a cheap supply is normal)
      - UBEC output: **6.0 V ± 0.2** — and confirm the UBEC jumper is on the **6 V**
        position. The Hobbywing UBEC-3A only offers 5 V or 6 V; **6.8 V was never
        reachable with the part that was bought**, which is why the servo torque
        bands in `ASSEMBLY.md` are stated at 6 V.
      - **Note which lead is + and which is −** before anything gets connected to it.
- [ ] **5.4** 6 V node touches **no** Pi pin. Not 5 V, not 3.3 V, not a GPIO.
- [ ] **5.5** The servo's two power leads and the coil's two leads do **not** run
      through breadboard clips. A clip is good for ~1 A; the coil is ~1.08 A and the
      servo stalls at ~1.67 A at 6 V. Solder 22 AWG **directly to the MOSFET's D and
      S legs**; only the gate side stays on the board, where it carries microamps.
- [ ] **5.6 Fuse budget.** Catalogue figures: coil 13 W @ 12 V ≈ **1.08 A**, UBEC
      draw ≈ **0.95 A** → **2.03 A against a 3 A fuse**. Both are catalogue values;
      **neither has been measured** — Stage 7.4 measures the coil.

**Gate:** do not connect the servo or the coil until 5.1–5.3 are ticked.

---

## Stage 6 — Servo, decoupled from the valve

`[part]` (needs Stage 5). **The coupler stays off the stem for all of this.**

- [ ] **6.1 Connect in this order: brown → ground bar, red → 6 V, orange → GPIO18.**
      Ground first, and it is also the last thing you ever disconnect. If the brown
      lead comes off while V+ is live, the motor's return current — up to 1.67 A —
      looks for a path home and the only one left is the signal wire into GPIO18,
      rated 8 mA on the Pi 4. That kills the GPIO and probably the Pi.
- [ ] **6.2 First start in `mode: hardware`, coupler off. Expected: the horn snaps
      to the 700 µs end and stays there.** That is `to_safe()` inside `__init__`,
      not a fault.
- [ ] **6.3 Walk the control endpoints, still decoupled: 700 µs (0 %) and 2300 µs
      (100 %).** Confirm both are inside the servo's travel and that neither buzzes
      (a buzzing servo is holding against a stop and is cooking itself).
      **There is no tool in this repo that does this** — see
      [Gaps](#what-this-checklist-cannot-verify-today).
- [ ] **6.4 Measure the ball valve's stem breakaway torque** before the coupling is
      designed or printed. Torque wrench, or a luggage scale on a known arm
      (torque = force × arm). Bands, **at 6 V**:
      | Measured | Verdict |
      |---|---|
      | ≤ 0.95 N·m | bare DS3218 at 6 V is fine |
      | 0.95–1.42 N·m | add the 2:1 reduction |
      | > 1.42 N·m | reduction **and** a bigger servo (DS3240MG), or a lower-friction valve |
      Land in **0.95–1.05 N·m** and fit the reduction: that is the band where the old
      6.8 V numbers said "bare servo" and the physics at 6 V says otherwise.
      **Record the pressure you measured at** — see the warning in
      [Gaps](#what-this-checklist-cannot-verify-today); stem torque tracks the ΔP
      *across the ball*, which is set by the regulator, not by the vessel.
- [ ] **6.5** Only now: fit the coupler, metal horn, M3 set screw **on the stem
      flat**, torque reacted into a metal frame, printed parts in PETG/ABS.

**Gate:** nothing gets coupled until 6.2 and 6.3 have been seen with your own eyes.

---

## Stage 7 — Diverter

`[part]`: needs the 1N5819, the 3-way solenoid, and Stage 5.

- [ ] **7.1 Gate side first, 12 V still off.** With the Pi booted and the app not
      running, **the gate node must sit at 0 V** (the 10 kΩ pull-down holds it there
      while GPIO23 is still an input). Without that resistor the gate floats during
      boot and the diverter can energise on its own — permeate into the measured
      cylinder from power-on, which corrupts the very first point and nothing in the
      data reveals it.
- [ ] **7.2 1N5819 across the coil, at the coil — not at the board.** Banded end
      (cathode) → coil+, anode → coil− = MOSFET drain. Confirm the band with the
      meter's diode test before soldering: **conducts from anode to cathode, OL the
      other way.** A Schottky reads noticeably lower than a silicon junction
      (~0.15–0.35 V at a DMM's test current, vs ~0.5–0.6 V) — useful for telling the
      1N5819 apart from a silicon diode in the same bag, though **this repo does not
      fix that number**; the direction is what must be right. In normal operation it
      is reverse-biased and carries nothing.
- [ ] **7.3 V1738 dry-fit, rail de-energised.** Meter: **header pole 1 ↔ fused
      +12 V: continuity. Pole 2 ↔ MOSFET drain: continuity. Pole 3 → nothing at
      all.** Then **push the plug in backwards on purpose and confirm the coil stays
      silent.** Pole 3 is not a spare, it is the anti-reversal key: flipped 180°, a
      3-pole plug maps 1→3, so coil+ dangles, the circuit opens and permeate keeps
      going to waste — the same direction as the designed failsafe. Label it `NC`.
      > If all three poles were landed, a reversed plug forward-biases the 1N5819
      > between +12 V and the drain: the first time GPIO23 goes high the coil is
      > bypassed by a dead short, and the 1 A diode blows — taking the fuse or the
      > MOSFET with it. Mark pole 1 on plug **and** header before any solder.
- [ ] **7.4 Measure the real coil current** (meter in series, or a clamp).
      **Expected ≈ 1.08 A** (13 W @ 12 V, supplier listing). Confirm
      coil + UBEC stays under 3 A.
- [ ] **7.5 Click test and port mapping, with water, not with faith.**
      De-energised → **ports 2↔3 = waste**. Energised → **ports 1↔2 = cylinder**.
      The permeate enters port **2** (the supplier calls it "outlet"); it is the
      common port. Plumbing it "as it sounds" — permeate into port 1 — means that
      **de-energised, port 1 closes and the permeate line is blind**, which puts the
      low-pressure silicone at vessel pressure until a barb or clamp lets go. The rig
      cannot detect it: there is no flow meter, pressure control still looks perfect,
      and the only symptom is an empty cylinder at the end of the point.
- [ ] **7.6 Reboot with 12 V live. Expected: the diverter stays at waste the whole
      way through boot** — `initial_value=False`. Inverting `active_high` without
      rewiring the MOSFET inverts the failsafe.

---

## Stage 8 — Fluid side, the regulator, and leaks

`[part]`: essentially everything on the wet side is missing. What is *not* blocked
is measuring.

- [ ] **8.1 Measure the four threads nobody has written down**: the rig's tube OD
      (probably 1/4"), the vessel's permeate-outlet thread, the vessel's pressure
      rating, and — **new and worth doing first** — the **LEX1's own process
      thread**. Keller's LEX1 commonly ships G1/4 male, the same as the transducer;
      if it matches, the fitting already holding the LEX1 accepts the transducer and
      the G1/4 → Swagelok adapter stops being a blocker. Trade-off if you borrow that
      port: the transducer displaces the calibration reference, so calibrate first or
      tee it.
- [ ] **8.2 Confirm there is a hand shutoff upstream, reachable in one second.**
      The ball valve's lever **has been removed** — the servo turns the stem — so
      during every pressurised step below **there is no manual override of the
      control valve itself.** The panel valve is the only thing a human can close.
      Know where it is before pressure exists.
- [ ] **8.3 Measure the line regulator's setting, and dial it to the working value.**
      This is the gate for the entire pressurised half of commissioning and the
      number the repo repeatedly says is missing (`wiring_fluidos.html`: *"presión de
      suministro: no medida, no está en el repo"*; `config.yaml` keeps
      `operator_raise_max` at 0 until it exists).
      Two constraints on *how* you measure it:
      - **The LEX1 tops out at 2 bar rel (200 kPa).** A lab air panel commonly sits
        far above that. **Do not put the LEX1 on an un-throttled panel line** — read
        the panel's own gauge, dial the regulator down, and only then meter it.
      - **The rig transducer is a 0–15 PSI part (saturates 103.4 kPa).** It must
        never see upstream panel pressure. It is teed **downstream of the ball
        valve** for exactly this reason (and because upstream it would measure the
        supply, and the loop could never close).
      - **Target: set the regulator so that a fully-open valve cannot exceed the
        specimen limit** (65 kPa), and preferably not the run ceiling. With no
        mechanical relief, the regulator *is* the backstop.
- [ ] **8.4 Leak test, before any real run.** Blank the permeate side (or fit a solid
      blank in place of the mesh — a leak test with the membrane installed cannot tell
      a leak from permeation, and at 35 kPa it pushes water through the specimen).
      Pressurise to the highest planned setpoint, shut the supply by hand, watch.
      **Proposed criterion: ≤ 1 kPa in 5 minutes.**
      Where that comes from: the rig's own `close_check` expects **≥ 1.0 kPa of decay
      in 20 s** through the membrane, so a leak at that rate would be
      indistinguishable from normal permeation. 1 kPa in 5 min puts a leak 15× below
      the permeation signal. **This threshold is a proposal — it is not in the repo
      and needs Adrián's sign-off.**

---

## Stage 9 — Pressurised calibration

`[part]`, and gated on 8.3. Everything here changes numbers in `config.yaml`.

- [ ] **9.1 Two-point transducer calibration against the Keller LEX1**
      (`−1…2 bar rel`, part `303030.0026`) — **not** against the dial gauge. The LEX1
      is calibration-grade, covers the 35–40 kPa working range with 5× headroom and
      reads without parallax. Its output is RS-485, so it cannot be the loop sensor;
      for calibration you read its display, which is all this needs.
      Point 1 = atmosphere (already done, Stage 2.3/3.3 → **0.000 kPa**).
      Point 2 = one pressurised point, set at the regulator, both instruments seeing
      the same tee.
      **Apply the result via `range_min`/`range_max`/`v_signal_min`/`v_signal_max` in
      `config.yaml`. Do not put offsets inside the driver.** If those four numbers
      cannot make a straight line close, ask Control for an explicit calibration
      field.
      > Sequencing note: with the lever off and the servo not yet coupled, nobody can
      > turn the ball valve by hand. Do this point with the ball left **open** and the
      > pressure set at the regulator.
- [ ] **9.2 Static valve-authority sweep** — coupler fitted, supply at the low
      regulator setting from 8.3, diverter to waste, **no specimen at risk**. Step the
      servo across its stroke and log the steady-state pressure at each step.
      **Expected: monotonic, and spread over a usable range across your setpoints.**
      A ball valve has nearly all of its authority near-closed, so most of the stroke
      will do nothing — that is normal and is the point of the sweep.
      **Set `servo_min_us`/`servo_max_us` to that useful sub-range**, not to the
      mechanical stops.
- [ ] **9.3 Calibrate `servo_close_us`** (today `0` = unset, which falls back to the
      0 % endpoint). With the supply on, step the pulse **down** from 0 % until flow
      fully stops, then add a small margin.
      **Do not jam it into the mechanical stop**: this position is held for as long
      as the rig sits idle, and a stalled servo cooks itself.
      Why it is separate from `servo_min_us`: 0 % is where *regulation* stops, not
      necessarily where the valve *seals* — with backlash in a printed coupling it can
      sit slightly cracked.
- [ ] **9.4** Re-check `valve.min_command` is **0.0**. `_apply()` clamps to
      `min_command`, so any positive value means **`to_safe()` can no longer reach
      0 %** — the safe state stops being reachable.

---

## Stage 10 — Safety acceptance

This is the stage that makes the rest of the document evidence rather than
housekeeping. Each check forces a real fault and demands the documented response.

- [ ] **10.1 `close_check`.** End a run above 5 kPa (below that it does not arm) and
      wait. **Expected: pressure falls ≥ `close_check_min` (1.0 kPa) within
      `close_check_s` (20 s); no warning in the UI.**
      If the warning *"valve may not have closed"* appears, the valve did not seat →
      go back to 9.3, and shut the supply by hand now.
- [ ] **10.2 Kill test (sustained fault).** Mid-run, **unplug the transducer's signal
      lead**. **Expected: `SENSOR_FAULT`, vent + abort, after `fault_grace_reads: 3`
      reads (~150 ms at 20 Hz).**
      The number behind it: with the signal lead gone, A0 is not floating — R2 (22 k)
      holds it at **0 V**, so the front end computes **−12.93 kPa**, well below
      `min_plausible = −5.0`. That is why the divider makes "unplugged" a *definite*
      reading instead of noise. This test is immune to the divider ratio: 0/ratio = 0
      whatever the ratio is.
- [ ] **10.3 Glitch test (transient fault) — a different failure, run it too.**
      Force a single isolated bad read (fewer than 3), e.g. one brief interruption of
      the I²C line. **Expected: no fault declared, pressure does not excursion, the
      valve does not stick open.** The loop holds its last good command and resumes.
      Guarded in `pid.py` (commit `867ba6d`); before that guard, one I²C hiccup
      poisoned the integrator and pinned the valve at 100 % until overpressure
      aborted the run.
- [ ] **10.4 Plant watchdog.** The clean way to fire it: **shut the supply at the
      panel and start a low setpoint.** The PID pins the valve open, nothing happens.
      **Expected: abort with `plant unresponsive: valve at 100% for 8 s but pressure
      held near …` — valve ≥ `watchdog_valve_pct` (70 %) for `watchdog_hold_s` (8 s)
      with no `watchdog_min_rise` (2 kPa) rise.**
      Safe by construction: there is no pressure source connected during the test.
      Note it only runs while a test is active.
- [ ] **10.5 Frozen-signal detector.** **This one has no clean physical trigger** —
      see [Gaps](#what-this-checklist-cannot-verify-today). What you *can* do:
      - **Prove it will not false-fire:** that is Stage 3.4, and it is the check that
        actually matters for a detector nobody wants switched off.
      - **Best-effort trigger (proposed, unverified):** with the **supply shut**,
        disconnect the transducer signal and drive A0 from a quiet fixed source
        somewhere inside the plausible band and below the run ceiling (**0.85 V at
        A0 ≈ 19 kPa**), then start a 20 kPa point. **Expected: `sensor signal frozen: raw
        … identical for 11 reads` within ~0.5 s.** If instead the watchdog fires at
        8 s, your bench source was not quiet enough — which is itself a useful
        result, and harmless because there is no pressure behind it.
      - Do **not** do this with the supply live: the loop would be chasing a lie
        while real pressure climbs, and there is no mechanical relief.
- [ ] **10.6 Overpressure / run-ceiling abort (proposed).** With **no specimen** (a
      solid blank in the flange, so nothing permeates) and the regulator set just
      above the ceiling, queue a 20 kPa point → ceiling 30 kPa. The valve opens, the
      dead-ended cell rises to the regulator setting. **Expected: abort at 30 kPa
      with `pressure … exceeded run ceiling 30.0 kPa`.** Nothing delicate is exposed,
      because there is no membrane in the rig.
- [ ] **10.7 Power-cut behaviour, at pressure.** Pull the 12 V with the cell
      pressurised. **Expected: the diverter drops to waste (de-energised = waste), and
      the servo holds position — it does NOT seal.** That is the designed behaviour,
      not a bug, and it is precisely why the supply gets closed by hand at the end of
      every session. With no mechanical relief, **nothing automatic vents the cell
      after a power cut.**
- [ ] **10.8 Ctrl+C / process kill** with a run active → valves to safe state, coil
      de-energised.

---

## Stage 10.5 — Does the diverter throttle the measurement? (blocking)

**Run this before Stage 11. If it fails, every number from a real run is wrong
and the fit will not tell you.**

The diverter sits on the permeate outlet, downstream of the membrane. Every
permeability number assumes that side is at atmosphere, so that the transducer's
reading *is* the transmembrane ΔP. A restricting valve puts backpressure there,
and the real ΔP is smaller than the measured one.

What makes this dangerous rather than merely inaccurate: orifice pressure drop
goes as **Q²**, and Q rises with ΔP. The error therefore grows with pressure, so
it does not shift the Darcy line — **it bends it**. The bias in `k` is a
deformation, not a scale factor.

The valve on order is a **231Y-6, 1.5 mm orifice, Cv 0.09–0.21** (the vendor's
own page states both; an independent orifice calculation, Cd 0.6, gives ~0.062,
which supports the pessimistic figure). That makes it transparent only up to
roughly **2–5 mL/s**:

| Permeate flow | Backpressure @ Cv 0.09 | @ Cv 0.21 |
|---|---|---|
| 5 mL/s | 5.3 kPa | 1.0 kPa |
| 10 mL/s | 21.4 kPa | 3.9 kPa |
| 15 mL/s | 48.1 kPa | 8.8 kPa |
| 30 mL/s | 192 kPa | 35.4 kPa |

Against a 35 kPa working pressure. At 30 mL/s with the *optimistic* Cv the valve
eats the entire test pressure — the membrane would see nothing.

- [ ] **10.5.1 Measure the free flow rate first.** With the valve bypassed —
      permeate straight into the cylinder — hold a setpoint and time a known
      volume. This single number decides everything via the table above, and it
      also closes the flow-rate unknown that Datos needs for the collection
      window. **Expected: unknown.** `flow_per_kpa_m3s` in `config.yaml` was
      chosen to produce a clean Darcy line in simulation; it was never measured.

- [ ] **10.5.2 If free flow ≤ 5 mL/s** — the valve is transparent, nothing to do.
      Record the number and move on.

- [ ] **10.5.3 If free flow is higher, run the comparison.** Same membrane, same
      setpoint, two runs: once through the diverter, once bypassing it and timing
      by hand. Compute `k` both ways. **They must agree within the run-to-run
      scatter.** If the diverter run gives a lower `k`, the valve is throttling
      and the diverted number is invalid.

- [ ] **10.5.4 Do NOT accept `R² ≥ 0.98` as evidence that this is fine.**
      Simulated against the real fit: a valve bending the line badly enough to
      put `k` **49.5 % low** still returns **R² = 0.9969** and
      `follows_darcy = True`. With three setpoints a smooth curvature is
      invisible to the criterion. The R² check catches noise and leaks; it does
      not catch this.

**If it does throttle**, the options in order — see the analysis handed to
General: a valve with a much larger Cv (~1.25 to pass 30 mL/s cleanly, which is
a substantially bigger part, not an upgrade); a scale replacing the diverter in
the flow path entirely; or a second transducer downstream. Note that the last
one **rescues the arithmetic but not the experiment** — if the valve is eating
the test pressure, the membrane never saw the ΔP that was commanded, and no
correction recovers a measurement that did not happen.

## Stage 11 — First real run

- [ ] **11.1** `config.yaml`: `mode: hardware`, `temperature.source: probe`,
      measured `divider_ratio`, calibrated `servo_min_us`/`servo_max_us`/
      `servo_close_us`. Specimen limit set for the actual mesh.
- [ ] **11.2** PID: expect to **lower** the sim gains. The shipped set
      (kp 4, ki 0.4, kd 1.0, ramp 3 kPa/s) holds overshoot under ~1 kPa in sim; real
      valves add deadband, hysteresis and lag. If it overshoots, lower `ramp_kpa_s`
      first, then `ki`.
- [ ] **11.3** Expect a **coarse hold, ±10–15 %**, not ±2 % — `tolerance_pct` is 10
      for that reason. A looser hold adds scatter, not bias: `Q` is regressed against
      the *measured* mean pressure per point.
- [ ] **11.4** Full sequence end to end. **Expected: `R² ≥ 0.98`
      (`follows_darcy = True`)**, a CSV + meta + analysis + PNG + XLSX in `runs/`, and
      a temperature column that **moves**.
- [ ] **11.5** Close the **panel valve** by hand. Every time. (Say *panel* valve,
      not *supply* valve: the control ball valve has had its handle removed so the
      servo can turn the stem, so the panel is the only thing a human can shut.)

---

## Temperature: is the probe really necessary?

Two questions that get collapsed into one, and they have different answers.

**The viscosity correction is mandatory.** `k = b·µ·L/A`, and µ comes from the water
temperature, so a temperature error lands **directly** on `k` with no dilution.
Measured against `water_viscosity_pa_s()` in `src/config.py`:

| Change | Effect on µ, and therefore on k |
|---|---|
| +1 °C near 20 °C | **−2.39 %** |
| 20 → 35 °C | **−28 %** |
| slope taken at 35 °C, read as 20 °C | **~39 % wrong** |
| wall thermometer 21 °C vs water at 24 °C | **~7 % wrong** |

There is no version of this experiment where that correction is optional.

**The DS18B20 is the convenient way to obtain it, not the only way.**
`temperature.source: manual` exists and works — the correction still happens, you
just supply the number.

**But if you run `manual`, measure the WATER, not the room.** They are not the same,
and the direction is predictable: the vessel is pressurised with **compressed air,
which heats as it compresses**, so the headspace — and eventually the water — sits
above ambient by an amount nobody here has measured. A wall thermometer is not a
substitute for a probe in the fluid. Full argument in
[`ASSEMBLY.md`](ASSEMBLY.md) → *"Water temperature is not room temperature"*.

Practical consequences for commissioning:

- With `probe`: the DS18B20 clips into the **permeate stream in the waste
  container** — fresh permeate is the water whose viscosity you want. Not inside the
  graduated cylinder: any submerged body displaces volume, and that volume adds
  straight to Q, and therefore to k.
- With `manual`: measure the water at the start **and** end of a run and record
  both. If they differ by more than ~1 °C, the run carries a ≥2.4 % uncertainty in
  `k` that the fit will not show you.
- Either way, 4.7 applies: **a temperature that never moves is a dead probe until
  proven otherwise.**

---

## Numbers to record

These are the quantities that are *assumed* today and that commissioning converts to
*measured*. Anything still blank means the rig is not commissioned, however good the
plots look.

| Quantity | Where it goes | How | Today |
|---|---|---|---|
| `divider_ratio` (measured) | `config.yaml` `sensor.divider_ratio` | Stage 2.2 | nominal 0.6875 |
| Meter input impedance used for it | this file / lab notebook | meter spec | unknown |
| Pi 5 V and 3.3 V rails, actual | lab notebook (2.3 depends on it) | Stage 1 | unmeasured |
| Transducer zero at your rail | lab notebook | Stage 2.3 | expected 0.500 V |
| Two-point calibration pair | `range_min/max`, `v_signal_min/max` | Stage 9.1 | uncalibrated |
| Noise floor: longest identical run | `safety.frozen_raw_reads` if it fails | Stage 3.4 | modelled, not measured |
| `servo_min_us` / `servo_max_us` | `config.yaml` `valve.*` | Stage 9.2 | 700 / 2300 assumed |
| `servo_close_us` | `config.yaml` `valve.servo_close_us` | Stage 9.3 | **0 = unset** |
| Stem breakaway torque **+ the ΔP it was measured at** | coupling design, servo choice | Stage 6.4 | unmeasured |
| Line regulator setting | gates `operator_raise_max`, Stages 8–10 | Stage 8.3 | **unknown** |
| Diverter coil current, real | fuse budget | Stage 7.4 | 1.08 A catalogue |
| DS18B20 `w1_id` | `config.yaml` `temperature.w1_id` | Stage 4.3 | empty |
| Vessel pressure rating | the whole ladder | Stage 8.1 | **not written anywhere** |
| Tube OD, permeate-port thread, LEX1 thread | fittings order | Stage 8.1 | unmeasured |
| V1738 pitch + current rating | Stage 0.6 | caliper + label | unrecorded |
| Leak rate at working pressure | acceptance | Stage 8.4 | no criterion in repo |

---

## What this checklist cannot verify today

Stated plainly so nobody assumes coverage that was not given.

1. **Nothing below has been executed.** Every expected value is derived from
   `config.yaml`, the drivers or a datasheet. The rig has no cable connected and the
   Pi has never had the software installed.
2. ~~There is no tool for the valve-authority sweep or for `servo_close_us`.~~
   **CLOSED** — `tools/valve_calib.py` now covers both: `--sweep` for the authority
   sweep and `--close` for the seating pulse. It builds **only** the valve (plus the
   sensor for the sweep), gates on a typed confirmation naming the decoupling
   requirement, and always releases through `close()`. Neither has been run on
   hardware yet.
3. **There is no manual diverter control** either — no UI button, no CLI flag. Check
   7.5 needs a few lines of Python against `GpioDiverter`.
4. **The frozen-signal detector cannot be triggered by any obvious physical action.**
   Unplugging the sensor or the I²C bus produces NaN, which safety deliberately
   treats as a *gap* rather than a fresh sample, and the plausibility path fires at 3
   reads — long before the frozen counter reaches 10. Only a *constant, plausible*
   value fires it, which is why 10.5 is written as a proposal. Verifying that it
   fires belongs in a software test, and **this repo has no test suite at all.**
5. **The relief valve is on order, but not fitted — so the two checks that depend
   on it still cannot be performed.** It was dropped, then reinstated on 2026-07-31
   when the rig became something operated remotely: with nobody in front of it,
   "shut the supply by hand" is a sentence with no one to execute it. Status is
   being confirmed with Roxanne.

   The documentation contradiction that used to sit here **is resolved** —
   `ASSEMBLY.md`, `CLAUDE.md`, `README.md`, the role files and the talk deck all now
   describe the current state. What has *not* changed is the physical rig: **ordered
   is not installed.** Until the part is mounted and set, no layer acts without the
   controller, and the air regulator's setting — still unrecorded — is the only
   physical bound on a runaway. Do not let a line on a purchase order read as
   protection.
6. **Breakaway torque at "0.5–1 bar in the vessel"** (`ASSEMBLY.md`) is **above the
   entire pressure ladder** — 50–100 kPa against a 65 kPa specimen limit and an
   80 kPa global cutoff, on a vessel whose rating is not documented anywhere, with no
   mechanical relief fitted and no software running. Stage 6.4 asks for the torque *at the
   regulator setting the rig will actually run*, because stem torque tracks the ΔP
   across the ball, which the regulator sets — not the vessel pressure. **That is a
   deliberate departure from `ASSEMBLY.md` and needs Adrián's OK.**
7. **The transducer's proof/burst pressure is not recorded** anywhere in this repo.
   Stage 8.3's "never expose it upstream" rests on its 103.4 kPa full scale, not on a
   known survivable overpressure.
8. **No accuracy reference for the DS18B20** exists in the BOM, so Stage 4.6 verifies
   plausibility and response, not calibration.
9. **`wiring_fluidos.html` is stale in two places** (it still treats the 40 PSI
   requirement as open — `INVENTORY.md` resolved it to 35 kPa on 2026-07-27 — and it
   names the dial gauge as the calibration reference, which `ASSEMBLY.md` superseded
   with the LEX1). Those sheets were left untouched here on purpose.

---

*Sources: `docs/ASSEMBLY.md` · `config.yaml` · `INVENTORY.md` · `BOM.csv` ·
`src/hal/*` · `src/safety.py` · `src/app.py` · `src/config.py` ·
`tools/noise_floor.py` · `docs/wiring_banco.html` · `docs/wiring_protoboard.html` ·
`docs/wiring_ubec.html` · `docs/wiring_fluidos.html` · `.claude/roles/hardware.md`.*
