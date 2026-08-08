"""Local web UI (FastAPI). Single self-contained page, no external assets.

Why a web UI (vs a CLI menu): the Pi runs headless in the lab, you reach it
through the Cloudflare tunnel from wherever you are, and a live pressure chart
lets you *watch* the loop settle into the tolerance band before collection
triggers. A thin CLI (src/ui/cli.py) covers SSH/tuning.

Run:  python run.py web --config config.yaml   (default http://127.0.0.1:8000)

THIS APP HAS A LOGIN, AND IT IS NOT THE WHOLE STORY.
One account, a cookie session, and every path behind it — stopping included, by
Adrián's decision of 2026-07-31. Provision it with tools/set_password.py; the
hash lives in ~/.membrane-rig/auth, never in this repo.

What it does not cover, so nobody assumes otherwise: over the lab LAN this is
plain HTTP, so the password and the session cookie cross the wire in the clear.
That is why the default bind is 127.0.0.1 and the tunnel is the intended path —
Cloudflare terminates TLS there — with Cloudflare Access in front of it as a
second gate that this app never sees. `--host 0.0.0.0` still exists, now as a
deliberate opt-in that warns at startup. See docs/REMOTE_ACCESS.md.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import secrets
import socket
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
import uvicorn

from ..app import RigController
from ..config import Config
from .auth import AUTH_PATH, hash_password, read_auth

# runs are named run_YYYYMMDD_HHMMSS — validate against this to block traversal
RUN_RE = re.compile(r"^run_\d{8}_\d{6}$")


def _list_runs(runs_dir: Path) -> list:
    """Scan runs/ and summarise every past run (newest first)."""
    out = []
    for meta_p in sorted(runs_dir.glob("run_*_meta.json"), reverse=True):
        name = meta_p.name[: -len("_meta.json")]
        try:
            m = json.loads(meta_p.read_text())
        except Exception:
            m = {}
        ana_p = runs_dir / f"{name}_analysis.json"
        ana = {}
        if ana_p.exists():
            try:
                ana = json.loads(ana_p.read_text())
            except Exception:
                ana = {}
        results = m.get("results", [])
        pore_um = ana.get("pore_size_um")
        if pore_um is None and ana.get("pore_size_m") is not None:
            pore_um = ana["pore_size_m"] * 1e6
        out.append({
            "name": name,
            "started": m.get("started"),
            "mode": m.get("mode"),
            "status": m.get("status"),
            "label": ana.get("label") or "",
            "setpoints": [r.get("setpoint_kpa") for r in results],
            "n_points": ana.get("n"),
            "k_darcy_m2": ana.get("k_darcy_m2"),
            "pore_size_um": pore_um,
            "r2": ana.get("r2"),
            "has_plot": (runs_dir / f"{name}_plot.png").exists(),
            "has_xlsx": (runs_dir / f"{name}_results.xlsx").exists(),
            "has_csv": (runs_dir / f"{name}.csv").exists(),
        })
    return out


class StartRequest(BaseModel):
    setpoints: List[float]
    tolerance_pct: Optional[float] = None
    dwell_s: Optional[float] = None
    collection_s: Optional[float] = None
    stabilize_timeout_s: Optional[float] = None
    kp: Optional[float] = None
    ki: Optional[float] = None
    kd: Optional[float] = None


class AnalyzeRequest(BaseModel):
    # Measured permeate keyed by point index (hardware mode). Grams preferred —
    # see VolumesRequest for why the mass is the datum and the volume is derived.
    volumes_g: Optional[Dict[int, float]] = None
    volumes_ml: Optional[Dict[int, float]] = None


class ExperimentRequest(BaseModel):
    """One queued experiment. `setpoints` is usually a single pressure."""
    label: Optional[str] = ""
    setpoints: List[float]
    collection_s: Optional[float] = None
    dwell_s: Optional[float] = None
    tolerance_pct: Optional[float] = None
    stabilize_timeout_s: Optional[float] = None


class ExperimentEdit(BaseModel):
    id: str
    label: Optional[str] = None
    setpoints: Optional[List[float]] = None
    collection_s: Optional[float] = None
    dwell_s: Optional[float] = None
    tolerance_pct: Optional[float] = None
    stabilize_timeout_s: Optional[float] = None


class IdRequest(BaseModel):
    id: str


class MoveRequest(BaseModel):
    id: str
    delta: int


class VolumesRequest(BaseModel):
    """Measured permeate for a queued item, keyed by point index.

    Grams are what the operator now reads off the balance, and the controller
    keeps them as the primary datum — the millilitres are derived from them at a
    single point, with the density and temperature used recorded alongside. Send
    `volumes_g`. `volumes_ml` stays for anything still posting volumes directly.
    """
    id: str
    volumes_g: Optional[Dict[int, float]] = None
    volumes_ml: Optional[Dict[int, float]] = None


class LimitRequest(BaseModel):
    limit: Optional[float] = None


class RaiseRequest(BaseModel):
    """New run ceiling, in display units (the controller converts)."""
    ceiling: float


class LoginRequest(BaseModel):
    password: str


# --- authentication ----------------------------------------------------------
# One account, a cookie session, and EVERY rig path behind it — stopping too.
#
# THE POLICY, AND ITS HISTORY, BECAUSE THE HISTORY IS WHY IT LOOKS ODD:
# The control, hardware and interface sessions jointly recommended exempting
# POST /stop. Stopping only ever moves the rig towards safe; Control verified by
# attack that there is no phase from which stopping leaves it worse; and
# Hardware pointed out that with no relief valve fitted, a servo that neither
# seals NOR holds its angle when it loses power (measured on the bench
# 2026-08-06 — released, it drifts off the commanded angle), and the ball
# valve's handle removed, /stop is one of only
# two things that can stop pressurisation — the other being a person at the
# panel. The recommendation was unanimous and the exemption was verified
# harmless.
#
# Adrián was given that recommendation, and then Hardware's physical argument on
# top of it, and chose the strict policy anyway on 2026-07-31: everything needs
# an account, stopping included. That is deliberate, not a default nobody picked.
# DO NOT "restore" the exemption because this comment makes it sound reasonable —
# reopening it is a conversation with Adrián, not a commit.
#
# What the decision costs, so it is not rediscovered as a surprise: an operator
# whose session has lapsed cannot stop from this page until they sign in. The
# mitigations are load-bearing, not polish — the in-page sign-in overlay that
# keeps you where you were, long sessions renewed on use, a rate limit that
# delays but never locks out, and a banner naming the physical fallback (close
# the panel valve by hand).
#
# /auth is open on purpose: it is how the page tells "signed out" apart from
# "rig unreachable", and it reveals nothing about the rig — only whether an
# account exists and whether this browser holds a session.
OPEN_PATHS = {"/login", "/logout", "/auth"}

SESSION_COOKIE = "rig_session"
# A week, renewed on every authenticated request. Long on purpose: with stopping
# behind the login, a session that lapses mid-run is not an inconvenience, it is
# the operator locked out of the stop button. Short expiry would buy nothing
# here — the asset behind this login is a valve, not a bank account, and the
# realistic threat is someone wandering onto the lab network, not a stolen
# laptop being replayed days later.
SESSION_MAX_AGE = 7 * 24 * 3600
BEACON_HEADER = "x-rig-token"


class Sessions:
    """In-memory sessions. Deliberately not signed cookies: a dict of random
    tokens has no crypto to get wrong, and losing sessions on restart is a
    cheap price. Single uvicorn process, so there is nothing to share.

    The rate limit is GLOBAL, not per-IP, and that is not laziness. Cloudflared
    runs ON the Pi and connects to localhost, so every remote user arrives from
    127.0.0.1 — a per-IP counter would lump them into one bucket anyway while
    looking like it distinguished them. There is one account, so one bucket is
    the honest model. Do not "improve" this into a per-IP limiter.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, float] = {}
        self._fails = 0
        self._blocked_until = 0.0

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.time() + SESSION_MAX_AGE
        self._fails = 0
        return token

    def valid(self, token: Optional[str]) -> bool:
        if not token:
            return False
        expiry = self._tokens.get(token)
        if expiry is None:
            return False
        if expiry < time.time():
            self._tokens.pop(token, None)
            return False
        self._tokens[token] = time.time() + SESSION_MAX_AGE   # renew on use
        return True

    def drop(self, token: Optional[str]) -> None:
        if token:
            self._tokens.pop(token, None)

    def throttle_left(self) -> float:
        return max(0.0, self._blocked_until - time.time())

    def record_failure(self) -> None:
        self._fails += 1
        # Escalating delay, HARD-CAPPED at a minute, and never a durable
        # lockout. With stopping behind the login, a long block is not a
        # security feature — it is the operator held away from the stop button
        # while the rig holds pressure, which is a safety failure mode wearing a
        # security costume. Guessing a password at one attempt per minute is
        # hopeless anyway; that is where the protection comes from, not from
        # locking anyone out for hours.
        if self._fails >= 3:
            self._blocked_until = time.time() + min(60.0, 2.0 ** (self._fails - 2))


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Membrane Rig")
    ctl = RigController(cfg)
    runs_dir = Path(cfg.logging.dir)

    sessions = Sessions()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        ctl.shutdown()

    def _authed(request: Request) -> bool:
        creds = read_auth()
        if not creds.get("PBKDF2_HASH"):
            # No account provisioned yet. Refusing everything would brick a
            # fresh Pi; the page says loudly that the rig is unprotected and
            # names the tool that fixes it.
            return True
        if sessions.valid(request.cookies.get(SESSION_COOKIE)):
            return True
        # The beacon polls /status from the Pi itself and has no session. It
        # carries a token from the same 600 file instead. NOT an exemption by
        # source address: cloudflared connects from localhost, so trusting
        # 127.0.0.1 would exempt every remote user through the tunnel — the
        # exact population this login exists for.
        token = creds.get("BEACON_TOKEN")
        supplied = request.headers.get(BEACON_HEADER)
        if (request.url.path == "/status" and token and supplied
                and hmac.compare_digest(token, supplied)):
            return True
        return False

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        path = request.url.path
        if path in OPEN_PATHS or _authed(request):
            return await call_next(request)
        if path == "/":
            return HTMLResponse(LOGIN_PAGE)
        return JSONResponse({"ok": False, "error": "not signed in",
                             "auth_required": True}, status_code=401)

    @app.post("/login")
    def login(req: LoginRequest, request: Request) -> JSONResponse:
        creds = read_auth()
        if not creds.get("PBKDF2_HASH"):
            return JSONResponse({"ok": False, "error":
                                 "No account is set on this rig yet. On the Pi, run "
                                 "tools/set_password.py."}, status_code=400)
        wait = sessions.throttle_left()
        if wait > 0:
            return JSONResponse({"ok": False, "error":
                                 f"Too many failed attempts. Wait {wait:.0f} s and try again."},
                                status_code=429)
        salt = bytes.fromhex(creds.get("PBKDF2_SALT", ""))
        iters = int(creds.get("PBKDF2_ITER", 600000))
        candidate = hash_password(req.password, salt, iters)
        if not hmac.compare_digest(candidate, creds.get("PBKDF2_HASH", "")):
            sessions.record_failure()
            return JSONResponse({"ok": False, "error": "That password is not right."},
                                status_code=401)
        token = sessions.issue()
        res = JSONResponse({"ok": True})
        # `Secure` only when the connection actually is HTTPS. Setting it
        # unconditionally would break sign-in over the lab LAN, where this is
        # served as plain HTTP — the browser would simply never send the cookie
        # back, and the failure looks like "the password does not work".
        res.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                       secure=request.url.scheme == "https", max_age=SESSION_MAX_AGE,
                       path="/")
        return res

    @app.post("/logout")
    def logout(request: Request) -> JSONResponse:
        sessions.drop(request.cookies.get(SESSION_COOKIE))
        res = JSONResponse({"ok": True})
        res.delete_cookie(SESSION_COOKIE, path="/")
        return res

    @app.get("/auth", response_class=JSONResponse)
    def auth_state(request: Request) -> dict:
        """Lets the page tell 'signed out' apart from 'rig unreachable' — two
        states that must not look alike when the page is the only instrument."""
        creds = read_auth()
        return {"configured": bool(creds.get("PBKDF2_HASH")),
                "signed_in": sessions.valid(request.cookies.get(SESSION_COOKIE))}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/config")
    def get_config() -> dict:
        return {
            "units": cfg.units,
            "mode": cfg.mode,
            "max_pressure": round(cfg.disp(cfg.safety.max_pressure_kpa), 2),
            "pressure_limit": round(cfg.disp(ctl.pressure_limit_kpa()), 2),
            "overshoot_margin": round(cfg.disp(cfg.safety.overshoot_margin_kpa), 2),
            "membrane_label": cfg.membrane.label,
            "setpoints": [round(cfg.disp(x), 2) for x in cfg.test.setpoints_kpa],
            "tolerance_pct": cfg.test.tolerance_pct,
            "dwell_s": cfg.test.dwell_s,
            "collection_s": cfg.test.collection_s,
            "stabilize_timeout_s": cfg.test.stabilize_timeout_s,
            "pid": {"kp": cfg.pid.kp, "ki": cfg.pid.ki, "kd": cfg.pid.kd},
        }

    @app.get("/status")
    def status() -> dict:
        return ctl.get_status()

    @app.post("/start")
    def start(req: StartRequest) -> JSONResponse:
        res = ctl.start_sequence(
            req.setpoints, tolerance_pct=req.tolerance_pct, dwell_s=req.dwell_s,
            collection_s=req.collection_s, stabilize_timeout_s=req.stabilize_timeout_s,
            kp=req.kp, ki=req.ki, kd=req.kd,
        )
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/stop")
    def stop() -> JSONResponse:
        res = ctl.stop()
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    # --- ceiling recovery ----------------------------------------------------
    # The rig holds at the run ceiling with the feed shut and waits for a
    # decision. These three are the only ways out (besides a hard abort, which
    # the rig takes by itself). `recover_stop` — not `/stop` — is what ends a
    # held run: plain stop() ends the run without leaving the held state, which
    # would strand the alarm on screen after the run is over.
    @app.post("/recover/retry")
    def recover_retry() -> JSONResponse:
        res = ctl.recover_retry()
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/recover/raise")
    def recover_raise(req: RaiseRequest) -> JSONResponse:
        res = ctl.recover_raise(req.ceiling)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/recover/stop")
    def recover_stop() -> JSONResponse:
        res = ctl.recover_stop()
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/analyze")
    def analyze(req: AnalyzeRequest) -> dict:
        if req.volumes_g:
            ctl.set_volumes(volumes_g=req.volumes_g)
        elif req.volumes_ml:
            ctl.set_volumes(volumes_ml=req.volumes_ml)
        return ctl.compute_and_save_analysis()

    # The rig parks between points with the feed sealed so the operator can put
    # the beaker on the balance. Nothing auto-resumes: the whole reason it stops
    # is that a person has to do something first, and a timer that gave up on
    # waiting would restart pressurisation while they were still weighing.
    @app.post("/resume")
    def resume() -> JSONResponse:
        res = ctl.resume_next_point()
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.get("/plot")
    def plot():
        p = ctl.logger.plot_path()
        if p and p.exists():
            return FileResponse(str(p), media_type="image/png")
        return JSONResponse({"error": "no plot yet"}, status_code=404)

    @app.get("/download")
    def download():
        p = ctl.logger.xlsx_path()
        if p and p.exists():
            return FileResponse(
                str(p), filename=p.name,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return JSONResponse({"error": "no export yet"}, status_code=404)

    # --- playlist ------------------------------------------------------------
    @app.get("/playlist")
    def playlist() -> dict:
        return ctl.playlist_state()

    @app.post("/playlist/add")
    def playlist_add(req: ExperimentRequest) -> JSONResponse:
        res = ctl.add_experiment(
            label=req.label or "", setpoints_display=req.setpoints,
            collection_s=req.collection_s, dwell_s=req.dwell_s,
            tolerance_pct=req.tolerance_pct,
            stabilize_timeout_s=req.stabilize_timeout_s)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/playlist/edit")
    def playlist_edit(req: ExperimentEdit) -> JSONResponse:
        res = ctl.update_experiment(
            req.id, setpoints_display=req.setpoints, label=req.label,
            collection_s=req.collection_s, dwell_s=req.dwell_s,
            tolerance_pct=req.tolerance_pct,
            stabilize_timeout_s=req.stabilize_timeout_s)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/playlist/remove")
    def playlist_remove(req: IdRequest) -> JSONResponse:
        # Deleting the item that is running would drop the record the controller
        # is still writing into — the run keeps going with nowhere to land its
        # results. `skip` and `requeue` already refuse this; so does this now.
        # The guard belongs here rather than on the button: the page is not the
        # only caller (curl, a stale second tab), and a rule enforced only in
        # the UI is not enforced.
        item = ctl.playlist.get(req.id)
        if item is not None and item.status == "running":
            return JSONResponse({"ok": False, "error": "cannot delete a running experiment"},
                                status_code=400)
        ok = ctl.playlist.remove(req.id)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 400)

    @app.post("/playlist/move")
    def playlist_move(req: MoveRequest) -> JSONResponse:
        ok = ctl.playlist.move(req.id, req.delta)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 400)

    @app.post("/playlist/play")
    def playlist_play() -> JSONResponse:
        res = ctl.play_next()
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/playlist/skip")
    def playlist_skip(req: IdRequest) -> JSONResponse:
        item = ctl.playlist.get(req.id)
        if item is None or item.status == "running":
            return JSONResponse({"ok": False, "error": "cannot skip that item"},
                                status_code=400)
        ctl.playlist.update(req.id, status="skipped")
        return JSONResponse({"ok": True})

    @app.post("/playlist/requeue")
    def playlist_requeue(req: IdRequest) -> JSONResponse:
        item = ctl.playlist.get(req.id)
        if item is None or item.status == "running":
            return JSONResponse({"ok": False, "error": "cannot re-queue that item"},
                                status_code=400)
        ctl.playlist.update(req.id, status="pending", note="", results=[])
        return JSONResponse({"ok": True})

    @app.post("/playlist/volumes")
    def playlist_volumes(req: VolumesRequest) -> JSONResponse:
        if req.volumes_g is None and req.volumes_ml is None:
            return JSONResponse({"ok": False, "error": "send volumes_g (or volumes_ml)"},
                                status_code=400)
        res = ctl.set_item_volumes(req.id, volumes_ml=req.volumes_ml,
                                   volumes_g=req.volumes_g)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.post("/playlist/analyze")
    def playlist_analyze() -> dict:
        return ctl.analyze_playlist()

    @app.post("/playlist/reset")
    def playlist_reset() -> dict:
        ctl.playlist.reset()
        return {"ok": True}

    @app.post("/playlist/clear")
    def playlist_clear() -> dict:
        ctl.playlist.clear()
        return {"ok": True}

    @app.post("/limit")
    def set_limit(req: LimitRequest) -> JSONResponse:
        res = ctl.set_membrane_limit(req.limit)
        return JSONResponse(res, status_code=200 if res.get("ok") else 400)

    @app.get("/playlist/file/{kind}")
    def playlist_file(kind: str):
        XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        files = {
            "plot": ("playlist_latest_plot.png", "image/png", False),
            "xlsx": ("playlist_latest_results.xlsx", XLSX, True),
            "analysis": ("playlist_latest_analysis.json", "application/json", False),
        }
        if kind not in files:
            return JSONResponse({"error": "bad kind"}, status_code=400)
        fn, mt, attach = files[kind]
        p = runs_dir / fn
        if not p.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(p), media_type=mt, filename=fn if attach else None)

    @app.get("/runs")
    def runs() -> dict:
        return {"runs": _list_runs(runs_dir)}

    @app.get("/runs/{name}/{kind}")
    def run_file(name: str, kind: str):
        if not RUN_RE.match(name):
            return JSONResponse({"error": "bad run name"}, status_code=400)
        XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        files = {
            "plot": (f"{name}_plot.png", "image/png", False),
            "xlsx": (f"{name}_results.xlsx", XLSX, True),
            "csv": (f"{name}.csv", "text/csv", True),
            "meta": (f"{name}_meta.json", "application/json", False),
            "analysis": (f"{name}_analysis.json", "application/json", False),
        }
        if kind not in files:
            return JSONResponse({"error": "bad kind"}, status_code=400)
        fn, mt, attach = files[kind]
        p = runs_dir / fn
        if not p.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(p), media_type=mt, filename=fn if attach else None)

    return app


def _local_addresses() -> List[str]:
    """Every IPv4 address this machine answers on, best effort.

    Plugging in an Ethernet cable gives the Pi a NEW address on a DIFFERENT
    interface, and the one thing the operator needs at that moment is the URL to
    type. Asking them to SSH in and read `ip addr` defeats the point, so the
    server says it itself.

    Deliberately dependency-free and wrapped in blanket excepts: this is a
    convenience banner, and a banner must never be the reason the rig fails to
    start.
    """
    found: List[str] = []

    def add(ip: str) -> None:
        if ip and not ip.startswith("127.") and ip not in found:
            found.append(ip)

    # Linux (the Pi): walk the real interfaces. Catches eth0 and wlan0 at once,
    # including an Ethernet link that came up after wifi.
    try:
        import fcntl
        import struct
        SIOCGIFADDR = 0x8915
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _, name in socket.if_nameindex():
                try:
                    packed = struct.pack("256s", name[:15].encode())
                    add(socket.inet_ntoa(fcntl.ioctl(s.fileno(), SIOCGIFADDR, packed)[20:24]))
                except Exception:
                    continue
        finally:
            s.close()
    except Exception:
        pass

    # Fallbacks that also work on macOS: whatever the hostname resolves to, plus
    # the address the kernel would use to reach the outside world.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))      # TEST-NET-1: routed nowhere, never sends
            add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    return found


def _print_banner(host: str, port: int, mode: str) -> None:
    """Say where the rig can actually be opened, not just that it started.

    Written to stderr, and flushed. Under systemd stdout is a pipe, so it is
    block-buffered and a banner printed there sits in the buffer of a process
    that never exits — `journalctl` would show the warnings and not the one line
    the operator actually needs. Learned by running it, not by reading it.
    """
    lines = [f"\n  Membrane rig — mode: {mode}"]
    if host in ("127.0.0.1", "localhost", "::1"):
        lines.append(f"  Open:  http://localhost:{port}")
        lines.append("  This machine only. To reach it from a laptop on the same network,")
        lines.append("  restart with --lan (and read the warning it prints).")
    else:
        lines.append(f"  Open:  http://localhost:{port}          (on the rig itself)")
        try:
            hostname = socket.gethostname().split(".")[0]
            if hostname:
                lines.append(f"         http://{hostname}.local:{port}   (needs mDNS/avahi)")
        except Exception:
            pass
        addrs = _local_addresses()
        lines.extend(f"         http://{ip}:{port}" for ip in addrs)
        if not addrs:
            lines.append("         (no network address found — is the cable in / wifi up?)")
    print("\n".join(lines) + "\n", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Membrane rig web UI")
    ap.add_argument("--config", default="config.yaml")
    # Localhost by default. This used to bind 0.0.0.0, which put a rig that had
    # no login at all on the whole campus network. There is a login now, but it
    # travels in the clear over plain HTTP, so the LAN is still the weak path:
    # reach the rig through the Cloudflare tunnel, which brings TLS. Binding
    # wide is now a deliberate --host 0.0.0.0, not the default nobody chose.
    ap.add_argument("--host", default="127.0.0.1")
    # Plain-language alias for --host 0.0.0.0. A systemd unit reading "--lan"
    # states the intent; one reading "--host 0.0.0.0" states a magic number, and
    # the difference matters when someone is deciding whether to keep it.
    ap.add_argument("--lan", action="store_true",
                    help="serve the local network too, so a laptop on the same "
                         "wire or wifi can open it (prints the URLs)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--hardware", action="store_true")
    args = ap.parse_args(argv)
    if args.lan:
        args.host = "0.0.0.0"
    cfg = Config.load(args.config)
    if args.sim:
        cfg.mode = "sim"
    if args.hardware:
        cfg.mode = "hardware"
    if not read_auth().get("PBKDF2_HASH"):
        print(f"WARNING: no account is set ({AUTH_PATH} has no password), so this "
              f"rig is UNPROTECTED.\n         Run: python tools/set_password.py",
              file=sys.stderr)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: serving on {args.host} exposes the rig to the network. "
              f"The login is sent in the clear\n         over plain HTTP — prefer the "
              f"tunnel (docs/REMOTE_ACCESS.md).", file=sys.stderr)
    app = create_app(cfg)
    _print_banner(args.host, args.port, cfg.mode)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# --- self-contained page (no CDNs; hand-rolled canvas chart) -----------------
LOGIN_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Membrane Rig — sign in</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--ink:#e6edf3;--muted:#8b949e;--acc:#2f81f7;
        --bad:#f85149;--warn:#d29922;--line:#30363d}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       padding:20px;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;
       background:var(--bg);color:var(--ink)}
  .box{width:100%;max-width:380px;background:var(--panel);border:1px solid var(--line);
       border-radius:10px;padding:22px}
  h1{font-size:17px;margin:0 0 4px}
  .sub{font-size:13px;color:var(--muted);margin-bottom:18px}
  label{display:block;font-size:12px;color:var(--muted);margin:14px 0 4px}
  input{width:100%;background:#0d1117;border:1px solid var(--line);color:var(--ink);
        border-radius:7px;padding:10px;min-height:44px;font:inherit}
  :focus-visible{outline:3px solid var(--acc);outline-offset:2px;border-radius:7px}
  button{width:100%;margin-top:16px;padding:12px;min-height:44px;border:0;border-radius:8px;
         font:inherit;font-weight:600;cursor:pointer;color:#fff;background:var(--acc)}
  button:disabled{opacity:.45;cursor:not-allowed}
  .err{color:var(--bad);font-size:13px;margin-top:12px;min-height:18px}
  .note{font-size:12px;color:var(--muted);margin-top:16px;padding-top:14px;
        border-top:1px solid var(--line)}
  .note b{color:var(--ink)}
</style></head>
<body>
<form class="box" id="f">
  <h1>Membrane Permeability Rig</h1>
  <div class="sub">Sign in to run the rig.</div>
  <label for="pw">Password</label>
  <input id="pw" type="password" autocomplete="current-password" autofocus/>
  <button id="go" type="submit">Sign in</button>
  <div class="err" id="err" role="alert"></div>
  <div class="note"><b>Stopping the rig needs an account too.</b> If the rig is running,
    something looks wrong, and you cannot sign in — go to the lab and close the panel
    valve by hand. That is the only way to stop pressurisation without this page.
    Forgotten the password? On the Pi, run <b>tools/set_password.py</b> to set a new one.</div>
</form>
<script>
const $=id=>document.getElementById(id);
$("f").onsubmit=async(e)=>{
  e.preventDefault();
  const btn=$("go"), pw=$("pw").value;
  if(!pw){ $("err").textContent="Enter the password."; return; }
  btn.disabled=true; btn.textContent="Signing in…"; $("err").textContent="";
  try{
    const r=await fetch("/login",{method:"POST",headers:{"Content-Type":"application/json"},
                                 body:JSON.stringify({password:pw})});
    const j=await r.json().catch(()=>({}));
    if(r.ok && j.ok){ location.reload(); return; }
    $("err").textContent=j.error||"Could not sign in.";
  }catch(e){
    $("err").textContent="Could not reach the rig. Check that it is powered and on the network.";
  }
  btn.disabled=false; btn.textContent="Sign in";
};
</script>
</body></html>"""


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Membrane Rig</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--ink:#e6edf3;--muted:#8b949e;--acc:#2f81f7;
        --ok:#3fb950;--warn:#d29922;--bad:#f85149;--line:#30363d}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
  header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
  header h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.2px}
  header .mode{font-size:12px;color:var(--muted)}
  .wrap{display:grid;grid-template-columns:340px 1fr;gap:18px;padding:18px;max-width:1200px}
  @media(max-width:820px){.wrap{grid-template-columns:1fr}}
  /* Grid items default to min-width:auto, so the widest table (the 9-column
     queue) sets the min-content width of the whole column and every card
     inherits it — that is what made the page 590px wide on a 375px phone.
     min-width:0 lets the column shrink; the tables scroll inside .tscroll. */
  .wrap>.card{min-width:0}
  .tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 12px}
  label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}
  input{width:100%;background:#0d1117;border:1px solid var(--line);color:var(--ink);
        border-radius:7px;padding:10px;min-height:44px;font:inherit}
  /* Focus must be obvious without a mouse. The UA ring is not dependable here:
     every control paints its own dark background, so define it. */
  :focus-visible{outline:3px solid var(--acc);outline-offset:2px;border-radius:7px}
  /* Available to a screen reader, invisible on screen. */
  .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
      clip:rect(0 0 0 0);white-space:nowrap;border:0}
  .hint{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;
        border-radius:50%;border:1px solid var(--muted);color:var(--muted);
        font-size:11px;font-weight:700;cursor:help;vertical-align:middle}
  .hint:hover,.hint:focus{color:var(--ink);border-color:var(--ink)}
  input.over{border-color:var(--bad);background:#2a1315}
  .row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  button{width:100%;margin-top:14px;padding:12px;min-height:44px;border:0;border-radius:8px;
         font:inherit;font-weight:600;cursor:pointer;color:#fff;background:var(--acc)}
  button.stop{background:var(--bad)}
  button.ghost{background:#21262d;color:var(--ink);border:1px solid var(--line)}
  button:disabled{opacity:.45;cursor:not-allowed}
  button.play{background:var(--ok);font-size:15px;padding:13px}
  .big{display:flex;gap:22px;align-items:flex-end;margin-bottom:6px}
  .big .v{font-size:40px;font-weight:700;line-height:1}
  .big .sp{font-size:15px;color:var(--muted)}
  .pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
  .st-idle,.st-pending{background:#21262d;color:var(--muted)}
  .st-stabilizing{background:#3a2d00;color:var(--warn)}
  .st-collecting,.st-running{background:#0d2818;color:var(--ok)}
  .st-done{background:#0d1e33;color:var(--acc)}
  .st-fault,.st-failed{background:#3a0d0d;color:var(--bad)}
  .st-skipped{background:#21262d;color:var(--muted);text-decoration:line-through}
  .meta{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin:10px 0}
  .meta b{color:var(--ink);font-weight:600}
  /* Provenance, never colour alone: each state carries its own words too. */
  .prov{font-size:12px}
  .prov.ok{color:var(--ok)}
  .prov.warn{color:var(--warn)}
  .prov.bad{color:var(--bad);font-weight:600}
  canvas{width:100%;height:280px;display:block;margin-top:8px}
  /* The chart's two lines were told apart only by colour and dash pattern, with
     nothing on the page saying which was which. */
  .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:2px}
  .legend span{display:flex;align-items:center;gap:6px}
  .legend .ln{display:inline-block;width:22px;height:0;border-top-width:3px}
  .legend .meas{border-top-style:solid;border-top-color:var(--acc)}
  .legend .targ{border-top-style:dashed;border-top-color:#8b949e}
  .legend .ceil{border-top-style:dotted;border-top-color:var(--bad)}
  .legend .sw{display:inline-block;width:22px;height:11px;border-radius:3px}
  .legend .band{background:rgba(63,185,80,.22);border:1px solid rgba(63,185,80,.45)}
  .chartwrap{position:relative}
  .charttip{position:absolute;top:4px;pointer-events:none;background:#0d1117;
            border:1px solid var(--line);border-radius:7px;padding:5px 9px;font-size:12px;
            color:var(--ink);white-space:nowrap;box-shadow:0 2px 10px rgba(0,0,0,.5)}
  .charttip[hidden]{display:none}
  .charttip .tt{color:var(--muted);margin-left:8px}
  table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
  th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  /* Download links sat at 15px tall — fine with a mouse, a poke in the dark on a
     phone. Padded into a real target without changing how they read. */
  td a{color:var(--acc);text-decoration:none;display:inline-block;
       padding:12px 10px 12px 0;min-height:44px}
  td a:hover{text-decoration:underline}
  .hbtn{width:auto;margin:0;padding:10px 14px;min-height:44px;font-size:12px}
  /* Row actions were 25x27 px, which is a coin-flip on a phone — and delete sat
     flush against the arrows, so a near-miss destroyed a queued experiment.
     44 px targets, and delete is pushed away from the movement controls. */
  .xbtn{width:auto;margin:0;padding:8px 12px;min-width:44px;min-height:44px;font-size:13px;
        background:#21262d;color:var(--muted);border:1px solid var(--line);margin-left:6px}
  .xbtn:hover{color:var(--ink)}
  .xbtn.del{margin-left:18px;border-color:#5a2326;color:#f0a0a0}
  .xbtn.del:hover{background:#3a0d0d;color:#fff}
  .xbtn.confirming{background:var(--bad);color:#fff;border-color:var(--bad)}
  .acts-cell{text-align:right;white-space:nowrap}
  .fault{background:#3a0d0d;border:1px solid var(--bad);color:#ffb3ad;padding:8px 12px;
         border-radius:8px;margin-bottom:12px;display:none}
  .warnbox{background:#3a2d00;border:1px solid var(--warn);color:#f0d48a;padding:8px 12px;
           border-radius:8px;margin-bottom:12px;display:none}
  .bandnote{font-size:12px;color:var(--muted);margin-top:4px}
  .limitbox{background:#12191f;border:1px solid var(--line);border-left:3px solid var(--warn);
            border-radius:7px;padding:10px 12px;font-size:12px;color:var(--muted);margin-bottom:6px}
  .limitbox b{color:var(--ink)}
  .gate{background:#0d1e33;border:1px solid var(--acc);border-radius:9px;padding:14px;margin-bottom:14px;display:none}
  .gate h3{margin:0 0 6px;font-size:14px}
  .editbar{display:flex;gap:10px;align-items:center;justify-content:space-between;
           flex-wrap:wrap;margin-top:16px;padding:9px 12px;border-radius:8px;
           background:#0d1e33;border:1px solid var(--acc);font-size:12px;color:var(--muted)}
  .editbar[hidden]{display:none}
  .editbar b{color:var(--ink)}
  /* The row being edited, so nobody loses track of which one the form is for. */
  .queue tr.editing{outline:2px solid var(--acc);outline-offset:-2px}
  .raisedtag{display:inline-block;padding:2px 7px;border-radius:999px;font-size:11px;
             font-weight:600;background:#3a2d00;color:var(--warn);border:1px solid var(--warn)}
  .queue td{vertical-align:middle}
  /* On a phone the 9-column queue scrolled sideways with the row actions parked
     off-screen and every name broken to one word per line. Below 700px each row
     becomes a stacked card instead: the name reads on one line and the buttons
     are where you can see them. Each cell carries its column name via data-th. */
  @media(max-width:700px){
    .queue thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
    .queue,.queue tbody,.queue tr,.queue td{display:block;width:100%}
    .queue tr{border:1px solid var(--line);border-radius:9px;padding:10px 12px;
              margin-bottom:10px;background:var(--panel)}
    .queue tr.next{border-color:var(--acc)}
    .queue tr.next td{background:transparent}
    .queue td{border:0;padding:3px 0;text-align:left;white-space:normal}
    .queue td::before{content:attr(data-th) " ";color:var(--muted);font-size:12px}
    .queue td.nm{font-size:16px;font-weight:600;padding-bottom:6px}
    .queue td.nm::before{content:""}
    .queue td.acts-cell{text-align:left;white-space:normal;padding-top:10px}
    .queue td.acts-cell::before{content:""}
    .xbtn{margin-left:0;margin-right:8px;margin-top:6px}
    .xbtn.del{margin-left:0;float:right}
  }
  .queue tr.next td{background:#131c26}
  details summary{cursor:pointer;color:var(--muted);font-size:12px;margin-top:14px;
                  padding:8px 0;min-height:32px}
  .glossary dl{margin:6px 0 0;font-size:12px;color:var(--muted)}
  .glossary dt{color:var(--ink);font-weight:600;margin-top:9px}
  .glossary dd{margin:2px 0 0}
  .err{color:var(--bad);font-size:12px;margin-top:6px;min-height:16px}

  /* --- safety bar -----------------------------------------------------------
     Sticky, so the live pressure and the stop control are reachable without
     scrolling and without pinch-zoom. This is the remote operator's only way to
     shut the feed: the page is their sole instrument when they cannot see the
     vessel. Never let this scroll away, and never let it shrink below a
     thumb-sized tap target. */
  .safetybar{position:sticky;top:0;z-index:50;background:var(--panel);
             border-bottom:1px solid var(--line);padding:8px 14px;
             display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  .safetybar .now{display:flex;gap:8px;align-items:baseline;min-width:0}
  .safetybar .nowv{font-size:26px;font-weight:700;line-height:1;white-space:nowrap}
  .safetybar .nowu{font-size:13px;color:var(--muted)}
  .safetybar .spacer{flex:1 1 auto}
  .estop{width:auto;margin:0;padding:12px 20px;min-height:44px;font-size:15px;
         background:var(--bad);flex:0 0 auto}
  .estop:disabled{opacity:.4}
  .barnote{flex-basis:100%;font-size:11px;color:var(--muted);margin:0}
  /* Stale = the numbers on screen are no longer known to be true. Dim everything
     that is a live reading so a frozen page can never be read as a live one. */
  body.stale .safetybar .now,body.stale .big,body.stale canvas{opacity:.35}
  .stalebar{display:none;background:#3a2d00;border:1px solid var(--warn);color:#f0d48a;
            border-radius:7px;padding:6px 10px;font-size:12px;flex-basis:100%}
  body.stale .stalebar{display:block}

  /* --- held-at-ceiling alarm ------------------------------------------------ */
  .authwrap{position:fixed;inset:0;z-index:200;display:flex;align-items:center;
            justify-content:center;padding:18px;background:rgba(8,10,14,.82)}
  .authwrap[hidden]{display:none}
  .authbox{width:100%;max-width:360px;background:var(--panel);border:1px solid var(--acc);
           border-radius:10px;padding:20px}
  .authbox h3{margin:0 0 4px;font-size:16px}
  .authsub{font-size:13px;color:var(--muted);margin-bottom:6px}
  .authnote{font-size:12px;color:var(--muted);margin-top:14px;padding-top:12px;
            border-top:1px solid var(--line)}
  .authnote b{color:var(--warn)}
  .nextstep{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin:14px 18px 0;
            padding:11px 14px;border-radius:9px;background:#12191f;
            border:1px solid var(--line);border-left:3px solid var(--acc);font-size:14px}
  .nextstep[hidden]{display:none}
  .ns-k{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
        color:var(--acc);flex:0 0 auto}
  .nextstep b{color:var(--ink)}
  .held{display:none;border-radius:10px;padding:14px;margin:14px 18px 0;
        border:1px solid var(--warn);background:#2a2000}
  .held.runaway{border-color:var(--bad);background:#2f1113}
  .held h3{margin:0 0 8px;font-size:15px;color:var(--ink)}
  .held .rec{font-size:15px;line-height:1.45;color:var(--ink);margin-bottom:10px}
  .held .facts{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);
               margin-bottom:12px}
  .held .facts b{color:var(--ink)}
  .held .acts{display:flex;gap:10px;flex-wrap:wrap}
  .held .acts button{width:auto;margin:0;min-height:44px;padding:11px 18px;flex:0 0 auto}
  .held .why{font-size:12px;color:var(--muted);margin-top:8px}
  .raisewrap{display:flex;gap:8px;align-items:center;flex:0 0 auto}
  .raisewrap input{width:110px}
</style></head>
<body>
<header><h1>Membrane Permeability Rig</h1><span class="mode" id="mode"></span></header>

<div class="safetybar" role="region" aria-label="Rig status and stop control">
  <div class="now">
    <span class="nowv" id="barPv">–</span><span class="nowu u"></span>
  </div>
  <span class="pill st-idle" id="barPhase">idle</span>
  <span id="barLive" class="sr" aria-live="polite"></span>
  <span class="spacer"></span>
  <button class="estop" id="stopBtn">■ Stop &amp; shut feed</button>
  <div class="barnote" id="barNote">Stop shuts the feed valve and routes permeate to waste.
    It does not vent the cell — and the panel valve still has to be closed by hand.</div>
  <div class="stalebar" id="staleBar" role="alert">⚠ No answer from the rig — the readings below are the
    last ones received and may be out of date.</div>
</div>

<!-- Signing back in happens HERE, over the page, never by navigating away.
     Stopping needs a session, so the distance between a lapsed session and the
     stop button is a safety number, not a convenience one: password, Enter, and
     the safety bar is already on screen behind this. Navigating to a login page
     and back would put two page loads in that path. -->
<div class="authwrap" id="authWrap" hidden>
  <form class="authbox" id="authForm">
    <h3 id="authTitle">Signed out</h3>
    <div class="authsub" id="authSub">Sign in again to control the rig.</div>
    <label for="authPw">Password</label>
    <input id="authPw" type="password" autocomplete="current-password"/>
    <button id="authGo" type="submit">Sign in</button>
    <div class="err" id="authErr" role="alert"></div>
    <div class="authnote">Stopping needs an account too. <b>If you cannot sign in and
      the rig needs to be stopped, go to the lab and close the panel valve by hand</b>
      — that is the only way to stop pressurisation without this page.</div>
  </form>
</div>

<!-- One line telling whoever opens this page what to do next. The rig is a cycle
     — set the limit, queue a test, run it, read the cylinder, fit — and a flat
     board of controls gives a newcomer no way to tell which control is the one
     for right now. Derived entirely from state already on screen; it never
     becomes the only place something is said. -->
<div class="nextstep" id="nextStep" hidden>
  <span class="ns-k" id="nsKicker">Next</span>
  <span id="nsText"></span>
</div>

<!-- Directly under the safety bar, not down in the playlist card: when the rig is
     held it is waiting on a decision, and a remote operator must not have to go
     looking for the buttons that make it. Hidden until held. -->
<div class="held" id="heldBox" role="group" aria-labelledby="heldTitle">
  <h3 id="heldTitle">–</h3>
  <div class="rec" id="heldRec"></div>
  <div class="facts" id="heldFacts"></div>
  <div class="acts">
    <button id="hRetry">↻ Retry this point</button>
    <div class="raisewrap">
      <button class="ghost" id="hRaise">▲ Raise ceiling</button>
      <input id="hRaiseVal" type="number" step="1" placeholder="new"
             aria-label="New ceiling pressure"/>
    </div>
    <button class="ghost" id="hStop">■ Stop the run</button>
  </div>
  <div class="why" id="heldWhy"></div>
  <div class="err" id="heldErr"></div>
</div>

<div class="wrap">

  <div class="card">
    <h2>Add experiment</h2>
    <div class="limitbox">
      Pressure limit <b id="limitTxt">–</b> <span class="u"></span>
      · safety cutoff <b id="cutoff">–</b>
      <div style="margin-top:4px">While a run is active the cutoff tightens to
      <b>setpoint + <span id="marginTxt">–</span></b>, so a low-pressure test can never
      drift up to the global limit.</div>
    </div>
    <label for="meshLimit">Specimen limit (<span class="u"></span>) — what this mesh tolerates</label>
    <input id="meshLimit" type="number" step="1" placeholder="e.g. 65"/>
    <button class="ghost" id="saveLimit" style="margin-top:8px">Save limit</button>

    <div class="editbar" id="editBar" hidden>
      <span>Editing <b id="editWhat">–</b> — it keeps its place in the queue.</span>
      <button class="hbtn ghost" id="editCancel">Cancel</button>
    </div>

    <label for="expLabel" style="margin-top:18px">Name</label>
    <input id="expLabel" placeholder="e.g. 60 mesh — point 1"/>
    <label for="expSp">Pressure (<span class="u"></span>) — comma-separated for a multi-point item</label>
    <input id="expSp" placeholder="20"/>
    <div class="row2">
      <div><label for="expCollect">Collection (s)</label>
           <input id="expCollect" type="number" step="1"/></div>
      <div><label for="expDwell">Dwell (s) <span class="hint" tabindex="0"
             title="How long the pressure must sit inside the tolerance band before
collection starts.">?</span></label>
           <input id="expDwell" type="number" step="1"/></div>
    </div>
    <label for="expTol">Tolerance band (± %) <span class="hint" tabindex="0"
      title="How far the pressure may wander from the target and still count as
holding steady.">?</span></label>
    <input id="expTol" type="number" step="0.1"/>
    <button id="addBtn">+ Add to playlist</button>
    <div class="err" id="addErr"></div>

    <details class="glossary">
      <summary>What these words mean</summary>
      <dl>
        <dt>Setpoint / target</dt><dd>The pressure you are asking the rig to hold
          across the specimen for this test.</dd>
        <dt>Tolerance band</dt><dd>How far the pressure may wander from the target and
          still count as holding steady.</dd>
        <dt>Dwell</dt><dd>How long it must hold steady before collection starts, so you
          measure flow at a settled pressure and not during the approach.</dd>
        <dt>Collection</dt><dd>How long permeate is routed to the cylinder. Volume ÷ this
          time is the flow rate.</dd>
        <dt>Diverter</dt><dd>The valve deciding where permeate goes: to <b>waste</b> while
          the pressure settles, to the <b>cylinder</b> once it is being measured.</dd>
        <dt>Ceiling / held</dt><dd>The pressure a run is not allowed to pass. Reaching it
          shuts the feed and parks the rig, waiting for you — that is “held”.</dd>
        <dt>Permeability (k)</dt><dd>What the whole experiment is for: how easily liquid
          passes through this specimen. It comes from the slope of flow against
          pressure across several tests, so one test is never enough.</dd>
        <dt>Water temperature</dt><dd>Not a background reading — it sets the water's
          viscosity, and <b>k is proportional to that</b>. About <b>2.4 % of k per
          °C</b>, so a temperature that was typed rather than measured carries
          straight into the answer. That is why the reading always says where it
          came from.</dd>
      </dl>
    </details>

    <details>
      <summary>Single run without the playlist (advanced)</summary>
      <label for="setpoints">Setpoints (comma-separated)</label><input id="setpoints"/>
      <div class="row"><input id="kp" type="number" step="0.1" title="Kp"/>
        <input id="ki" type="number" step="0.1" title="Ki"/><input id="kd" type="number" step="0.01" title="Kd"/></div>
      <div class="bandnote">PID gains Kp / Ki / Kd</div>
      <button class="ghost" id="startBtn">Start single run</button>
    </details>
  </div>

  <div class="card">
    <div class="fault" id="faultBox" role="alert"></div>
    <div class="warnbox" id="closeWarn" role="alert"></div>
    <div class="big">
      <div><div class="v"><span id="pv">–</span><span style="font-size:18px" class="u"></span></div></div>
      <div class="sp">setpoint <b id="spv">–</b> · valve <b id="valve">–</b>% · <span id="phasePill" class="pill st-idle">idle</span></div>
    </div>
    <div class="meta">
      <span id="nowWrap" style="display:none">running <b id="nowLabel">–</b></span>
      <span>point <b id="idx">–</b></span>
      <span>diverter <b id="div">–</b></span>
      <span>in-band <b id="band">–</b></span>
      <span>elapsed <b id="elapsed">–</b>s</span>
      <span id="collectWrap" style="display:none">collect left <b id="cleft">–</b>s</span>
      <span>abort above <b id="ceil">–</b> <span class="u"></span></span>
      <span id="tempWrap">water <b id="wtemp">–</b>°C <span id="wtempSrc"></span></span>
    </div>
    <div class="chartwrap">
      <canvas id="chart" width="900" height="280" role="img"
              aria-label="Live chart of measured pressure against the target over time.
The readings above give the same values as text."></canvas>
      <div class="charttip" id="chartTip" hidden></div>
    </div>
    <div class="legend">
      <span><i class="ln meas"></i>measured pressure</span>
      <span><i class="ln targ"></i>target (setpoint)</span>
      <span><i class="sw band"></i>tolerance band</span>
      <span><i class="ln ceil"></i>ceiling (abort)</span>
    </div>
    <div class="tscroll"><table id="results"><thead><tr>
      <th>Setpoint</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th><th>In-band</th><th>n</th><th></th>
    </tr></thead><tbody></tbody></table></div>
  </div>

  <div class="card" id="playlistCard" style="grid-column:1/-1">
    <h2 style="display:flex;justify-content:space-between;align-items:center">
      <span>Playlist — <span id="plCounts">–</span></span>
      <span><button class="hbtn ghost" id="resetPl">re-queue all</button>
            <button class="hbtn ghost" id="clearPl">clear</button></span>
    </h2>

    <div class="gate" id="gateBox">
      <h3 id="gateTitle">–</h3>
      <div id="gateBody" style="color:var(--muted);font-size:13px"></div>
      <div id="gateVols"></div>
    </div>

    <button class="play" id="playBtn">▶ Play next experiment</button>
    <div class="err" id="playErr"></div>

    <div class="tscroll"><table class="queue" id="queueTable"><thead><tr>
      <th>#</th><th>Name</th><th>Pressure</th><th>Collect</th><th>Status</th>
      <th>Mean</th><th>Volume</th><th>Q (m³/s)</th><th></th>
    </tr></thead><tbody></tbody></table></div>
    <div class="bandnote" id="emptyNote" style="display:none">
      Nothing queued yet — add experiments on the left. Each one runs on its own;
      the rig stops and waits for you between them.</div>
    <button class="ghost" id="analyzePl" style="margin-top:16px">Fit Q vs ΔP across the whole playlist</button>
  </div>

  <div class="card" id="analysisCard" style="grid-column:1/-1;display:none">
    <h2>Permeability — Q vs ΔP (slope method)</h2>
    <div id="volForm"></div>
    <div class="meta" id="anaSummary"></div>
    <div id="downloads" style="margin:6px 0 10px"></div>
    <img id="plotImg" alt="Q vs ΔP plot" style="width:100%;max-width:760px;border-radius:8px;background:#fff;display:none"/>
  </div>

  <div class="card" id="historyCard" style="grid-column:1/-1">
    <h2 style="display:flex;justify-content:space-between;align-items:center">
      <span>Data history — all collected runs</span>
      <button class="hbtn" id="refreshRuns">↻ refresh</button></h2>
    <div class="tscroll"><table id="runsTable"><thead><tr>
      <th>Date</th><th>Membrane</th><th>Setpoints</th><th>n</th>
      <th>k (m²)</th><th>pore (µm)</th><th>R²</th><th>Files</th>
    </tr></thead><tbody></tbody></table></div>
    <img id="histPlot" alt="selected run plot" style="width:100%;max-width:760px;margin-top:12px;border-radius:8px;background:#fff;display:none"/>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
let U="kPa", CUTOFF=0, LIMIT=0, MODE="sim", wasFinished=false, plSig="";

function fmt(x,d=2){return (x==null||x==="")?"–":Number(x).toFixed(d);}
// Operator-typed text (labels, notes) goes into innerHTML in several places. It
// used to be pasted raw on the grounds that only the person at the bench could
// type it — but the playlist is a file that outlives the session, the rig is now
// reachable over the tunnel, and whoever reads the queue is no longer whoever
// filled it in. Escape it.
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function toDisp(vk){return U==="psi"? vk/6.894757293168361 : vk;}
async function post(url,body){
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
                           body:JSON.stringify(body||{})});
  let j={}; try{ j=await r.json(); }catch(e){}
  return {ok:r.ok && j.ok!==false, data:j};
}

// Every button that talks to the rig goes through this. Over the tunnel a round
// trip is long enough that a button which does nothing visible reads as broken,
// and the operator presses it again — which for /playlist/play or a recovery
// verb means asking twice for something that should happen once. Busy state
// disables it, then a tick or a cross says which way it went.
async function act(btn,url,body,okLabel){
  if(btn.dataset.busy) return {ok:false,data:{}};
  const label=btn.textContent;
  btn.dataset.busy="1"; btn.disabled=true; btn.textContent="working…";
  let res;
  try{ res=await post(url,body); }
  catch(e){ res={ok:false,data:{error:"could not reach the rig"}}; }
  btn.textContent=res.ok?("✓ "+(okLabel||label)):("✕ "+label);
  setTimeout(()=>{ btn.textContent=label; btn.disabled=false;
                   delete btn.dataset.busy; }, res.ok?900:1600);
  return res;
}

async function loadConfig(){
  const c=await (await fetch("/config")).json();
  U=c.units; CUTOFF=c.max_pressure; LIMIT=c.pressure_limit; MODE=c.mode;
  document.querySelectorAll(".u").forEach(e=>e.textContent=U);
  $("mode").textContent="mode: "+c.mode+"  ·  limit "+c.pressure_limit+" "+U+"  ·  cutoff "+c.max_pressure+" "+U;
  $("cutoff").textContent=c.max_pressure+" "+U;
  $("limitTxt").textContent=c.pressure_limit;
  $("marginTxt").textContent=c.overshoot_margin+" "+U;
  $("expCollect").value=c.collection_s; $("expDwell").value=c.dwell_s; $("expTol").value=c.tolerance_pct;
  $("expLabel").value=c.membrane_label||"";
  $("setpoints").value=c.setpoints.join(", ");
  $("kp").value=c.pid.kp; $("ki").value=c.pid.ki; $("kd").value=c.pid.kd;
}

// --- pressure guard in the field itself -------------------------------------
// Warn while the operator types, using the bounds the control layer PUBLISHES
// rather than a copy of its policy. The rule used to be hard-coded here as
// "> LIMIT", which quietly missed the other half of check_setpoints(): a
// setpoint of 0 or below was rejected only on submit. Inclusivity comes from
// the payload too, so the edge (exactly the specimen limit is allowed) is not
// something this file has to guess.
//
// This is a preview, never a gate. check_setpoints() stays the authority: if the
// server refuses, its wording is what gets shown, not this one.
let BOUNDS=null;
function boundsCheck(v){
  const u=(BOUNDS&&BOUNDS.units)||U;
  if(!BOUNDS)
    return v<=LIMIT ? null : `${v} ${u} is above the ${LIMIT} ${u} limit for this specimen.`;
  if(BOUNDS.min!=null){
    const bad=BOUNDS.min_inclusive ? v<BOUNDS.min : v<=BOUNDS.min;
    // Phrased without echoing the value: "0 kPa must be above 0 kPa" is true and
    // unreadable.
    if(bad) return `Pressure must be above ${fmt(BOUNDS.min,0)} ${u}.`;
  }
  if(BOUNDS.max!=null){
    const bad=BOUNDS.max_inclusive ? v>BOUNDS.max : v>=BOUNDS.max;
    if(bad) return `${v} ${u} is above the ${fmt(BOUNDS.max,0)} ${u} limit for this specimen.`;
  }
  return null;
}
function checkSp(){
  const vals=$("expSp").value.split(",").map(s=>parseFloat(s.trim())).filter(x=>!isNaN(x));
  let problem=null;
  for(const v of vals){ problem=boundsCheck(v); if(problem) break; }
  $("expSp").classList.toggle("over",!!problem);
  $("expSp").setAttribute("aria-invalid",problem?"true":"false");
  $("addErr").textContent=problem?(problem+" Change it before adding."):"";
  return !problem;
}
$("expSp").oninput=checkSp;

$("saveLimit").onclick=async()=>{
  const v=parseFloat($("meshLimit").value);
  const r=await act($("saveLimit"),"/limit",{limit:isNaN(v)?null:v},"Saved");
  if(r.ok){ LIMIT=r.data.limit; $("limitTxt").textContent=LIMIT; checkSp(); loadPlaylist(true); }
  else alert(r.data.error||"could not set the limit");
};

// --- editing a queued experiment ---------------------------------------------
// POST /playlist/edit existed from the start and nothing ever called it, so
// fixing a typo meant deleting the experiment and re-typing it — which also
// dropped it to the back of the queue.
//
// The form on the left becomes the editor rather than growing a second one in
// the row. Two reasons, and the first is a trap: the poll rebuilds the queue's
// tbody whenever the playlist signature changes, so inputs living inside a row
// get wiped from under whoever is typing. The form is never re-rendered by the
// poll. The second is that this form already carries the live bounds check, so
// an edit is validated exactly like an add instead of needing its own copy.
let EDIT_ID=null;
function setEditing(it){
  EDIT_ID=it?it.id:null;
  $("editBar").hidden=!it;
  $("addBtn").textContent=it?"Save changes":"+ Add to playlist";
  if(it){
    $("editWhat").textContent=it.label||"this experiment";
    $("expLabel").value=it.label||"";
    $("expSp").value=(it.setpoints||[]).join(", ");
    $("expCollect").value=it.collection_s;
    $("expDwell").value=it.dwell_s;
    $("expTol").value=it.tolerance_pct;
    checkSp();
    $("expLabel").scrollIntoView({behavior:"smooth",block:"center"});
    $("expLabel").focus();
  }else{
    $("addErr").textContent="";
    $("expSp").value=""; checkSp();
  }
}
$("editCancel").onclick=()=>setEditing(null);

$("addBtn").onclick=async()=>{
  if(!checkSp()) return;
  const sp=$("expSp").value.split(",").map(s=>parseFloat(s.trim())).filter(x=>!isNaN(x));
  if(!sp.length){ $("addErr").textContent="Enter at least one pressure."; return; }
  const body={
    label:$("expLabel").value, setpoints:sp,
    collection_s:parseFloat($("expCollect").value)||null,
    dwell_s:parseFloat($("expDwell").value)||null,
    tolerance_pct:parseFloat($("expTol").value)||null};
  if(EDIT_ID){
    const r=await post("/playlist/edit",{id:EDIT_ID,...body});
    if(r.ok){ setEditing(null); loadPlaylist(true); }
    else $("addErr").textContent=r.data.error||"could not save the changes";
    return;
  }
  const r=await post("/playlist/add",body);
  if(r.ok){ $("addErr").textContent=""; $("expSp").value=""; loadPlaylist(true); }
  else $("addErr").textContent=r.data.error||"could not add";
};

$("playBtn").onclick=async()=>{
  const r=await act($("playBtn"),"/playlist/play",null,"Started");
  $("playErr").textContent=r.ok?"":(r.data.error||"could not start");
  if(r.ok) loadPlaylist(true);
};
$("resetPl").onclick=async()=>{ await post("/playlist/reset"); loadPlaylist(true); };
$("clearPl").onclick=async()=>{
  if(confirm("Remove every experiment from the playlist?")){ await post("/playlist/clear"); loadPlaylist(true); }
};
$("analyzePl").onclick=async()=>{
  const a=await (await fetch("/playlist/analyze",{method:"POST"})).json();
  showAnalysis(a,true);
};

$("startBtn").onclick=async()=>{
  const r=await post("/start",{
    setpoints:$("setpoints").value.split(",").map(s=>parseFloat(s.trim())).filter(x=>!isNaN(x)),
    tolerance_pct:parseFloat($("expTol").value), dwell_s:parseFloat($("expDwell").value),
    collection_s:parseFloat($("expCollect").value),
    kp:parseFloat($("kp").value), ki:parseFloat($("ki").value), kd:parseFloat($("kd").value)});
  if(!r.ok) alert("Could not start: "+(r.data.error||""));
};
// The stop control in the safety bar. While the rig is held at the ceiling it
// ends the run through /recover/stop, the call meant for that state: it leaves
// the held state deliberately rather than relying on the teardown to do it.
// (Plain /stop also clears it — _end_run calls _exit_held — so this is about
// saying what we mean, not about routing around a bug.)
let HELD=false, SIGNED_OUT=false;

// --- signing back in, in place -----------------------------------------------
// Stopping requires a session, so "how long from a lapsed session to a stopped
// rig" is a safety number, not a convenience one. Everything here exists to keep
// it short: no navigation away, the password focused the moment it opens, and on
// success the page is exactly where it was with the stop button under the thumb.
function showAuth(intent){
  const w=$("authWrap");
  if(!w.hidden) return;
  w.hidden=false;
  $("authTitle").textContent=intent==="stop"?"Sign in to stop the rig":"Signed out";
  $("authSub").textContent=intent==="stop"
    ? "Stopping needs an account. Sign in and the stop button is right behind this."
    : "Sign in again to control the rig.";
  $("authErr").textContent="";
  $("authPw").value="";
  $("authPw").focus();
}
$("authForm").onsubmit=async(e)=>{
  e.preventDefault();
  const btn=$("authGo"), pw=$("authPw").value;
  if(!pw){ $("authErr").textContent="Enter the password."; return; }
  btn.disabled=true; btn.textContent="Signing in…"; $("authErr").textContent="";
  try{
    const r=await fetch("/login",{method:"POST",headers:{"Content-Type":"application/json"},
                                 body:JSON.stringify({password:pw})});
    const j=await r.json().catch(()=>({}));
    if(r.ok && j.ok){
      $("authWrap").hidden=true;
      SIGNED_OUT=false; missed=0; setStale(false);
      $("stopBtn").textContent="■ Stop & shut feed";
      await poll();
      $("stopBtn").focus();     // land on the control that was wanted
      btn.disabled=false; btn.textContent="Sign in";
      return;
    }
    $("authErr").textContent=j.error||"Could not sign in.";
  }catch(err){
    $("authErr").textContent="Could not reach the rig.";
  }
  btn.disabled=false; btn.textContent="Sign in";
};

$("stopBtn").onclick=async()=>{
  // Signed out, this button is honest about what it does: it opens sign-in. A
  // control labelled Stop that cannot stop is worse than one that says so.
  if(SIGNED_OUT){ showAuth("stop"); return; }
  if(!confirm("Stop the run?\n\nThis shuts the feed valve and routes permeate to waste. "+
              "It does NOT vent the cell, and the air valve on the lab panel still has to be "+
              "closed by hand."))
    return;
  const r=await post(HELD?"/recover/stop":"/stop");
  if(!r.ok && r.data && r.data.error) alert("Could not stop: "+r.data.error);
};

// --- held at the ceiling -----------------------------------------------------
// Fail-safe contract with the control layer: `retry_advised` is the ONLY thing
// that decides whether Retry is live — never parse `recommendation`. Anything
// unexpected (no alarm object, a severity we don't know, retry_advised missing)
// is treated as "runaway": Retry off, Stop primary. Absence must degrade to the
// cautious side, because the remote operator cannot see the vessel.
let heldSpoken="";
function renderHeld(s){
  const box=$("heldBox"), a=s.held_alarm;
  if(!s.held){ box.style.display="none"; box.removeAttribute("aria-live"); heldSpoken=""; return; }
  box.style.display="block";
  // Three states, not two. `severity` says what happened and is frozen at the
  // trip; `retry_advised` says whether the button would do anything and is
  // refreshed every tick, so it flips to true on its own as the cell bleeds
  // below the ceiling.
  //   runaway  — the dangerous one, or anything we cannot read. Go and look.
  //   waiting  — an ordinary overshoot whose retry is only blocked for now.
  //              Painting this red would send someone to the lab for something
  //              that clears itself in seconds, and cry wolf against the alarm
  //              that matters.
  //   ready    — ordinary overshoot, retry live.
  // The fail-safe is unchanged: only an explicitly known pair is treated as
  // benign; a severity we do not recognise or a missing flag is still runaway.
  const known=!!a && a.severity==="overshoot";
  const runaway=!known || (a.retry_advised!==true && a.retry_advised!==false);
  const waiting=known && a.retry_advised===false;
  box.className="held"+(runaway?" runaway":"");
  // Announce it, and let the machine flag pick how hard to interrupt: a runaway
  // is worth cutting across whatever the screen reader was saying; a normal
  // overshoot is not. Same flag that drives the button — never the prose.
  box.setAttribute("aria-live",runaway?"assertive":"polite");
  const u=(a&&a.units)||U;
  $("heldTitle").textContent=runaway
    ? "⛔ Held at the ceiling — do not retry"
    : waiting
      ? "⏳ Held at the ceiling — waiting for the pressure to fall"
      : "⏸ Held at the ceiling — waiting for you";
  $("heldRec").textContent=(a&&a.recommendation)||
    "The rig stopped at its ceiling and the feed is shut. No detail came through, "+
    "so treat this as the unsafe case: check the rig before doing anything.";
  $("heldFacts").innerHTML=a?
    // pressure_now is refreshed every tick while held, so the operator can watch
    // the cell bleed down instead of guessing whether anything is happening.
    (a.pressure_now!=null?`<span>now <b>${fmt(a.pressure_now)} ${u}</b></span>`:"")+
    `<span>reached <b>${fmt(a.pressure_reached)} ${u}</b></span>`+
    `<span>ceiling <b>${fmt(a.ceiling)} ${u}</b> (${a.ceiling_source||"–"})</span>`+
    `<span>setpoint <b>${a.setpoint==null?"–":fmt(a.setpoint)+" "+u}</b></span>`+
    `<span>hit <b>${a.retry_n}</b> of max <b>${a.retry_max}</b></span>`+
    `<span>layer <b>${esc(a.layer)||"–"}</b></span>`:"";
  // Retry: driven by the machine flag alone. In the waiting state it re-enables
  // itself on a later tick — nothing for the operator to do but watch.
  const rt=$("hRetry");
  rt.disabled=runaway||waiting;
  rt.className=(runaway||waiting)?"ghost":"";
  // Raise: born disabled — raise_max <= ceiling means config has it switched off.
  const canRaise=!!a && a.raise_max>a.ceiling;
  $("hRaise").disabled=!canRaise;
  $("hRaiseVal").disabled=!canRaise;
  if(canRaise && !$("hRaiseVal").value) $("hRaiseVal").value=a.raise_max;
  let why=[];
  if(runaway) why.push("Retry is disabled: retrying would repeat the excursion.");
  // Say WHY the button is dead and that it will come back by itself. Without
  // this the operator taps a button that looks available, nothing happens, and
  // three taps later the run is gone with "physical problem" — which is exactly
  // the trap the control layer just closed.
  else if(waiting) why.push(a.retry_blocked_reason
    ? "Retry is waiting: "+a.retry_blocked_reason+". It re-enables itself once the "+
      "pressure is below the ceiling — you do not have to do anything."
    : "Retry is not available yet; it re-enables itself once the pressure has "+
      "fallen below the ceiling.");
  if(!canRaise) why.push("Raising the ceiling is switched off in the rig's config "+
                         "(safety.operator_raise_max = 0).");
  else why.push(`You may raise up to ${fmt(a.raise_max)} ${u}. A raised run is tagged and `+
                `left out of the combined fit.`);
  $("heldWhy").textContent=why.join(" ");
}
$("hRetry").onclick=async()=>{
  const r=await act($("hRetry"),"/recover/retry",null,"Retrying");
  $("heldErr").textContent=r.ok?"":(r.data.error||"could not retry");
};
$("hStop").onclick=async()=>{
  if(!confirm("End this run?\n\nThe feed is already shut. The run will be closed out "+
              "and its collected points kept.")) return;
  const r=await post("/recover/stop");
  $("heldErr").textContent=r.ok?"":(r.data.error||"could not stop");
};
$("hRaise").onclick=async()=>{
  const v=parseFloat($("hRaiseVal").value);
  if(isNaN(v)){ $("heldErr").textContent="Enter the new ceiling."; return; }
  if(!confirm(`Raise this run's ceiling to ${v} ${U}?\n\n`+
              "The specimen will see pressure it was not declared to tolerate. "+
              "This run gets tagged and is excluded from the combined fit.")) return;
  const r=await post("/recover/raise",{ceiling:v});
  $("heldErr").textContent=r.ok?"":(r.data.error||"could not raise the ceiling");
};

// --- playlist rendering ------------------------------------------------------
async function loadPlaylist(force){
  let d; try{ d=await (await fetch("/playlist")).json(); }catch(e){ return; }
  const sig=JSON.stringify(d.items.map(i=>[i.id,i.status,i.setpoints,i.collection_s,i.label,
                                            i.ceiling_raised,
                                            (i.results||[]).map(r=>r.volume_ml)]))+d.limit;
  if(!force && sig===plSig) return;
  plSig=sig;
  // `max` follows the specimen limit, which the operator can tighten mid-session,
  // so re-read the bounds on every playlist refresh and re-check what is already
  // typed — a value that was fine a moment ago may not be now.
  if(d.setpoint_bounds){ BOUNDS=d.setpoint_bounds; checkSp(); }
  LIMIT=d.limit; $("limitTxt").textContent=d.limit;
  if(d.membrane_limit!=null && !$("meshLimit").value) $("meshLimit").value=d.membrane_limit;
  const c=d.counts;
  $("plCounts").textContent=`${c.done} done · ${c.pending} pending · ${c.total} total`;
  $("emptyNote").style.display=c.total?"none":"block";
  // Drop out of edit mode by itself if the target stopped being editable — it
  // was deleted, or it started running while the form sat open. Saving then
  // would fail on the server anyway; better to not leave a form claiming to
  // edit something that is gone.
  if(EDIT_ID){
    const t=d.items.find(i=>i.id===EDIT_ID);
    if(!t || t.status!=="pending") setEditing(null);
  }
  const tb=$("queueTable").querySelector("tbody"); tb.innerHTML="";
  d.items.forEach((it,n)=>{
    const r0=(it.results||[])[0]||{};
    const isNext=it.id===d.next_id;
    const tr=document.createElement("tr");
    if(isNext) tr.className="next";
    if(it.id===EDIT_ID) tr.className=(tr.className+" editing").trim();
    const nm=esc(it.label)||"–";
    const acts=
      `<button class="xbtn" data-up="${it.id}" aria-label="Move ${nm} earlier">↑</button>`+
      `<button class="xbtn" data-down="${it.id}" aria-label="Move ${nm} later">↓</button>`+
      // Edit only on a pending item: the server refuses to edit one that is
      // running, and one that has already produced results would silently
      // disagree with the numbers next to it.
      (it.status==="pending"
        ?`<button class="xbtn" data-edit="${it.id}" aria-label="Edit ${nm}">edit</button>`:"")+
      (it.status==="pending"
        ?`<button class="xbtn" data-skip="${it.id}" aria-label="Skip ${nm}">skip</button>`
        :`<button class="xbtn" data-requeue="${it.id}" aria-label="Re-run ${nm}">re-run</button>`)+
      `<button class="xbtn del" data-del="${it.id}" aria-label="Delete ${nm}">✕ delete</button>`;
    tr.innerHTML=
      `<td data-th="#">${isNext?"▶":""} ${n+1}</td>`+
      `<td class="nm" data-th="Name">${nm}</td>`+
      `<td data-th="Pressure">${it.setpoints.join(", ")} ${U}</td>`+
      `<td data-th="Collect">${it.collection_s}s</td>`+
      `<td data-th="Status"><span class="pill st-${it.status}">${it.status}</span>`+
        // A raised-ceiling run is left out of the combined fit, so the queue has
        // to say which rows those are — otherwise the fit silently has fewer
        // points than the table shows and nobody can tell which ones went.
        (it.ceiling_raised?` <span class="raisedtag" title="Ran above the declared `+
          `ceiling — excluded from the combined fit">▲ raised</span>`:"")+
        (it.note?` <span style="color:var(--bad);font-size:11px">${esc(it.note)}</span>`:"")+`</td>`+
      `<td data-th="Mean">${r0.mean_kpa!=null?fmt(toDisp(r0.mean_kpa))+" "+U:"–"}</td>`+
      `<td data-th="Volume">${r0.volume_ml?fmt(r0.volume_ml,0)+" mL":"–"}</td>`+
      `<td data-th="Flow Q">${r0.flow_m3s?Number(r0.flow_m3s).toExponential(3)+" m³/s":"–"}</td>`+
      `<td class="acts-cell" data-th="">${acts}</td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll("[data-up]").forEach(b=>b.onclick=async()=>{await post("/playlist/move",{id:b.dataset.up,delta:-1});loadPlaylist(true);});
  tb.querySelectorAll("[data-down]").forEach(b=>b.onclick=async()=>{await post("/playlist/move",{id:b.dataset.down,delta:1});loadPlaylist(true);});
  // Delete asks twice, in place. Not a native confirm(): on a phone it is ugly
  // and some webviews suppress it outright, which would turn "are you sure?"
  // into a silent deletion. The button becomes its own confirmation, announces
  // itself, and backs out on blur or after a few seconds so it cannot sit armed.
  tb.querySelectorAll("[data-del]").forEach(b=>{
    let armed=false, t=null;
    const disarm=()=>{armed=false; clearTimeout(t); b.classList.remove("confirming");
                      b.textContent="✕ delete"; b.setAttribute("aria-label","Delete "+b.dataset.nm);};
    b.dataset.nm=b.getAttribute("aria-label").replace(/^Delete /,"");
    b.onblur=disarm;
    b.onclick=async()=>{
      if(!armed){
        armed=true; b.classList.add("confirming"); b.textContent="✕ really delete?";
        b.setAttribute("aria-label","Confirm deleting "+b.dataset.nm+". Press again to delete.");
        t=setTimeout(disarm,4000);
        return;
      }
      disarm();
      await post("/playlist/remove",{id:b.dataset.del});
      loadPlaylist(true);
    };
  });
  tb.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>{
    setEditing(d.items.find(i=>i.id===b.dataset.edit));
    loadPlaylist(true);
  });
  tb.querySelectorAll("[data-skip]").forEach(b=>b.onclick=async()=>{await post("/playlist/skip",{id:b.dataset.skip});loadPlaylist(true);});
  tb.querySelectorAll("[data-requeue]").forEach(b=>b.onclick=async()=>{await post("/playlist/requeue",{id:b.dataset.requeue});loadPlaylist(true);});
  renderGate(d);
  renderNextStep(d);
}

// What the operator should do now, picked from the state the page already has.
// Deliberately silent while something is running or held — the safety bar and
// the alarm own the screen then, and a suggestion would be competing noise.
function renderNextStep(d){
  const el=$("nextStep"), txt=$("nsText");
  const running=d.items.some(i=>i.status==="running");
  if(running || HELD){ el.hidden=true; return; }
  const nxt=d.items.find(i=>i.id===d.next_id);
  // Same trap as the gate: name the experiment that actually ran, not the first
  // one in the queue that happens to be missing a volume.
  const ran=lastRunItem(d);
  const needsVol=(ran && ran.needs_volume) ? ran : d.items.find(i=>i.needs_volume);
  const done=d.counts.done;
  let msg="";
  if(!d.membrane_limit)
    msg="<b>Start here:</b> tell the rig what this specimen can take, in "+
        "“Specimen limit”, then save it. Nothing can be queued above that.";
  else if(needsVol)
    msg="<b>Read the cylinder</b> for “"+esc(needsVol.label||"the last test")+"”, type the "+
        "millilitres below, and empty it before the next run.";
  else if(!d.counts.total)
    msg="<b>Add your first test:</b> give it a name and a pressure on the left, "+
        "then “Add to playlist”.";
  else if(nxt)
    msg="<b>Ready to run</b> “"+esc(nxt.label||"the next test")+"” at "+
        nxt.setpoints.join(", ")+" "+U+". Press <b>Play next experiment</b> when the "+
        "cylinder is empty and in place.";
  else if(done>=2)
    msg="<b>All tests are done.</b> Fit Q vs ΔP across the whole playlist to get "+
        "permeability for this specimen.";
  else if(done===1)
    msg="<b>One test is done.</b> Add at least one more pressure — permeability comes "+
        "from the slope through several points, not from one.";
  else
    msg="Nothing left pending. Re-queue a test or add a new one.";
  txt.innerHTML=msg;
  el.hidden=false;
}

// WHICH experiment just ran — not "the last terminal one in queue order", which
// is a different item as soon as anything runs out of order. Re-queue an early
// item and run it again and the queue scan lands on a LATER finished item: the
// gate would then label the cylinder reading with the wrong experiment and post
// the volume onto its results, corrupting k for both. The controller already
// knows the answer and publishes it as status.item_id, which survives the end of
// the run; the queue scan stays only as a fallback for the first paint, before
// the first poll has told us anything.
let CURRENT_ITEM_ID=null;
function lastRunItem(d){
  if(CURRENT_ITEM_ID){
    const it=d.items.find(i=>i.id===CURRENT_ITEM_ID);
    if(it && (it.status==="done"||it.status==="failed")) return it;
    if(it) return null;   // it is running or re-queued: nothing finished to show
  }
  return [...d.items].reverse().find(i=>i.status==="done"||i.status==="failed");
}

// The pause between experiments: read the cylinder, then press play.
function renderGate(d){
  const box=$("gateBox"), running=d.items.find(i=>i.status==="running");
  const nxt=d.items.find(i=>i.id===d.next_id);
  const last=lastRunItem(d);
  if(running){ box.style.display="none"; return; }
  if(!last && !nxt){ box.style.display="none"; return; }
  box.style.display="block";
  let title="", body="", vols="";
  if(last && last.status==="done"){
    title=`✓ “${last.label||"experiment"}” finished`;
    const pts=(last.results||[]).filter(r=>r.success);
    if(MODE==="hardware" && pts.some(r=>!(r.volume_ml>0))){
      // Grams off the balance, not millilitres off a meniscus. The controller
      // keeps the mass as the primary datum and derives the volume from it, so
      // this field must send what was actually read. Both surfaces changed
      // together — a CLI in grams and a page in millilitres would put two units
      // behind one number and nothing downstream would notice.
      body="Weigh what each point collected and enter the GRAMS from the balance, "+
           "then empty the beaker before the next run.";
      vols="<div style='margin-top:8px'>";
      (last.results||[]).forEach((r,i)=>{ if(!r.success) return;
        const id="gm"+i;
        vols+=`<label for="${id}">point ${i+1} — ${fmt(toDisp(r.setpoint_kpa))} ${U}, `+
              `${r.collection_s}s — weight in grams</label>`+
              `<input class="gvol" id="${id}" data-i="${i}" type="number" step="0.01" `+
              `min="0.05" max="3000" placeholder="grams (g)" value="${r.mass_g||""}"/>`;});
      vols+=`<div class="bandnote">Grams, not millilitres. The volume is worked out `+
            `from the weight and the water temperature.</div>`+
            `<button class="ghost" id="saveVols" data-id="${last.id}">Save weights</button>`+
            `<div class="err" id="volErr"></div></div>`;
    } else {
      const v=pts.map(r=>(r.mass_g?fmt(r.mass_g,2)+" g":fmt(r.volume_ml,0)+" mL")).join(", ");
      body=`Collected ${v||"–"}. Empty the beaker before the next run.`;
    }
  } else if(last && last.status==="failed"){
    title=`✗ “${last.label||"experiment"}” did not complete`;
    body=esc(last.note||"")+" — check the rig before continuing.";
  }
  if(nxt){
    body+=`${body?"<br>":""}<b style="color:var(--ink)">Next up:</b> “${esc(nxt.label)||"experiment"}” at `+
          `${nxt.setpoints.join(", ")} ${U} for ${nxt.collection_s}s. Press play when you are ready.`;
  } else {
    body+=`${body?"<br>":""}<b style="color:var(--ink)">Playlist finished</b> — nothing pending. `+
          `The rig has shut its feed valve; <b style="color:var(--ink)">close the panel valve by `+
          `hand</b> before you leave — the servo neither seals nor stays put when it loses `+
          `power: it drifts to an angle nobody has measured, so the feed can be left part open.`;
  }
  $("gateTitle").textContent=title||"Ready";
  $("gateBody").innerHTML=body;
  $("gateVols").innerHTML=vols;
  const sv=$("saveVols");
  if(sv) sv.onclick=async()=>{
    // Same guard as the CLI prompt, for the same reason: with two units in play
    // a number typed in the wrong one is invisible downstream — it only makes k
    // wrong, and R² never notices.
    const v={}; let bad=null;
    document.querySelectorAll(".gvol").forEach(inp=>{
      const x=parseFloat(inp.value);
      if(isNaN(x)) return;
      if(x<0.05||x>3000){ bad=bad||`${x} g is outside 0.05–3000 g. This field is in GRAMS.`; return; }
      v[inp.dataset.i]=x;
    });
    const e=$("volErr"); if(e) e.textContent=bad||"";
    if(bad) return;
    if(!Object.keys(v).length){ if(e) e.textContent="Enter at least one weight."; return; }
    const r=await act(sv,"/playlist/volumes",{id:sv.dataset.id,volumes_g:v},"Saved");
    if(!r.ok && e) e.textContent=(r.data&&r.data.error)||"could not save the weights";
    if(r.ok) loadPlaylist(true);
  };
}

function phaseClass(p){return "pill st-"+(p||"idle");}

// Kept so the tooltip can answer "what was the value here" without re-deriving
// the scales from a second copy of the data.
let CHART={hist:null,sx:null,sy:null,t0:0,pad:0};

function draw(hist, tol, ceiling){
  const cv=$("chart"), ctx=cv.getContext("2d");
  const W=cv.width=cv.clientWidth*devicePixelRatio, H=cv.height=280*devicePixelRatio;
  ctx.clearRect(0,0,W,H); ctx.scale(1,1);
  const pad=38*devicePixelRatio;
  CHART.hist=null;
  if(!hist||hist.length<2){ctx.fillStyle="#8b949e";ctx.font=(13*devicePixelRatio)+"px sans-serif";
    ctx.fillText("waiting for data…",pad,H/2);return;}
  const t0=hist[0][0], t1=hist[hist.length-1][0];
  let pmin=Infinity,pmax=-Infinity;
  for(const h of hist){pmin=Math.min(pmin,h[1],h[2]);pmax=Math.max(pmax,h[1],h[2]);}
  pmin=Math.min(pmin, 0); pmax=Math.max(pmax*1.1, pmax+ (tol||1));
  // The ceiling joins the scale only when it is close enough that showing it
  // costs nothing. A run at 20 with a ceiling clamped to 65 would otherwise
  // squash the trace into the bottom third to display a line nothing is near.
  // When it is off-scale it still gets drawn — pinned to the top edge and
  // labelled with an arrow, so "the limit is above this view" is visible rather
  // than merely absent.
  const ceilOnScale = ceiling!=null && ceiling<=pmax*1.6;
  if(ceilOnScale) pmax=Math.max(pmax,ceiling*1.04);
  const sx=t=>pad+(t-t0)/Math.max(1e-6,(t1-t0))*(W-1.4*pad);
  const sy=p=>H-pad-(p-pmin)/Math.max(1e-6,(pmax-pmin))*(H-1.6*pad);
  CHART={hist:hist,sx:sx,sy:sy,t0:t0,pad:pad};

  // Tolerance band first, under everything: the operator is waiting for the
  // blue line to sit inside this, and that is easier to see as a region than by
  // comparing two numbers in the meta row.
  if(tol>0){
    ctx.fillStyle="rgba(63,185,80,.10)";
    ctx.beginPath();
    hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[2]+tol);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    for(let i=hist.length-1;i>=0;i--){const h=hist[i];ctx.lineTo(sx(h[0]),sy(h[2]-tol));}
    ctx.closePath();ctx.fill();
  }

  ctx.strokeStyle="#30363d";ctx.lineWidth=devicePixelRatio;ctx.beginPath();
  ctx.moveTo(pad,H-pad);ctx.lineTo(W-0.4*pad,H-pad);ctx.moveTo(pad,H-pad);ctx.lineTo(pad,0.6*pad);ctx.stroke();
  ctx.fillStyle="#8b949e";ctx.font=(11*devicePixelRatio)+"px sans-serif";
  for(let i=0;i<=4;i++){const p=pmin+(pmax-pmin)*i/4;const y=sy(p);
    ctx.fillText(p.toFixed(1),4,y+3);ctx.strokeStyle="#1c2128";ctx.beginPath();
    ctx.moveTo(pad,y);ctx.lineTo(W-0.4*pad,y);ctx.stroke();}

  // The ceiling: the pressure this run is not allowed to pass. Drawn so the
  // safety ladder is something the operator SEES rather than reads in a box.
  if(ceiling!=null){
    const y=ceilOnScale?sy(ceiling):0.6*pad;
    ctx.save();
    ctx.setLineDash([3*devicePixelRatio,3*devicePixelRatio]);
    ctx.strokeStyle="#f85149";ctx.lineWidth=1.5*devicePixelRatio;
    ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(W-0.4*pad,y);ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle="#f85149";ctx.font=(11*devicePixelRatio)+"px sans-serif";
    const label=(ceilOnScale?"ceiling ":"ceiling ↑ ")+fmt(ceiling,1)+" "+U;
    ctx.fillText(label, W-0.4*pad-ctx.measureText(label).width, y-4*devicePixelRatio);
    ctx.restore();
  }

  ctx.setLineDash([6*devicePixelRatio,4*devicePixelRatio]);ctx.strokeStyle="#8b949e";ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[2]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle="#2f81f7";ctx.lineWidth=2*devicePixelRatio;ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
}

// Point at the trace to read it. Works with a finger as well as a mouse — over
// the tunnel this chart is often the only thing telling the operator what the
// cell is doing, and "roughly where the line is" is not a reading.
function chartProbe(clientX){
  const cv=$("chart"), tipEl=$("chartTip");
  if(!CHART.hist){ tipEl.hidden=true; return; }
  const r=cv.getBoundingClientRect();
  const xCss=clientX-r.left;
  const x=xCss*devicePixelRatio;
  let best=null,bestD=Infinity;
  for(const h of CHART.hist){
    const d=Math.abs(CHART.sx(h[0])-x);
    if(d<bestD){bestD=d;best=h;}
  }
  if(!best){ tipEl.hidden=true; return; }
  tipEl.hidden=false;
  tipEl.innerHTML=`<b>${fmt(best[1])} ${U}</b>`+
    (best[2]!=null?` · target ${fmt(best[2])}`:"")+
    `<span class="tt">t+${fmt(best[0]-CHART.t0,1)}s</span>`;
  const px=CHART.sx(best[0])/devicePixelRatio;
  tipEl.style.left=Math.max(4,Math.min(px-tipEl.offsetWidth/2,r.width-tipEl.offsetWidth-4))+"px";
}
(function(){
  const cv=$("chart");
  cv.addEventListener("mousemove",e=>chartProbe(e.clientX));
  cv.addEventListener("mouseleave",()=>{$("chartTip").hidden=true;});
  cv.addEventListener("touchstart",e=>{if(e.touches[0])chartProbe(e.touches[0].clientX);},{passive:true});
  cv.addEventListener("touchmove",e=>{if(e.touches[0])chartProbe(e.touches[0].clientX);},{passive:true});
  cv.addEventListener("touchend",()=>{$("chartTip").hidden=true;});
})();

function showAnalysis(a, combined){
  if(!a) return;
  $("analysisCard").style.display="block";
  const tag=combined?" (whole playlist)":"";
  if(a.n<2){ $("anaSummary").innerHTML="<span>not enough flow points to fit a slope yet"+tag+"</span>"; return; }
  $("anaSummary").innerHTML=
     `<span>points <b>${a.n}</b>${tag}</span>`+
     `<span>slope <b>${Number(a.slope_per_kpa).toExponential(3)}</b> (m³/s)/kPa</span>`+
     `<span>R² <b>${Number(a.r2).toFixed(5)}</b></span>`+
     `<span>Darcy k <b>${Number(a.k_darcy_m2).toExponential(3)}</b> m²</span>`+
     // k is only ever as good as the slope it came from, and R2 does not measure
     // that: three points can sit on a line beautifully with the slope still
     // poorly pinned. null here means UNKNOWN (no residual degrees of freedom
     // below 3 points) — it must never render as "+/- 0", which would claim a
     // precision nobody measured.
     (a.k_stderr_m2==null
       ? `<span title="Needs at least 3 points to estimate">k uncertainty `+
         `<b>n/a</b> (needs ≥3 points)</span>`
       : `<span>k uncertainty <b>± ${Number(a.k_stderr_m2).toExponential(2)}</b> m² `+
         `(${Number(a.k_stderr_pct).toFixed(2)}%)</span>`)+
     `<span>pore d <b>${Number(a.pore_size_um).toFixed(3)}</b> µm</span>`+
     `<span title="R² measures how well the points fit a line, not how tightly `+
     `the slope is pinned down">${a.follows_darcy?"✓ follows Darcy's law":"⚠ low R²"}</span>`+
     // Beside k, not tucked away in the meta row. k goes as viscosity and
     // viscosity goes as temperature, so a temperature that was not measured is
     // this number's largest error — and this is the line where the number is
     // being claimed.
     (a.temp_warning?`<span class="prov bad">⚠ ${esc(a.temp_warning)}</span>`:"");
  const base=combined?"/playlist/file/":"";
  $("downloads").innerHTML = a.xlsx_file
    ? `<a href="${combined?"/playlist/file/xlsx":"/download?ts="+Date.now()}"
         style="color:var(--acc);font-weight:600;text-decoration:none">⬇ Download Excel (.xlsx)</a>` : "";
  const img=$("plotImg"), key=(combined?"pl:":"run:")+(a.plot_file||"");
  if(a.plot_file && img.dataset.file!==key){
    img.dataset.file=key;
    img.src=(combined?"/playlist/file/plot?ts=":"/plot?ts=")+Date.now();
    img.style.display="block";
  } else if(!a.plot_file){
    // Analysing with no run open (set_volumes after a server restart) produces
    // no plot. Leaving the previous one up would caption someone else's figure
    // with these numbers.
    img.dataset.file=""; img.removeAttribute("src"); img.style.display="none";
  }
}
async function computeAnalysis(volumes){
  const body=volumes?{volumes_ml:volumes}:{};
  const a=await (await fetch("/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)})).json();
  showAnalysis(a);
}
function buildVolForm(results){
  const w=$("volForm");
  let html="<label style='color:var(--ink)'>Enter measured permeate volume (mL) for each point:</label>";
  results.forEach((r,i)=>{ if(!r.success) return;
    html+=`<label>point ${i} — ${fmt(toDisp(r.setpoint_kpa))} ${U}, t=${r.collection_s}s</label>`+
          `<input class="volin" data-i="${i}" type="number" step="0.1" placeholder="mL"/>`;
  });
  html+='<button id="volBtn">Compute plot</button>';
  w.innerHTML=html;
  $("analysisCard").style.display="block";
  $("volBtn").onclick=()=>{
    const vols={};
    document.querySelectorAll(".volin").forEach(inp=>{const v=parseFloat(inp.value); if(!isNaN(v)) vols[inp.dataset.i]=v;});
    computeAnalysis(vols);
  };
}
function hideAnalysis(){
  $("analysisCard").style.display="none"; $("volForm").innerHTML="";
  const img=$("plotImg"); img.style.display="none"; img.dataset.file="";
}
function onFinished(s){
  // A playlist item handles its volumes in the gate panel above the queue.
  if(s.item_id) return;
  if(MODE==="hardware" && !s.analysis){ buildVolForm(s.results||[]); }
  else if(s.analysis){ showAnalysis(s.analysis); }
  else { computeAnalysis(null); }
}

async function loadRuns(){
  try{
    const d=await (await fetch("/runs")).json();
    const tb=$("runsTable").querySelector("tbody"); tb.innerHTML="";
    (d.runs||[]).forEach(r=>{
      const date=r.started? r.started.replace("T"," ").slice(0,19):r.name;
      const k=r.k_darcy_m2!=null?Number(r.k_darcy_m2).toExponential(3):"–";
      const pore=r.pore_size_um!=null?Number(r.pore_size_um).toFixed(2):"–";
      const r2=r.r2!=null?Number(r.r2).toFixed(4):"–";
      const sp=(r.setpoints||[]).map(x=>fmt(toDisp(x),0)).join(", ");
      let files="";
      if(r.has_plot) files+=`<a href="#" data-plot="${r.name}">plot</a>`;
      if(r.has_xlsx) files+=`<a href="/runs/${r.name}/xlsx">excel</a>`;
      if(r.has_csv)  files+=`<a href="/runs/${r.name}/csv">csv</a>`;
      const tr=document.createElement("tr");
      tr.innerHTML=`<td>${date}</td><td>${r.label||"–"}</td><td>${sp}</td>`+
        `<td>${r.n_points??"–"}</td><td>${k}</td><td>${pore}</td><td>${r2}</td><td>${files||"–"}</td>`;
      tb.appendChild(tr);
    });
    tb.querySelectorAll("a[data-plot]").forEach(a=>a.onclick=e=>{
      e.preventDefault();
      const img=$("histPlot"); img.src=`/runs/${a.dataset.plot}/plot?ts=`+Date.now();
      img.style.display="block"; img.scrollIntoView({behavior:"smooth",block:"nearest"});
    });
  }catch(e){}
}
$("refreshRuns").onclick=loadRuns;

// A failed poll used to be swallowed silently, leaving the last good numbers on
// screen looking live. Next to the rig you notice; over the tunnel you cannot,
// and a frozen page reading "60 kPa, collecting" is the worst thing this UI can
// do. Two misses (~1 s) flips the page into a visibly stale state.
let missed=0, lastTs=null, sameTs=0, isStale=false, lastSpoken="";
// Two ways the page can stop being truthful, and they need OPPOSITE handling of
// the stop button:
//   linkDown=true  — we cannot reach the rig at all. A press could not arrive,
//                    so the button is disabled rather than pretending.
//   linkDown=false — the server answers but the control loop has stopped
//                    ticking. /stop still runs _safe_all() in the request
//                    thread, so stopping very likely still WORKS and is the
//                    safest thing left. Never take it away here.
function setStale(on,msg,linkDown){
  isStale=on;
  document.body.classList.toggle("stale",on);
  if(on){
    $("stopBtn").disabled=!!linkDown;
    $("barPhase").className="pill st-fault";
    $("barPhase").textContent=linkDown?"no link":"loop stalled";
    if(msg) $("staleBar").textContent="⚠ "+msg;
  }
}

async function poll(){
  // Two separate failures, both of which must be VISIBLE. Fetching is the link
  // to the rig: only a successful fetch may clear the stale flag, and the miss
  // counter must not be reset anywhere else, or a persistent failure below
  // would keep resetting it and never trip. A render blow-up is different but
  // no safer: the screen is then half-updated, so it is not to be trusted
  // either. Silence is the one option this page does not have.
  let s;
  try{
    const r=await fetch("/status");
    if(r.status===401){ const e=new Error("signed out"); e.authRequired=true; throw e; }
    if(!r.ok) throw new Error("HTTP "+r.status);
    s=await r.json();
    missed=0;
    // A healthy 200 is not proof the rig is alive. The control loop stamps `ts`
    // on every tick — 20 Hz, and it keeps ticking while idle — so a stamp that
    // stops moving means the loop has stalled while the web server carries on
    // answering cheerfully with whatever was last written. Compare successive
    // stamps instead of measuring against the local clock: the phone and the Pi
    // do not share one, and a clock skew must not read as a stalled rig.
    if(s.ts!=null && s.ts===lastTs){ sameTs++; } else { sameTs=0; lastTs=s.ts; }
    if(sameTs>=4)
      setStale(true,"The rig is answering, but its control loop has not ticked for "+
                    "several seconds — the readings below are frozen, not live. "+
                    "Stop still reaches the rig; use it.",false);
    else setStale(false);
  }catch(e){
    // Three ways the page stops being able to speak for the rig, and they are
    // NOT the same: the link is down, the loop is wedged, or the session ran
    // out. Only the first means a press cannot arrive. Signed out still has a
    // working connection, and stopping needs no session by design — so the one
    // control that must survive everything does.
    if(e && e.authRequired){
      // Signed out. Under the policy Adrián set on 2026-07-31 this DOES take the
      // stop button away, so the banner has to name the only thing that still
      // works without a session: a person at the panel valve.
      setStale(true,"Your session has ended — you cannot stop the rig from this page "+
                    "until you sign in. If it needs stopping now, close the panel "+
                    "valve by hand in the lab.",true);
      $("barPhase").textContent="signed out";
      $("stopBtn").textContent="🔒 Sign in to stop";
      $("stopBtn").disabled=false;      // it opens sign-in; it does not pretend to stop
      SIGNED_OUT=true;
      showAuth();
      return;
    }
    if(++missed>=2) setStale(true,"No answer from the rig — the readings below are the "+
                                  "last ones received and may be out of date.",true);
    return;
  }
  try{
    if(s.running && wasFinished){ wasFinished=false; }
    if(s.finished && !wasFinished){ wasFinished=true; onFinished(s); loadPlaylist(true); setTimeout(loadRuns,1300); }
    else if(s.analysis && !s.item_id){ showAnalysis(s.analysis); }
    $("pv").textContent=fmt(s.pressure_disp);
    $("spv").textContent=s.setpoint_disp==null?"–":fmt(s.setpoint_disp)+" "+U;
    $("valve").textContent=fmt(s.valve_command,1);
    const ph=$("phasePill"); ph.className=phaseClass(s.fault?"fault":s.phase);
    ph.textContent=s.fault?"fault":s.phase;
    $("idx").textContent=(s.total? (Math.min(s.index+((s.phase==='done')?0:1),s.total))+"/"+s.total : "–");
    $("div").textContent=s.diverter_measured?"MEASURED":"waste";
    $("band").textContent=s.in_band?"yes":"no";
    $("elapsed").textContent=fmt(s.elapsed_s,1);
    // Name the bound that set the ceiling whenever it was NOT the run ceiling:
    // clamping to the specimen limit means the real margin is tighter than
    // setpoint+overshoot, and that should never be silent.
    $("ceil").textContent=fmt(s.run_ceiling_disp,1)+
      ((s.run_ceiling_source && s.run_ceiling_source!=="run ceiling")
        ? " ("+s.run_ceiling_source+")" : "");
    // Water temperature ALWAYS carries where it came from. It is not decoration:
    // µ is derived from it and k is derived from µ, so a configured constant
    // dressed as a reading would put invented precision straight into the
    // published number. The page showed no temperature at all until the control
    // layer could say its provenance — a value that cannot say where it came
    // from is worse on screen than absent.
    $("wtemp").textContent=fmt(s.water_temp_c,1);
    const src=s.water_temp_source||"unknown";
    const srcEl=$("wtempSrc");
    // `manual` is red, not amber, and the reason is a number from Datos: k goes
    // as µ, and µ moves −2.43 %/°C while ρ moves only −0.021 %/°C. So a
    // temperature that was typed instead of measured is not a footnote about
    // provenance — it is THE dominant term in k's error budget, and 2 °C off
    // means about −4.7 % in k. That was already true before the switch to
    // weighing; the graduated cylinder's ~0.4 % was simply louder and hid it.
    // Weighing to 0.01 % strips it bare, so a `manual` run can now be worse than
    // the measurement it replaced. Amber would undersell that.
    const known={"probe":["measured","ok"],
                 "manual":["not measured — set in config; ±1 °C ≈ ∓2.4 % in k","bad"],
                 "sim":["simulated","warn"],
                 "probe (no recent reading)":["⚠ probe not answering — last value","bad"]};
    const d=known[src]||[src+" — provenance unknown","bad"];
    srcEl.textContent="("+d[0]+")";
    srcEl.className="prov "+d[1];
    srcEl.title=(src==="probe")
      ? "Measured by the DS18B20 probe."
      : "Water temperature sets the viscosity, and k is proportional to it. "+
        "A value that was not measured carries straight into the published k.";
    HELD=!!s.held;
    CURRENT_ITEM_ID=s.item_id||null;
    $("barPv").textContent=fmt(s.pressure_disp);
    // While stale the bar is owned by setStale: overwriting it here would put a
    // healthy-looking phase back on a page whose numbers are known to be frozen,
    // and would re-enable a stop button that cannot reach anything.
    if(!isStale){
      const bp=$("barPhase");
      if(s.fault){ bp.className="pill st-fault"; bp.textContent="fault"; }
      else if(s.held){ bp.className="pill st-fault"; bp.textContent="held"; }
      else { bp.className=phaseClass(s.phase); bp.textContent=s.phase; }
      $("stopBtn").disabled=!(s.running||s.held);
      // Announce the state only when it CHANGES. The pressure updates twice a
      // second; piping that into a live region would make the page unusable
      // with a screen reader instead of more accessible.
      const spoken=bp.textContent;
      if(spoken!==lastSpoken){
        lastSpoken=spoken;
        $("barLive").textContent=`Rig ${spoken}, ${fmt(s.pressure_disp)} ${U}`;
      }
    }
    renderHeld(s);
    $("nowWrap").style.display=(s.running&&s.item_label)?"inline":"none";
    $("nowLabel").textContent=s.item_label||"–";
    $("collectWrap").style.display=(s.phase==="collecting")?"inline":"none";
    $("cleft").textContent=fmt(s.collect_remaining_s,0);
    $("playBtn").disabled=s.running;
    $("playBtn").textContent=s.running?"running…":"▶ Play next experiment";
    $("addBtn").disabled=s.running;
    const fb=$("faultBox"); if(s.fault){fb.style.display="block";fb.textContent="⚠ "+s.fault;}else{fb.style.display="none";}
    const cw=$("closeWarn");
    if(s.close_warning){cw.style.display="block";cw.textContent="⚠ "+s.close_warning;}
    else{cw.style.display="none";}
    const tol=s.setpoint_disp? s.setpoint_disp*(parseFloat($("expTol").value)||10)/100 : 1;
    draw(s.history, tol, s.run_ceiling_disp);
    const tb=$("results").querySelector("tbody"); tb.innerHTML="";
    (s.results||[]).forEach(r=>{
      const tr=document.createElement("tr");
      const d=v=>fmt(v==null?null:(U==="psi"? v/6.894757293168361 : v));
      tr.innerHTML=`<td>${d(r.setpoint_kpa)}</td><td>${d(r.mean_kpa)}</td><td>${fmt(U==="psi"?r.std_kpa/6.894757293168361:r.std_kpa,3)}</td>
        <td>${d(r.min_kpa)}</td><td>${d(r.max_kpa)}</td><td>${fmt(r.in_band_fraction*100,1)}%</td>
        <td>${r.n_samples}</td><td>${r.success?"✓":"✗ "+(r.note||"")}</td>`;
      tb.appendChild(tr);
    });
    if(!s.running) loadPlaylist(false);
  }catch(e){
    setStale(true,"This page hit an error while drawing the rig's state ("+e.message+"). "+
                  "What you see may be incomplete — reload before acting on it.");
  }
}
loadConfig().then(()=>{loadPlaylist(true);loadRuns();poll();setInterval(poll,500);});
</script>
</body></html>"""
