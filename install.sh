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
elif command -v pigpiod >/dev/null 2>&1; then
  PIGPIO_OK=1   # ya compilado desde fuente en una corrida anterior
else
  # Trixie dropped the package, but pigpio still BUILDS and runs on a Pi 4
  # (BCM2711) — it is only the Pi 5's RP1 it cannot drive, and this rig is
  # pinned to a Pi 4 anyway. Verified on Adrián's board 2026-08-06:
  # pigpio.pi().connected == True, hardware rev 0xc03115.
  #
  # Built single-threaded ON PURPOSE. 'make -j4' saturates all four cores and
  # starves the Raspberry Pi Connect agent, which drops the remote shell
  # mid-build and takes the session with it. -j1 with nice is slower and
  # survives.
  echo "==> pigpio no esta en apt (normal en Trixie) — compilando desde fuente"
  ( cd /tmp && rm -rf pigpio \
    && git clone -q --depth 1 https://github.com/joan2937/pigpio.git \
    && cd pigpio && nice -n 15 make -j1 && sudo make install ) \
    && PIGPIO_OK=1 || PIGPIO_OK=0
  [ "$PIGPIO_OK" = "1" ] && echo "  pigpio compilado e instalado en /usr/local/bin/pigpiod" \
                        || echo "  !! fallo la compilacion — el SERVO queda bloqueado, el sensado NO"
fi

echo "==> Enabling I2C (ADS1115) and 1-Wire (DS18B20)"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_onewire 0

# --- Servo pin sanity at boot (measured 2026-08-06, do not drop) -------------
# Symptom this fixes: on power-up the servo thrashes — "se mueve como loco" —
# before any rig software runs, and keeps thrashing until some program claims
# the pin. Two causes, fixed together because they are both one line:
#
#   gpio=18=op,dl   Until pigpio claims it, GPIO18 is an INPUT. The servo's
#                   signal wire then floats next to a 12 V rail and a switching
#                   MOSFET, reads the noise as pulse commands, and hunts.
#                   Driven low from boot = no valid pulses = the servo sits still.
#   audio=off       The onboard audio driver (snd_bcm2835) claims the PWM block
#                   that pigpio uses to time its pulses. This rig has no audio;
#                   the servo is the entire purpose of that pin.
#
# This lives here rather than only in the docs because it is BOOT config, not
# repo config: it survives on the SD card and nowhere else, so a re-flashed Pi
# silently gets the thrash back with no trace of why. Idempotent — safe to re-run.
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
if [ -f "$CFG" ]; then
  echo "==> Servo pin boot config ($CFG)"
  sudo cp -n "$CFG" "$CFG.bak-preinstall" || true
  sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CFG"
  if ! grep -q '^gpio=18=' "$CFG"; then
    # Appended under [all] explicitly: a bare append can land inside a
    # conditional section ([pi5], [cm4]) and then silently does nothing.
    printf '\n[all]\n# servo signal: driven low from boot so it cannot float (see install.sh)\ngpio=18=op,dl\n' \
      | sudo tee -a "$CFG" >/dev/null
  fi
  grep -nE '^(dtparam=audio|gpio=18)' "$CFG" | sed 's/^/    /'
else
  echo "!! no encontré config.txt — aplica a mano: dtparam=audio=off y gpio=18=op,dl"
fi

if [ "${PIGPIO_OK:-0}" = "1" ]; then
  echo "==> pigpio daemon (hardware-timed servo pulses)"

  # Claim the servo pin the instant the daemon comes up, every time.
  #
  # `gpio=18=op,dl` in config.txt only fires at BOOT. pigpiod resets the pin to
  # an INPUT when it starts, so every daemon restart re-opens the same window:
  # the signal wire floats, the servo reads noise as commands and thrashes.
  # Found the hard way — restarting pigpiod for an unrelated measurement set the
  # servo off again, hours after the boot-time fix was declared done. A boot-only
  # guard is not a guard, it is a coincidence that holds until something restarts.
  #
  # ExecStartPost runs after every start, restart and reload, which is exactly
  # the set of events config.txt cannot see. The sleep lets the daemon open its
  # socket before pigs connects to it.
  sudo mkdir -p /etc/systemd/system/pigpiod.service.d
  sudo tee /etc/systemd/system/pigpiod.service.d/servo-pin.conf >/dev/null <<'UNIT'
[Service]
# Servo signal (GPIO18): drive it LOW as soon as pigpiod is up, so it never
# floats between daemon start and the first set_servo_pulsewidth() from the app.
ExecStartPost=/bin/sh -c 'sleep 0.5; pigs modes 18 w; pigs w 18 0'
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable --now pigpiod
  sudo systemctl restart pigpiod
  sleep 1
  echo "    GPIO18 modo=$(pigs mg 18) (1=salida)  nivel=$(pigs r 18) (0=bajo)"
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
