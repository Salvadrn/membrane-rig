# membrane-rig-status — the status beacon Worker

A read-only heartbeat for the rig, on the edge. **It cannot control anything.**

## What this is, and what it is not

A Cloudflare Worker runs in Cloudflare's network. It has no route into the lab
LAN, so it can never reach the Pi and can never move the valve. That is a
property, not a limitation: the thing that *does* reach the Pi is the Cloudflare
Tunnel (`setup-tunnel.sh`), and everything that commands hardware stays behind it
with Access in front (`docs/REMOTE_ACCESS.md`).

So the split is:

| | Serves | Reaches the Pi | Can move hardware |
|---|---|---|---|
| **Tunnel + Access** | the real UI | yes | yes — login required |
| **This Worker** | last known status | no | **no, by construction** |

## Why bother, when the tunnel already serves a UI

The tunnel only answers while the Pi *and* `cloudflared` are both alive. When
either is not, you get an error page — and an error page cannot tell you whether
the rig is fine and your phone has no signal, or the loop died mid-run.

This Worker stores the last heartbeat with its timestamp, so silence becomes a
readable number: *"no beat for 340 s"*. It is the remote counterpart of the
`status["ts"]` heartbeat Control added in-loop for the same reason.

## Deploy

Four commands. Run them from this directory.

```bash
npx wrangler login
```

```bash
npx wrangler kv namespace create RIG_STATUS
```

Paste the printed id into `wrangler.jsonc`, replacing `PENDIENTE`. It is not a
secret.

```bash
npx wrangler secret put INGEST_SECRET
```

Paste a long random string when prompted — generate it with
`openssl rand -base64 32`. This never goes in a file in this repo.

```bash
npx wrangler deploy
```

That publishes to `membrane-rig-status.<your-subdomain>.workers.dev`. **No custom
domain is required**, which is also why it does not touch `divid.site`. Point it
at a domain later with a route in `wrangler.jsonc` if you want a nicer name.

## Then, on the Pi

`tools/status_beacon.py` polls the app's own status endpoint and pushes it out
every 5 s. Its docstring has the environment variables and a systemd unit. The
secret must match the one you just set.

## Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/` | GET | phone-sized status page |
| `/api/status` | GET | the same as JSON, plus `age_s` and `stale` |
| `/ingest` | POST | the Pi pushes here; needs the `x-rig-key` header |

`/` and `/api/status` are open. They expose pressure, setpoint, ceiling,
temperature and fault state — telemetry, no controls, no credentials. If that is
more than you want public, put Access in front of the Worker route too; the
beacon's own `POST /ingest` is authenticated separately and is unaffected.

## Deliberate design choices

**An allow-list, not the whole status blob.** `status_beacon.py` forwards ten
named fields. The app's status is Control's to extend, and a field added there
should not silently start being published to the internet.

**HTTP, not an import.** The beacon talks to the app over its published status
endpoint instead of importing `src/`. A deployment tool that reaches into
another agent's internals breaks the moment they refactor.

**Staleness is decided on read.** The KV record carries `received_at_ms` and the
Worker computes the age when serving. A missing key would be ambiguous — never
started, or expired? — so the record lives 24 h and the age carries the meaning.

**Hash before comparing.** `crypto.subtle.timingSafeEqual` throws on a length
mismatch, and that exception would leak the secret's length, so both sides are
SHA-256'd first.
