#!/usr/bin/env bash
# Quiet, unattended sync. Safe to run on a schedule: if the phone isn't on the
# network, or another machine is mid-sync, it exits without doing anything.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
LOG=data/autosync.log
mkdir -p data
exec >>"$LOG" 2>&1
stamp() { date "+%Y-%m-%d %H:%M:%S"; }

# keep the log to the last ~500 lines
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 800 ] && tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

ARCHIVE=$("$PY" -c "from wellbeing import archive; print(archive.archive_dir())" 2>/dev/null)
if [ -z "${ARCHIVE:-}" ] || [ ! -d "$ARCHIVE" ]; then
  echo "$(stamp) archive not reachable; skipping"; exit 0
fi

# Both laptops may be scheduled; a short-lived lock in the shared archive keeps
# them from exporting at the same moment and leaving Drive conflict copies.
LOCK="$ARCHIVE/sync.lock"
ME="$(hostname -s)"
if [ -f "$LOCK" ]; then
  AGE=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK") ))
  HOLDER=$(cat "$LOCK" 2>/dev/null)
  if [ "$AGE" -lt 900 ] && [ "$HOLDER" != "$ME" ]; then
    echo "$(stamp) $HOLDER is syncing (${AGE}s ago); skipping"; exit 0
  fi
fi
echo "$ME" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

if ! "$PY" -m wellbeing connect >/dev/null 2>&1; then
  echo "$(stamp) phone not on this network; skipping"; exit 0
fi

echo "$(stamp) syncing from $ME"
"$PY" -m wellbeing deep-sync && "$PY" -m wellbeing export | tail -1
echo "$(stamp) done"
