#!/usr/bin/env bash
# Start the dashboard and open it. It fetches the phone's latest uploads from
# Google Drive itself, in the background, once the page is open.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

# Serve straight away; the page itself reads the phone's latest uploads from
# Drive in the background (/api/sync). Only a database with nothing in it --
# a fresh install -- is filled from the archive first.
if ! "$PY" -c "from wellbeing import db; import sys; sys.exit(0 if db.connect().execute('SELECT 1 FROM events LIMIT 1').fetchone() else 1)" 2>/dev/null; then
  echo "  First run: building the database from the archive (about 20 seconds)..."
  "$PY" -m wellbeing import || echo "  (couldn't read the archive -- starting empty)"
fi

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
