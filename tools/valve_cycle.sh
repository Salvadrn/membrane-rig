#!/bin/bash
# Cycle the valve between two dial angles, on the KERNEL's hardware PWM.
#
#   sudo bash tools/valve_cycle.sh            # 90 <-> 180, 3 rounds
#   sudo bash tools/valve_cycle.sh 90 180 5   # explicit
#
# Exists because the working path has two halves that are easy to separate: the
# pin must be routed to PWM0 (pinctrl a5) AND the duty has to be written. Run
# the second without the first and the pulse is generated perfectly and never
# reaches the wire — that collision cost an afternoon here, and it looks exactly
# like "the servo doesn't move".
#
# The routing is NOT permanent: a `gpio=18=...` line in config.txt wins over the
# PWM overlay at boot, so this re-asserts it every time rather than assuming.
#
# It ends HOLDING the last position. The kernel keeps emitting after this exits,
# which is what stops the valve drifting — this servo does not hold by friction.
set -euo pipefail
A=${1:-90}; B=${2:-180}; N=${3:-3}
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="$HERE/.venv/bin/python"

pinctrl set 18 a5
echo "GPIO18: $(pinctrl get 18)"
for i in $(seq 1 "$N"); do
  for g in "$A" "$B"; do
    "$PY" "$HERE/tools/servo_pwm.py" "$g" --dial >/dev/null
    echo "  vuelta $i/$N  ->  tus $g grados"
    sleep 4
  done
done
echo "fin — sostenido en tus $B grados"
