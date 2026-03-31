# Raspberry Pi 3 Touch + ESP32 LED System

Complete base system for a Raspberry Pi 3 touchscreen controller.

It now supports two modes:

- `simulator`: test everything without ESP32
- `mqtt`: real communication with ESP32 over MQTT

## What is included

- `backend/`: Node.js backend (REST + WebSocket + simulator or MQTT + persisted state + scheduler)
- `deploy/mosquitto/mosquitto.conf`: local MQTT broker config
- `deploy/systemd/*.service`: auto-start backend + kiosk on boot
- `esp32/esp32_led_controller.ino`: ESP32 firmware template for LED strip

## 1) Quick simulator test

This is the default mode now.

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

- `/` = existing main dashboard from `web/`
- `/touch` = simplified touch dashboard from `backend/public/`

In simulator mode:

- no ESP32 is required
- no Mosquitto is required
- telemetry is generated automatically
- commands, scheduler and persisted state can already be tested end-to-end

## 2) Raspberry Pi setup for real ESP32 mode

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

Set this in `.env` before switching to real hardware:

```env
DEVICE_MODE=mqtt
```

## 3) Backend install

```bash
cd backend
cp .env.example .env
npm install
npm start
```

Open dashboard:

- `http://<pi-ip>:3000`
- `http://<pi-ip>:3000/touch` for the alternate simplified touch UI

## 4) systemd auto-start (production)

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

## 4.1) Smart Pi Touch 7-inch notes

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

## 5) ESP32 firmware

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

## 6) MQTT topic contract

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

## 7) Persistence behavior

Backend keeps `backend/data/state.json` up to date.

This means after reboot:

- last desired mode/effect/brightness are restored
- scheduler settings remain available
- touch UI reconnects and shows latest state without starting from zero

## 8) Notes

- This is a production-ready baseline and can be extended with auth hardening, TLS, and richer scheduling UI.
- The `backend/` simulator mode is the recommended first test path before connecting the ESP32.
- Later, switching to the real device is just changing `DEVICE_MODE=simulator` to `DEVICE_MODE=mqtt` and setting MQTT credentials.
- If you use a different backend port (for example `3001`), update the kiosk service URL accordingly.

## 9) Native Raspberry Pi fullscreen app (recommended)

If you want a real native fullscreen app (no browser kiosk), use the Tkinter controller:

- app file: `native-controller/app.py`
- autostart desktop file: `deploy/native-app/led-controller.desktop`

Install on Pi (after copying `/opt/led-pi`):

```bash
chmod +x /opt/led-pi/native-controller/app.py
cp /opt/led-pi/deploy/native-app/led-controller.desktop ~/.config/autostart/
sudo systemctl disable led-kiosk.service || true
sudo systemctl stop led-kiosk.service || true
sudo reboot
```

By default the app connects to `http://127.0.0.1:3001`.

If backend runs on another machine, set env var in the desktop entry `Exec` line:

```ini
Exec=env LED_BACKEND_URL=http://192.168.0.201:3001 /usr/bin/python3 /opt/led-pi/native-controller/app.py
```

This app is touch-first and runs fullscreen at login.

### 9.1 Local standalone mode on Pi (no ESP32)

If you want the Pi to run everything locally right now (native app + local backend simulator), run:

```bash
sudo mkdir -p /opt/led-pi/native-controller /opt/led-pi/deploy/native-app
sudo cp /tmp/app.py /opt/led-pi/native-controller/app.py
sudo cp /tmp/led-controller.desktop /opt/led-pi/deploy/native-app/led-controller.desktop
sudo cp /tmp/install-native-controller.sh /opt/led-pi/deploy/native-app/install-native-controller.sh
chmod +x /opt/led-pi/native-controller/app.py /opt/led-pi/deploy/native-app/install-native-controller.sh
/opt/led-pi/deploy/native-app/install-native-controller.sh
sudo reboot
```

After reboot the native fullscreen touch app starts automatically and controls the local simulator backend on `127.0.0.1:3001`.

### 9.2 One-command deploy from Mac

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

- compile check for `pi-system/native-controller/app.py`
- upload to `/tmp/app.py` on Pi
- copy to `/home/<user>/LEDTEST/pi-system/native-controller/app.py`
- restart the native app
- print process + last log lines
