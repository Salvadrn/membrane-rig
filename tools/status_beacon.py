"""Push the rig's status to the Cloudflare status Worker.

Runs ON the Pi, beside the rig app. Read-only in both directions: it polls the
app's own HTTP status endpoint and POSTs the result out. It never commands
anything, and nothing it receives can command anything — the Worker is a
beacon, not a control path (cloudflare/rig-status/src/index.js).

It talks to the app over HTTP rather than importing src/ on purpose: the app is
Control's area, and a deployment tool that reaches into another agent's
internals breaks the moment they refactor. The status endpoint is a published
interface; get_status() is not.

Usage on the Pi, after install.sh and after the Worker is deployed:

    export RIG_INGEST_SECRET='...'          # same value as: wrangler secret put INGEST_SECRET
    export RIG_BEACON_URL='https://<worker>.workers.dev/ingest'
    ./.venv/bin/python tools/status_beacon.py

As a service (survives reboots, restarts on failure):

    sudo tee /etc/systemd/system/rig-beacon.service >/dev/null <<'EOF'
    [Unit]
    Description=Membrane rig status beacon
    After=network-online.target
    [Service]
    Environment=RIG_INGEST_SECRET=...
    Environment=RIG_BEACON_URL=https://<worker>.workers.dev/ingest
    WorkingDirectory=/home/pi/membrane-rig
    ExecStart=/home/pi/membrane-rig/.venv/bin/python tools/status_beacon.py
    Restart=always
    RestartSec=10
    [Install]
    WantedBy=multi-user.target
    EOF
    sudo systemctl enable --now rig-beacon
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

APP_STATUS_URL = os.environ.get("RIG_APP_STATUS_URL", "http://127.0.0.1:8000/status")
BEACON_URL = os.environ.get("RIG_BEACON_URL", "")
SECRET = os.environ.get("RIG_INGEST_SECRET", "")

POST_PERIOD_S = 5.0  # the Worker calls the rig stale after 20 s, i.e. three missed beats
HTTP_TIMEOUT_S = 4.0  # under the period, so a hung request cannot stack up beats

# Only these keys leave the Pi. An allow-list rather than forwarding the whole
# status blob: the app's status is Control's to extend, and a field added there
# should not silently start being published to the internet.
FIELDS = (
    "state",
    "pressure_kpa",
    "setpoint_kpa",
    "run_ceiling_kpa",
    "run_ceiling_source",
    "temperature_c",
    "temperature_source",
    "diverter",
    "fault",
    "ts",
)


def fetch_status() -> dict | None:
    try:
        with urllib.request.urlopen(APP_STATUS_URL, timeout=HTTP_TIMEOUT_S) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # app down, restarting, or not serving yet
        print(f"[beacon] cannot read app status: {exc}", file=sys.stderr, flush=True)
        return None
    if not isinstance(payload, dict):
        print("[beacon] status endpoint did not return an object", file=sys.stderr, flush=True)
        return None
    return {k: payload[k] for k in FIELDS if k in payload}


def push(body: dict) -> None:
    req = urllib.request.Request(
        BEACON_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "x-rig-key": SECRET},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        # 401 means the secret drifted; say so plainly instead of retrying forever in silence.
        print(f"[beacon] worker rejected the push: {exc.code}", file=sys.stderr, flush=True)
    except Exception as exc:
        # Lab wifi drops are the normal case here, not an error worth stopping for.
        print(f"[beacon] push failed: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    if not BEACON_URL or not SECRET:
        print(
            "[beacon] set RIG_BEACON_URL and RIG_INGEST_SECRET first — see the docstring",
            file=sys.stderr,
        )
        return 2
    print(f"[beacon] {APP_STATUS_URL} -> {BEACON_URL} every {POST_PERIOD_S:.0f}s", flush=True)
    while True:
        status = fetch_status()
        if status is not None:
            push(status)
        time.sleep(POST_PERIOD_S)


if __name__ == "__main__":
    raise SystemExit(main())
