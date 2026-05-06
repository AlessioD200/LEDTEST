#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/pi-system/backend"

cd "$REPO_ROOT"
git pull --ff-only

cd "$BACKEND_DIR"
npm install --omit=dev

sudo systemctl restart led-backend.service
sudo systemctl restart led-kiosk.service || true

echo "Update complete."
