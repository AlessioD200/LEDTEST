# Raspberry Pi 3 LED System

Touchscreen LED control system for a Raspberry Pi 3 and 7-inch display.

Recommended production mode:

- `local-pi`: the Raspberry Pi drives the LED strip directly

Optional modes:

- `simulator`: test without hardware
- `mqtt`: legacy ESP32 transport, still available if needed

For the direct Raspberry Pi install path, follow `RPI3_INSTALL.md`.

## Fast install and update (push/pull)

If you want the simplest workflow, use only git push on your Mac and one script on the Pi.

First install on Pi (one time):

```bash
cd /home/ledvives/LEDTEST
chmod +x pi-system/deploy/install-from-git.sh
./pi-system/deploy/install-from-git.sh
```

Daily update on Pi after you push to GitHub:

```bash
cd /home/ledvives/LEDTEST
chmod +x pi-system/deploy/update-from-git.sh
./pi-system/deploy/update-from-git.sh
```

That update script does:

- `git pull --ff-only`
- `npm install --omit=dev` in backend
- restart `led-backend.service`
- restart `led-kiosk.service`

## What is included

- `backend/`: Node.js backend (REST + WebSocket + simulator or MQTT + persisted state + scheduler)
- `local-device/rpi_led_bridge.py`: local WS281x bridge for direct Raspberry Pi strip control
- `deploy/mosquitto/mosquitto.conf`: local MQTT broker config
- `deploy/systemd/*.service`: auto-start backend + kiosk on boot
- `esp32/esp32_led_controller.ino`: ESP32 firmware template for LED strip

## 1) Native app first (recommended)

This project is designed to run as a real native app, not as a browser web app.

Native app file:

- `native-controller/app_kivy.py`

Autostart entry:

- `deploy/native-app/led-controller.desktop`

Install script for production on Pi:

- `deploy/native-app/install-native-controller.sh`

Run on Pi:

```bash
cd /opt/led-pi/deploy/native-app
LED_MQTT_USER=leduser LED_MQTT_PASSWORD=your-password ./install-native-controller.sh
sudo reboot
```

After reboot:

- native fullscreen app starts automatically
- backend starts in `mqtt` mode
- app controls ESP32 via backend API + MQTT transport

## 2) Quick simulator test (optional)

```bash
cd backend
cp .env.example .env
npm install
npm start
```

Open:

- `http://localhost:3000`
- or `http://<pi-ip>:3000`

Default URLs now are:

- `/` = primary touchscreen dashboard from `web/` (same UI concept as ESP web)
- `/touch` = lightweight fallback dashboard from `backend/public/`

ESP32-compatible API behavior on Pi backend:

- `/api/state` returns ESP-style fields (`lux`, `temp`, `mode`, `auto`, `br`, `effects`) plus `desired/device/sensors/scheduler/version`
- legacy routes are supported: `/mode/:mode`, `/toggle/auto`, `/set_global?br=..`, `/lightshow/:effect/toggle`
- `/api/sensor` is available for lux/temp reads
- OTA-style routes are available: `/api/update` and `/api/update/status`

Important:

- The ESP32 web interface is not `web/index.html`.
- The ESP32 web interface is generated directly inside `main.py` (`get_html()`), then served by the ESP32 itself.

In simulator mode:

- no ESP32 is required
- no Mosquitto is required
- telemetry is generated automatically
- commands, scheduler and persisted state can already be tested end-to-end

## 3) Raspberry Pi setup for real ESP32 mode

Install packages:

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients chromium-browser nodejs npm
```

Create MQTT user:

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd leduser
sudo cp deploy/mosquitto/mosquitto.conf /etc/mosquitto/mosquitto.conf
sudo systemctl restart mosquitto
sudo systemctl enable mosquitto
```

Set this in `.env` for real hardware:

```env
DEVICE_MODE=mqtt
```

## 4) Backend install

```bash
cd backend
cp .env.example .env
npm install
npm start
```

Open dashboard:

- `http://<pi-ip>:3000`
- `http://<pi-ip>:3000/touch` fallback touch UI (explicit route)

## 5) systemd auto-start (production)

Copy project to `/opt/led-pi` (expected layout `/opt/led-pi/backend`).

Install services:

```bash
sudo cp deploy/systemd/led-backend.service /etc/systemd/system/
sudo cp deploy/systemd/led-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable led-backend.service
sudo systemctl enable led-kiosk.service
sudo systemctl start led-backend.service
sudo systemctl start led-kiosk.service
```

## 5.1) Smart Pi Touch 7-inch notes

For a Smart Pi Touch (7 inch), this project is designed to be fully touch-driven in browser kiosk mode:

- all controls are web-based (no desktop interaction needed)
- dashboard values and settings are visible and editable by touch
- large touch targets are enabled in the UI for coarse pointer devices

Recommended on Pi:

```bash
sudo systemctl restart led-kiosk.service
```

The provided kiosk service already enables:

- Chromium kiosk fullscreen
- touch events enabled
- scale factor for better readability on 7-inch

## 6) ESP32 firmware

Open `esp32/esp32_led_controller.ino` in Arduino IDE.

Libraries needed:

- FastLED
- PubSubClient
- ArduinoJson

Update these values in the sketch:

- `WIFI_SSID`
- `WIFI_PASS`
- `MQTT_HOST`
- `MQTT_USER`
- `MQTT_PASS`
- pin and LED type if needed

Upload to ESP32.

## 7) MQTT topic contract

Using `DEVICE_ID=esp32-led-1`:

- Command: `led/esp32-led-1/cmd`
- Status: `led/esp32-led-1/status`
- Telemetry: `led/esp32-led-1/telemetry`
- Heartbeat: `led/esp32-led-1/heartbeat`
- Online: `led/esp32-led-1/online`

### Command payload example

```json
{
  "type": "set_state",
  "desired": {
    "power": true,
    "mode": "blue",
    "brightness": 60,
    "color": { "r": 255, "g": 255, "b": 255 },
    "effect": "pulse"
  },
  "ts": 1711900000000
}
```

## 8) Persistence behavior

Backend keeps `backend/data/state.json` up to date.

This means after reboot:

- last desired mode/effect/brightness are restored
- scheduler settings remain available
- touch UI reconnects and shows latest state without starting from zero

## 9) Notes

- This is a production-ready baseline and can be extended with auth hardening, TLS, and richer scheduling UI.
- The `backend/` simulator mode is the recommended first test path before connecting the ESP32.
- Later, switching to the real device is just changing `DEVICE_MODE=simulator` to `DEVICE_MODE=mqtt` and setting MQTT credentials.
- If you use a different backend port (for example `3001`), update the kiosk service URL accordingly.

## 10) Native Raspberry Pi fullscreen app (recommended)

If you want a real native fullscreen app (no browser kiosk), use the Kivy controller:

- app file: `native-controller/app_kivy.py`
- autostart desktop file: `deploy/native-app/led-controller.desktop`

Install on Pi (after copying `/opt/led-pi`):

```bash
chmod +x /opt/led-pi/native-controller/app_kivy.py
cp /opt/led-pi/deploy/native-app/led-controller.desktop ~/.config/autostart/
sudo systemctl disable led-kiosk.service || true
sudo systemctl stop led-kiosk.service || true
sudo reboot
```

By default the app connects to `http://127.0.0.1:3001`.

If backend runs on another machine, set env var in the desktop entry `Exec` line:

```ini
Exec=env LED_BACKEND_URL=http://192.168.0.201:3001 /usr/bin/python3 /opt/led-pi/native-controller/app_kivy.py
```

This app is touch-first and runs fullscreen at login.

### 10.1 Local standalone mode on Pi (no ESP32)

If you want the Pi to run everything locally right now (native app + local backend simulator), run:

```bash
sudo mkdir -p /opt/led-pi/native-controller /opt/led-pi/deploy/native-app
sudo cp /tmp/app_kivy.py /opt/led-pi/native-controller/app_kivy.py
sudo cp /tmp/led-controller.desktop /opt/led-pi/deploy/native-app/led-controller.desktop
sudo cp /tmp/install-native-controller.sh /opt/led-pi/deploy/native-app/install-native-controller.sh
chmod +x /opt/led-pi/native-controller/app_kivy.py /opt/led-pi/deploy/native-app/install-native-controller.sh
/opt/led-pi/deploy/native-app/install-native-controller.sh
sudo reboot
```

After reboot the native fullscreen touch app starts automatically and controls the local simulator backend on `127.0.0.1:3001`.

The Kivy app includes an `Info & Updates` page that checks `origin/main` via git and can run `git pull --ff-only` directly on the Pi repo (`/home/ledvives/LEDTEST`).
After a push from your Mac, open the app on the Pi and use:

- `Check git updates`
- `Update via git pull`

### 10.2 One-command deploy from Mac

From your Mac, use the helper script in the repository root:

```bash
cd /Users/alessio/Documents/GitHub/LEDTEST
chmod +x deploy-native.sh
./deploy-native.sh
```

Optional custom user/ip:

```bash
./deploy-native.sh ledvives 192.168.0.93
```

What it does:

- compile check for `pi-system/native-controller/app_kivy.py`
- upload to `/tmp/app_kivy.py` on Pi
- copy to `/home/<user>/LEDTEST/pi-system/native-controller/app_kivy.py`
- restart the native app
- print process + last log lines
