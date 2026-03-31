#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_REL="pi-system/native-controller/app_kivy.py"
APP_LOCAL="$ROOT_DIR/$APP_REL"

PI_USER="${1:-ledvives}"
PI_HOST="${2:-192.168.0.93}"
PI_TARGET="/home/$PI_USER/LEDTEST/pi-system/native-controller/app_kivy.py"

echo "[1/5] Compile check"
python3 -m py_compile "$APP_LOCAL"

echo "[2/5] Upload to Pi /tmp"
scp "$APP_LOCAL" "$PI_USER@$PI_HOST:/tmp/app_kivy.py"

echo "[3/5] Copy to target + restart"
ssh -t "$PI_USER@$PI_HOST" "
  cp /tmp/app_kivy.py '$PI_TARGET' &&
  pkill -f 'python3 .*native-controller/app_kivy.py' || true
  nohup env DISPLAY=:0 XAUTHORITY=/home/$PI_USER/.Xauthority \
    python3 '$PI_TARGET' >/tmp/led-native.log 2>&1 &
"

echo "[4/5] Process check"
ssh "$PI_USER@$PI_HOST" "pgrep -af 'native-controller/app_kivy.py' || true"

echo "[5/5] Log check"
ssh "$PI_USER@$PI_HOST" "tail -n 60 /tmp/led-native.log || echo 'Geen logbestand gevonden (app mogelijk niet gestart in desktop sessie). '"

echo "Klaar. Als je een display-fout ziet, start de app via desktop-autostart op de Pi."
