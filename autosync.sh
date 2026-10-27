#!/usr/bin/env bash
# Quiet, unattended sync: read what the phone uploaded to Drive into the
# database and the archive. Runs in the `sync` container (docker compose run
# --rm sync), started by the Windows task PhoneUsageAutosync. If the archive
# isn't reachable, or a run is already going, it exits without doing anything.
set -uo pipefail
cd "$(dirname "$0")"
PY=${PY:-python}
LOG=data/autosync.log
mkdir -p data
exec >>"$LOG" 2>&1
stamp() { date "+%Y-%m-%d %H:%M:%S"; }

# keep the log to the last ~500 lines
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 800 ] && tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

# One run at a time, even if the task fires while a slow one is still going.
exec 9>data/.autosync.lock
flock -n 9 || { echo "$(stamp) a sync is already running; skipping"; exit 0; }

INBOX=$("$PY" -c "from wellbeing import inbox; print(inbox.inbox_dir() or '')" 2>/dev/null)
if [ -z "${INBOX:-}" ] || [ ! -d "$INBOX" ]; then
  echo "$(stamp) no phone uploads at ${INBOX:-My Drive/PhoneUsage/phone} yet (is Google Drive running, and the phone app connected?); skipping"
  exit 0
fi
ARCHIVE=$("$PY" -c "from wellbeing import archive; print(archive.archive_dir())" 2>/dev/null)

# A fresh machine starts from the archive, if there is one; a brand-new archive
# is created in the phone's timezone by the first ingest (inbox.bootstrap_archive).
if [ -f "$ARCHIVE/archive.json" ] && [ -d "$ARCHIVE/events" ] && \
   ! "$PY" -c "from wellbeing import db; import sys; sys.exit(0 if db.connect().execute('SELECT 1 FROM events LIMIT 1').fetchone() else 1)"; then
  echo "$(stamp) empty database: importing the archive"
  "$PY" -m wellbeing import 2>&1 | sed "s/^/$(stamp)   /"
fi

# The phone collects and uploads to My Drive/PhoneUsage/phone on its own; this
# only reads what arrived. Nothing new is a quiet no-op.
echo "$(stamp) reading the phone's uploads"
"$PY" -m wellbeing ingest-phone 2>&1 | sed "s/^/$(stamp)   /"
echo "$(stamp) done"
