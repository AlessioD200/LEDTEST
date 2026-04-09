#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/led-pi/native-controller"
ASSET_DIR="$APP_DIR/assets"
AUTOSTART_DIR="$HOME/.config/autostart"
BACKEND_DIR="/opt/led-pi/backend"
ENV_FILE="$BACKEND_DIR/.env"
REPO_APP="/home/ledvives/LEDTEST/pi-system/native-controller/app_kivy.py"
MOSQ_CONF_SRC="/opt/led-pi/deploy/mosquitto/mosquitto.conf"

# Configure these via env vars before running for production:
#   LED_MQTT_USER=myuser LED_MQTT_PASSWORD=mypass ./install-native-controller.sh
MQTT_USER="${LED_MQTT_USER:-leduser}"
MQTT_PASSWORD="${LED_MQTT_PASSWORD:-change-me}"

mkdir -p "$APP_DIR"
mkdir -p "$ASSET_DIR"
mkdir -p "$AUTOSTART_DIR"

if [[ ! -f "$REPO_APP" ]]; then
	echo "Missing app at $REPO_APP"
	exit 1
fi
chmod +x "$REPO_APP"

if [[ -f "/tmp/Logo-v.png" ]]; then
	cp "/tmp/Logo-v.png" "$ASSET_DIR/Logo-v.png"
fi

cp /opt/led-pi/deploy/native-app/led-controller.desktop "$AUTOSTART_DIR/led-controller.desktop"

if [[ ! -d "$BACKEND_DIR" ]]; then
	echo "Missing backend dir at $BACKEND_DIR"
	exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
	cp "$BACKEND_DIR/.env.example" "$ENV_FILE"
fi

# Force native production mode with real ESP32 via MQTT.
if grep -q '^PORT=' "$ENV_FILE"; then
	sed -i 's/^PORT=.*/PORT=3001/' "$ENV_FILE"
else
	echo 'PORT=3001' >> "$ENV_FILE"
fi

if grep -q '^DEVICE_MODE=' "$ENV_FILE"; then
	sed -i 's/^DEVICE_MODE=.*/DEVICE_MODE=mqtt/' "$ENV_FILE"
else
	echo 'DEVICE_MODE=mqtt' >> "$ENV_FILE"
fi

if grep -q '^MQTT_URL=' "$ENV_FILE"; then
	sed -i 's|^MQTT_URL=.*|MQTT_URL=mqtt://127.0.0.1:1883|' "$ENV_FILE"
else
	echo 'MQTT_URL=mqtt://127.0.0.1:1883' >> "$ENV_FILE"
fi

if grep -q '^MQTT_USER=' "$ENV_FILE"; then
	sed -i "s/^MQTT_USER=.*/MQTT_USER=$MQTT_USER/" "$ENV_FILE"
else
	echo "MQTT_USER=$MQTT_USER" >> "$ENV_FILE"
fi

if grep -q '^MQTT_PASSWORD=' "$ENV_FILE"; then
	sed -i "s/^MQTT_PASSWORD=.*/MQTT_PASSWORD=$MQTT_PASSWORD/" "$ENV_FILE"
else
	echo "MQTT_PASSWORD=$MQTT_PASSWORD" >> "$ENV_FILE"
fi

sudo apt update
sudo apt install -y python3-kivy x11-xserver-utils unclutter mosquitto mosquitto-clients nodejs npm

if [[ -f "$MOSQ_CONF_SRC" ]]; then
	sudo cp "$MOSQ_CONF_SRC" /etc/mosquitto/mosquitto.conf
fi

if [[ -n "$MQTT_USER" && -n "$MQTT_PASSWORD" ]]; then
	sudo mosquitto_passwd -b -c /etc/mosquitto/passwd "$MQTT_USER" "$MQTT_PASSWORD"
fi

sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

cd "$BACKEND_DIR"
npm install --omit=dev

# Disable old browser kiosk service if present.
sudo systemctl disable led-kiosk.service >/dev/null 2>&1 || true
sudo systemctl stop led-kiosk.service >/dev/null 2>&1 || true

sudo systemctl enable led-backend.service
sudo systemctl restart led-backend.service

echo "Native LED controller installed in MQTT mode (real ESP32). Reboot to start automatically."
