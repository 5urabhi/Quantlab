#!/usr/bin/env bash
# Local-only React/Vite frontend with Python FastAPI research engine.
# No external deployment, broker orders, or Redis/Docker service.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

info() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Preserve the existing Ubuntu setup logic; it installs Node/npm and a Python
# virtual environment and runs a TypeScript build before starting any servers.
info "Preparing Python and React environments"
bash scripts/start.sh setup

test -x .venv/bin/uvicorn || fail "FastAPI dependencies missing from .venv"
# Setup runs in a CHILD shell, so its PATH changes are not inherited.
# Re-select exactly the same verified Node/npm pair in this parent process.
# Offline mode only: the setup stage already downloaded it if necessary.
source "$ROOT/scripts/node_runtime.sh"
quantlab_activate_node_runtime "$ROOT" offline ||
  fail "Node/npm toolchain not available after setup"
info "Serving with Node $(node --version) and npm $(npm --version)"

API_PID=""
cleanup() {
  if [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

info "Starting local Python research API at http://127.0.0.1:8765"
# Disable raw HTTP access logs: Kite's one-use request_token appears in a
# local OAuth callback query string; that value must never reach console logs.
.venv/bin/uvicorn workstation_api.app:app --host 127.0.0.1 --port 8765 --no-access-log &
API_PID=$!
# On existing market libraries, importing analytics and reconciling the
# source-backed SQLite tables can take longer than 10 seconds. Do not kill
# a healthy worker solely because application startup took slightly longer.
# A wall-clock deadline prevents every curl request from extending the wait.
API_READY_TIMEOUT_SECONDS="${QUANTLAB_API_READY_TIMEOUT_SECONDS:-120}"
case "$API_READY_TIMEOUT_SECONDS" in
  ''|*[!0-9]*) fail "QUANTLAB_API_READY_TIMEOUT_SECONDS must be 10–600" ;;
esac
if [ "$API_READY_TIMEOUT_SECONDS" -lt 10 ] ||
   [ "$API_READY_TIMEOUT_SECONDS" -gt 600 ]; then
  fail "QUANTLAB_API_READY_TIMEOUT_SECONDS must be 10–600"
fi
API_READY_DEADLINE=$((SECONDS + API_READY_TIMEOUT_SECONDS))
API_LAST_STATUS_AT=$SECONDS
while :; do
  kill -0 "$API_PID" 2>/dev/null ||
    fail "Python API exited during startup; check the FastAPI error above"
  if curl --fail --silent --max-time 3 \
      http://127.0.0.1:8765/api/health >/dev/null; then
    break
  fi
  if [ "$SECONDS" -ge "$API_READY_DEADLINE" ]; then
    fail "Python API health endpoint still unavailable after ${API_READY_TIMEOUT_SECONDS}s; check FastAPI logs above. Use two terminals to start the API separately for diagnosis."
  fi
  if [ $((SECONDS - API_LAST_STATUS_AT)) -ge 15 ]; then
    info "Python API still starting; large saved market databases can delay readiness"
    API_LAST_STATUS_AT=$SECONDS
  fi
  sleep 1
done
info "Python API healthy; starting browser UI"

info "Starting the React/Vite RESEARCH WORKSTATION"
info "Open http://127.0.0.1:5173"
info "Press Ctrl+C to stop both local servers"
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
