# Installing on the Raspberry Pi

From a blank microSD to the rig serving its web UI. You need: the Pi 4, the
microSD, a laptop, and (once) the microSD reader.

## 1. Flash the microSD (on your laptop)

Use the **Raspberry Pi Imager** (raspberrypi.com/software):
- OS: **Raspberry Pi OS Lite (64-bit)** — no desktop needed, the rig is headless.
- Click the **gear / "Edit settings"** before writing:
  - hostname: `membrane-rig`
  - **Enable SSH** (password auth is fine)
  - username `pi`, pick a password
  - Wi-Fi: your network's SSID + password

> **Campus Wi-Fi warning (UCSD):** eduroam / UCSD-PROTECTED use WPA2-Enterprise,
> which the Imager cannot preconfigure and the Pi struggles with headless.
> Easiest options in the lab: a phone hotspot, the guest network, or a direct
> Ethernet cable to your laptop. Once you can SSH in you can set up anything.

Insert the card, power the Pi, wait ~2 min for first boot.

## 2. SSH in from your laptop

```bash
ssh pi@membrane-rig.local
```

(If `.local` doesn't resolve, find the IP from your router/hotspot and use that.)

## 3. Get the code (the repo is private)

Create an SSH key on the Pi and add it to your GitHub account:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Copy that line into GitHub → Settings → SSH and GPG keys → New SSH key. Then:

```bash
git clone git@github.com:Salvadrn/membrane-rig.git
cd membrane-rig
```

## 4. Run the installer

```bash
bash install.sh
sudo reboot        # required the FIRST time (1-Wire overlay loads on boot)
```

The script installs system packages, enables **I2C** (ADS1115) and **1-Wire**
(DS18B20), starts **pigpiod** (servo pulses), and builds the Python venv with
all dependencies (the Pi-only hardware libs install automatically here — they
are platform-gated in requirements.txt).

## 5. Configure

```bash
nano config.yaml
```
- `mode: hardware`
- `temperature.source: probe` (once the DS18B20 is wired; until then leave
  `manual` and set `manual_c`)
- check pins match your wiring (`valve.servo_pin: 18`, `diverter.pin: 23`,
  `sensor.ads_channel: 0`)

## 6. Test

```bash
./.venv/bin/python run.py web --host 0.0.0.0
```

From your laptop: **http://membrane-rig.local:8000** — you should see the live
pressure reading (~0 kPa at atmosphere). Sanity checks:

```bash
i2cdetect -y 1                      # ADS1115 shows up at 0x48
ls /sys/bus/w1/devices/             # DS18B20 shows as 28-xxxxxxxx
```

## 7. Start on boot (recommended)

```bash
sudo tee /etc/systemd/system/membrane-rig.service > /dev/null <<'EOF'
[Unit]
Description=Membrane permeability rig
After=network-online.target pigpiod.service

[Service]
WorkingDirectory=/home/pi/membrane-rig
ExecStart=/home/pi/membrane-rig/.venv/bin/python run.py web --hardware --host 0.0.0.0
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now membrane-rig
```

From then on the rig is live at `membrane-rig.local:8000` whenever it has power.
Logs: `journalctl -u membrane-rig -f`.

## Updating later

```bash
cd ~/membrane-rig
git pull
./.venv/bin/pip install -r requirements.txt   # only if requirements changed
sudo systemctl restart membrane-rig
```
