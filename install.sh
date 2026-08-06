#!/usr/bin/env bash
# Membrane rig — one-shot installer. Run ON the Raspberry Pi, from the repo root:
#   bash install.sh
# Installs system packages, enables I2C (ADS1115) + 1-Wire (DS18B20), starts the
# pigpio daemon (servo pulses), and builds the Python venv. Idempotent — safe to
# re-run. NOTE: the first time 1-Wire is enabled, a reboot is required.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> System packages"
sudo apt-get update
# Build chain for lgpio, which arrives as a transitive dependency of
# adafruit-blinka and ships no aarch64 wheel, so pip COMPILES it from source.
# It needs all of: swig (generates the binding), python3-dev (headers),
# build-essential (compiler) and liblgpio-dev (the C library it LINKS against).
# Missing any one of them kills the pip stage AFTER apt has reported success,
# which reads like a Python problem and is not one. Found the hard way, one
# layer at a time, on Adrián's Trixie board.
sudo apt-get install -y git python3-venv python3-pip i2c-tools \
                        swig python3-dev build-essential \
                        liblgpio-dev python3-lgpio

# pigpio: NOT available on Raspberry Pi OS Trixie (Debian 13) and later — the
# package was dropped upstream (unmaintained, no Pi 5 support). It is only
# needed by ServoValve/PwmValve, which are Stage 6+; the whole sensing chain
# (ADS1115, DS18B20) works without it. So this is a WARNING, not a failure:
# a missing servo driver must not block commissioning the sensors.
if sudo apt-get install -y pigpio 2>/dev/null; then
  PIGPIO_OK=1
else
  PIGPIO_OK=0
  echo ""
  echo "  !! pigpio NO disponible en este OS (normal en Trixie/Debian 13)."
  echo "     El SENSADO funciona igual. Lo que queda bloqueado es el SERVO."
  echo "     Ver docs/ASSEMBLY.md -> 'pigpio y el servo en Trixie'."
  echo ""
fi

echo "==> Enabling I2C (ADS1115) and 1-Wire (DS18B20)"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_onewire 0

if [ "${PIGPIO_OK:-0}" = "1" ]; then
  echo "==> pigpio daemon (hardware-timed servo pulses)"
  sudo systemctl enable --now pigpiod
else
  echo "==> pigpiod omitido (pigpio no instalado) — el servo no funcionará todavía"
fi

echo "==> Python environment"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo ""
echo "Done. Next steps:"
echo "  1. If this was the FIRST run (1-Wire just enabled):  sudo reboot"
echo "  2. Edit config.yaml:  mode: hardware   (and temperature.source: probe once the DS18B20 is wired)"
echo "  3. Test:   ./.venv/bin/python run.py web    # then: curl http://127.0.0.1:8000/status"
echo "     remote access goes through the Cloudflare Tunnel (setup-tunnel.sh);"
echo "     plain-LAN serving needs an explicit --host 0.0.0.0 and is unencrypted"
echo "  4. Autostart on boot: see docs/INSTALL.md (systemd unit)"
