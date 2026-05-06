#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

if [[ -d .git ]]; then
  git pull --ff-only || true
fi

chmod +x "$REPO_ROOT/pi-system/deploy/install-rpi3-local.sh"
"$REPO_ROOT/pi-system/deploy/install-rpi3-local.sh"
