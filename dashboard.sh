#!/usr/bin/env bash
# Refresh this machine's database from the shared archive and the phone's
# Drive inbox, then serve it. The phone never needs to be connected.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

"$PY" -m wellbeing import || echo "  (couldn't read the shared archive -- serving what's already local)"
# Then whatever the phone uploaded since, which also updates the archive.
"$PY" -m wellbeing ingest-phone || echo "  (no new phone data read -- see above)"

pkill -f "wellbeing serve" 2>/dev/null
sleep 1
nohup "$PY" -m wellbeing serve > data/serve.log 2>&1 &

for _ in $(seq 1 15); do
  curl -sf -o /dev/null http://127.0.0.1:5000/ && break
  sleep 1
done

echo ""
echo "  Dashboard at http://127.0.0.1:5000"
command -v wslview >/dev/null && wslview http://127.0.0.1:5000
