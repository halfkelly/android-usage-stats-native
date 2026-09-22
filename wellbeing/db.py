"""SQLite store.

The phone only keeps 24h of events and rolling interval buckets, so a sync
appends into this database and nothing the phone forgets is lost. Derived
tables (`sessions`, `usage_slice`) are rebuilt from `events` for whatever
window a sync touched, so `events` stays the single source of truth.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "usage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    ts_ms       INTEGER NOT NULL,
    type        TEXT NOT NULL,
    package     TEXT NOT NULL DEFAULT '',
    class       TEXT NOT NULL DEFAULT '',
    instance_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (ts_ms, type, package, class, instance_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS events_ts   ON events (ts_ms);
CREATE INDEX IF NOT EXISTS events_type ON events (type, ts_ms);

-- one foreground stretch, already clipped to a single local day
CREATE TABLE IF NOT EXISTS sessions (
    day      TEXT NOT NULL,
    package  TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms   INTEGER NOT NULL,
    PRIMARY KEY (start_ms, package)
);
CREATE INDEX IF NOT EXISTS sessions_day ON sessions (day, package);

-- per hour rollup, so the dashboard never scans raw sessions
CREATE TABLE IF NOT EXISTS usage_slice (
    day     TEXT NOT NULL,
    hour    INTEGER NOT NULL,
    package TEXT NOT NULL,
    ms      INTEGER NOT NULL,
    PRIMARY KEY (day, hour, package)
) WITHOUT ROWID;

-- the phone's own rolling buckets, kept for cross-checking and day-one display
CREATE TABLE IF NOT EXISTS interval_stats (
    interval       TEXT NOT NULL,
    package        TEXT NOT NULL,
    range_start_ms INTEGER NOT NULL,
    range_end_ms   INTEGER,
    total_ms       INTEGER,
    visible_ms     INTEGER,
    fs_ms          INTEGER,
    launches       INTEGER,
    last_used_ms   INTEGER,
    last_component_ms INTEGER,
    captured_ms    INTEGER NOT NULL,
    PRIMARY KEY (interval, package, range_start_ms)
);

-- device-wide counters (screen on/off, keyguard) with count AND duration
CREATE TABLE IF NOT EXISTS event_stats (
    interval       TEXT NOT NULL,
    range_start_ms INTEGER NOT NULL,
    range_end_ms   INTEGER,
    event_type     INTEGER NOT NULL,
    count          INTEGER,
    total_time_ms  INTEGER,
    last_event_ms  INTEGER,
    PRIMARY KEY (interval, range_start_ms, event_type)
);

-- time per device configuration: orientation, night mode, locale, density
CREATE TABLE IF NOT EXISTS config_stats (
    interval        TEXT NOT NULL,
    range_start_ms  INTEGER NOT NULL,
    range_end_ms    INTEGER,
    config          TEXT NOT NULL,
    activations     INTEGER,
    total_active_ms INTEGER,
    last_active_ms  INTEGER,
    PRIMARY KEY (interval, range_start_ms, config)
);

CREATE TABLE IF NOT EXISTS apps (
    package    TEXT PRIMARY KEY,
    label      TEXT,
    source     TEXT,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS syncs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    device       TEXT,
    android      TEXT,
    events_seen  INTEGER,
    events_added INTEGER,
    first_ts_ms  INTEGER,
    last_ts_ms   INTEGER
);
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not add
# them to a database that already exists, so they are applied explicitly.
_ADDED_COLUMNS = {
    "interval_stats": {"last_component_ms": "INTEGER"},
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def insert_events(conn: sqlite3.Connection, events) -> int:
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO events (ts_ms, type, package, class, instance_id)"
        " VALUES (?, ?, ?, ?, ?)",
        [(e.ts_ms, e.type, e.package, e.klass, e.instance_id) for e in events],
    )
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] - before


def insert_interval_stats(conn: sqlite3.Connection, stats) -> int:
    now = int(time.time() * 1000)
    rows = [
        (
            s.interval, s.package, s.range_start_ms, s.range_end_ms, s.total_ms,
            s.visible_ms, s.fs_ms, s.launches, s.last_used_ms,
            getattr(s, "last_component_ms", None), now,
        )
        for s in stats
        if s.range_start_ms is not None
    ]
    conn.executemany(
        """INSERT INTO interval_stats (interval, package, range_start_ms, range_end_ms,
               total_ms, visible_ms, fs_ms, launches, last_used_ms, last_component_ms, captured_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(interval, package, range_start_ms) DO UPDATE SET
               range_end_ms = COALESCE(excluded.range_end_ms, interval_stats.range_end_ms),
               total_ms     = COALESCE(MAX(excluded.total_ms, interval_stats.total_ms), excluded.total_ms, interval_stats.total_ms),
               visible_ms   = COALESCE(MAX(excluded.visible_ms, interval_stats.visible_ms), excluded.visible_ms, interval_stats.visible_ms),
               fs_ms        = COALESCE(MAX(excluded.fs_ms, interval_stats.fs_ms), excluded.fs_ms, interval_stats.fs_ms),
               launches     = COALESCE(MAX(excluded.launches, interval_stats.launches), excluded.launches, interval_stats.launches),
               last_used_ms = COALESCE(MAX(excluded.last_used_ms, interval_stats.last_used_ms), excluded.last_used_ms, interval_stats.last_used_ms),
               last_component_ms = COALESCE(MAX(excluded.last_component_ms, interval_stats.last_component_ms), excluded.last_component_ms, interval_stats.last_component_ms),
               captured_ms  = excluded.captured_ms""",
        rows,
    )
    return len(rows)


def insert_event_stats(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany(
        """INSERT INTO event_stats (interval, range_start_ms, range_end_ms, event_type,
                                    count, total_time_ms, last_event_ms)
           VALUES (:interval, :range_start_ms, :range_end_ms, :event_type,
                   :count, :total_time_ms, :last_event_ms)
           ON CONFLICT(interval, range_start_ms, event_type) DO UPDATE SET
               range_end_ms  = COALESCE(excluded.range_end_ms, event_stats.range_end_ms),
               count         = COALESCE(MAX(excluded.count, event_stats.count), excluded.count, event_stats.count),
               total_time_ms = COALESCE(MAX(excluded.total_time_ms, event_stats.total_time_ms), excluded.total_time_ms, event_stats.total_time_ms),
               last_event_ms = COALESCE(MAX(excluded.last_event_ms, event_stats.last_event_ms), excluded.last_event_ms, event_stats.last_event_ms)""",
        rows,
    )
    return len(rows)


def insert_config_stats(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany(
        """INSERT INTO config_stats (interval, range_start_ms, range_end_ms, config,
                                     activations, total_active_ms, last_active_ms)
           VALUES (:interval, :range_start_ms, :range_end_ms, :config,
                   :activations, :total_active_ms, :last_active_ms)
           ON CONFLICT(interval, range_start_ms, config) DO UPDATE SET
               range_end_ms    = COALESCE(excluded.range_end_ms, config_stats.range_end_ms),
               activations     = COALESCE(MAX(excluded.activations, config_stats.activations), excluded.activations, config_stats.activations),
               total_active_ms = COALESCE(MAX(excluded.total_active_ms, config_stats.total_active_ms), excluded.total_active_ms, config_stats.total_active_ms),
               last_active_ms  = COALESCE(MAX(excluded.last_active_ms, config_stats.last_active_ms), excluded.last_active_ms, config_stats.last_active_ms)""",
        rows,
    )
    return len(rows)


def upsert_labels(conn: sqlite3.Connection, labels: dict[str, tuple[str, str]]) -> None:
    now = int(time.time() * 1000)
    conn.executemany(
        """INSERT INTO apps (package, label, source, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(package) DO UPDATE SET
               label=excluded.label, source=excluded.source, updated_at=excluded.updated_at""",
        [(p, lbl, src, now) for p, (lbl, src) in labels.items()],
    )


def record_sync(conn: sqlite3.Connection, **kw) -> None:
    conn.execute(
        """INSERT INTO syncs (ts_ms, device, android, events_seen, events_added,
                              first_ts_ms, last_ts_ms)
           VALUES (:ts_ms, :device, :android, :events_seen, :events_added,
                   :first_ts_ms, :last_ts_ms)""",
        {"ts_ms": int(time.time() * 1000), **kw},
    )
