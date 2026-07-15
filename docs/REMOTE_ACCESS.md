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

The UI **controls a pressurised rig** (opens the air valve, runs sequences). The
app has **no built-in login**. So you must put **Cloudflare Access** in front of
the tunnel — a free auth gate that only lets *your* email(s) through. **Never
expose the bare tunnel.** Without Access, anyone who learns the URL can drive
your hardware.

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

## Notes

- The rig is reachable only while the Pi is powered and both services
  (`membrane-rig`, `cloudflared`) are up. `systemctl status cloudflared` to check.
- `mode: sim` on a laptop still uses plain `localhost:8000` — the tunnel is only
  for the deployed Pi.
- To revoke access instantly: disable the Access application, or
  `cloudflared tunnel delete membrane-rig`.
