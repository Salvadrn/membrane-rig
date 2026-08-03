"""Local web UI (FastAPI). Single self-contained page, no external assets.

Why a web UI (vs a CLI menu): the Pi runs headless in the lab, you reach it
from a laptop/phone on the LAN, and a live pressure chart lets you *watch* the
loop settle into the tolerance band before collection triggers. A thin CLI
(src/ui/cli.py) covers SSH/tuning.

Run:  python run.py web --config config.yaml   (default http://0.0.0.0:8000)

THERE IS NO LOGIN HERE, BY DESIGN — AND SOMETHING ELSE MUST PROVIDE ONE.
Every endpoint is unauthenticated: anyone who can reach this port can open the
feed valve on a pressurised cell. That is acceptable only while the port is
reachable from the lab LAN alone. The moment it is published — the Cloudflare
Tunnel in docs/REMOTE_ACCESS.md — **Cloudflare Access has to sit in front of
it**, and the server must stay bound to 127.0.0.1 so the tunnel is the only way
in. Never expose the bare tunnel. If you add authentication here one day, say so
in REMOTE_ACCESS.md too, because that doc currently promises this file has none.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
import uvicorn

from ..app import RigController
from ..config import Config

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
    # measured permeate volumes (mL) keyed by point index (hardware mode)
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
    id: str
    volumes_ml: Dict[int, float]


class LimitRequest(BaseModel):
    limit: Optional[float] = None


class RaiseRequest(BaseModel):
    """New run ceiling, in display units (the controller converts)."""
    ceiling: float


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Membrane Rig")
    ctl = RigController(cfg)
    runs_dir = Path(cfg.logging.dir)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        ctl.shutdown()

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
        if req.volumes_ml:
            ctl.set_volumes(req.volumes_ml)
        return ctl.compute_and_save_analysis()

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
        res = ctl.set_item_volumes(req.id, req.volumes_ml)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Membrane rig web UI")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--hardware", action="store_true")
    args = ap.parse_args(argv)
    cfg = Config.load(args.config)
    if args.sim:
        cfg.mode = "sim"
    if args.hardware:
        cfg.mode = "hardware"
    app = create_app(cfg)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# --- self-contained page (no CDNs; hand-rolled canvas chart) -----------------
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
  canvas{width:100%;height:280px;display:block;margin-top:8px}
  /* The chart's two lines were told apart only by colour and dash pattern, with
     nothing on the page saying which was which. */
  .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:2px}
  .legend span{display:flex;align-items:center;gap:6px}
  .legend .ln{display:inline-block;width:22px;height:0;border-top-width:3px}
  .legend .meas{border-top-style:solid;border-top-color:var(--acc)}
  .legend .targ{border-top-style:dashed;border-top-color:#8b949e}
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
    </div>
    <canvas id="chart" width="900" height="280" role="img"
            aria-label="Live chart of measured pressure against the target over time.
The readings above give the same values as text."></canvas>
    <div class="legend">
      <span><i class="ln meas"></i>measured pressure</span>
      <span><i class="ln targ"></i>target (setpoint)</span>
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
  const r=await post("/limit",{limit:isNaN(v)?null:v});
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
  const r=await post("/playlist/play");
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
let HELD=false;
$("stopBtn").onclick=async()=>{
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
  const r=await post("/recover/retry");
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
      body="Read the graduated cylinder and enter the collected volume, then empty it before the next run.";
      vols="<div style='margin-top:8px'>";
      (last.results||[]).forEach((r,i)=>{ if(!r.success) return;
        vols+=`<label>point ${i+1} — ${fmt(toDisp(r.setpoint_kpa))} ${U}, ${r.collection_s}s</label>`+
              `<input class="gvol" data-i="${i}" type="number" step="0.1" placeholder="mL" value="${r.volume_ml||""}"/>`;});
      vols+=`<button class="ghost" id="saveVols" data-id="${last.id}">Save volumes</button></div>`;
    } else {
      const v=pts.map(r=>fmt(r.volume_ml,0)+" mL").join(", ");
      body=`Collected ${v||"–"}. Empty the cylinder before the next run.`;
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
          `hand</b> before you leave, since the servo only holds position and does not seal on power loss.`;
  }
  $("gateTitle").textContent=title||"Ready";
  $("gateBody").innerHTML=body;
  $("gateVols").innerHTML=vols;
  const sv=$("saveVols");
  if(sv) sv.onclick=async()=>{
    const v={}; document.querySelectorAll(".gvol").forEach(inp=>{
      const x=parseFloat(inp.value); if(!isNaN(x)) v[inp.dataset.i]=x;});
    await post("/playlist/volumes",{id:sv.dataset.id,volumes_ml:v});
    loadPlaylist(true);
  };
}

function phaseClass(p){return "pill st-"+(p||"idle");}

function draw(hist, tol){
  const cv=$("chart"), ctx=cv.getContext("2d");
  const W=cv.width=cv.clientWidth*devicePixelRatio, H=cv.height=280*devicePixelRatio;
  ctx.clearRect(0,0,W,H); ctx.scale(1,1);
  const pad=38*devicePixelRatio;
  if(!hist||hist.length<2){ctx.fillStyle="#8b949e";ctx.font=(13*devicePixelRatio)+"px sans-serif";
    ctx.fillText("waiting for data…",pad,H/2);return;}
  const t0=hist[0][0], t1=hist[hist.length-1][0];
  let pmin=Infinity,pmax=-Infinity;
  for(const h of hist){pmin=Math.min(pmin,h[1],h[2]);pmax=Math.max(pmax,h[1],h[2]);}
  pmin=Math.min(pmin, 0); pmax=Math.max(pmax*1.1, pmax+ (tol||1));
  const sx=t=>pad+(t-t0)/Math.max(1e-6,(t1-t0))*(W-1.4*pad);
  const sy=p=>H-pad-(p-pmin)/Math.max(1e-6,(pmax-pmin))*(H-1.6*pad);
  ctx.strokeStyle="#30363d";ctx.lineWidth=devicePixelRatio;ctx.beginPath();
  ctx.moveTo(pad,H-pad);ctx.lineTo(W-0.4*pad,H-pad);ctx.moveTo(pad,H-pad);ctx.lineTo(pad,0.6*pad);ctx.stroke();
  ctx.fillStyle="#8b949e";ctx.font=(11*devicePixelRatio)+"px sans-serif";
  for(let i=0;i<=4;i++){const p=pmin+(pmax-pmin)*i/4;const y=sy(p);
    ctx.fillText(p.toFixed(1),4,y+3);ctx.strokeStyle="#1c2128";ctx.beginPath();
    ctx.moveTo(pad,y);ctx.lineTo(W-0.4*pad,y);ctx.stroke();}
  ctx.setLineDash([6*devicePixelRatio,4*devicePixelRatio]);ctx.strokeStyle="#8b949e";ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[2]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle="#2f81f7";ctx.lineWidth=2*devicePixelRatio;ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
}

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
     `the slope is pinned down">${a.follows_darcy?"✓ follows Darcy's law":"⚠ low R²"}</span>`;
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
    // safety bar mirrors the live reading and the state
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
    draw(s.history, tol);
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
