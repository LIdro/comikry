#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Comikry — start script
#  Usage: ./start.sh [--prod] [--host HOST] [--port PORT]
#
#  Defaults: development mode on 0.0.0.0:8000
#  Pass --prod for production (no auto-reload, 4 workers).
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Defaults ────────────────────────────────────────────────
MODE="dev"
HOST="0.0.0.0"
PORT="8000"

# ── Parse args ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)   MODE="prod"; shift ;;
    --host)   HOST="$2";   shift 2 ;;
    --port)   PORT="$2";   shift 2 ;;
    *)        echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Virtual environment ─────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
UVICORN="$VENV_DIR/bin/uvicorn"
PIP="$VENV_DIR/bin/pip"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "► Creating virtual environment …"
  python3 -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# ── Dependencies ─────────────────────────────────────────────
echo "► Installing / verifying dependencies …"
"$PIP" install -q -r requirements.txt

# ── .env check ───────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo ""
  echo "⚠️  No .env file found."
  echo "   Copy .env.example → .env and set your OPENROUTER_API_KEY."
  echo "   Example:"
  echo "     cp .env.example .env"
  echo ""
  exit 1
fi

if grep -qE "OPENROUTER_API_KEY=your_openrouter_api_key_here|OPENROUTER_API_KEY=YOUR_KEY_HERE" "$SCRIPT_DIR/.env" 2>/dev/null; then
  echo ""
  echo "⚠️  OPENROUTER_API_KEY is still the placeholder value."
  echo "   Edit .env and set a real key before starting."
  echo ""
  exit 1
fi

# ── Storage dir ──────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/storage"

# ── Launch ───────────────────────────────────────────────────
echo ""
if [[ "$MODE" == "prod" ]]; then
  echo "🚀  Starting Comikry in PRODUCTION mode on http://$HOST:$PORT"
  exec "$UVICORN" backend.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers 4
else
  echo "🚀  Starting Comikry in DEVELOPMENT mode on http://$HOST:$PORT"
  echo "    (auto-reload enabled — do not use in production)"
  exec "$UVICORN" backend.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload
fi
