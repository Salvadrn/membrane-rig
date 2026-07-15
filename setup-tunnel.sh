#!/usr/bin/env bash
# Expose the rig at a subdomain via a Cloudflare Tunnel. Run ON the Pi, after
# install.sh. Usage:
#   bash setup-tunnel.sh [hostname]        # default: rig.divid.site
# Needs a Cloudflare account that owns the domain's zone (divid.site).
# AFTER this: turn on Cloudflare Access for the hostname (docs/REMOTE_ACCESS.md) —
# the UI controls hardware, so it must NOT be public without a login.
set -euo pipefail
HOST="${1:-rig.divid.site}"
NAME="membrane-rig"

echo "==> Installing cloudflared"
if ! command -v cloudflared >/dev/null 2>&1; then
  ARCH=$(dpkg --print-architecture)   # arm64 on a 64-bit Pi 4
  curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb" -o /tmp/cloudflared.deb
  sudo dpkg -i /tmp/cloudflared.deb
fi

echo "==> Cloudflare login — open the URL it prints and pick the zone for $HOST"
cloudflared tunnel login

echo "==> Creating tunnel '$NAME'"
cloudflared tunnel create "$NAME" 2>/dev/null || echo "  (tunnel already exists, reusing)"
TUNNEL_ID=$(cloudflared tunnel list | awk -v n="$NAME" '$2==n {print $1}')
echo "  tunnel id: $TUNNEL_ID"

echo "==> Writing ~/.cloudflared/config.yml  (hostname: $HOST)"
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: $NAME
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: $HOST
    service: http://localhost:8000
  - service: http_status:404
EOF

echo "==> Routing DNS: $HOST -> this tunnel (creates the CNAME in Cloudflare)"
cloudflared tunnel route dns "$NAME" "$HOST"

echo "==> Installing cloudflared as a boot service"
sudo tee /etc/systemd/system/cloudflared-rig.service >/dev/null <<EOF
[Unit]
Description=cloudflared tunnel for the membrane rig
After=network-online.target
Wants=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/cloudflared tunnel run $NAME
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared-rig

echo ""
echo "Tunnel is up: https://$HOST  ->  the rig's web UI."
echo ""
echo "NEXT — DO THIS BEFORE USING IT (it controls hardware):"
echo "  Cloudflare dashboard -> Zero Trust -> Access -> Applications -> Add ->"
echo "  Self-hosted -> domain: $HOST -> policy Allow -> Emails -> your address."
echo "Until Access is on, anyone with the URL can drive the rig. Don't skip it."
echo ""
echo "Also confirm the rig binds localhost only (membrane-rig.service ExecStart):"
echo "  run.py web --hardware --host 127.0.0.1"
