#!/usr/bin/env bash
# Refresh this machine's database from the shared archive, then serve it.
# No phone needed -- this is how a second computer views the dashboard.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

"$PY" -m wellbeing import || echo "  (couldn't read the shared archive -- serving what's already local)"

pkill -f "wellbeing serve" 2>/dev/null
sleep 1
nohup "$PY" -m wellbeing serve > data/serve.log 2>&1 &

for _ in $(seq 1 15); do
  curl -sf -o /dev/null http://127.0.0.1:5000/ && break
  sleep 1
done

echo ""
echo "  Dashboard at http://127.0.0.1:5000"
command -v open >/dev/null && open http://127.0.0.1:5000
command -v wslview >/dev/null && wslview http://127.0.0.1:5000
