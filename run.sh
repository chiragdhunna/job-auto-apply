#!/usr/bin/env bash
#
# run.sh — start the INTERACTIVE app:
#   1. FastAPI backend    (http://localhost:8000)
#   2. Streamlit dashboard (http://localhost:8501)
#
# The discovery/scoring pipeline is deliberately NOT started here — run it
# separately with ./discover.sh so batch LLM work (slow on Ollama) never
# competes with your interactive clicks (tailor resume, score one job, drafts).
# Ctrl-C stops both processes.
#
set -euo pipefail
cd "$(dirname "$0")"

# --- venv (optional) ------------------------------------------------------- #
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  if [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate   # Windows (Git Bash / MINGW)
  elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate       # Linux / macOS
  fi
fi

PY="${PYTHON:-python3}"

# --- first-run helpers ----------------------------------------------------- #
if [ ! -f ".env" ]; then
  echo "No .env found — creating one from .env.example. Edit it before real use."
  cp .env.example .env
fi

echo "Initializing database…"
"$PY" init_db.py

BACKEND_PORT="${BACKEND_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8501}"
export BACKEND_URL="${BACKEND_URL:-http://localhost:${BACKEND_PORT}}"

pids=()
cleanup() {
  echo ""
  echo "Shutting down…"
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting FastAPI backend on :${BACKEND_PORT}…"
"$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
pids+=($!)

sleep 3

echo "Starting Streamlit dashboard on :${DASHBOARD_PORT}…"
"$PY" -m streamlit run dashboard/app.py \
  --server.port "${DASHBOARD_PORT}" --server.address 0.0.0.0 &
pids+=($!)

echo ""
echo "──────────────────────────────────────────────────────────"
echo "  Backend   : http://localhost:${BACKEND_PORT}  (docs at /docs)"
echo "  Dashboard : http://localhost:${DASHBOARD_PORT}"
echo ""
echo "  Fresh jobs?  ./discover.sh          (one discovery+scoring cycle)"
echo "               ./discover.sh --loop   (keep running on the interval)"
echo "  Ctrl-C to stop."
echo "──────────────────────────────────────────────────────────"

wait
