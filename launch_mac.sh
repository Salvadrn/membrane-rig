#!/usr/bin/env bash
# Start the rig UI on this Mac and open it in the default browser.
#
# Used by "Membrane Rig.app" (see make_mac_app.sh) but also fine to run directly:
#   bash launch_mac.sh            # sim mode (no hardware)
#   bash launch_mac.sh --hardware # talk to a real rig
#
# Starting it twice is harmless: if the port is already serving, this just opens
# the browser at the existing server instead of failing on a bound port.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PORT="${MEMBRANE_RIG_PORT:-8000}"
MODE="${1:---sim}"
LOG="$DIR/runs/server.log"
PY="$DIR/.venv/bin/python"

mkdir -p "$DIR/runs"

if [ ! -x "$PY" ]; then
  osascript -e 'display alert "Membrane Rig" message "The Python environment is missing.

Open Terminal and run:
  cd ~/Desktop/membrane-rig
  python3 -m venv .venv
  .venv/bin/pip install PyYAML fastapi uvicorn pydantic matplotlib openpyxl" as critical' 2>/dev/null
  exit 1
fi

already_serving() {
  curl -fsS -m 2 "http://127.0.0.1:$PORT/config" >/dev/null 2>&1
}

if already_serving; then
  open "http://localhost:$PORT"
  exit 0
fi

nohup "$PY" -u run.py web --config config.yaml "$MODE" \
      --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &

# wait for it to answer before opening the browser, so we never show a dead tab
for _ in $(seq 1 40); do
  if already_serving; then
    open "http://localhost:$PORT"
    exit 0
  fi
  sleep 0.25
done

osascript -e "display alert \"Membrane Rig\" message \"The server did not start within 10 s.

Check the log:
  $LOG\" as critical" 2>/dev/null
exit 1
