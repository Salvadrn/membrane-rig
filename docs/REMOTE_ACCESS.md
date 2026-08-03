# Remote access via a subdomain (rig.divid.site)

Reach the rig from anywhere at **`https://rig.divid.site`** instead of
`membrane-rig.local:8000`, using a **Cloudflare Tunnel** on the `divid.site`
zone you already control. (Prefer ACREC? Swap the hostname for
`rig.acrec…` — same steps, as long as that zone is in the same Cloudflare
account.)

## Why a tunnel (not mDNS / port-forwarding)

- **Works behind the university firewall.** The Pi makes an *outbound* connection
  to Cloudflare — no public IP, no port forwarding, no IT ticket. This is the big
  win over `.local`, which is flaky on eduroam.
- Stable name + automatic HTTPS.
- The web server stays bound to `127.0.0.1` — only the tunnel can reach it, so the
  rig is **not** exposed on the lab LAN either.

## ⚠️ Security — this is non-negotiable

The UI **controls a pressurised rig** (opens the air valve, runs sequences).

**The app now has its own login**, and you still want **Cloudflare Access** in
front of the tunnel. They cover different things and neither replaces the other:
Access keeps strangers off the URL entirely, and the app's login is what protects
the rig on the **lab LAN**, which Access never sees. **Never expose the bare
tunnel.**

### Setting the account up (on the Pi, once)

```bash
./.venv/bin/python tools/set_password.py
```

Writes a PBKDF2 hash — never the password — to `~/.membrane-rig/auth` at mode
600, outside the repo. The same run generates the **beacon token**, so
provisioning is one step. Rotate the password by running it again; rotate only
the beacon's token with `--rotate-token` (the beacon must then be restarted).
`--show-token` prints the current token.

If no account is set the rig serves normally and says so loudly at startup — a
fresh Pi should tell you what to do, not lock you out of hardware.

### What the login does and does not protect

- **Over the tunnel: good.** Cloudflare terminates TLS, so the password and the
  session cookie are encrypted, and the cookie is issued with `Secure`.
- **On the lab LAN: partial, and know why.** The app speaks plain HTTP there, so
  the password and cookie cross the network **in the clear** and anyone
  capturing traffic can take them. It stops casual access — which is the problem
  it was built for — and it does not stop someone sniffing the wire. That is why
  the server now binds to **`127.0.0.1` by default** and the tunnel is the
  intended path. `--host 0.0.0.0` still works and now prints a warning.
- The cookie carries `Secure` only over HTTPS. It cannot be set unconditionally:
  on a plain-HTTP LAN the browser would refuse to send it back and sign-in would
  simply appear broken.

### Stopping never needs an account

`POST /stop` and `POST /recover/stop` are the only control paths that work
without signing in, and that is deliberate — agreed by the control, hardware and
interface sessions. Stopping only ever moves the rig towards safe: it shuts the
feed and routes permeate to waste, and there is no phase from which stopping
leaves it worse. It matters because of what this rig physically is right now:
the relief valve is not fitted, the servo holds position rather than sealing when
it loses power, and the ball valve's handle was removed so the servo can turn the
stem. **`/stop` is one of only two things that can stop pressurisation, and the
other one is a person standing at the panel.** A login prompt between someone and
that button is the trade not to make.

Everything else needs a session — including `POST /recover/retry`, which
re-pressurises the cell, and `POST /recover/raise`, which **raises a safety
ceiling**. This UI only ever tightens; raising is the one action that loosens, so
it is never reachable without an account.

If your session ends while the page is open, the readings dim and the page says
so — but **Stop stays live**. "I cannot trust the screen", "I cannot reach the
rig" and "I am not signed in" are three different states here, and only the
middle one takes the stop button away.

## Setup (on the Pi, once it's running)

1. **Install cloudflared**
   ```bash
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cloudflared.deb
   sudo dpkg -i cloudflared.deb
   ```
2. **Log in** (opens a browser link; pick the divid.site zone)
   ```bash
   cloudflared tunnel login
   ```
3. **Create the tunnel** (writes a credentials JSON in ~/.cloudflared/)
   ```bash
   cloudflared tunnel create membrane-rig
   ```
4. **Config** `~/.cloudflared/config.yml`:
   ```yaml
   tunnel: membrane-rig
   credentials-file: /home/pi/.cloudflared/<TUNNEL-ID>.json
   ingress:
     - hostname: rig.divid.site
       service: http://localhost:8000
     - service: http_status:404
   ```
5. **Route the DNS** (creates the CNAME in the divid.site zone automatically)
   ```bash
   cloudflared tunnel route dns membrane-rig rig.divid.site
   ```
6. **Run it as a service**
   ```bash
   sudo cloudflared service install
   sudo systemctl enable --now cloudflared
   ```
7. **Bind the app to localhost** (edit the `membrane-rig.service` ExecStart):
   ```
   ... run.py web --hardware --host 127.0.0.1
   ```
   (localhost only — the tunnel reaches it; the LAN cannot.)

## Turn on the auth gate (Cloudflare Access — do this before real use)

Cloudflare dashboard → **Zero Trust → Access → Applications → Add application**
→ Self-hosted:
- Application domain: `rig.divid.site`
- Policy: **Allow**, rule = *Emails* → your address(es) (add lab members as
  needed). Login via one-time PIN or Google.

Now `rig.divid.site` shows a Cloudflare login first; only approved emails reach
the rig. Free tier covers up to 50 users.

## What the page does when you are not standing next to the rig

Operating over the tunnel means the page is your **only** instrument: you cannot
see the vessel, hear the valve, or read the cylinder. The UI is built for that,
and the parts below exist specifically for it.

- **The safety bar is pinned to the top of the page.** Live pressure, the current
  phase, and **Stop** stay on screen without scrolling or zooming, at a
  thumb-sized tap target. Whatever else changes on this page, that has to remain
  true — a stop control you have to scroll to find is not a stop control.
- **Stop shuts the feed; it does not vent the cell.** It fully closes the feed
  valve and routes permeate to waste. The cell then bleeds down through the
  membrane.
- **Nothing on this rig protects it without the software.** The mechanical relief
  valve is on order and **not fitted**, and the servo holds its position rather
  than sealing when it loses power. So every layer that can stop a pressure
  excursion — the run ceiling, the global cutoff, the sensor checks — needs the
  controller powered and running. Operating remotely, that is the assumption you
  are making: if the software cannot act and you are not at the bench, nothing
  else will.
- **The panel valve still has to be closed by hand**, and remotely *nobody can
  do that*. The servo only holds position; it does not seal when it loses power.
  So a remote session is never fully "put away" until someone walks to the bench.
  Plan the end of a remote run around that.
- **A page that loses contact says so.** If two polls in a row fail, the readings
  dim, the phase reads *no link*, and Stop is disabled — because a control that
  cannot reach the rig must not look like one that can. The numbers on screen are
  then the last ones received, not the current ones.
- **Held at the ceiling.** If a run trips its ceiling, the rig shuts the feed and
  waits for you, and the page shows what to do — not just what happened. When the
  pressure is still rising while the valve is being commanded shut, **Retry is
  disabled**: that is the signature of a stuck valve or a lying sensor, and
  retrying only repeats the excursion. That case needs someone at the bench.

## Notes

- The rig is reachable only while the Pi is powered and both services
  (`membrane-rig`, `cloudflared`) are up. `systemctl status cloudflared` to check.
- `mode: sim` on a laptop still uses plain `localhost:8000` — the tunnel is only
  for the deployed Pi.
- To revoke access instantly: disable the Access application, or
  `cloudflared tunnel delete membrane-rig`.
