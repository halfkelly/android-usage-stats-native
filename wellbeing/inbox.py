"""The phone's own uploads: My Drive/PhoneUsage/phone/.

The companion app collects every 6 hours and uploads, with no computer
involved (android/DRIVE_SETUP.md). Drive for desktop brings the folder here:

    PhoneUsage/phone/
      events/events-YYYY-MM-DD.csv       one local day; rewritten until the day is over
      snapshots/buckets-YYYY-MM-DD.csv   the phone's buckets as of that day's last run
      snapshots/eventstats-...csv, configs-...csv
      device.json                        timezone, device, last collection

`ingest_inbox` reads what changed since the last run into usage.db. The inbox is
the phone's, read-only from here: the shared archive (PhoneUsage/archive/) is
still what `export` writes and every machine imports.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import appdump, archive, db, labels

FOLDER_NAME = "phone"                 # inside archive.PROJECT_FOLDER
LEGACY_FOLDER_NAME = "PhoneUsageInbox"  # the app's first layout, at the top of My Drive
ENV_VAR = "PHONE_USAGE_INBOX"
SNAPSHOT_KINDS = ("buckets", "eventstats", "configs")
_DAY_FILE = re.compile(r"^(?P<kind>[a-z]+)-(?P<day>\d{4}-\d{2}-\d{2})(?: \(\d+\))?\.csv$")


def inbox_dir() -> Path | None:
    """`PHONE_USAGE_INBOX`, else beside an overridden archive, else in My Drive/PhoneUsage."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    if os.environ.get(archive.ENV_VAR):
        overridden = Path(os.environ[archive.ENV_VAR]).expanduser()
        if overridden.name == archive.LEGACY_FOLDER_NAME:
            # The old top-level archive: its parent is My Drive itself.
            return archive.project_path(overridden.parent, FOLDER_NAME, LEGACY_FOLDER_NAME)
        return overridden.parent / FOLDER_NAME
    root = archive.drive_root()
    return archive.project_path(root, FOLDER_NAME, LEGACY_FOLDER_NAME) if root else None


def read_device(inbox: Path) -> dict:
    try:
        return json.loads((inbox / "device.json").read_text())
    except (OSError, ValueError):
        return {}


# The phone collects every 6 h; a day with nothing new means it has stopped
# (sign-in expired, access removed, One UI killing it) -- and its raw events
# only last ~10 days, so this is worth saying out loud.
STALE_MS = 24 * 3_600_000


def staleness(inbox: Path | None) -> str | None:
    """A warning when the phone hasn't uploaded for a day, else None."""
    if inbox is None or not inbox.is_dir():
        return "nothing from the phone yet -- is the app connected to Google Drive?"
    collected = read_device(inbox).get("collected_at_ms")
    if not collected:
        return None
    age = int(time.time() * 1000) - collected
    if age <= STALE_MS:
        return None
    return (f"the phone hasn't uploaded for {age // 3_600_000} hours -- open Usage Dump "
            f"on the phone to see why (it keeps raw events only ~10 days)")


def _day_files(folder: Path) -> list[tuple[str, str, Path]]:
    """[(kind, day, path)] oldest day first. Drive's own "name (1).csv" copies are kept:
    they are another upload of the same day, and the dedup makes them harmless."""
    out = []
    if folder.is_dir():
        for p in folder.iterdir():
            m = _DAY_FILE.match(p.name)
            if m:
                out.append((m["kind"], m["day"], p))
    return sorted(out, key=lambda t: (t[1], t[2].name))


def _changed(conn, inbox: Path, path: Path) -> bool:
    st = path.stat()
    row = conn.execute("SELECT mtime_ns, size FROM inbox_files WHERE path = ?",
                       (str(path.relative_to(inbox)),)).fetchone()
    return row is None or (row["mtime_ns"], row["size"]) != (st.st_mtime_ns, st.st_size)


def _mark(conn, inbox: Path, path: Path) -> None:
    st = path.stat()
    conn.execute(
        "INSERT OR REPLACE INTO inbox_files (path, mtime_ns, size, ingested_ms) VALUES (?, ?, ?, ?)",
        (str(path.relative_to(inbox)), st.st_mtime_ns, st.st_size, int(time.time() * 1000)))


def ingest_inbox(conn, inbox: Path, *, fetch_labels: bool = False, everything: bool = False) -> dict:
    """Ingest every changed day file, then the newest snapshots.

    Android moves its whole stored history when the phone's clock is corrected,
    so the shift is measured once, over everything that changed, and undone on
    all of it -- a new day has nothing stored to measure against but is in the
    same moved frame. Each day file is then inserted as its own capture and
    refused on its own (the rest still go in) if it would still rewrite that
    day's stored history. A refused file is not marked, so it is retried.
    """
    from .sync import rebuild

    if not inbox.is_dir():
        raise FileNotFoundError(f"No phone inbox at {inbox}")
    batch = []
    for kind, _day, path in _day_files(inbox / "events"):
        if kind == "events" and (everything or _changed(conn, inbox, path)):
            batch.append((path, appdump.parse_events(path)))
    shift = appdump.detect_clock_shift(conn, [e for _, evs in batch for e in evs])
    if shift:
        appdump.apply_shift(shift, [e for _, evs in batch for e in evs], [], [], [])

    seen = added = 0
    files = []
    refused: list[str] = []
    lo = hi = None
    for path, events in batch:
        if not events:
            _mark(conn, inbox, path)
            continue
        first, last = min(e.ts_ms for e in events), max(e.ts_ms for e in events)
        try:
            n = db.insert_phone_events(conn, events, window=(first, last))
        except db.OverlapError as exc:
            refused.append(f"{path.name}: {exc}")
            continue
        _mark(conn, inbox, path)
        files.append(path.name)
        seen += len(events)
        added += n
        lo = first if lo is None else min(lo, first)
        hi = last if hi is None else max(hi, last)

    # Each snapshot holds everything the phone still has, so only the newest of
    # each kind matters. It is in the same frame as the events, so the same shift.
    snaps = {}
    for kind, _day, path in _day_files(inbox / "snapshots"):
        if kind in SNAPSHOT_KINDS:
            snaps[kind] = path  # sorted oldest first, so the newest wins
    snap_counts = {k: 0 for k in SNAPSHOT_KINDS}
    buckets, estats, configs = [], [], []
    if "buckets" in snaps and (everything or _changed(conn, inbox, snaps["buckets"])):
        buckets = appdump.parse_buckets(snaps["buckets"])
    if "eventstats" in snaps and (everything or _changed(conn, inbox, snaps["eventstats"])):
        estats = appdump.parse_event_stats(snaps["eventstats"])
    if "configs" in snaps and (everything or _changed(conn, inbox, snaps["configs"])):
        configs = appdump.parse_config_stats(snaps["configs"])
    if shift:
        appdump.apply_shift(shift, [], buckets, estats, configs)
    db.insert_interval_stats(conn, buckets)
    db.insert_event_stats(conn, estats)
    db.insert_config_stats(conn, configs)
    snap_counts.update(buckets=len(buckets), eventstats=len(estats), configs=len(configs))
    for kind, rows in (("buckets", buckets), ("eventstats", estats), ("configs", configs)):
        if rows:
            _mark(conn, inbox, snaps[kind])

    if lo is not None:
        rebuild(conn, lo, hi)

    packages = ({r[0] for r in conn.execute(
        "SELECT DISTINCT package FROM events WHERE ts_ms BETWEEN ? AND ? AND package != ''",
        (lo, hi))} if lo is not None else set()) | {b.package for b in buckets}
    if packages:
        known = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
        db.upsert_labels(conn, labels.resolve(sorted(packages), known=known, fetch=fetch_labels))

    device = read_device(inbox)
    if files:
        db.record_sync(conn, device=device.get("device") or "phone-inbox",
                       android=device.get("android", ""), events_seen=seen, events_added=added,
                       first_ts_ms=lo, last_ts_ms=hi)
    return {"source": str(inbox), "files": files, "events_seen": seen, "events_added": added,
            "refused": refused, "clock_shift_ms": shift, "snapshots": snap_counts,
            "device": device}
