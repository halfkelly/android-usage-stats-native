#!/usr/bin/env bash
# Make sure the dashboard container is running, then open it. It reads the
# phone's latest uploads from Google Drive itself, once the page is open.
set -uo pipefail
cd "$(dirname "$0")"

docker compose up -d dashboard >/dev/null || { echo "  couldn't start the dashboard container (is Docker running?)"; exit 1; }
for _ in $(seq 1 30); do
  curl -sf -o /dev/null http://127.0.0.1:5000/ && break
  sleep 1
done
curl -sf -o /dev/null http://127.0.0.1:5000/ || { echo "  the dashboard didn't answer -- docker compose logs dashboard"; exit 1; }

echo ""
echo "  Dashboard at http://127.0.0.1:5000"
command -v wslview >/dev/null && wslview http://127.0.0.1:5000
