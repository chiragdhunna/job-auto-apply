#!/usr/bin/env bash
#
# run.sh — start the whole job-auto-apply system locally:
#   1. FastAPI backend   (http://localhost:8000)
#   2. APScheduler loop   (runs the pipeline on interval)
#   3. Streamlit dashboard (http://localhost:8501)
#
# All three are started as background processes; Ctrl-C stops all of them.
#
set -euo pipefail
cd "$(dirname "$0")"

# --- venv (optional) ------------------------------------------------------- #
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/Scripts/activate
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

# Give the API a moment to come up before the scheduler/dashboard hit it.
sleep 3

echo "Starting scheduler loop…"
"$PY" -m scheduler.runner &
pids+=($!)

echo "Starting Streamlit dashboard on :${DASHBOARD_PORT}…"
"$PY" -m streamlit run dashboard/app.py \
  --server.port "${DASHBOARD_PORT}" --server.address 0.0.0.0 &
pids+=($!)

echo ""
echo "──────────────────────────────────────────────────────────"
echo "  Backend   : http://localhost:${BACKEND_PORT}  (docs at /docs)"
echo "  Dashboard : http://localhost:${DASHBOARD_PORT}"
echo "  Scheduler : running (see logs/scheduler.log)"
echo "  Ctrl-C to stop everything."
echo "──────────────────────────────────────────────────────────"

# Wait on all background processes; if one dies, keep the others until Ctrl-C.
wait
