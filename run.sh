#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

ROOT="$(pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Stopping TRADELE..."
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  # Kill anything still holding the ports (uvicorn reloader children, etc.)
  lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

if [[ -z "$VIRTUAL_ENV" ]]; then
  if [[ -d .venv ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    echo "Create venv first: python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
fi

if [[ ! -d UI/node_modules ]]; then
  echo "Installing UI dependencies..."
  (cd UI && npm install)
fi

# Cursor/sandbox injects HTTP(S)_PROXY to a local tunnel that 403s api.kite.trade.
# Clear proxies so Zerodha OAuth and market data work.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy
unset GIT_HTTP_PROXY GIT_HTTPS_PROXY
export NO_PROXY='*'
export no_proxy='*'

echo "Starting backend  → http://localhost:8000"
uvicorn TRADELE.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Starting frontend → http://localhost:5173"
(cd UI && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "TRADELE running. Press Ctrl+C to stop both."
echo "  API:  http://localhost:8000"
echo "  UI:   http://localhost:5173"
echo ""

wait
