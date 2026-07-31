// Read-only status beacon for the membrane rig.
//
// SCOPE — read this before adding anything.
//
// This Worker NEVER controls the rig. It accepts telemetry the Pi pushes out
// and serves it back for a phone. Every actuator — servo, diverter, playlist,
// the HELD recovery buttons — stays behind the Cloudflare Tunnel with Access in
// front of it (docs/REMOTE_ACCESS.md). The rig pressurises a cell with a
// delicate mesh; a public edge endpoint that can move a valve is not a feature.
//
// Why it exists at all, given the tunnel already serves the UI: the tunnel only
// answers while the Pi and cloudflared are both alive. When they are not, the
// tunnel gives an error page that cannot distinguish "the rig is fine, my phone
// has no signal" from "the loop died mid-run". This Worker stores the last
// heartbeat, so silence becomes a readable number instead of a blank screen.
// That is the same failure Control addressed in-loop with status["ts"].

const MAX_BODY = 16 * 1024; // a status blob is ~1 KB; anything larger is a bug or an attack
const KEY = "latest";

// Heartbeat is 5 s (see POST_PERIOD_S in tools/status_beacon.py). Three missed
// beats is the threshold where a network blip stops being the likely story.
const STALE_AFTER_S = 20;

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return new Uint8Array(digest);
}

// Hash both sides first: timingSafeEqual throws on length mismatch, and the
// exception itself would leak the secret's length.
async function secretMatches(presented, expected) {
  if (typeof presented !== "string" || typeof expected !== "string") return false;
  const [a, b] = await Promise.all([sha256(presented), sha256(expected)]);
  return crypto.subtle.timingSafeEqual(a, b);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

async function readStatus(env) {
  const stored = await env.RIG_STATUS.get(KEY, { type: "json" });
  if (!stored) return { state: "never_seen" };
  const ageS = Math.round((Date.now() - stored.received_at_ms) / 1000);
  return { ...stored, age_s: ageS, stale: ageS > STALE_AFTER_S };
}

async function handleIngest(request, env) {
  if (!env.INGEST_SECRET) {
    console.error({ event: "ingest_misconfigured", reason: "INGEST_SECRET unset" });
    return json({ error: "server not configured" }, 503);
  }
  const presented = request.headers.get("x-rig-key") ?? "";
  if (!(await secretMatches(presented, env.INGEST_SECRET))) {
    console.warn({ event: "ingest_rejected", reason: "bad key" });
    return json({ error: "unauthorized" }, 401);
  }

  // Bound the body before reading it. content-length can lie, so the decoded
  // string is checked too.
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY) return json({ error: "payload too large" }, 413);
  const raw = await request.text();
  if (raw.length > MAX_BODY) return json({ error: "payload too large" }, 413);

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return json({ error: "body is not valid JSON" }, 400);
  }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return json({ error: "body must be a JSON object" }, 400);
  }

  const record = { ...payload, received_at_ms: Date.now() };
  // The Pi may push while offline-buffered, so expiration is generous; staleness
  // is decided on read from received_at_ms, not by the key disappearing.
  await env.RIG_STATUS.put(KEY, JSON.stringify(record), { expirationTtl: 86400 });
  console.log({ event: "ingest_ok", state: payload.state ?? null });
  return json({ ok: true });
}

const PAGE = `<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rig — estado</title><style>
:root{color-scheme:dark light}
body{margin:0;padding:24px;font:16px/1.5 system-ui,sans-serif;background:#111417;color:#e8e8e8}
h1{font-size:18px;font-weight:500;margin:0 0 4px}
.sub{color:#8b9199;font-size:13px;margin:0 0 24px}
.big{font-size:44px;font-weight:500;margin:0;letter-spacing:-.02em}
.unit{font-size:18px;color:#8b9199;font-weight:400}
.row{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #23282d}
.k{color:#8b9199}
.pill{display:inline-block;padding:4px 12px;border-radius:999px;font-size:13px;margin-bottom:20px}
.ok{background:#12341c;color:#79cf90}.bad{background:#3a1512;color:#f0928a}
.note{margin-top:28px;color:#6b7178;font-size:13px;line-height:1.6}
a{color:#7fb8dd}
</style></head><body>
<h1>Membrane rig</h1><p class="sub">Solo lectura. El control vive en el túnel.</p>
<div id="app">Cargando…</div>
<p class="note">Esta página no puede mover nada: ni la válvula, ni el diverter, ni la playlist.
Es un latido, para saber si el rig sigue vivo sin abrir el túnel.</p>
<script>
const F=(v,d=2)=>typeof v==="number"?v.toFixed(d):"—";
async function tick(){
  const app=document.getElementById("app");
  try{
    const r=await fetch("/api/status",{cache:"no-store"});
    const s=await r.json();
    if(s.state==="never_seen"){app.innerHTML='<span class="pill bad">sin datos</span><p class="note">El beacon nunca ha reportado. Revisa que <code>status_beacon.py</code> corra en la Pi.</p>';return;}
    const live=!s.stale;
    app.innerHTML=
      '<span class="pill '+(live?"ok":"bad")+'">'+(live?"vivo · hace "+s.age_s+" s":"SIN LATIDO hace "+s.age_s+" s")+'</span>'+
      '<p class="big">'+F(s.pressure_kpa)+'<span class="unit"> kPa</span></p>'+
      '<div class="row"><span class="k">estado</span><span>'+(s.state??"—")+'</span></div>'+
      '<div class="row"><span class="k">setpoint</span><span>'+F(s.setpoint_kpa)+' kPa</span></div>'+
      '<div class="row"><span class="k">techo</span><span>'+F(s.run_ceiling_kpa)+' kPa</span></div>'+
      '<div class="row"><span class="k">temperatura</span><span>'+F(s.temperature_c,1)+' °C'+(s.temperature_source==="manual"?" (manual)":"")+'</span></div>'+
      '<div class="row"><span class="k">diverter</span><span>'+(s.diverter??"—")+'</span></div>'+
      (s.fault?'<div class="row"><span class="k">falla</span><span style="color:#f0928a">'+s.fault+'</span></div>':"");
  }catch(e){app.textContent="No se pudo leer el estado.";}
}
tick();setInterval(tick,5000);
</script></body></html>`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/ingest") {
        if (request.method !== "POST") return json({ error: "use POST" }, 405);
        return await handleIngest(request, env);
      }
      if (url.pathname === "/api/status") {
        return json(await readStatus(env));
      }
      if (url.pathname === "/") {
        return new Response(PAGE, {
          headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
        });
      }
      return json({ error: "not found" }, 404);
    } catch (err) {
      console.error({ event: "unhandled", path: url.pathname, message: String(err) });
      return json({ error: "internal error" }, 500);
    }
  },
};
