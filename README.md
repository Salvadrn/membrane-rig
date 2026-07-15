# Membrane Permeability Test Rig — Automated Control

Raspberry Pi 4 control system that replaces the two manual steps in the
permeability test (holding pressure by hand + stopwatch/hose swap) with a PID
pressure loop and an automatic diverter, and logs a full pressure trace per run.

Runs in two modes from the same code:
- **`sim`** — a first-order plant model, no hardware. Tune all the logic and the
  PID on your laptop.
- **`hardware`** — real ADS1115 sensor, PWM proportional valve, GPIO diverter.

---

## How it works

```
compressor → reservoir → hose → membrane cylinder ─┬─→ [proportional valve] → (backpressure/bleed)
                                                    └─→ [3-way diverter] ─→ waste  (Position A, safe)
                                                                          └→ measured container (Position B)
```

Per setpoint the controller walks a state machine:

1. **STABILIZING** — PID modulates the proportional valve to hold the target
   pressure; diverter routes to **waste**. When pressure stays within **±tolerance**
   of the setpoint continuously for **dwell_s**, it advances.
2. **COLLECTING** — diverter switches to the **measured** container and a timer
   starts. The PID keeps holding pressure; pressure stats are accumulated over
   the collection window only. After **collection_s**, diverter returns to waste
   and the result is recorded.
3. Next setpoint, or **DONE**.

A **safety monitor** runs every loop tick independent of the state machine:
overpressure → immediate vent+abort; implausible/unhealthy sensor reading →
vent+abort (so a disconnected sensor reading "0" can never make the PID slam the
valve shut).

---

## Design choices (and why)

- **Language: Python 3.11.** The process is slow (seconds), so no hard real-time
  is needed, and the sensor/PWM libraries are mature.
- **pigpio** for the valve PWM — DMA/hardware-timed, so the duty cycle is
  jitter-free even under load. `RPi.GPIO` software PWM would inject timing noise
  the PID would fight.
- **gpiozero** (pigpio backend) for the diverter — clean API and guaranteed pin
  cleanup so the coil de-energises to the safe (waste) state on exit.
- **ADS1115** ADC over I2C — the Pi has no analog input. 16-bit, plenty for a
  4–20 mA or 0.5–4.5 V transducer.
- **Web UI** (FastAPI, single self-contained page) as the primary interface — the
  Pi runs headless in the lab, you reach it from a laptop/phone on the LAN, and
  the **live pressure chart** lets you *watch* the loop settle into the band. A
  thin **CLI** covers SSH/tuning. No external/CDN assets, so it works on an
  offline lab network.
- **Hardware Abstraction Layer** — the control code only talks to three abstract
  types (`PressureSensor`, `ProportionalValve`, `DiverterValve`). Swapping a
  sensor/valve model = one new driver class; nothing else changes. The mock
  drivers implement the same contracts, which is what makes sim mode possible.

---

## Project layout

```
membrane-rig/
├── config.yaml            # every tunable — no code edits needed to run a test
├── requirements.txt
├── run.py                 # entry point:  run.py web  |  run.py cli
├── runs/                  # per-run CSV + metadata JSON output
└── src/
    ├── config.py          # load/validate YAML, unit (kPa/psi) conversion
    ├── hal/
    │   ├── interfaces.py   # the three HAL contracts + Reading
    │   ├── mock.py         # simulated sensor/valve/diverter
    │   ├── ads1115_sensor.py  # real sensor (current-loop OR voltage-divider)
    │   ├── pwm_valve.py    # real proportional valve (pigpio HW PWM) + driver notes
    │   ├── gpio_diverter.py# real 3-way solenoid
    │   └── __init__.py     # build_hal() factory
    ├── control/
    │   ├── pid.py          # anti-windup, derivative-on-measurement
    │   └── plant_sim.py    # first-order plant for sim mode
    ├── safety.py           # overpressure + sensor-sanity watchdog
    ├── sequencer.py        # the per-setpoint state machine
    ├── logging_csv.py      # per-run timeseries CSV + metadata JSON
    ├── app.py              # RigController: the background control loop
    └── ui/{web.py, cli.py} # interfaces
```

---

## Quick start (laptop, sim mode)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install PyYAML fastapi uvicorn pydantic matplotlib openpyxl   # sim + plot + xlsx

python run.py web                # open http://localhost:8000
# or headless:
python run.py cli                # runs the setpoints from config.yaml, then
                                 # auto-fits Q vs ΔP and writes a plot
# plot existing data (no rig), e.g. your spreadsheet exported to CSV:
python run.py analyze mydata.csv --area-cm2 0.64 --thickness-mm 0.117
```

`config.yaml` ships with `mode: sim`. Everything works with no hardware.

---

## Configuration

All parameters live in `config.yaml` — nothing requires editing code. Highlights:

| Key | Meaning |
|-----|---------|
| `units` | `kPa` or `psi` — the unit for every pressure below and in the UI |
| `mode` | `sim` or `hardware` |
| `sensor.type` | `current_loop` (4–20 mA) or `voltage_divider` (0.5–4.5 V) |
| `sensor.range_min/max` | pressure at the sensor's min/full-scale signal |
| `valve.pwm_pin`, `valve.invert` | proportional-valve PWM pin and sense |
| `diverter.pin`, `diverter.active_high` | diverter GPIO |
| `pid.kp/ki/kd`, `pid.sample_hz` | control gains and loop rate |
| `safety.max_pressure` | hard cutoff → vent+abort |
| `test.tolerance_pct/dwell_s/collection_s` | stabilisation band, dwell, collection time |
| `test.setpoints` | the sequence to run (also editable in the UI) |
| `sim.*` | plant model gains + simulated permeate flow for sim mode |
| `membrane.area_cm2/thickness_mm/viscosity_pa_s/label` | geometry + fluid props for the Darcy calc |
| `analysis.auto_plot/title` | auto-generate the Q-vs-ΔP plot when a run finishes |

Values entered in the web UI (setpoints, tolerance, dwell, collection, PID gains)
override the config for that run.

---

## Wiring assumptions (hardware mode)

> ⚠️ These are the assumptions the code is written against. Confirm against your
> actual valve/sensor datasheets before powering the rig. **Common ground**
> between the Pi and the 12 V supply is required.

**Pressure transducer → ADS1115 → Pi (I2C):**
- ADS1115 `VDD→3.3V`, `GND→GND`, `SCL→GPIO3`, `SDA→GPIO2`, `ADDR→GND` (0x48).
- **4–20 mA sensor** (`sensor.type: current_loop`): run the loop so current
  returns through a **precision shunt resistor** to GND; ADS1115 A0 measures the
  voltage across it. 150 Ω → 4 mA = 0.60 V, 20 mA = 3.00 V (safe at gain 1,
  ±4.096 V). Set `shunt_ohms` to your actual resistor.
- **0.5–4.5 V sensor** (`sensor.type: voltage_divider`): the signal exceeds the
  ADS1115's input at 3.3 V, so scale it with a divider. R1 = 10 k, R2 = 20 k →
  ratio 0.667 → 4.5 V maps to ~3.0 V. Set `divider_ratio = R2/(R1+R2)`.

**Pressure-control valve — two driver options (`valve.type`):**

*`servo` (default, recommended for low pressure 10–60 kPa):* a hobby servo turns a
quarter-turn valve. True water proportional solenoids are expensive and most
won't actuate below ~0.5 bar, so a servo-turned valve is cheaper and works at
any pressure.

**Topology (this rig): a SINGLE inline throttle in the feed line** between the
reservoir and the cell — the same place the manual rig's needle valve regulates
today. This works because the high-permeability mesh membrane passes enough flow
(tens of mL/s) that the valve and the membrane form a natural pressure divider:
opening the valve raises cell pressure, closing lowers it (it drains through the
membrane). Command sense: **0% = valve closed = lowest pressure (SAFE)**,
100% = open = highest. A bleed-to-waste layout is also supported — just calibrate
the servo endpoints (or `invert`) the other way; only needed for very-low-flow
(tight) membranes where an inline valve loses authority.
```
GPIO18 (servo_pin) ── servo signal
servo V+  ← separate 5–6 V supply (NOT the Pi rail — servos brown-out the Pi)
common GND between Pi and servo supply
servo horn ──[coupler/bracket]── valve stem
```
pigpio sends clean servo pulses; `servo_min_us`/`servo_max_us` calibrate the
endpoints. command 0% → lowest pressure (inline throttle: valve CLOSED), 100% →
highest (open). **A servo holds position on power loss** (no spring-return), so the
mechanical relief valve is the hardware failsafe. Mechanical note: a hobby servo
only turns ~180°, so pair it with a **quarter-turn (90°) metering/ball valve** so
the servo's travel spans the valve's full range (a multi-turn needle valve gives
only partial range from a servo; use a stepper for full multi-turn control).

*`pwm` (MOSFET-driven proportional solenoid):*
```
GPIO18 ──[1kΩ]── gate │ logic-level N-MOSFET (IRLZ44N)
   valve coil: +12V ── coil ── MOSFET drain ;  source ── GND
   flyback diode (1N5819/SB560) across coil, cathode → +12V
```
PWM duty sets coil current → valve position. A **12 V normally-open** bleed
solenoid fails safe (power loss → open → vent). Set `valve.invert: true` if your
valve/linkage behaves the opposite way (applies to both types).

**Diverter (3-way solenoid):** same MOSFET+flyback (or a relay module) on
`GPIO23`. **De-energised = waste** (fail-safe); energised = measured container.

**On the Pi, before running hardware mode:**
```bash
sudo systemctl enable --now pigpiod          # pigpio daemon for PWM
sudo raspi-config    # enable I2C
pip install -r requirements.txt
python run.py web --hardware --host 0.0.0.0   # serves to the whole network
```

---

## Connecting the Pi to your computer (real-time view)

The web UI **is** the real-time view: the Pi runs the server, and any computer (or
phone) on the same network watches the live pressure chart, the current run, and
the whole **data history** in a browser — no software to install on the laptop.

**Cross-platform.** Because you operate it through a browser, the viewing/control
side works identically on **macOS, Windows, Linux, iOS and Android** — it's just a
web page. The *control code* runs on the Raspberry Pi (Linux); your Mac/Windows
machine only views and commands it. You can also run the whole thing in `sim` mode
on a **Mac or Windows laptop** (pure Python — `pip install PyYAML fastapi uvicorn
pydantic matplotlib openpyxl`) to exercise the full logic with no hardware; the
Pi-only drivers (`pigpio`, `adafruit-circuitpython-ads1x15`, `gpiozero`) are
platform-gated so they aren't installed or imported off the Pi.

```bash
# on the Pi:
python run.py web --host 0.0.0.0 --port 8000
# on your laptop, open:
http://raspberrypi.local:8000        # mDNS name (macOS/Windows/Linux)
#   or  http://<pi-ip>:8000          # find it on the Pi with:  hostname -I
```

Three ways to link them — pick by your lab:

1. **Same Wi-Fi / router (easiest).** Put the Pi and laptop on the lab network;
   open `raspberrypi.local:8000`. Good if the network is reliable.
2. **Direct Ethernet cable (recommended for a bench).** One cable Pi ↔ laptop, no
   router or IT needed — deterministic and isolated. Modern Pi + laptop
   auto-negotiate a link; reach it at `raspberrypi.local:8000`. This is the most
   robust option for a fixed rig.
3. **Pi as a Wi-Fi hotspot.** The Pi broadcasts its own network and the laptop
   joins it — for when there's neither shared Wi-Fi nor a spare laptop Ethernet
   port (a bit more setup on the Pi).

**Auto-start on boot** (so the rig is live whenever the Pi is powered) — create
`/etc/systemd/system/membrane-rig.service`:
```ini
[Unit]
After=network-online.target pigpiod.service
[Service]
WorkingDirectory=/home/pi/membrane-rig
ExecStart=/home/pi/membrane-rig/.venv/bin/python run.py web --hardware --host 0.0.0.0
Restart=always
User=pi
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now membrane-rig
```

The **Data history** panel lists every past run (date, membrane, setpoints, k,
pore size, R²) with one-click download of each run's plot / Excel / CSV — that's
your accumulated dataset, all in one place.

---

## Parts still to buy

**Raspberry Pi + networking**

| Part | Notes |
|------|-------|
| Raspberry Pi 4 (2 GB+) | the controller; you may already have this |
| USB-C power supply (official 5 V/3 A) | stable supply matters for clean ADC reads |
| microSD card (16 GB+) | Raspberry Pi OS Lite is enough (headless) |
| Ethernet cable (Cat5e/6) | for the direct-cable option; Wi-Fi is built in |

**Sensing + actuation**

| Part | Notes |
|------|-------|
| Pressure transducer | 0–100 kPa range (covers your 10–60 kPa tests with headroom). 4–20 mA **or** 0.5–4.5 V — both supported. |
| ADS1115 breakout | 16-bit I2C ADC (the Pi has no analog input) |
| Precision shunt resistor | ~150 Ω, 0.1% (only for the 4–20 mA option) — **or** two divider resistors (10 k + 20 k) for the 0.5–4.5 V option |
| Proportional solenoid valve | 12 V, normally-open, water-compatible, sized for your flow/pressure |
| 3-way solenoid valve | 12 V, water-compatible, normally routes to waste |
| 2× logic-level N-MOSFET | IRLZ44N (or a 2-channel MOSFET driver module) |
| 2× flyback diode | 1N5819 / SB560 (skip if the driver module has them) |
| 12 V power supply | sized for both valves' inrush current |
| Mechanical pressure-relief valve | **safety** — rated below the rig limit; independent of software |
| Wiring, 1 kΩ gate resistors, fittings, tubing, graduated cylinder | — |

---

## Build review — fix these before first power-on

A design/BOM audit flagged the following. The `config.yaml` and BOM already
reflect them; don't skip them or the rig won't assemble or won't control.

**Assembly (won't connect otherwise):**
- The transducer is **G1/4 (BSPP, flat-washer seal)**; the valves are **1/4" NPT
  (tapered)** — they do **not** mate. Use a **G1/4-F × 1/4"-NPT-M adapter with a
  sealing washer**; no PTFE on that flat seal (PTFE only on NPT joints).
- Every threaded port needs an **NPT×barb** adapter to reach the silicone, every
  barb a **clamp**, and the sensor + relief valve each a **tee**. The 12V barrel
  plug needs a **barrel-jack→screw-terminal** pigtail. (All under "Fittings &
  fixes" in the BOM.)

**Electrical:**
- Power the **ADS1115 at 3.3 V** and feed the 0.5–4.5 V sensor through a
  **10k/20k divider** (→ ~3.0 V). Never feed 0.5–4.5 V straight in — it clips and
  can over-volt the ADC. Config uses `sensor.type: voltage_divider`.
- Add a **10k gate-to-source pulldown** + 150–330 Ω series gate resistor on the
  MOSFET, or the diverter can energise at boot before the code runs.
- Add ~1000 µF at the UBEC output and ~470 µF at the 12 V input for rail
  stability, and an **inline 3 A fuse** on the 12 V.

**Control (servo + ball valve = coarse):**
- A quarter-turn ball valve is quick-opening, so expect **~±10–15 %** pressure
  hold, not ±2 % (`tolerance_pct` is set to 10). The permeability `k` is **still
  valid** because `Q` is regressed vs the *measured* mean ΔP per point.
- A bleed valve only has authority with a **fixed restriction upstream** —
  install the manual needle valve (in the BOM) between the source and the bleed
  tee, or the loop can't regulate.

**First test once assembled — static valve-authority sweep:** with the source
pressurised and the diverter to waste, step the valve across its full stroke and
log steady-state pressure. Confirm it's monotonic across 10–60 kPa and spread
over a usable range *before* tuning the PID.

---

## Tuning the PID

Do this in **sim mode first** (`run.py web` or `run.py cli`), then refine on the
real rig. The valve command is 0–100% "pressure authority" (0 = lowest pressure /
safe, 100 = max pressure).

**The plant is asymmetric — tune for NO overshoot.** Opening the air valve
raises pressure in seconds, but closing it does *not* bring it down quickly:
pressure only decays as water permeates (tens of seconds, and never instantly).
Overshoot is therefore expensive to undo. Three defences are built in:
1. `test.sort_ascending` — setpoints always run low→high (never wait on a fall),
2. `test.ramp_kpa_s` — the PID chases a ramped target, approaching from below,
3. a low-pass filtered derivative (inside the PID) lets a strong `kd` brake the
   approach without sensor noise shaking the servo.
The shipped gains (kp 4, ki 0.4, kd 1.0, ramp 3 kPa/s) hold overshoot under
~1 kPa in sim with the compressor wobbling ±8 kPa. On the real rig, if you see
overshoot: lower `ramp_kpa_s` first, then lower `ki`. If pressure still falls
too slowly for your workflow, the hardware fix is a tiny fixed bleed orifice on
the air line (adds down-authority at the cost of some air).

1. **Start with P only.** Set `ki: 0`, `kd: 0`. Raise `kp` until the pressure
   responds briskly and slightly overshoots the setpoint, then oscillates a
   little. Halve that `kp`.
2. **Add I to kill steady-state error.** Increase `ki` until the pressure settles
   *onto* the setpoint within a few seconds without slow drift. Too much `ki` →
   slow oscillation/overshoot. The anti-windup means the integral won't blow up
   while the valve is saturated during pressurisation.
3. **Add a little D to damp overshoot.** Small `kd` (start ~0.05–0.2) reduces
   overshoot. Because D acts on measurement, changing setpoints between test
   points won't cause a derivative kick. Too much `kd` amplifies sensor noise —
   if the valve chatters, back it off.
4. **Check against the band.** The goal is to enter and hold ±`tolerance_pct`
   for `dwell_s`. Watch the live chart / the `in_band` column. Widen the band or
   lengthen dwell if a noisy sensor makes stabilisation flaky.
5. **On real hardware**, expect to lower the gains vs sim — real valves have
   deadband, hysteresis and transport lag the model doesn't capture.

Rules of thumb: sluggish to reach setpoint → raise `kp`; never quite reaches it
→ raise `ki`; overshoots/rings → raise `kd` or lower `kp`; valve buzzes → lower
`kd` (and/or the sensor is noisy).

---

## Output files

Per run (one session), in `runs/`:
- `run_YYYYMMDD_HHMMSS.csv` — timestamped trace: elapsed, phase, setpoint,
  pressure (display unit **and** kPa), valve command, diverter position, in-band
  flag. Plot pressure vs time for your stability analysis.
- `run_YYYYMMDD_HHMMSS_meta.json` — setpoints, PID gains, tolerance/dwell/collection,
  and per-setpoint summary: mean / std / min / max / in-band fraction / sample
  count during the **collection** window, plus volume + flow, plus timestamps.
- `run_YYYYMMDD_HHMMSS_analysis.json` — slope fit + Darcy k + pore size.
- `run_YYYYMMDD_HHMMSS_plot.png` — the Q-vs-ΔP chart (below).
- `run_YYYYMMDD_HHMMSS_results.xlsx` — **native Excel** workbook: data table, an
  editable scatter chart with a linear trendline (equation + R² shown by Excel),
  the Darcy k and mean-pore-size cells, and a "Per point" sheet with the
  collection stats. Downloadable from the web UI (⬇ Download Excel).

---

## Permeability analysis (Q vs ΔP) — automatic

When a run finishes, the rig fits permeate flow rate `Q` against transmembrane
pressure `ΔP` over **all** collected points (replicates included) and derives:

```
Q = a + b·ΔP                     (least-squares fit, with R²)
k_Darcy = b_Pa · μ · L / A       (slope method — not per-point averaging)
mean hydraulic pore size  d = √(32·k)
```

This is the same slope method as `lab.divid.site`: averaging per-point `k` bakes
in experimental error; the slope over all data is robust and `R²` tells you how
well the data obeys Darcy's law. Set `A`, `L`, `μ` per membrane in
`config.yaml → membrane`. The chart (scatter + trendline + equation + R² + k +
pore size) is written as a PNG **and as a native Excel workbook** (`_results.xlsx`)
whose chart is a real, editable Excel scatter+trendline — download it from the
web UI or open the file directly.

**Where does `Q` come from?** `Q = collected volume / collection time`. The rig
already automates the timing precisely; the **volume** is the one thing no sensor
replaces — read it off the graduated cylinder and enter it:
- **CLI (hardware):** you're prompted for each point's volume after the run.
- **Web UI (hardware):** a volume field appears per point; submit to draw the plot.
- **sim mode:** a simulated Darcy plant produces the flow, so the whole pipeline
  (collect → Q → fit → plot) runs automatically with no input — good for testing.

**Plot existing data** (e.g. your spreadsheet) without the rig:

```bash
python run.py analyze data.csv --area-cm2 0.64 --thickness-mm 0.117 --label "60 mesh"
# data.csv: a "pressure" column (kPa) and a "flow"/"flow_rate" column (m³/s)
```

To get replicate scatter like a real dataset, list a setpoint multiple times,
e.g. `test.setpoints: [15, 15, 20, 20, 30, 30]`.

---

## Safety notes

- Software cutoff (`safety.max_pressure`) vents and aborts on overpressure.
- Sensor sanity check: implausible or unhealthy readings (e.g. a disconnected
  4–20 mA loop) trigger vent+abort after `fault_grace_reads` consecutive bad
  reads — a single glitch won't abort a run, but a real fault will.
- Ctrl+C, unhandled exceptions and process shutdown all drive the valves to the
  safe state (valve vented, diverter to waste).
- **Software limits are not a substitute for hardware protection.** Fit a
  mechanical pressure-relief valve rated below your rig's limit. The software is
  the first line of defence, not the last.
