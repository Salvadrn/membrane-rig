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
  header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:baseline}
  header h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.2px}
  header .mode{font-size:12px;color:var(--muted)}
  .wrap{display:grid;grid-template-columns:340px 1fr;gap:18px;padding:18px;max-width:1200px}
  @media(max-width:820px){.wrap{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 12px}
  label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}
  input{width:100%;background:#0d1117;border:1px solid var(--line);color:var(--ink);
        border-radius:7px;padding:8px 10px;font:inherit}
  .row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  button{width:100%;margin-top:14px;padding:10px;border:0;border-radius:8px;font:inherit;
         font-weight:600;cursor:pointer;color:#fff;background:var(--acc)}
  button.stop{background:var(--bad)}
  button:disabled{opacity:.45;cursor:not-allowed}
  .big{display:flex;gap:22px;align-items:flex-end;margin-bottom:6px}
  .big .v{font-size:40px;font-weight:700;line-height:1}
  .big .sp{font-size:15px;color:var(--muted)}
  .pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
  .st-idle{background:#21262d;color:var(--muted)}
  .st-stabilizing{background:#3a2d00;color:var(--warn)}
  .st-collecting{background:#0d2818;color:var(--ok)}
  .st-done{background:#0d1e33;color:var(--acc)}
  .st-fault{background:#3a0d0d;color:var(--bad)}
  .meta{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin:10px 0}
  .meta b{color:var(--ink);font-weight:600}
  canvas{width:100%;height:280px;display:block;margin-top:8px}
  table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
  th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  td a{color:var(--acc);text-decoration:none;margin-right:8px}
  td a:hover{text-decoration:underline}
  .hbtn{width:auto;margin:0;padding:5px 12px;font-size:12px}
  .fault{background:#3a0d0d;border:1px solid var(--bad);color:#ffb3ad;padding:8px 12px;
         border-radius:8px;margin-bottom:12px;display:none}
  .bandnote{font-size:12px;color:var(--muted);margin-top:4px}
</style></head>
<body>
<header><h1>Membrane Permeability Rig</h1><span class="mode" id="mode"></span></header>
<div class="wrap">
  <div class="card">
    <h2>Test parameters</h2>
    <label>Setpoints (comma-separated, <span class="u"></span>)</label>
    <input id="setpoints"/>
    <label>Tolerance band (± %)</label><input id="tol" type="number" step="0.1"/>
    <label>Stabilise dwell (s)</label><input id="dwell" type="number" step="1"/>
    <label>Collection duration (s)</label><input id="collect" type="number" step="1"/>
    <div>
      <label>PID gains (Kp / Ki / Kd)</label>
      <div class="row"><input id="kp" type="number" step="0.1"/>
        <input id="ki" type="number" step="0.1"/><input id="kd" type="number" step="0.01"/></div>
    </div>
    <button id="startBtn">Start sequence</button>
    <button id="stopBtn" class="stop" disabled>Stop</button>
    <div class="bandnote">Safety cutoff: <b id="cutoff"></b> <span class="u"></span></div>
  </div>

  <div class="card">
    <div class="fault" id="faultBox"></div>
    <div class="big">
      <div><div class="v"><span id="pv">–</span><span style="font-size:18px" class="u"></span></div></div>
      <div class="sp">setpoint <b id="spv">–</b> · valve <b id="valve">–</b>% · <span id="phasePill" class="pill st-idle">idle</span></div>
    </div>
    <div class="meta">
      <span>test <b id="idx">–</b></span>
      <span>diverter <b id="div">–</b></span>
      <span>in-band <b id="band">–</b></span>
      <span>elapsed <b id="elapsed">–</b>s</span>
      <span id="collectWrap" style="display:none">collect left <b id="cleft">–</b>s</span>
      <span>run <b id="run">–</b></span>
    </div>
    <canvas id="chart" width="900" height="280"></canvas>
    <table id="results"><thead><tr>
      <th>Setpoint</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th><th>In-band</th><th>n</th><th></th>
    </tr></thead><tbody></tbody></table>
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
let U="kPa", CUTOFF=0, MODE="sim", wasFinished=false;

function fmt(x,d=2){return (x==null||x==="")?"–":Number(x).toFixed(d);}
function toDisp(vk){return U==="psi"? vk/6.894757293168361 : vk;}

async function loadConfig(){
  const c=await (await fetch("/config")).json();
  U=c.units; CUTOFF=c.max_pressure; MODE=c.mode;
  document.querySelectorAll(".u").forEach(e=>e.textContent=U);
  $("mode").textContent="mode: "+c.mode+"  ·  cutoff "+c.max_pressure+" "+U;
  $("cutoff").textContent=c.max_pressure;
  $("setpoints").value=c.setpoints.join(", ");
  $("tol").value=c.tolerance_pct; $("dwell").value=c.dwell_s; $("collect").value=c.collection_s;
  $("kp").value=c.pid.kp; $("ki").value=c.pid.ki; $("kd").value=c.pid.kd;
}

$("startBtn").onclick=async()=>{
  const body={
    setpoints:$("setpoints").value.split(",").map(s=>parseFloat(s.trim())).filter(x=>!isNaN(x)),
    tolerance_pct:parseFloat($("tol").value), dwell_s:parseFloat($("dwell").value),
    collection_s:parseFloat($("collect").value),
    kp:parseFloat($("kp").value), ki:parseFloat($("ki").value), kd:parseFloat($("kd").value)
  };
  const r=await fetch("/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const j=await r.json(); if(!j.ok) alert("Could not start: "+j.error);
};
$("stopBtn").onclick=async()=>{ await fetch("/stop",{method:"POST"}); };

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
  // axes
  ctx.strokeStyle="#30363d";ctx.lineWidth=devicePixelRatio;ctx.beginPath();
  ctx.moveTo(pad,H-pad);ctx.lineTo(W-0.4*pad,H-pad);ctx.moveTo(pad,H-pad);ctx.lineTo(pad,0.6*pad);ctx.stroke();
  ctx.fillStyle="#8b949e";ctx.font=(11*devicePixelRatio)+"px sans-serif";
  for(let i=0;i<=4;i++){const p=pmin+(pmax-pmin)*i/4;const y=sy(p);
    ctx.fillText(p.toFixed(1),4,y+3);ctx.strokeStyle="#1c2128";ctx.beginPath();
    ctx.moveTo(pad,y);ctx.lineTo(W-0.4*pad,y);ctx.stroke();}
  // setpoint (dashed) + band
  ctx.setLineDash([6*devicePixelRatio,4*devicePixelRatio]);ctx.strokeStyle="#8b949e";ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[2]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
  ctx.setLineDash([]);
  // pressure
  ctx.strokeStyle="#2f81f7";ctx.lineWidth=2*devicePixelRatio;ctx.beginPath();
  hist.forEach((h,i)=>{const x=sx(h[0]),y=sy(h[1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
}

function showAnalysis(a){
  if(!a) return;
  $("analysisCard").style.display="block";
  if(a.n<2){ $("anaSummary").innerHTML="<span>not enough flow points to fit a slope yet</span>"; return; }
  $("anaSummary").innerHTML=
     `<span>slope <b>${Number(a.slope_per_kpa).toExponential(3)}</b> (m³/s)/kPa</span>`+
     `<span>R² <b>${Number(a.r2).toFixed(5)}</b></span>`+
     `<span>Darcy k <b>${Number(a.k_darcy_m2).toExponential(3)}</b> m²</span>`+
     `<span>pore d <b>${Number(a.pore_size_um).toFixed(3)}</b> µm</span>`+
     `<span>${a.follows_darcy?"✓ follows Darcy's law":"⚠ low R²"}</span>`;
  const dl=$("downloads");
  dl.innerHTML = a.xlsx_file
    ? `<a href="/download?ts=${Date.now()}" style="color:var(--acc);font-weight:600;text-decoration:none">⬇ Download Excel (.xlsx)</a>`
    : "";
  const img=$("plotImg");
  if(a.plot_file && img.dataset.file!==a.plot_file){
    img.dataset.file=a.plot_file; img.src="/plot?ts="+Date.now(); img.style.display="block";
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
  if(MODE==="hardware" && !s.analysis){ buildVolForm(s.results||[]); }
  else if(s.analysis){ showAnalysis(s.analysis); }
  else { computeAnalysis(null); }   // sim: volumes already collected -> auto-fit
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
  }catch(e){/* transient */}
}
$("refreshRuns").onclick=loadRuns;

async function poll(){
  try{
    const s=await (await fetch("/status")).json();
    if(s.running && wasFinished){ wasFinished=false; hideAnalysis(); }
    if(s.finished && !wasFinished){ wasFinished=true; onFinished(s); setTimeout(loadRuns,1300); }
    else if(s.analysis){ showAnalysis(s.analysis); }
    $("pv").textContent=fmt(s.pressure_disp);
    $("spv").textContent=s.setpoint_disp==null?"–":fmt(s.setpoint_disp)+" "+U;
    $("valve").textContent=fmt(s.valve_command,1);
    const ph=$("phasePill"); ph.className=phaseClass(s.fault?"fault":s.phase);
    ph.textContent=s.fault?"fault":s.phase;
    $("idx").textContent=(s.total? (Math.min(s.index+((s.phase==='done')?0:1),s.total))+"/"+s.total : "–");
    $("div").textContent=s.diverter_measured?"MEASURED":"waste";
    $("band").textContent=s.in_band?"yes":"no";
    $("elapsed").textContent=fmt(s.elapsed_s,1);
    $("run").textContent=s.run_name||"–";
    $("collectWrap").style.display=(s.phase==="collecting")?"inline":"none";
    $("cleft").textContent=fmt(s.collect_remaining_s,0);
    $("startBtn").disabled=s.running; $("stopBtn").disabled=!s.running;
    const fb=$("faultBox"); if(s.fault){fb.style.display="block";fb.textContent="⚠ "+s.fault;}else{fb.style.display="none";}
    const tol=s.setpoint_disp? s.setpoint_disp*(parseFloat($("tol").value)||2)/100 : 1;
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
  }catch(e){/* transient */}
}
loadConfig().then(()=>{loadRuns();poll();setInterval(poll,500);});
</script>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
