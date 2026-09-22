"""Pull a dump off the phone, ingest it, and rebuild the derived tables."""
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import adb, db, labels
from .parse import Event, foreground_sessions, parse_dump

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"

# Only these are needed to rebuild sessions; the rest are stored anyway because
# they are cheap and answer questions like "how many notifications today".
SESSION_TYPES = (
    "ACTIVITY_RESUMED", "ACTIVITY_PAUSED", "ACTIVITY_STOPPED",
    "SCREEN_INTERACTIVE", "SCREEN_NON_INTERACTIVE",
    "KEYGUARD_SHOWN", "KEYGUARD_HIDDEN",
)

HOUR_MS = 3_600_000
LOOKBACK_MS = 6 * HOUR_MS  # enough context to close a session opened before the window


def day_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def day_start_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day).timestamp() * 1000)


def backup_db(conn: sqlite3.Connection) -> Path | None:
    """Copy the database aside before a sync writes to it.

    The database is the only place hour- and session-level history lives once
    the phone has pruned its events, so every write gets a one-file undo.
    """
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if not path:
        return None
    src = Path(path)
    if not src.exists():
        return None
    dst = src.with_suffix(src.suffix + ".bak")
    # sqlite3's own backup API is used rather than a file copy so the snapshot
    # is consistent even with a write-ahead log pending.
    with sqlite3.connect(dst) as out:
        conn.backup(out)
    return dst


def sync(conn: sqlite3.Connection, serial: str | None = None, *,
         fetch_labels: bool = False, keep_raw: bool = True) -> dict:
    """Capture from the attached device and ingest. Returns a summary dict."""
    backup_db(conn)
    serial = adb.require_device(serial)
    device = adb.device_name(serial)
    android = adb.android_release(serial)
    text = adb.dump_usagestats(serial)

    if keep_raw:
        RAW_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        (RAW_DIR / f"dump-{stamp}.txt").write_text(text)

    summary = ingest(conn, text, device=device, android=android, fetch_labels=fetch_labels)
    summary["device"] = device
    summary["serial"] = serial
    return summary


def ingest(conn: sqlite3.Connection, text: str, *, device: str = "", android: str = "",
           fetch_labels: bool = False) -> dict:
    """Ingest a dump's text. Safe to re-run on the same dump."""
    dump = parse_dump(text)
    if not dump.events and not dump.stats:
        raise ValueError("dump contained no usage stats for user 0")

    added = db.insert_events(conn, dump.events)
    db.insert_interval_stats(conn, dump.stats)

    first_ts = min((e.ts_ms for e in dump.events), default=None)
    last_ts = max((e.ts_ms for e in dump.events), default=None)
    if first_ts is not None:
        rebuild(conn, first_ts, dump.device_now_ms or last_ts)

    packages = {e.package for e in dump.events if e.package} | {s.package for s in dump.stats}
    known = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    new_labels = labels.resolve(sorted(packages), known=known, fetch=fetch_labels)
    db.upsert_labels(conn, new_labels)

    db.record_sync(conn, device=device, android=android, events_seen=len(dump.events),
                   events_added=added, first_ts_ms=first_ts, last_ts_ms=last_ts)

    return {
        "events_seen": len(dump.events),
        "events_added": added,
        "interval_rows": len(dump.stats),
        "labels_added": len(new_labels),
        "range": (first_ts, last_ts),
        "days": sorted({day_str(t) for t in (first_ts, last_ts) if t}),
    }


def rebuild(conn: sqlite3.Connection, from_ms: int, until_ms: int | None = None) -> list[str]:
    """Recompute sessions and hourly slices for every local day from `from_ms`.

    Days are rebuilt whole: events are re-read from the database (not just the
    dump), so a day that was ingested across several syncs still comes out
    right. Extra lookback is loaded so a session opened the previous evening
    can be closed correctly, but only whole days are replaced.
    """
    until_ms = until_ms or int(time.time() * 1000)
    first_day = datetime.fromtimestamp(from_ms / 1000).date()
    replace_from = day_start_ms(first_day)

    rows = conn.execute(
        "SELECT ts_ms, type, package, class, instance_id FROM events"
        " WHERE ts_ms >= ? AND ts_ms <= ? AND type IN (%s) ORDER BY ts_ms"
        % ",".join("?" * len(SESSION_TYPES)),
        (replace_from - LOOKBACK_MS, until_ms, *SESSION_TYPES),
    ).fetchall()
    events = [Event(r["ts_ms"], r["type"], r["package"], r["class"], r["instance_id"]) for r in rows]

    sessions = foreground_sessions(events, until_ms)
    # Drop the lookback tail; those days are already materialised correctly.
    sessions = [(p, max(a, replace_from), b) for p, a, b in sessions if b > replace_from]

    split = _split_by_hour(sessions)

    last_day = datetime.fromtimestamp(until_ms / 1000).date()
    conn.execute("BEGIN")
    conn.execute("DELETE FROM sessions WHERE day >= ? AND day <= ?", (str(first_day), str(last_day)))
    conn.execute("DELETE FROM usage_slice WHERE day >= ? AND day <= ?", (str(first_day), str(last_day)))
    conn.executemany(
        "INSERT OR REPLACE INTO sessions (day, package, start_ms, end_ms) VALUES (?, ?, ?, ?)",
        [(day_str(a), p, a, b) for p, a, b in _split_by_day(sessions)],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO usage_slice (day, hour, package, ms) VALUES (?, ?, ?, ?)",
        [(d, h, p, ms) for (d, h, p), ms in split.items()],
    )
    conn.execute("COMMIT")

    days = sorted({d for d, _, _ in split})
    return days


def _boundaries(start: int, end: int, step_of):
    """Yield [(a, b)] pieces of [start, end) that never cross a boundary."""
    cur = start
    while cur < end:
        nxt = min(step_of(cur), end)
        if nxt <= cur:  # defensive: never loop forever on a bad boundary
            break
        yield cur, nxt
        cur = nxt


def _next_midnight(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000).date() + timedelta(days=1)
    return day_start_ms(d)


def _next_hour(ms: int) -> int:
    dt = datetime.fromtimestamp(ms / 1000).replace(minute=0, second=0, microsecond=0)
    return int((dt + timedelta(hours=1)).timestamp() * 1000)


def _split_by_day(sessions):
    for pkg, a, b in sessions:
        for x, y in _boundaries(a, b, _next_midnight):
            yield pkg, x, y


def _split_by_hour(sessions) -> dict[tuple[str, int, str], int]:
    out: dict[tuple[str, int, str], int] = defaultdict(int)
    for pkg, a, b in sessions:
        for x, y in _boundaries(a, b, _next_hour):
            dt = datetime.fromtimestamp(x / 1000)
            out[(dt.strftime("%Y-%m-%d"), dt.hour, pkg)] += y - x
    return out
