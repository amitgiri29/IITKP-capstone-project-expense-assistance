#!/usr/bin/env bash
# Start the API and the UI together, wait until both are healthy, open the browser.
# Press Ctrl+C to stop both. Logs: runtime/logs/api.log and runtime/logs/ui.log
#
#   bash run.sh                              # ports 8000 (API) and 8501 (UI)
#   EA_API_PORT=8100 EA_UI_PORT=8601 bash run.sh
#   EA_NO_BROWSER=1 bash run.sh              # do not open a browser
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
API_PORT="${EA_API_PORT:-8000}"
UI_PORT="${EA_UI_PORT:-8501}"
VPY="$ROOT/.venv/bin/python"
[ -x "$VPY" ] || { echo "No .venv found. Run: bash setup.sh"; exit 1; }

port_busy() { "$VPY" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', $1)) == 0 else 1)"; }
for port in "$API_PORT" "$UI_PORT"; do
  if port_busy "$port"; then
    echo "Port $port is already in use (is the app already running?)."
    echo "Stop the other process, or pick other ports: EA_API_PORT=8100 EA_UI_PORT=8601 bash run.sh"
    exit 1
  fi
done

wait_for() {  # wait_for URL SECONDS PID NAME
  local i
  for i in $(seq 1 "$2"); do
    if "$VPY" -c "import urllib.request,sys; urllib.request.urlopen('$1', timeout=2)" 2>/dev/null; then return 0; fi
    kill -0 "$3" 2>/dev/null || { echo "$4 exited during startup. Last log lines:"; tail -20 "runtime/logs/$4.log"; return 1; }
    sleep 1
  done
  echo "$4 did not become healthy within $2 s. See runtime/logs/$4.log"; return 1
}

mkdir -p runtime/logs
API_PID=""; UI_PID=""
cleanup() {
  trap - INT TERM EXIT
  echo; echo "Stopping…"
  [ -n "$UI_PID" ] && kill "$UI_PID" 2>/dev/null || true
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "Stopped."
}
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

echo "Starting API on http://127.0.0.1:$API_PORT (first start may download the embedding model)…"
"$VPY" -m uvicorn api.main:app --host 127.0.0.1 --port "$API_PORT" >runtime/logs/api.log 2>&1 &
API_PID=$!
wait_for "http://127.0.0.1:$API_PORT/health" 240 "$API_PID" api

echo "Starting UI on http://127.0.0.1:$UI_PORT …"
EXPENSE_API_BASE_URL="http://127.0.0.1:$API_PORT" "$VPY" -m streamlit run ui/app.py \
  --server.port "$UI_PORT" --server.address 127.0.0.1 --server.headless true \
  --browser.gatherUsageStats false >runtime/logs/ui.log 2>&1 &
UI_PID=$!
wait_for "http://127.0.0.1:$UI_PORT/_stcore/health" 60 "$UI_PID" ui

STATUS="$("$VPY" - "$API_PORT" <<'PY' 2>/dev/null || true
import json, sys, urllib.error, urllib.request
try:
    body = json.load(urllib.request.urlopen('http://127.0.0.1:%s/ready' % sys.argv[1], timeout=5))
except urllib.error.HTTPError as error:  # 503 lists the failing components
    body = json.load(error)
c = body.get('components', {})
model, emb = c.get('model', {}), c.get('embeddings', {})
print('AI %s (%s) · search %s' % ('online' if model.get('ok') else 'offline', model.get('provider', '?'),
                                  emb.get('retrieval_mode', '?')))
PY
)"

cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
    SPARKS AI Lab · Expense Policy Assistant is running
    Open:   http://127.0.0.1:$UI_PORT
    API:    http://127.0.0.1:$API_PORT   (health: /health, /ready)
    Status: ${STATUS:-unknown}
    Logs:   runtime/logs/api.log, runtime/logs/ui.log
    Stop:   press Ctrl+C in this window
  └──────────────────────────────────────────────────────────────┘

EOF
if [ -z "${EA_NO_BROWSER:-}" ]; then
  if command -v open >/dev/null 2>&1; then open "http://127.0.0.1:$UI_PORT"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:$UI_PORT" >/dev/null 2>&1 || true; fi
fi

# Keep running until either process exits or the user presses Ctrl+C.
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do sleep 2; done
echo "A server stopped unexpectedly. See runtime/logs/."
exit 1
