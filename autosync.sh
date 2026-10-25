#!/usr/bin/env bash
# Quiet, unattended sync. Safe to run on a schedule: if the archive isn't
# reachable, or another machine is mid-sync, it exits without doing anything.
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

# Refuse to run unattended against anything but the real shared archive.
# archive_dir() falls back to data/csv when Drive cannot be found, and a
# scheduled run that quietly exports there would exit 0, look like a success,
# and reach no other machine. A genuine archive always has archive.json; the
# fallback directory left over from an older setup may not, and either way it
# is not the one the other computer reads.
FALLBACK=$("$PY" -c "from wellbeing import archive; print(archive.LOCAL_FALLBACK)" 2>/dev/null)
if [ -n "${FALLBACK:-}" ] && [ "$ARCHIVE" = "$FALLBACK" ]; then
  echo "$(stamp) archive resolved to the local fallback ($ARCHIVE), not the shared one; skipping"
  exit 0
fi
if [ ! -f "$ARCHIVE/archive.json" ]; then
  echo "$(stamp) no archive.json in $ARCHIVE; refusing to start a fresh archive unattended"
  exit 0
fi

# Both laptops may be scheduled; a short-lived lock in the shared archive keeps
# them from exporting at the same moment and leaving Drive conflict copies.
LOCK="$ARCHIVE/sync.lock"
ME="$(hostname -s)"
if [ -f "$LOCK" ]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK") ))
  HOLDER=$(cat "$LOCK" 2>/dev/null)
  if [ "$AGE" -lt 900 ] && [ "$HOLDER" != "$ME" ]; then
    echo "$(stamp) $HOLDER is syncing (${AGE}s ago); skipping"; exit 0
  fi
fi
echo "$ME" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Pull down whatever the other machine has already archived, before deciding
# whether this one can reach the phone. Syncing and viewing are separate jobs:
# the dashboard reads the local database, so a laptop that never sees the phone
# would otherwise sit on stale numbers forever while the archive moved on.
# Costs a couple of seconds and is a no-op when nothing is new.
IMPORTED=$("$PY" -m wellbeing import 2>&1 | grep -oE "[0-9,]+ events \([0-9,]+ new\)" | head -1)
[ -n "$IMPORTED" ] && echo "$(stamp) archive -> local db: $IMPORTED"

# The phone collects and uploads to My Drive/PhoneUsage/phone on its own; this
# only reads what arrived. Nothing new is a quiet no-op.
echo "$(stamp) reading the phone's inbox on $ME"
"$PY" -m wellbeing ingest-phone 2>&1 | sed "s/^/$(stamp)   /"
echo "$(stamp) done"
