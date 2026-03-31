#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/led-pi/native-controller"
ASSET_DIR="$APP_DIR/assets"
AUTOSTART_DIR="$HOME/.config/autostart"
BACKEND_DIR="/opt/led-pi/backend"
ENV_FILE="$BACKEND_DIR/.env"

mkdir -p "$APP_DIR"
mkdir -p "$ASSET_DIR"
mkdir -p "$AUTOSTART_DIR"

SOURCE_APP="/tmp/app.py"
if [[ -f "$SOURCE_APP" ]]; then
	cp "$SOURCE_APP" "$APP_DIR/app.py"
elif [[ ! -f "$APP_DIR/app.py" ]]; then
	echo "Missing app.py in /tmp and $APP_DIR"
	exit 1
fi
chmod +x "$APP_DIR/app.py"

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

# Force local standalone simulator mode (no ESP32 required).
if grep -q '^PORT=' "$ENV_FILE"; then
	sed -i 's/^PORT=.*/PORT=3001/' "$ENV_FILE"
else
	echo 'PORT=3001' >> "$ENV_FILE"
fi

if grep -q '^DEVICE_MODE=' "$ENV_FILE"; then
	sed -i 's/^DEVICE_MODE=.*/DEVICE_MODE=simulator/' "$ENV_FILE"
else
	echo 'DEVICE_MODE=simulator' >> "$ENV_FILE"
fi

sudo apt update
sudo apt install -y python3-tk x11-xserver-utils unclutter

cd "$BACKEND_DIR"
npm install --omit=dev

# Disable old browser kiosk service if present.
sudo systemctl disable led-kiosk.service >/dev/null 2>&1 || true
sudo systemctl stop led-kiosk.service >/dev/null 2>&1 || true

sudo systemctl enable led-backend.service
sudo systemctl restart led-backend.service

echo "Native LED controller installed in local simulator mode. Reboot to start automatically."
