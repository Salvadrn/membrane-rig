# Running the rig without the person who built it

Adrián built this rig and is leaving it in the lab. This is the map for whoever
runs it next. It is deliberately **not** an encyclopedia — the detail lives in
`ASSEMBLY.md`, `COMMISSIONING.md` and `INVENTORY.md`, and this points at them.

Read section 1 now, before anything goes wrong. Sections 2 and 3 can wait until
you need them.

> **Status: the rig is not yet commissioned.** Nothing in this repo has been run
> on hardware. Before the first real experiment, someone must work through
> [`COMMISSIONING.md`](COMMISSIONING.md) end to end. Until then, treat every
> number the software reports as unverified.

> ### ⚠ THIS PARTICULAR RASPBERRY PI: header pins 6 and 14 are damaged
>
> Both are ground pins, and **pin 6 is the one every wiring document used to
> name.** They are physically unusable on this board.
>
> | Instead of | Use | For |
> |---|---|---|
> | pin 6 (GND) | **pin 9** | sensing ground, and every voltage measured "against GND" |
> | pin 14 (GND) | **pin 20** | diverter-side reference, *if a local one is wired at all — see below* |
>
> The wiring sheets and `COMMISSIONING.md` have been updated to say pin 9. This
> note exists because **you may be holding a printed or older copy that still
> says pin 6**, and because a replacement Pi will have working pins — at which
> point this note stops applying and the substitution should be undone.
>
> **Two consequences that are easy to miss:**
>
> - **Every "measure X against pin 6" reads a false result on this board.** A
>   damaged pin is open, so pin 1 → pin 6 reads 0 V and pin 1 ↔ pin 6 reads OL —
>   which looks exactly like *"both rails dead"* and *"no short"*. Someone
>   following an old checklist would conclude this healthy Pi is broken. Measure
>   against **pin 9**.
> - **Do not force a wire into pin 6 or 14.** Pin 6 sits beside pin 4 (5 V), and
>   pin 14 sits between pin 12 (servo signal) and pin 16 (diverter gate). A bent
>   pin touching its neighbour is a 5 V-to-ground short on one side and an
>   actuator fault on the other. Mark them physically — this rig has already lost
>   one board to a 3.3 V short.

---

## 1 · Something is wrong

### The one thing that always works

**Close the air valve on the lab panel.** By hand. That is the only action that
stops pressurisation regardless of software, power, or network.

It matters more here than on most rigs, for two reasons you should know before
you need them:

- **The control valve does not spring shut — and it does not hold position
  either.** It is a ball valve turned by a servo. Measured on the bench
  (2026-08-06): on power loss the servo *drifts off the commanded angle*, to a
  position nobody chose — it neither seals nor stays put. Killing power to the rig
  does **not** make it safe: the feed can be left open, or part open, at an angle
  you did not set. Which way it drifts and how far is **not yet measured**
  (COMMISSIONING 10.7), so assume the worst and close the panel valve by hand.
- **The mechanical relief valve is on order but NOT FITTED.** Until it is
  mounted and set, no layer of protection acts without the controller being
  alive. A line on a purchase order is not a protective layer.

The ball valve's own handle has been removed so the servo can turn the stem, so
**the panel valve is the only thing a human can shut.** Know where it is before
you start a run. If you are not physically at the rig, you cannot do this — see
"If you are remote" below.

### What each alarm means

| What you see | What it means | What to do |
|---|---|---|
| **Sensor fault** | The pressure reading is missing or implausible. The rig has already shut the feed and aborted. | Safe. Check the transducer's wiring before restarting. A disconnected sensor reads −12.93 kPa, which is what triggers this. |
| **Overpressure** | Pressure exceeded the ceiling for this run. Already shut the feed and aborted. | Safe. Do not raise any limit to make it go away — find out why it overshot. |
| **Frozen signal** | The sensor is returning bit-identical values: it is stuck, not steady. Aborted. | Safe. The probe or the I²C bus is dead. Do **not** disable this check; if it fires spuriously, raise `safety.frozen_raw_reads`. |
| **Plant watchdog** | The valve is commanded open but pressure never moved. Either the valve is stuck or the supply is shut. Aborted. | Safe. Check the supply and the servo coupling. |
| **⚠ Valve may not have closed** | **This is the one that needs a human.** The run ended, the software commanded the valve shut, and pressure did not fall. The feed may still be open with the cell pressurised. | **Go and close the panel valve by hand.** The software has already done everything it can. |

Everything except the last one is the software succeeding at its job: it saw a
problem and put the rig in a safe state. The last one is the software telling you
it *failed* and needs you.

### This looks wrong but isn't

**A queue item in red (FAILED) has not lost its data.** Stopping a run marks the
item failed, but every point it already measured is still there — in the run's
CSV and in the item itself. What it is *not* in, yet, is the combined fit, which
only counts items marked done.

> **Re-queueing does not recover them — it re-runs the whole experiment**, and
> costs you the bench time and the setup again. **Marking the item done** is what
> pulls its measured points into the combined fit.

The item's own note says this where you will see it, in the queue.

This will come up more than you expect, because stopping a run is a normal thing
to do: a session times out, you log back in, you stop. That is not a failure, and
neither is what it leaves behind.

### Never do these

- **Never loosen a pressure limit** to make an abort stop happening. The limits
  in `config.yaml` protect a delicate mesh and a vessel whose pressure rating is
  not documented anywhere. If a limit is in your way, something else is wrong.
- **Never disable the frozen-signal check.** It is the sharpest protection
  against a sensor stuck at a plausible value — the failure mode that produces
  confident, wrong results. Raise the threshold instead.
- **Never leave the rig pressurised and unattended.** Close the panel valve at
  the end of every session. Not best practice — required, because nothing else
  holds the feed shut.

### If you are remote

You can start, watch and stop a run from the web interface. You **cannot**:

- close the panel valve,
- read the graduated cylinder — there is no flow meter, so **every data point
  needs someone physically present** to read and enter the volume,
- respond to "valve may not have closed".

So: **do not start a pressurised run unless someone is in the lab.** Remote
operation is for watching and stopping, not for unattended experiments.

**Keep a session open for the whole run.** Every action in the app — including
stop — requires being logged in. If your session expires while pressure is up,
you have to authenticate before you can stop anything, and that is time you may
not want to spend. Log in before you start, and stay logged in until the run
ends.

The panel valve is the only control that never asks for a password. That is
another reason someone should be in the lab whenever the rig is pressurised.

---

## 2 · Operating

### Starting up

1. **Power the Pi.** The app starts automatically.
2. **Open the interface.** `<TUNNEL HOSTNAME — PENDING>` — the tunnel is set up
   per [`REMOTE_ACCESS.md`](REMOTE_ACCESS.md), but the final hostname is waiting
   on Adrián's domain decision. On the lab network, `membrane-rig.local:8000`
   works.
3. **Log in.** Every action needs an account — including stop. See "Accounts"
   below if one has not been set up yet.
4. **Open the air supply** at the panel, and confirm the regulator setting.

### Accounts

Run this **on the Pi** to create the login, or to change it later:

```
./.venv/bin/python tools/set_password.py
```

The password is stored **hashed** (PBKDF2-SHA256) in `~/.membrane-rig/auth`,
mode 600, outside the repo — so it never reaches git and re-deploying the code
does not disturb it. The same run also issues the beacon token, so provisioning
a fresh Pi is one command.

| Need | Command |
|---|---|
| Set or change the password | `tools/set_password.py` |
| New beacon token only | `tools/set_password.py --rotate-token` (restart the beacon after) |
| See the current token | `tools/set_password.py --show-token` |

**If no account is configured**, the rig still serves and warns loudly at
startup. That is deliberate: a fresh Pi should tell you what to do, not lock you
out of your own hardware.

**Rotate the password when someone leaves the group**, and after anyone watches
you type it. There is one account; it is shared by whoever operates the rig.

### Running an experiment

The interface queues experiments as a playlist and runs them one at a time, each
one gated by you pressing play. For each pressure setpoint the rig:

1. drives to the setpoint and holds it inside a tolerance band,
2. switches the diverter to the measuring container and collects for a fixed
   window,
3. waits for you to **read the cylinder and enter the volume**,
4. moves to the next setpoint.

Then it fits flow against pressure and reports the permeability `k`, the mean
pore size, and the R² of the fit.

**Read the cylinder at eye level, at the bottom of the meniscus.** That reading
is currently the largest human contribution to the error budget.

**If R² comes out below 0.98** the software flags the run as not following
Darcy's law. Usually that means a leak or a bad volume reading. **But R² is not
a general safety net** — see §3, "What R² will not catch".

### Where results go

Every run writes a CSV and a plot under `runs/`. Excel export is available from
the interface. Nothing is deleted automatically.

### Shutting down

1. Let the current run finish, or press stop.
2. **Close the panel valve by hand.**
3. Leave the Pi running — it costs nothing and keeps the rig reachable.

---

## 3 · Maintaining

### Calibrations, and when they expire

| What | When to redo it | How |
|---|---|---|
| `sensor.divider_ratio` | If the divider is ever rebuilt | Measure Vout/Vin on the soldered divider, or use `tools/noise_floor.py`'s companion procedure in `COMMISSIONING.md` |
| Transducer 2-point | Yearly, or if the transducer is moved or replaced | Against the Keller LEX1 on the bench — it is a calibration-grade instrument and a better reference than the dial gauge |
| `servo_min_us` / `servo_max_us` | If the coupling is disturbed | `./.venv/bin/python tools/valve_calib.py --sweep` |
| `servo_close_us` | Same, and any time "valve may not have closed" starts appearing | `./.venv/bin/python tools/valve_calib.py --close` |
| Noise floor | Once at commissioning; again if the front end changes | `./.venv/bin/python tools/noise_floor.py` |

**Read the safety notes in `valve_calib.py` before running either mode.** It
moves the servo on purpose, and the servo drives to its endpoint the moment the
driver is constructed.

### If you change a part

Two rules, both learned the hard way on this project:

1. **Re-measure what that part determined.** Swap the transducer and the 2-point
   calibration is void. Rebuild the divider and `divider_ratio` is void.
2. **Sweep what was *derived* from it, not just its name.** A find/replace on
   the part number is not enough. Numbers calculated from the old value, claims
   that depended on it, and recommendations that only made sense with it are all
   stale — and none of them contain the string you would search for. This bit
   this project at least three times.

### What R² will not catch

`R² ≥ 0.98` checks that the points fall on a line. It does **not** verify that
the line means what you think:

- A **constant** offset — a zero error, a static water column, a small leak —
  shifts the fit's intercept and leaves `k` correct. Harmless.
- Anything that **grows with flow** — a restricting diverter, a narrow dip tube
  — *bends* the line instead. Simulated: an error big enough to put `k` **49.5 %
  low** still returns **R² = 0.9969** and passes the Darcy check.

With three setpoints, a smooth curvature is invisible. Two specific instances of
this are open and must be settled during commissioning — see `COMMISSIONING.md`
§ Stage 10.5 and `ASSEMBLY.md` § "Where the transducer goes".

### Where everything lives

| Document | What it answers |
|---|---|
| [`COMMISSIONING.md`](COMMISSIONING.md) | "Is the rig ready?" — the staged checklist, with the expected number at every step |
| [`ASSEMBLY.md`](ASSEMBLY.md) | "How is it built and why?" — wiring, mechanics, the reasoning behind each choice |
| [`INVENTORY.md`](../INVENTORY.md) | "What do we physically have?" — parts on hand, what is blocked, what still needs measuring |
| [`REMOTE_ACCESS.md`](REMOTE_ACCESS.md) | "How do I reach it from outside?" |
| [`INSTALL.md`](INSTALL.md) | "How do I set up the Pi from scratch?" |
| `docs/wiring_*.html` | Pin-by-pin sheets for each subsystem. Print them: `tools/sheets_to_pdf.py` |

### Numbers this rig still owes

These are recorded as unknown on purpose. Do not invent them.

- **The air regulator's setting.** Until the relief valve is fitted, this is the
  only physical bound on what the cell can see, and nobody has written it down.
- **The vessel's pressure rating.** `ASSEMBLY.md` tells you to set the relief
  below it; that limit exists nowhere in this repo.
- **The real permeate flow.** Every flow figure in the config is a simulation
  parameter chosen to draw a clean line. It decides whether the diverter
  throttles the measurement and whether the collection window fits the cylinder.

---

## Who to ask

- **Adrián Martínez** — built it. Different time zone; not a real-time resource.
- **Kwangsoo Cho** (`kwcho@ucsd.edu`) — lab mentor, and the route for purchases.
- **Prof. Renkun Chen** (`rkchen@ucsd.edu`) — PI.

If something is unsafe and nobody answers: **close the panel valve and leave it
closed.** Nothing about this rig is urgent enough to run past a problem you do
not understand.
