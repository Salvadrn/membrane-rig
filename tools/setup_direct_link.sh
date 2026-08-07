#!/usr/bin/env bash
# Run this ON THE PI, once. Afterwards ANY computer can plug an Ethernet cable
# into the rig and open the page with no setup of its own.
#
#   sudo bash tools/setup_direct_link.sh
#
# WHY
# The lab network blocks device-to-device traffic, so a laptop cannot reach the
# Pi through it — not over HTTP and not over SSH. The fix is to stop asking that
# network for anything: the Pi runs its own tiny network on eth0 and hands the
# laptop everything it needs.
#
# WHAT IT DOES
#   * eth0 becomes a shared network at 10.55.0.1/24. NetworkManager starts
#     dnsmasq on it, so a computer that plugs in gets an address, a route and DNS
#     by DHCP — automatically, on any OS, with nothing configured on its side.
#     That is the whole point: "any computer", not "any computer I have set up".
#   * avahi is installed so the name works too, not just the number.
#   * autoconnect, so it is still true after a power cut. This is production.
#
# WHAT IT DELIBERATELY DOES NOT DO
#   * It does not touch wifi. The Pi keeps its uplink, so Pi Connect keeps
#     working while the cable is in — you do not lose the console you are pasting
#     this into.
#   * It does not make the cable the Pi's default route. A point-to-point link
#     that steals the default route cuts the Pi off the internet, which is the
#     classic way this setup looks fine and strands you.
#
# 10.55.0.0/24 is chosen to stay clear of what these machines already use: the
# campus wifi here hands out 100.64.x (CGNAT) and lab gear tends to sit on
# 192.168.x or 10.0.x.
set -uo pipefail

IFACE="${RIG_LINK_IFACE:-eth0}"
CON="rig-direct"
PI_IP="10.55.0.1"
PORT="${MEMBRANE_RIG_PORT:-8000}"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" = "0" ] || die "run with sudo:  sudo bash tools/setup_direct_link.sh"
command -v nmcli >/dev/null 2>&1 || die "nmcli not found — this expects NetworkManager (Raspberry Pi OS Bookworm/Trixie)."
ip link show "$IFACE" >/dev/null 2>&1 || die "no interface '$IFACE'. Set RIG_LINK_IFACE=<name> and re-run."

# Shared mode works by NetworkManager starting its own dnsmasq on the interface.
# A system-wide dnsmasq already holding port 53 makes that fail, and the symptom
# is unhelpful: the profile activates, the laptop plugs in, and no address ever
# arrives. Say so up front instead of letting it look like a cable problem.
if systemctl is-active --quiet dnsmasq 2>/dev/null; then
  echo "WARNING: a system dnsmasq service is running. NetworkManager needs to start"
  echo "         its own on $IFACE, and the two collide on port 53 — the laptop"
  echo "         would plug in and never get an address."
  echo "         If this rig does not need that dnsmasq:  sudo systemctl disable --now dnsmasq"
  echo "         Continuing anyway; check with the plug-in test at the end."
fi

say "Configuring $IFACE as a shared network at $PI_IP/24"
# Replace rather than edit: re-running this must converge to the same state
# instead of stacking half-configured profiles.
nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$CON" && \
  nmcli connection delete "$CON" >/dev/null 2>&1
nmcli connection add type ethernet ifname "$IFACE" con-name "$CON" \
      ipv4.method shared ipv4.addresses "$PI_IP/24" \
      ipv6.method ignore autoconnect yes >/dev/null \
  || die "nmcli could not create the '$CON' profile."
nmcli connection up "$CON" >/dev/null 2>&1 \
  || echo "   (profile saved; it will come up when a cable is plugged in)"

say "Installing avahi so the name resolves, not just the number"
if command -v avahi-daemon >/dev/null 2>&1; then
  echo "   already installed"
else
  if apt-get install -y -q avahi-daemon >/dev/null 2>&1; then
    echo "   installed"
  else
    echo "   COULD NOT INSTALL (no network right now?)."
    echo "   Not fatal: http://$PI_IP:$PORT works without it. Retry later with:"
    echo "     sudo apt-get install -y avahi-daemon"
  fi
fi
systemctl enable --now avahi-daemon >/dev/null 2>&1 || true

say "Checking the rig serves the network and not just itself"
UNIT_OK=no
if systemctl show membrane-rig -p ExecStart 2>/dev/null | grep -q -- "--lan"; then
  UNIT_OK=yes
  echo "   membrane-rig runs with --lan"
else
  echo "   WARNING: membrane-rig is NOT running with --lan, so it answers only"
  echo "   on the Pi itself and no laptop will see it. Fix:"
  echo "     cd ~/membrane-rig && git pull"
  echo "     sudo sed -i 's|run.py web --hardware|run.py web --hardware --lan|' \\"
  echo "        /etc/systemd/system/membrane-rig.service"
  echo "     sudo systemctl daemon-reload && sudo systemctl restart membrane-rig"
fi

HOSTN="$(hostname -s 2>/dev/null || echo membrane-rig)"
cat <<EOF

== Done.

Any computer, no setup on its side:
  1. Plug an Ethernet cable between the computer and the Pi.
  2. Open   http://$PI_IP:$PORT
     or     http://$HOSTN.local:$PORT      (needs avahi on both ends)

The computer gets its address by DHCP from the Pi, so this works from a Mac,
Windows or Linux laptop that has never been configured for this rig.

Still true after a reboot: the profile is autoconnect, and avahi is enabled.

EOF
[ "$UNIT_OK" = yes ] || echo "One thing is still missing — see the --lan warning above."
