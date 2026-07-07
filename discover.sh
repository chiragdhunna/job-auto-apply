#!/usr/bin/env bash
#
# discover.sh — run the DISCOVERY + SCORING pipeline (the LLM-heavy batch):
#   scrape ATS boards + web boards (+ LinkedIn/Indeed browser discovery if
#   toggled and logged in) → score everything new with the active LLM.
#
#   ./discover.sh          run ONE full cycle, then exit  (default)
#   ./discover.sh --loop   keep running on the run_interval_minutes cadence
#
# Kept separate from ./run.sh on purpose: batch scoring on Ollama is slow and
# CPU/GPU-hungry — running it on demand means it never competes with your
# interactive dashboard actions (tailor resume, outreach drafts).
# The dashboard (./run.sh) does NOT need to be running for this to work; both
# share the same SQLite database.
#
set -euo pipefail
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  if [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate   # Windows (Git Bash / MINGW)
  elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate       # Linux / macOS
  fi
fi

PY="${PYTHON:-python3}"

if [ ! -f ".env" ]; then
  echo "No .env found — creating one from .env.example. Edit it before real use."
  cp .env.example .env
fi

if [ "${1:-}" = "--loop" ]; then
  echo "Starting pipeline loop (interval from settings; Ctrl-C to stop)…"
  exec "$PY" -m scheduler.runner
else
  echo "Running ONE discovery + scoring cycle (this can take a while on Ollama)…"
  exec "$PY" -m scheduler.runner --once
fi
