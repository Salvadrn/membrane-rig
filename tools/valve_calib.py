"""Move the servo valve on purpose — the two calibrations that have no other way to run.

`docs/ASSEMBLY.md` asks for two measurements before the rig can hold a setpoint:

  * the **static authority sweep** — step the valve 0→100 %, log pressure, and
    read off the sub-range that actually does something, which becomes
    `valve.servo_min_us` / `servo_max_us`;
  * **`servo_close_us`** — the pulse that SEATS the valve, a little past where
    regulation stops, because 0 % is the bottom of the control range and with
    backlash in a printed coupling it can sit slightly cracked.

Neither had a runnable procedure. The only ways to move the servo were to run a
full PID test or to write Python at the bench — and starting the app in
`mode: hardware` is itself a hazard, because `build_hal()` constructs
`ServoValve` before anything else and its `__init__` drives to 700 µs on the
spot. This is the valve's equivalent of `tools/noise_floor.py`.

It builds ONLY the valve and (for the sweep) the sensor. No diverter, no
temperature, no controller, no PID.

    ./.venv/bin/python tools/valve_calib.py --sweep     # authority sweep
    ./.venv/bin/python tools/valve_calib.py --close     # seat calibration

SAFETY — read before running either mode:

  * **Decouple the servo from the valve stem for `--sweep` the first time.**
    Constructing ServoValve drives to `servo_min_us` (700 µs) immediately. If
    the coupling is already fitted and 700 µs lies past the mechanical stop,
    that stalls the servo against the valve.
  * There is **no mechanical relief valve** on this rig, so the supply pressure
    is the only thing bounding a runaway. Know the regulator setting before
    admitting air, and keep a hand on the panel valve.
  * `--close` needs the supply ON and someone watching flow. Step down until
    flow stops, then add a small margin. Do NOT jam the servo into the
    mechanical stop: that position is held for as long as the rig sits idle,
    and a stalled servo cooks.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config  # noqa: E402

BANNER = """
========================================================================
  THE SERVO IS ABOUT TO MOVE.
  Constructing the driver drives it to {us} us before anything else runs.

  Confirm all of these:
    - the servo is DECOUPLED from the valve stem, or you have already
      verified {us} us is inside the stem's travel
    - the servo is powered from the UBEC (6 V), never the Pi rail
    - you know the air regulator setting; there is NO relief valve
========================================================================
"""


def confirm(cfg) -> None:
    print(BANNER.format(us=cfg.valve.servo_min_us))
    if input("type 'move' to continue: ").strip() != "move":
        print("aborted — nothing was driven.")
        raise SystemExit(1)


def build_valve(cfg):
    from src.hal.servo_valve import ServoValve  # lazy: needs pigpio
    return ServoValve(cfg)


def build_sensor(cfg):
    from src.hal.ads1115_sensor import Ads1115Sensor  # lazy: needs board/busio
    return Ads1115Sensor(cfg)


def read_mean(sensor, n: int = 20, hz: float = 20.0) -> float:
    """Mean of n healthy reads, or nan if the sensor is not co-operating."""
    vals = []
    for _ in range(n):
        r = sensor.read()
        if r.healthy and r.pressure_kpa == r.pressure_kpa:
            vals.append(r.pressure_kpa)
        time.sleep(1.0 / hz)
    return sum(vals) / len(vals) if vals else float("nan")


def sweep(cfg, args) -> int:
    v = cfg.valve
    print(f"\nsweep {args.start:g} -> {args.stop:g} % in {args.step:g} % steps, "
          f"{args.dwell:g} s dwell")
    print(f"pulse range {v.servo_min_us}-{v.servo_max_us} us on GPIO{v.servo_pin}\n")

    sensor = build_sensor(cfg)
    valve = build_valve(cfg)
    rows = []
    try:
        cmd = args.start
        while cmd <= args.stop + 1e-9:
            valve.set_command(cmd)
            time.sleep(args.dwell)
            p = read_mean(sensor)
            frac = cmd / 100.0
            us = v.servo_min_us + frac * (v.servo_max_us - v.servo_min_us)
            rows.append((cmd, us, p))
            print(f"  {cmd:6.1f} %   {us:7.0f} us   {p:8.2f} kPa")
            cmd += args.step
    finally:
        print("\nreturning to safe (0 %) and releasing...")
        valve.close()

    live = [r for r in rows if r[2] == r[2]]
    if len(live) < 3:
        print("\nnot enough good readings to suggest endpoints.")
        return 1

    lo, hi = min(r[2] for r in live), max(r[2] for r in live)
    band = hi - lo
    if band < 1.0:
        print(f"\nWARNING pressure moved only {band:.2f} kPa across the whole sweep.")
        print("        Either the supply is shut, the coupling is slipping, or the")
        print("        servo is not reaching the valve. Fix that before reading anything.")
        return 1

    # Useful sub-range: where the curve actually does something. Trim the ends
    # that sit within 5 % of the extremes — a ball valve is flat near full open.
    thr_lo, thr_hi = lo + 0.05 * band, hi - 0.05 * band
    active = [r for r in live if thr_lo <= r[2] <= thr_hi]
    if active:
        c0, c1 = active[0][0], active[-1][0]
        u0, u1 = active[0][1], active[-1][1]
        print(f"\npressure spanned {lo:.2f} -> {hi:.2f} kPa ({band:.2f} kPa)")
        print(f"useful travel is roughly {c0:.0f} % to {c1:.0f} %  =  {u0:.0f} to {u1:.0f} us")
        print("\nSuggestion for config.yaml (verify against the table above — this is")
        print("a hint from one sweep, not a measurement to paste blindly):")
        print(f"  servo_min_us: {u0:.0f}")
        print(f"  servo_max_us: {u1:.0f}")
    return 0


def close_calib(cfg, args) -> int:
    v = cfg.valve
    start = int(v.servo_max_us if v.invert else v.servo_min_us)
    direction = 1 if v.invert else -1
    print(f"\nseat calibration: stepping {'up' if direction > 0 else 'down'} from "
          f"{start} us in {args.step_us} us steps")
    print("supply must be ON. Watch the flow, not the screen.\n")

    valve = build_valve(cfg)
    seated = None
    try:
        us = start
        while args.min_us <= us <= args.max_us:
            valve._pi.set_servo_pulsewidth(v.servo_pin, int(us))
            time.sleep(args.dwell)
            ans = input(f"  {us:5d} us  — has flow FULLY stopped? [y/N/q] ").strip().lower()
            if ans == "q":
                break
            if ans == "y":
                seated = us
                break
            us += direction * args.step_us
    finally:
        print("\nreturning to safe and releasing...")
        valve.close()

    if seated is None:
        print("\nno seat point found in range. If the valve never sealed, the coupling")
        print("may be slipping or the stem is past its stop — do not force it.")
        return 1

    margin = direction * args.margin_us
    suggested = int(seated + margin)
    print(f"\nflow stopped at {seated} us; adding {args.margin_us} us of margin.")
    print("\nFor config.yaml:")
    print(f"  servo_close_us: {suggested}")
    print("\nCheck it is NOT against the mechanical stop before committing to it —")
    print("this position is held the whole time the rig sits idle, and a stalled")
    print("servo overheats. If it is at the stop, back off and re-run the sweep first.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sweep", action="store_true", help="static valve-authority sweep")
    mode.add_argument("--close", action="store_true", help="find the seating pulse")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--stop", type=float, default=100.0)
    ap.add_argument("--step", type=float, default=10.0)
    ap.add_argument("--dwell", type=float, default=3.0)
    ap.add_argument("--step-us", type=int, default=10)
    ap.add_argument("--margin-us", type=int, default=20)
    ap.add_argument("--min-us", type=int, default=500)
    ap.add_argument("--max-us", type=int, default=2500)
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    if cfg.valve.type != "servo":
        print(f"valve.type is '{cfg.valve.type}', not 'servo' — nothing to calibrate.")
        return 1
    if cfg.mode != "hardware":
        print(f"WARNING config mode is '{cfg.mode}'. This tool talks to real pigpio "
              f"regardless;\n        the mode field only affects the app.")

    if not args.yes:
        confirm(cfg)

    return sweep(cfg, args) if args.sweep else close_calib(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
