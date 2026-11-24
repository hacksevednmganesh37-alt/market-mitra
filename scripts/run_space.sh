#!/usr/bin/env bash
# Entry point for hosting Market Mitra on a Hugging Face Docker Space (or any single container).
# Runs the Market Analyst and Market Trader (restarted automatically if they ever exit)
# and the Mitra Desk web app on $PORT (Hugging Face uses 7860).
cd "$(dirname "$0")/.."
PORT="${PORT:-7860}"
mkdir -p work

keep_running() {  # $1 = python module
  while true; do
    python -m "$1"
    echo "[run_space] $1 exited, restarting in 5s" >&2
    sleep 5
  done
}

keep_running agents.analyst_agent &
keep_running agents.trader_agent &
exec uvicorn web.server:app --host 0.0.0.0 --port "$PORT"
