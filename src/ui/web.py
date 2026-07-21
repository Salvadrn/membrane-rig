"""Local web UI (FastAPI). Single self-contained page, no external assets.

Why a web UI (vs a CLI menu): the Pi runs headless in the lab, you reach it
from a laptop/phone on the LAN, and a live pressure chart lets you *watch* the
loop settle into the tolerance band before collection triggers. A thin CLI
(src/ui/cli.py) covers SSH/tuning.

Run:  python run.py web --config config.yaml   (default http://0.0.0.0:8000)
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
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 12px}
  label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}
  input{width:100%;background:#0d1117;border:1px solid var(--line);color:var(--ink);
        border-radius:7px;padding:8px 10px;font:inherit}
  input.over{border-color:var(--bad);background:#2a1315}
  .row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  button{width:100%;margin-top:14px;padding:10px;border:0;border-radius:8px;font:inherit;
         font-weight:600;cursor:pointer;color:#fff;background:var(--acc)}
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
  table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
  th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  td a{color:var(--acc);text-decoration:none;margin-right:8px}
  td a:hover{text-decoration:underline}
  .hbtn{width:auto;margin:0;padding:5px 12px;font-size:12px}
  .xbtn{width:auto;margin:0;padding:3px 8px;font-size:12px;background:#21262d;color:var(--muted);
        border:1px solid var(--line);margin-left:4px}
  .xbtn:hover{color:var(--ink)}
  .fault{background:#3a0d0d;border:1px solid var(--bad);color:#ffb3ad;padding:8px 12px;
         border-radius:8px;margin-bottom:12px;display:none}
  .bandnote{font-size:12px;color:var(--muted);margin-top:4px}
  .limitbox{background:#12191f;border:1px solid var(--line);border-left:3px solid var(--warn);
            border-radius:7px;padding:10px 12px;font-size:12px;color:var(--muted);margin-bottom:6px}
  .limitbox b{color:var(--ink)}
  .gate{background:#0d1e33;border:1px solid var(--acc);border-radius:9px;padding:14px;margin-bottom:14px;display:none}
  .gate h3{margin:0 0 6px;font-size:14px}
  .queue td{vertical-align:middle}
  .queue tr.next td{background:#131c26}
  details summary{cursor:pointer;color:var(--muted);font-size:12px;margin-top:14px}
  .err{color:var(--bad);font-size:12px;margin-top:6px;min-height:16px}
</style></head>
<body>
<header><h1>Membrane Permeability Rig</h1><span class="mode" id="mode"></span></header>
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
    <label>Specimen limit (<span class="u"></span>) — what this mesh tolerates</label>
    <input id="meshLimit" type="number" step="1" placeholder="e.g. 65"/>
    <button class="ghost" id="saveLimit" style="margin-top:8px">Save limit</button>

    <label style="margin-top:18px">Name</label>
    <input id="expLabel" placeholder="e.g. 60 mesh — point 1"/>
    <label>Pressure (<span class="u"></span>) — comma-separated for a multi-point item</label>
    <input id="expSp" placeholder="20"/>
    <div class="row2">
      <div><label>Collection (s)</label><input id="expCollect" type="number" step="1"/></div>
      <div><label>Dwell (s)</label><input id="expDwell" type="number" step="1"/></div>
    </div>
    <label>Tolerance band (± %)</label><input id="expTol" type="number" step="0.1"/>
    <button id="addBtn">+ Add to playlist</button>
    <div class="err" id="addErr"></div>

    <details>
      <summary>Single run without the playlist (advanced)</summary>
      <label>Setpoints (comma-separated)</label><input id="setpoints"/>
      <div class="row"><input id="kp" type="number" step="0.1" title="Kp"/>
        <input id="ki" type="number" step="0.1" title="Ki"/><input id="kd" type="number" step="0.01" title="Kd"/></div>
      <div class="bandnote">PID gains Kp / Ki / Kd</div>
      <button class="ghost" id="startBtn">Start single run</button>
    </details>
  </div>

  <div class="card">
    <div class="fault" id="faultBox"></div>
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
    <canvas id="chart" width="900" height="280"></canvas>
    <table id="results"><thead><tr>
      <th>Setpoint</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th><th>In-band</th><th>n</th><th></th>
    </tr></thead><tbody></tbody></table>
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

    <table class="queue" id="queueTable"><thead><tr>
      <th>#</th><th>Name</th><th>Pressure</th><th>Collect</th><th>Status</th>
      <th>Mean</th><th>Volume</th><th>Q (m³/s)</th><th></th>
    </tr></thead><tbody></tbody></table>
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
    <table id="runsTable"><thead><tr>
      <th>Date</th><th>Membrane</th><th>Setpoints</th><th>n</th>
      <th>k (m²)</th><th>pore (µm)</th><th>R²</th><th>Files</th>
    </tr></thead><tbody></tbody></table>
    <img id="histPlot" alt="selected run plot" style="width:100%;max-width:760px;margin-top:12px;border-radius:8px;background:#fff;display:none"/>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
let U="kPa", CUTOFF=0, LIMIT=0, MODE="sim", wasFinished=false, plSig="";

function fmt(x,d=2){return (x==null||x==="")?"–":Number(x).toFixed(d);}
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
function checkSp(){
  const over=$("expSp").value.split(",").map(s=>parseFloat(s.trim()))
              .filter(x=>!isNaN(x)).some(x=>x>LIMIT);
  $("expSp").classList.toggle("over",over);
  $("addErr").textContent=over?("Above the "+LIMIT+" "+U+" limit for this specimen."):"";
  return !over;
}
$("expSp").oninput=checkSp;

$("saveLimit").onclick=async()=>{
  const v=parseFloat($("meshLimit").value);
  const r=await post("/limit",{limit:isNaN(v)?null:v});
  if(r.ok){ LIMIT=r.data.limit; $("limitTxt").textContent=LIMIT; checkSp(); loadPlaylist(true); }
  else alert(r.data.error||"could not set the limit");
};

$("addBtn").onclick=async()=>{
  if(!checkSp()) return;
  const sp=$("expSp").value.split(",").map(s=>parseFloat(s.trim())).filter(x=>!isNaN(x));
  if(!sp.length){ $("addErr").textContent="Enter at least one pressure."; return; }
  const r=await post("/playlist/add",{
    label:$("expLabel").value, setpoints:sp,
    collection_s:parseFloat($("expCollect").value)||null,
    dwell_s:parseFloat($("expDwell").value)||null,
    tolerance_pct:parseFloat($("expTol").value)||null});
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
$("stopBtn")&&($("stopBtn").onclick=async()=>{ await post("/stop"); });

// --- playlist rendering ------------------------------------------------------
async function loadPlaylist(force){
  let d; try{ d=await (await fetch("/playlist")).json(); }catch(e){ return; }
  const sig=JSON.stringify(d.items.map(i=>[i.id,i.status,i.setpoints,i.collection_s,i.label,
                                            (i.results||[]).map(r=>r.volume_ml)]))+d.limit;
  if(!force && sig===plSig) return;
  plSig=sig;
  LIMIT=d.limit; $("limitTxt").textContent=d.limit;
  if(d.membrane_limit!=null && !$("meshLimit").value) $("meshLimit").value=d.membrane_limit;
  const c=d.counts;
  $("plCounts").textContent=`${c.done} done · ${c.pending} pending · ${c.total} total`;
  $("emptyNote").style.display=c.total?"none":"block";
  const tb=$("queueTable").querySelector("tbody"); tb.innerHTML="";
  d.items.forEach((it,n)=>{
    const r0=(it.results||[])[0]||{};
    const isNext=it.id===d.next_id;
    const tr=document.createElement("tr");
    if(isNext) tr.className="next";
    const acts=
      `<button class="xbtn" data-up="${it.id}">↑</button>`+
      `<button class="xbtn" data-down="${it.id}">↓</button>`+
      (it.status==="pending"?`<button class="xbtn" data-skip="${it.id}">skip</button>`:
                             `<button class="xbtn" data-requeue="${it.id}">re-run</button>`)+
      `<button class="xbtn" data-del="${it.id}">✕</button>`;
    tr.innerHTML=
      `<td>${isNext?"▶":""} ${n+1}</td>`+
      `<td>${it.label||"–"}</td>`+
      `<td>${it.setpoints.join(", ")} ${U}</td>`+
      `<td>${it.collection_s}s</td>`+
      `<td><span class="pill st-${it.status}">${it.status}</span>`+
        (it.note?` <span style="color:var(--bad);font-size:11px">${it.note}</span>`:"")+`</td>`+
      `<td>${r0.mean_kpa!=null?fmt(toDisp(r0.mean_kpa)):"–"}</td>`+
      `<td>${r0.volume_ml?fmt(r0.volume_ml,0)+" mL":"–"}</td>`+
      `<td>${r0.flow_m3s?Number(r0.flow_m3s).toExponential(3):"–"}</td>`+
      `<td style="text-align:right;white-space:nowrap">${acts}</td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll("[data-up]").forEach(b=>b.onclick=async()=>{await post("/playlist/move",{id:b.dataset.up,delta:-1});loadPlaylist(true);});
  tb.querySelectorAll("[data-down]").forEach(b=>b.onclick=async()=>{await post("/playlist/move",{id:b.dataset.down,delta:1});loadPlaylist(true);});
  tb.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{await post("/playlist/remove",{id:b.dataset.del});loadPlaylist(true);});
  tb.querySelectorAll("[data-skip]").forEach(b=>b.onclick=async()=>{await post("/playlist/skip",{id:b.dataset.skip});loadPlaylist(true);});
  tb.querySelectorAll("[data-requeue]").forEach(b=>b.onclick=async()=>{await post("/playlist/requeue",{id:b.dataset.requeue});loadPlaylist(true);});
  renderGate(d);
}

// The pause between experiments: read the cylinder, then press play.
function renderGate(d){
  const box=$("gateBox"), running=d.items.find(i=>i.status==="running");
  const nxt=d.items.find(i=>i.id===d.next_id);
  const last=[...d.items].reverse().find(i=>i.status==="done"||i.status==="failed");
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
    body=(last.note||"")+" — check the rig before continuing.";
  }
  if(nxt){
    body+=`${body?"<br>":""}<b style="color:var(--ink)">Next up:</b> “${nxt.label||"experiment"}” at `+
          `${nxt.setpoints.join(", ")} ${U} for ${nxt.collection_s}s. Press play when you are ready.`;
  } else {
    body+=`${body?"<br>":""}Playlist finished — nothing pending.`;
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
     `<span>pore d <b>${Number(a.pore_size_um).toFixed(3)}</b> µm</span>`+
     `<span>${a.follows_darcy?"✓ follows Darcy's law":"⚠ low R²"}</span>`;
  const base=combined?"/playlist/file/":"";
  $("downloads").innerHTML = a.xlsx_file
    ? `<a href="${combined?"/playlist/file/xlsx":"/download?ts="+Date.now()}"
         style="color:var(--acc);font-weight:600;text-decoration:none">⬇ Download Excel (.xlsx)</a>` : "";
  const img=$("plotImg"), key=(combined?"pl:":"run:")+(a.plot_file||"");
  if(a.plot_file && img.dataset.file!==key){
    img.dataset.file=key;
    img.src=(combined?"/playlist/file/plot?ts=":"/plot?ts=")+Date.now();
    img.style.display="block";
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

async function poll(){
  try{
    const s=await (await fetch("/status")).json();
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
    $("ceil").textContent=fmt(s.run_ceiling_disp,1);
    $("nowWrap").style.display=(s.running&&s.item_label)?"inline":"none";
    $("nowLabel").textContent=s.item_label||"–";
    $("collectWrap").style.display=(s.phase==="collecting")?"inline":"none";
    $("cleft").textContent=fmt(s.collect_remaining_s,0);
    $("playBtn").disabled=s.running;
    $("playBtn").textContent=s.running?"running…":"▶ Play next experiment";
    $("addBtn").disabled=s.running;
    const fb=$("faultBox"); if(s.fault){fb.style.display="block";fb.textContent="⚠ "+s.fault;}else{fb.style.display="none";}
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
  }catch(e){}
}
loadConfig().then(()=>{loadPlaylist(true);loadRuns();poll();setInterval(poll,500);});
</script>
</body></html>"""
