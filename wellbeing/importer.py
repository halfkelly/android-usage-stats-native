"""Rebuild a local database from the shared CSV archive.

The machine that syncs the phone writes the archive; every other machine runs
this to get a database it can serve the dashboard from. `events/` is the
authority -- sessions and hourly slices are recomputed from it -- while the
bucket files carry the phone's own long-range counters, which cannot be derived
from events and so are imported directly.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from . import archive, db, labels
from .parse import Event, PackageStat
from .sync import rebuild


def _rows(path: Path):
    if not path.exists():
        return
    with path.open(newline="") as fh:
        yield from csv.DictReader(fh)


def _int(row: dict, *names: str) -> int | None:
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            try:
                return int(float(v))
            except ValueError:
                return None
    return None


def _window_end(row: dict) -> int | None:
    """Exact window end if the archive has it, else the minute-precision label.

    Archives written before `range_end_at` existed carry only `window_end`, so
    parse that rather than import a NULL that would erase the window's end.
    """
    exact = _int(row, "range_end_at", "range_end_ms")
    if exact is not None:
        return exact
    label = (row.get("window_end") or "").strip()
    if not label:
        return None
    try:
        return int(datetime.strptime(label, "%Y-%m-%d %H:%M").timestamp() * 1000)
    except ValueError:
        return None


def import_archive(conn: sqlite3.Connection, csv_dir: Path | None = None) -> dict:
    csv_dir = Path(csv_dir) if csv_dir else archive.archive_dir()
    if not csv_dir.exists():
        raise FileNotFoundError(f"No archive at {csv_dir}")

    # --- events: the authority ---------------------------------------------
    events: list[Event] = []
    for path in sorted((csv_dir / "events").glob("events-*.csv")):
        for row in _rows(path):
            ts = _int(row, "ts_at", "ts_ms")
            if ts is None or not row.get("type"):
                continue
            events.append(Event(ts_ms=ts, type=row["type"], package=row.get("package", ""),
                                klass=row.get("class", ""), instance_id=row.get("instance_id", "")))
    added = db.insert_events(conn, events)

    # --- the phone's own buckets: not derivable from events -----------------
    buckets = []
    for row in _rows(csv_dir / "app_buckets.csv"):
        start = _int(row, "range_start_at", "range_start_ms")
        if start is None or not row.get("package"):
            continue
        buckets.append(PackageStat(
            package=row["package"], interval=row.get("interval", "daily"),
            range_start_ms=start, range_end_ms=_window_end(row),
            total_ms=_int(row, "total_ms"), visible_ms=_int(row, "visible_ms"),
            fs_ms=_int(row, "fs_ms"), launches=_int(row, "launches"),
            last_used_ms=_int(row, "last_used_at", "last_used_ms"),
            last_component_ms=_int(row, "last_component_at", "last_component_ms"),
        ))
    db.insert_interval_stats(conn, buckets)

    counters = [
        {"interval": r.get("interval", ""), "range_start_ms": _int(r, "range_start_at", "range_start_ms"),
         "range_end_ms": _window_end(r), "event_type": _int(r, "event_type"), "count": _int(r, "count"),
         "total_time_ms": _int(r, "total_time_ms"), "last_event_ms": _int(r, "last_event_at", "last_event_ms")}
        for r in _rows(csv_dir / "device_counters.csv")
    ]
    counters = [c for c in counters if c["range_start_ms"] is not None and c["event_type"] is not None]
    db.insert_event_stats(conn, counters)

    configs = [
        {"interval": r.get("interval", ""), "range_start_ms": _int(r, "range_start_at", "range_start_ms"),
         "range_end_ms": _window_end(r), "config": r.get("config", ""), "activations": _int(r, "activations"),
         "total_active_ms": _int(r, "total_active_ms"), "last_active_ms": _int(r, "last_active_at", "last_active_ms")}
        for r in _rows(csv_dir / "device_configs.csv")
    ]
    configs = [c for c in configs if c["range_start_ms"] is not None and c["config"]]
    db.insert_config_stats(conn, configs)

    # --- app names: taken from the archive, so no lookup is needed ----------
    names: dict[str, tuple[str, str]] = {}
    for name in ("app_daily.csv", "app_buckets.csv", "app_hourly.csv"):
        for row in _rows(csv_dir / name):
            pkg, label = row.get("package"), row.get("app")
            if pkg and label and pkg not in names:
                names[pkg] = (label, "archive")
    known = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    db.upsert_labels(conn, {p: v for p, v in names.items() if p not in known})

    days = []
    if events:
        days = rebuild(conn, min(e.ts_ms for e in events), max(e.ts_ms for e in events))

    return {"source": str(csv_dir), "events": len(events), "events_added": added,
            "buckets": len(buckets), "counters": len(counters), "configs": len(configs),
            "labels": len(names), "days": len(days)}


def start_from_archive(conn: sqlite3.Connection) -> dict | None:
    """A new machine, or a deleted database: import the archive before anything
    else. Otherwise the first sync fills the database with only the phone's last
    ~10 days, and from then on it is no longer empty, so nothing ever brings in
    the history. None when the database has events or there is no archive yet.
    """
    if conn.execute("SELECT 1 FROM events LIMIT 1").fetchone():
        return None
    folder = archive.archive_dir()
    if not (folder / archive.META_FILE).exists() or not (folder / "events").is_dir():
        return None
    print(f"a new database: reading the archive first ({folder})", flush=True)
    result = import_archive(conn, folder)
    print(f"  {result['events']:,} events, {result['days']:,} days")
    return result
