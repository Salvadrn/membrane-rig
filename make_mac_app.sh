#!/usr/bin/env bash
# Build double-clickable Mac apps for the rig UI.
#
#   bash make_mac_app.sh              # -> ~/Desktop/Membrane Rig.app  (+ Stop)
#   bash make_mac_app.sh /Applications
#
# "Membrane Rig.app"  starts the server if needed and opens the browser.
# "Stop Membrane Rig.app" shuts the server down.
# Re-run this script after moving the repo — the app hard-codes the repo path.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/Membrane Rig.app"
STOP="$DEST/Stop Membrane Rig.app"

chmod +x "$DIR/launch_mac.sh"

# osacompile ad-hoc-signs the bundle and fails if the destination carries
# extended attributes (iCloud-synced Desktop does). Build in a clean temp dir,
# strip xattrs, then move into place.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

osacompile -o "$TMP/Membrane Rig.app" \
  -e "do shell script \"bash '$DIR/launch_mac.sh' --sim &> /dev/null &\""
osacompile -o "$TMP/Stop Membrane Rig.app" \
  -e "do shell script \"pkill -f 'run.py web' || true\"" \
  -e "display notification \"Server stopped\" with title \"Membrane Rig\""

xattr -cr "$TMP/Membrane Rig.app" "$TMP/Stop Membrane Rig.app" 2>/dev/null || true
rm -rf "$APP" "$STOP"
mkdir -p "$DEST"
ditto "$TMP/Membrane Rig.app" "$APP"
ditto "$TMP/Stop Membrane Rig.app" "$STOP"

echo "Built:"
echo "  $APP"
echo "  $STOP"
echo
echo "Double-click \"Membrane Rig\" to open the interface at http://localhost:8000"
echo "It runs in SIMULATION mode. For the real rig, edit launch_mac.sh (--hardware)"
echo "or open the Pi's own address instead."
