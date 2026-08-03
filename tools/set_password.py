"""Create or rotate the rig's login, and the beacon's token, in one go.

The UI has one account. Its credential never goes in the repo or in config.yaml
— six sessions commit this checkout and a secret in it would be pushed within
the hour. It lives in ~/.membrane-rig/auth, mode 600, owned by the user the
service runs as.

    ./.venv/bin/python tools/set_password.py                 # create or rotate
    ./.venv/bin/python tools/set_password.py --show-token    # print the beacon token
    ./.venv/bin/python tools/set_password.py --rotate-token  # new token only

The same run also writes BEACON_TOKEN, because provisioning should be one step:
tools/status_beacon.py reads it from this file and sends it as X-Rig-Token so it
can poll /status without a session. Rotating the password does NOT rotate the
token (the beacon would stop reporting until someone restarted it) — ask for
--rotate-token when you mean it.

PBKDF2 comes from hashlib rather than bcrypt/argon2 on purpose: the Pi may sit
on a network with no way out to install wheels, and the rest of this project
takes no dependency it cannot carry itself.
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ui.auth import (AUTH_PATH, ITERATIONS, MIN_LENGTH,  # noqa: E402
                         hash_password, read_auth, write_auth)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Set the rig's login and beacon token.")
    ap.add_argument("--user", default=None, help="account name (default: keep, or 'rig')")
    ap.add_argument("--rotate-token", action="store_true",
                    help="issue a new beacon token (the beacon must be restarted)")
    ap.add_argument("--show-token", action="store_true",
                    help="print the current beacon token and exit")
    args = ap.parse_args(argv)

    existing = read_auth()

    if args.show_token:
        token = existing.get("BEACON_TOKEN")
        if not token:
            print(f"No beacon token in {AUTH_PATH}. Run this tool with no flags first.",
                  file=sys.stderr)
            return 2
        print(token)
        return 0

    if args.rotate_token and existing:
        existing["BEACON_TOKEN"] = secrets.token_hex(32)
        write_auth(existing)
        print(f"New beacon token written to {AUTH_PATH}.")
        print("Restart the beacon so it picks it up:  sudo systemctl restart rig-beacon")
        return 0

    user = args.user or existing.get("USER") or "rig"
    print(f"Setting the password for account '{user}'.")
    print(f"It is stored hashed (PBKDF2-SHA256, {ITERATIONS:,} iterations) in {AUTH_PATH}.\n")
    pw = getpass.getpass("New password: ")
    if len(pw) < MIN_LENGTH:
        print(f"Too short — use at least {MIN_LENGTH} characters. "
              "This is the only thing between the campus network and a pressurised "
              "cell.", file=sys.stderr)
        return 2
    if pw != getpass.getpass("Repeat: "):
        print("They do not match; nothing was written.", file=sys.stderr)
        return 2

    salt = secrets.token_bytes(16)
    fields = {
        "USER": user,
        "PBKDF2_ITER": str(ITERATIONS),
        "PBKDF2_SALT": salt.hex(),
        "PBKDF2_HASH": hash_password(pw, salt),
        # Keep the existing token unless there is none: rotating it here would
        # silently stop the beacon every time someone changed their password.
        "BEACON_TOKEN": existing.get("BEACON_TOKEN") or secrets.token_hex(32),
    }
    write_auth(fields)
    print(f"\nWritten to {AUTH_PATH} (mode 600).")
    if not existing.get("BEACON_TOKEN"):
        print("A beacon token was generated too — see tools/status_beacon.py.")
    print("Restart the rig service so it reloads:  sudo systemctl restart membrane-rig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
