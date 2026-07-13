# Assembly guide

Air-over-water rig: compressed air (lab panel, yellow line) pressurises the
stainless vessel through the **existing needle valve**, which a servo turns.
Water permeates the membrane; the 3-way solenoid routes permeate to waste or
the graduated cylinder. See the BOM (`BOM.xlsx`) for parts.

## Parts YOU design (3D-printed)

### 1. Servo↔needle-valve coupling (the critical part)
A cup that grips the needle valve's knob, driven by the servo.
- Measure the knob with a caliper: outer Ø, height, shape (knurled/round/winged).
  Model the **negative** of the knob inside the cup; add an M3 set-screw boss on
  the side to lock it (don't rely on friction alone).
- Top face: screw one of the servo's included **25T horns** into the print
  (2–4 self-tappers). Do NOT print the 25T spline — FDM can't hold that detail.
- Minimise backlash: snug fit, walls ≥3 mm. Print in PETG/ABS (PLA creeps).

### 2. Servo mount
Holds the servo **body** coaxial with the valve stem so torque reacts into
structure, not into the tubing.
- Clamp to the valve body hex (measure across-flats) or bolt to the baseplate.
- DS3218 is standard size (~40×20×40.5 mm, 4 ear holes). Slot the mount's holes
  so you can align servo axis ↔ valve stem axis (misalignment = binding).
- Leave finger access to the coupling set screw.

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
1. Needle-valve knob: Ø, height, shape → coupling (№1)
2. Valve body hex across-flats + free space around it → mount (№2)
3. **Swagelok tube OD** on the rig (likely 1/4") → the green BOM fittings
4. Existing manometer port thread → transducer adapter

## Wiring (all grounds common)

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
3. **Print & fit coupling + mount**; servo onto the needle valve. Run the
   **static valve-authority sweep** (servo 0→100 %, log pressure) — this maps
   the useful travel; set `servo_min_us`/`servo_max_us` to that sub-range.
4. **3-way solenoid** into the permeate line (barbs + clamps); probe clipped in
   the waste stream.
5. Tune the PID (see README), then run a full sequence end-to-end.

## First safety checks
- Relief valve set below the vessel's limit and above your max test point.
- Kill test: unplug the sensor mid-run → the rig must vent/abort (sensor fault).
- Servo power loss: valve holds position — confirm the relief covers that case.
