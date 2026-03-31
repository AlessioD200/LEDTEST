#!/usr/bin/env bash
set -u

# Touchscreen kiosk launcher for Raspberry Pi desktop session.
# Usage:
#   start-led-controller.sh [KIOSK_URL]
# Example:
#   start-led-controller.sh http://127.0.0.1:3001/

KIOSK_URL="${1:-http://127.0.0.1:3001/}"
DISPLAY_VAL="${DISPLAY:-:0}"
XAUTH_VAL="${XAUTHORITY:-$HOME/.Xauthority}"

export DISPLAY="$DISPLAY_VAL"
export XAUTHORITY="$XAUTH_VAL"

xset s off >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true

pkill -f "unclutter" >/dev/null 2>&1 || true
if command -v unclutter >/dev/null 2>&1; then
  unclutter -display "$DISPLAY" -noevents -grab >/dev/null 2>&1 &
fi

# Wait for backend URL briefly so Chromium does not open an immediate error page.
for _ in $(seq 1 25); do
  if curl -fsS "$KIOSK_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Relaunch Chromium if it crashes/closes.
while true; do
  /usr/bin/chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --touch-events=enabled \
    --overscroll-history-navigation=0 \
    --force-device-scale-factor=1.2 \
    --user-data-dir=/tmp/chromium-kiosk \
    --no-first-run \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-dev-shm-usage \
    "$KIOSK_URL"

  sleep 2
done
