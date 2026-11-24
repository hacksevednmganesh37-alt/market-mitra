#!/usr/bin/env bash
# Start the Market Analyst, the Market Trader and Mitra Desk (web app on port 8000) in the background.
cd "$(dirname "$0")/.."

# BAND agent identities. If the MITRA_* secrets are not set, reuse the two BAND agents
# created earlier for VTU Exam Radar (same room). Names must match the names in BAND.
if [ -z "$MITRA_ANALYST_ID" ] && [ -n "$RADAR_DATA_ID" ]; then
  export MITRA_ANALYST_ID="$RADAR_DATA_ID" MITRA_ANALYST_KEY="$RADAR_DATA_KEY"
  export MITRA_ANALYST_NAME="${MITRA_ANALYST_NAME:-Radar Data}"
fi
if [ -z "$MITRA_TRADER_ID" ] && [ -n "$RADAR_BUILDER_ID" ]; then
  export MITRA_TRADER_ID="$RADAR_BUILDER_ID" MITRA_TRADER_KEY="$RADAR_BUILDER_KEY"
  export MITRA_TRADER_NAME="${MITRA_TRADER_NAME:-Radar Builder}"
fi

# one BAND agent can only run once, so stop any older copies (including VTU Exam Radar's agents)
PROCS='agents\.analyst_agent|agents\.trader_agent|agents\.data_agent|agents\.builder_agent|uvicorn web\.server'
pkill -f "$PROCS" 2>/dev/null
for _ in $(seq 1 10); do pgrep -f "$PROCS" >/dev/null || break; sleep 1; done
pkill -9 -f "$PROCS" 2>/dev/null
rm -f /tmp/band-agent-* 2>/dev/null
sleep 1

nohup uv run python -m agents.analyst_agent > /tmp/analyst.log 2>&1 &
nohup uv run python -m agents.trader_agent > /tmp/trader.log 2>&1 &
nohup uv run uvicorn web.server:app --host 0.0.0.0 --port 8000 > /tmp/desk.log 2>&1 &
sleep 8
if [ -n "$CODESPACE_NAME" ]; then
  gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" >/dev/null 2>&1 || true
  echo "Web app: https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
fi
echo "Agents running: $(pgrep -fc 'python -m agents\.(analyst|trader)_agent') (expect 4: 2 agents + 2 uv wrappers)"
grep -h "Uvicorn running" /tmp/desk.log
echo "Logs: /tmp/analyst.log /tmp/trader.log /tmp/desk.log"
