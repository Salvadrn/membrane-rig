"""The rig's credential file: where it lives, how it is hashed, how it is read.

Owned here rather than in the tool that writes it, so the format has one home
and `tools/set_password.py` consumes it instead of defining it.

The credential is NEVER in the repo or in config.yaml. Six sessions commit this
checkout; a secret in it would be pushed within the hour. It lives in
~/.membrane-rig/auth at mode 600, owned by whoever the service runs as.

PBKDF2 from hashlib, not bcrypt/argon2: the Pi can sit on a network with no way
out to install wheels, and nothing else in this project takes a dependency it
cannot carry itself.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

AUTH_PATH = Path(os.environ.get("MEMBRANE_RIG_AUTH",
                                Path.home() / ".membrane-rig" / "auth"))
ITERATIONS = 600_000          # OWASP's floor for PBKDF2-HMAC-SHA256, 2023
MIN_LENGTH = 10


def hash_password(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               iterations).hex()


def read_auth(path: Path = None) -> dict:
    """Parse the KEY=value file. A missing file returns {} — the app reports
    'no account configured' rather than crashing, so a fresh Pi tells you what
    to do instead of locking everyone out with a stack trace."""
    path = Path(path or AUTH_PATH)
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def write_auth(fields: dict, path: Path = None) -> None:
    """Create the file 600 BEFORE the secret lands in it. Writing it
    world-readable and chmod-ing a moment later leaves a window in which anyone
    on the box can read the hash."""
    path = Path(path or AUTH_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("# membrane-rig credentials — never commit this file\n")
        for k, v in fields.items():
            fh.write(f"{k}={v}\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
