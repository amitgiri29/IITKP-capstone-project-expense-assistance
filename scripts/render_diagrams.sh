#!/usr/bin/env bash
# Render architecture/diagrams/*.html to PNG with playwright-cli (localhost only), then trim margins.
# Usage: scripts/render_diagrams.sh   (needs: python3 -m http.server 8765 --bind 127.0.0.1 from the repo root)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${PLAYWRIGHT_SECURE_CONFIG:?set PLAYWRIGHT_SECURE_CONFIG to the playwright-cli secure-config.json}"
playwright-cli --config="$CONFIG" open about:blank >/dev/null
for page in "$ROOT"/architecture/diagrams/*.html; do
  name="$(basename "$page" .html)"
  playwright-cli resize 1680 1400 >/dev/null
  playwright-cli goto "http://127.0.0.1:8765/architecture/diagrams/$name.html" >/dev/null
  sleep 2
  playwright-cli screenshot --filename="$ROOT/architecture/diagrams/$name.png" >/dev/null
done
playwright-cli close >/dev/null
"$ROOT/.venv/bin/python" "$ROOT/scripts/trim_images.py" "$ROOT"/architecture/diagrams/*.png
