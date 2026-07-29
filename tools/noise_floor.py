"""Measure the ADC noise floor — the number the frozen-signal detector rests on.

`docs/ASSEMBLY.md` ("First safety checks") says to log `Reading.raw` at rest and
confirm it moves by more than one LSB between samples, because `safety.py` faults
when raw comes back bit-identical for `safety.frozen_raw_reads` samples. That
check assumes a live analog chain always jitters — an assumption taken from the
sim's modelled noise, never measured on hardware.

The CSV logger does not carry a `raw` column, so there was no way to run that
step. This is that way. Run it on the Pi with the ADS1115 wired and the rig at
rest (no pressure):

    ./.venv/bin/python tools/noise_floor.py            # 60 s at 20 Hz
    ./.venv/bin/python tools/noise_floor.py --seconds 120

It builds ONLY the sensor, never the full HAL, so it does not construct
ServoValve and therefore never touches pigpio or drives the servo to 700 us.

Reads the verdict the way safety.py will: the longest run of bit-identical raw
values. If that run approaches `frozen_raw_reads`, RAISE the config value — do
not remove the check, which is the sharpest protection against a stuck sensor.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--hz", type=float, default=20.0)
    args = ap.parse_args()

    cfg = Config.load(args.config)
    s = cfg.sensor

    # One ADS1115 count at gain 1 is 125 uV at the ADC. `raw` is referred to the
    # SENSOR side (v_adc / divider_ratio), so one count is bigger there.
    lsb_adc_v = 125e-6
    lsb_raw = lsb_adc_v / s.divider_ratio if s.type == "voltage_divider" else lsb_adc_v / s.shunt_ohms
    span_v = s.v_signal_max - s.v_signal_min
    kpa_per_raw = (s.range_max_kpa - s.range_min_kpa) / span_v
    lsb_kpa = lsb_raw * kpa_per_raw

    print(f"config          {args.config}  (type={s.type}, ratio={s.divider_ratio})")
    print(f"1 LSB           {lsb_raw*1e6:.1f} uV of raw  =  {lsb_kpa:.4f} kPa")
    print(f"frozen_raw_reads {getattr(cfg.safety, 'frozen_raw_reads', '(not in config)')}")
    print(f"sampling        {args.hz:g} Hz for {args.seconds:g} s\n")

    from src.hal.ads1115_sensor import Ads1115Sensor  # lazy: needs board/busio

    sensor = Ads1115Sensor(cfg)

    period = 1.0 / args.hz
    raws: list[float] = []
    unhealthy = 0
    run = best_run = 1
    next_t = time.monotonic()
    deadline = next_t + args.seconds

    while time.monotonic() < deadline:
        r = sensor.read()
        if not r.healthy or r.raw != r.raw:  # NaN
            unhealthy += 1
        else:
            if raws and r.raw == raws[-1]:
                run += 1
                best_run = max(best_run, run)
            else:
                run = 1
            raws.append(r.raw)
        next_t += period
        time.sleep(max(0.0, next_t - time.monotonic()))

    if len(raws) < 2:
        print(f"FAIL  only {len(raws)} healthy reads ({unhealthy} unhealthy) — fix the wiring first")
        return 1

    deltas = [abs(b - a) for a, b in zip(raws, raws[1:])]
    moved = sum(1 for d in deltas if d >= lsb_raw)
    identical = sum(1 for d in deltas if d == 0.0)

    print(f"healthy reads   {len(raws)}   unhealthy {unhealthy}")
    print(f"raw             mean {statistics.fmean(raws)*1e3:.3f} mV   "
          f"stdev {statistics.stdev(raws)*1e6:.1f} uV = {statistics.stdev(raws)/lsb_raw:.2f} LSB")
    print(f"                spread {(max(raws)-min(raws))/lsb_raw:.1f} LSB")
    print(f"sample-to-sample  moved >= 1 LSB: {moved}/{len(deltas)} ({moved/len(deltas)*100:.1f} %)")
    print(f"                  bit-identical:  {identical}/{len(deltas)} ({identical/len(deltas)*100:.1f} %)")
    print(f"longest identical run  {best_run} samples\n")

    n = getattr(cfg.safety, "frozen_raw_reads", None)
    if n is None:
        print("NOTE  safety.frozen_raw_reads is not in this config — nothing to tune yet.")
        return 0

    if best_run >= n:
        print(f"FAIL  a healthy sensor already repeated {best_run} times, at or over "
              f"frozen_raw_reads={n}.\n      This WILL fire spurious SENSOR_FAULTs. "
              f"Raise frozen_raw_reads to at least {best_run * 3} and re-run.\n"
              f"      Do NOT disable the check — it is what catches a sensor stuck at a "
              f"plausible value,\n      and there is no mechanical relief valve backing it up.")
        return 1

    margin = n / best_run
    verdict = "PASS" if margin >= 3 else "MARGINAL"
    print(f"{verdict}  longest healthy run {best_run} vs frozen_raw_reads={n} "
          f"({margin:.1f}x margin).")
    if margin < 3:
        print(f"      Under 3x is thin. Consider raising frozen_raw_reads to {best_run * 3}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
