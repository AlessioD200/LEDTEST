#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/led-pi/native-controller"
AUTOSTART_DIR="$HOME/.config/autostart"

mkdir -p "$APP_DIR"
mkdir -p "$AUTOSTART_DIR"

cp /opt/led-pi/native-controller/app.py "$APP_DIR/app.py"
chmod +x "$APP_DIR/app.py"

cp /opt/led-pi/deploy/native-app/led-controller.desktop "$AUTOSTART_DIR/led-controller.desktop"

# Disable old browser kiosk service if present.
sudo systemctl disable led-kiosk.service >/dev/null 2>&1 || true
sudo systemctl stop led-kiosk.service >/dev/null 2>&1 || true

echo "Native LED controller installed. Reboot to start automatically."
