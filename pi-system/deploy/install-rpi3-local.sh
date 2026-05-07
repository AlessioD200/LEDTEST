#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PI_SYSTEM_DIR="$PROJECT_ROOT/pi-system"
BACKEND_DIR="$PI_SYSTEM_DIR/backend"
ENV_FILE="$BACKEND_DIR/.env"
APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
APP_HOME="$HOME"
PORT="${LED_PORT:-3001}"
KIOSK_URL="http://127.0.0.1:${PORT}/"
LED_COUNT_VALUE="${LED_COUNT:-144}"
LED_BRIGHTNESS_VALUE="${LED_BRIGHTNESS:-255}"
SPI_BUS_VALUE="${SPI_BUS:-0}"
SPI_DEVICE_VALUE="${SPI_DEVICE:-0}"
PIR_GPIO_PIN_VALUE="${PIR_GPIO_PIN:-}"

set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

ensure_chromium() {
  if command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
    return
  fi
  sudo apt install -y chromium-browser || sudo apt install -y chromium
}

cat <<EOF
Installing Raspberry Pi local LED controller
Project root: $PROJECT_ROOT
User: $APP_USER
Backend port: $PORT
EOF

sudo apt update
sudo apt install -y nodejs npm python3 python3-pip curl x11-xserver-utils unclutter
ensure_chromium
# Enable hardware SPI if not already active
if ! grep -q '^dtparam=spi=on' /boot/config.txt 2>/dev/null && \
   ! grep -q '^dtparam=spi=on' /boot/firmware/config.txt 2>/dev/null; then
  BOOT_CFG=""
  [[ -f /boot/firmware/config.txt ]] && BOOT_CFG=/boot/firmware/config.txt || BOOT_CFG=/boot/config.txt
  echo "dtparam=spi=on" | sudo tee -a "$BOOT_CFG" >/dev/null
  echo "SPI enabled in $BOOT_CFG — a reboot will be required before first use."
fi
sudo python3 -m pip install --break-system-packages spidev RPi.GPIO

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$BACKEND_DIR/.env.example" "$ENV_FILE"
fi

set_env PORT "$PORT"
set_env DEVICE_MODE local-pi
set_env PYTHON_BIN /usr/bin/python3
set_env LED_COUNT "$LED_COUNT_VALUE"
set_env LED_BRIGHTNESS "$LED_BRIGHTNESS_VALUE"
set_env SPI_BUS "$SPI_BUS_VALUE"
set_env SPI_DEVICE "$SPI_DEVICE_VALUE"
if [[ -n "$PIR_GPIO_PIN_VALUE" ]]; then
  set_env PIR_GPIO_PIN "$PIR_GPIO_PIN_VALUE"
fi

chmod +x "$PI_SYSTEM_DIR/deploy/kiosk/start-led-controller.sh"
chmod +x "$PI_SYSTEM_DIR/local-device/rpi_led_bridge.py"

cd "$BACKEND_DIR"
npm install --omit=dev

sudo tee /etc/systemd/system/led-backend.service >/dev/null <<EOF
[Unit]
Description=LED Pi Backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BACKEND_DIR
Environment=NODE_ENV=production
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/node $BACKEND_DIR/src/index.js
Restart=always
RestartSec=3
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/led-kiosk.service >/dev/null <<EOF
[Unit]
Description=LED Touch Kiosk
After=graphical.target led-backend.service
Requires=led-backend.service

[Service]
Type=simple
User=$APP_USER
Environment=DISPLAY=:0
Environment=XAUTHORITY=$APP_HOME/.Xauthority
ExecStart=/usr/bin/env bash $PI_SYSTEM_DIR/deploy/kiosk/start-led-controller.sh $KIOSK_URL
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable led-backend.service
sudo systemctl restart led-backend.service
sudo systemctl enable led-kiosk.service
sudo systemctl restart led-kiosk.service || true

echo
echo "Installed. Backend: $KIOSK_URL"
echo "Check backend: sudo systemctl status led-backend.service"
echo "Check kiosk:   sudo systemctl status led-kiosk.service"
echo "Open dashboard in a browser if the kiosk is not active yet: $KIOSK_URL"