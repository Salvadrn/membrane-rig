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
sudo apt-get install -y git python3-venv python3-pip pigpio i2c-tools

echo "==> Enabling I2C (ADS1115) and 1-Wire (DS18B20)"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_onewire 0

echo "==> pigpio daemon (hardware-timed servo pulses)"
sudo systemctl enable --now pigpiod

echo "==> Python environment"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo ""
echo "Done. Next steps:"
echo "  1. If this was the FIRST run (1-Wire just enabled):  sudo reboot"
echo "  2. Edit config.yaml:  mode: hardware   (and temperature.source: probe once the DS18B20 is wired)"
echo "  3. Test:   ./.venv/bin/python run.py web --host 0.0.0.0"
echo "     then open http://$(hostname).local:8000 from your laptop"
echo "  4. Autostart on boot: see docs/INSTALL.md (systemd unit)"
