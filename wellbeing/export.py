"""CSV export, for pivoting the history outside the dashboard."""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from . import archive, stats

# The raw event stream is the only source from which every other figure can be
# recomputed, and the phone discards it after ~10 days. Archiving it in monthly
# partitions means a lost or rebuilt database costs nothing.
EVENTS_DIR = "events"

ROOT = Path(__file__).resolve().parent.parent


def _merge(path: Path, fields: list[str], rows: list[dict],
           key: tuple[str, ...], richer: str) -> tuple[int, int]:
    """Write `rows`, keeping any row already in the file that is not superseded.

    The CSVs are an archive, not a snapshot. The phone discards usage data after
    about ten days, so a day that once made it into a CSV must survive every
    later export -- including one run against a rebuilt or restored database
    that no longer knows about it. Rows are matched on `key`; when both the file
    and the new export have a row, the one with the larger `richer` value wins,
    so a fuller reading is never replaced by a thinner one.
    """
    existing: dict[tuple, dict] = {}
    if path.exists():
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                existing[tuple(row.get(k, "") for k in key)] = row

    kept = len(existing)
    for row in rows:
        k = tuple(str(row.get(f, "")) for f in key)
        old = existing.get(k)
        if old is None:
            existing[k] = {f: _cell(row.get(f)) for f in fields}
        else:
            # Merge cell by cell, and never let a number go down. Every figure
            # here is a count or a duration over a fixed period, so it can only
            # grow as more of that period is captured -- a smaller value means
            # the writer saw less, not that the truth changed.
            #
            # The old rule trusted a single column: if `richer` was larger, the
            # whole row won. One machine with a gap in its event stream sent a
            # device_daily row whose screen_on_ms was larger while every other
            # field was 0, and it overwrote six good days in one export. Judging
            # each cell on its own makes that impossible, whatever the writer.
            prefer_new = _num(row.get(richer)) >= _num(old.get(richer))
            existing[k] = {f: _keep_larger(row.get(f), old.get(f), prefer_new) for f in fields}

    out = sorted(existing.values(), key=lambda r: tuple(str(r.get(k, "")) for k in key))
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    tmp.replace(path)          # atomic, so an interrupted export cannot truncate the archive
    return len(out), max(0, len(out) - kept)


def _keep_larger(new, old, prefer_new: bool) -> str:
    """Pick one cell. Numbers never decrease; blanks never erase; text follows the
    fuller row."""
    n, o = _cell(new), _cell(old)
    if n == "" or o == "":
        return n or o
    if _is_num(n) and _is_num(o):
        return n if float(n) >= float(o) else o
    return n if prefer_new else o


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _cell(v) -> str:
    return "" if v is None else str(v)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return -1.0



# Durations are stored only as milliseconds. A rounded `minutes` copy alongside
# them would be a second source of truth that drifts: rounding loses up to 3s a
# row, so a month of summed minutes disagrees with the same month of summed ms.
# Consumers divide by 60000.

# Timestamp columns use the `_at` suffix, durations use `_ms`. Both are
# milliseconds, but one is a point in time and the other a length, and the old
# shared `_ms` suffix made them look interchangeable.
TIMESTAMP_RENAMES = {
    "ts_ms": "ts_at",
    "last_used_ms": "last_used_at",
    "range_start_ms": "range_start_at",
    "range_end_ms": "range_end_at",
    "last_component_ms": "last_component_at",
    "last_active_ms": "last_active_at",
    "last_event_ms": "last_event_at",
}


def _renamed(row: dict) -> dict:
    return {TIMESTAMP_RENAMES.get(k, k): v for k, v in row.items()}


def _archive_events(conn, out_dir: Path) -> tuple[int, int]:
    """Append raw events to monthly partitions, deduplicated.

    This is the backstop: every other file can be recomputed from these rows,
    and the phone discards them after ~10 days.
    """
    ev_dir = out_dir / EVENTS_DIR
    ev_dir.mkdir(parents=True, exist_ok=True)
    fields = ["ts_at", "type", "package", "class", "instance_id"]
    by_month: dict[str, list[dict]] = {}
    for r in conn.execute("SELECT ts_ms, type, package, class, instance_id FROM events"):
        month = datetime.fromtimestamp(r["ts_ms"] / 1000).strftime("%Y-%m")
        by_month.setdefault(month, []).append(_renamed(dict(r)))

    total = added = 0
    for month, rows in sorted(by_month.items()):
        path = ev_dir / f"events-{month}.csv"
        existing: dict[tuple, dict] = {}
        if path.exists():
            with path.open(newline="") as fh:
                for row in csv.DictReader(fh):
                    existing[tuple(row.get(f, "") for f in fields)] = row
        before = len(existing)
        for row in rows:
            existing[tuple(str(row.get(f, "")) for f in fields)] = row
        out = sorted(existing.values(), key=lambda r: int(r["ts_at"]))
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(out)
        tmp.replace(path)
        total += len(out)
        added += len(out) - before
    return total, added


def _relabel(out_dir: Path, labels: dict[str, str]) -> int:
    """Rewrite the display-name column of every archived file from `labels`.

    The `app` column is cosmetic -- `package` is the identity -- so it must not
    be governed by the fuller-reading rule in `_merge`, which would otherwise
    freeze a name onto any row the current export does not supersede, including
    days older than the database. Renaming an app here renames it everywhere.
    """
    changed = 0
    for name in ("app_daily.csv", "app_hourly.csv", "app_buckets.csv"):
        path = out_dir / name
        if not path.exists():
            continue
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            fields, rows = reader.fieldnames or [], list(reader)
        if "app" not in fields or "package" not in fields:
            continue
        hits = 0
        for row in rows:
            want = labels.get(row.get("package", ""))
            if want and row.get("app") != want:
                row["app"] = want
                hits += 1
        if not hits:
            continue
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(path)
        changed += hits
    return changed


def export_garmin(conn: sqlite3.Connection, out_dir: Path | None = None) -> tuple[int, int]:
    """Archive the Garmin daily rows beside the phone ones, keyed on the same day.

    Garmin's API is unofficial and already broke once, so this follows the same
    append-only rule as everything else: a day that has been fetched survives,
    whatever happens to the API later.
    """
    from . import garmin
    out_dir = Path(out_dir) if out_dir else archive.archive_dir(create=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return _merge(out_dir / "garmin_daily.csv", garmin.FIELDS,
                  garmin.daily(conn), key=("day",), richer="steps")


def export_all(conn: sqlite3.Connection, start: str, end: str,
               out_dir: Path | None = None, include_chrome: bool = False) -> dict[str, tuple[int, int]]:
    out_dir = Path(out_dir) if out_dir else archive.archive_dir(create=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, tuple[int, int]] = {}

    # --- device-wide, per calendar day --------------------------------------
    coverage = stats.day_coverage(conn, start, end)
    daily = stats.daily_totals(conn, start, end, include_chrome)
    for row in daily:
        cov = coverage.get(row["day"], {})
        row.update({
            "screen_ms": row["ms"],
            "apps_used": row["apps"],
            "covered_from": cov.get("covered_from", ""),
            "covered_to": cov.get("covered_to", ""),
            "covered_hours": cov.get("covered_hours", 0),
            "complete_day": "yes" if cov.get("complete") else "no",
        })
    written["daily.csv"] = _merge(
        out_dir / "daily.csv",
        ["day", "screen_ms", "apps_used", "unlocks", "notifications",
         "covered_from", "covered_to", "covered_hours", "complete_day"],
        daily, key=("day",), richer="covered_hours",
    )

    dev = stats.device_daily(conn, start, end)
    written["device_daily.csv"] = _merge(
        out_dir / "device_daily.csv",
        ["day", "screen_on_ms", "app_foreground_ms", "idle_screen_ms", "unlocked_ms",
         "unlocks", "notifications", "notifications_seen", "interactions", "apps_used",
         "sessions", "longest_session_ms", "first_use", "last_use"],
        dev, key=("day",), richer="screen_on_ms",
    )

    written["hourly.csv"] = _merge(
        out_dir / "hourly.csv", ["day", "hour", "ms"],
        stats.hourly_rows(conn, start, end, include_chrome), key=("day", "hour"), richer="ms",
    )

    # --- per app, per calendar day ------------------------------------------
    written["app_daily.csv"] = _merge(
        out_dir / "app_daily.csv",
        ["day", "app", "package", "ms", "opens", "longest_session_ms", "first_use",
         "last_use", "foreground_service_ms", "notifications", "notifications_seen",
         "interactions", "pickups_started", "micro_pickups", "impulse_pickups"],
        stats.app_daily_full(conn, start, end), key=("day", "package"), richer="ms",
    )

    written["app_hourly.csv"] = _merge(
        out_dir / "app_hourly.csv", ["day", "hour", "app", "package", "ms"],
        stats.app_hourly(conn, start, end), key=("day", "hour", "package"), richer="ms",
    )

    # --- pick-ups: one row each, and per day --------------------------------
    written["pickups.csv"] = _merge(
        out_dir / "pickups.csv",
        ["day", "time", "start_at", "unlock_at", "end_at", "duration_ms", "unlocked",
         "first_app", "first_package", "packages", "trigger_app", "trigger_package",
         "trigger_delay_ms", "micro", "impulse"],
        stats.pickup_rows(conn, start, end), key=("start_at",), richer="duration_ms",
    )
    written["pickup_daily.csv"] = _merge(
        out_dir / "pickup_daily.csv",
        ["day", "pickups", "glances", "micro", "impulse", "impulse_micro", "pickup_ms",
         "glance_ms"],
        stats.pickup_daily(conn, start, end), key=("day",), richer="pickups",
    )

    # --- the phone's own per-app buckets, every interval and window ---------
    labels = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    buckets = [
        _renamed({**dict(r), "app": labels.get(r["package"], r["package"]),
                  "window_start": datetime.fromtimestamp(r["range_start_ms"] / 1000).strftime("%Y-%m-%d %H:%M"),
                  "window_end": datetime.fromtimestamp(r["range_end_ms"] / 1000).strftime("%Y-%m-%d %H:%M")
                                 if r["range_end_ms"] else ""})
        for r in conn.execute(
            """SELECT interval, package, range_start_ms, range_end_ms, total_ms,
                      visible_ms, fs_ms, launches, last_used_ms, last_component_ms
               FROM interval_stats ORDER BY interval, range_start_ms, total_ms DESC""")
    ]
    written["app_buckets.csv"] = _merge(
        out_dir / "app_buckets.csv",
        ["interval", "window_start", "window_end", "app", "package", "total_ms",
         "visible_ms", "fs_ms", "launches", "last_used_at", "last_component_at",
         "range_start_at", "range_end_at"],
        buckets, key=("interval", "range_start_at", "package"), richer="total_ms",
    )

    # --- device counters (screen / keyguard) with count AND duration --------
    from .appdump import EVENT_TYPES
    counters = [
        _renamed({**dict(r), "event": EVENT_TYPES.get(r["event_type"], str(r["event_type"])),
                  "window_start": datetime.fromtimestamp(r["range_start_ms"] / 1000).strftime("%Y-%m-%d %H:%M")})
        for r in conn.execute(
            """SELECT interval, range_start_ms, range_end_ms, event_type, count,
                      total_time_ms, last_event_ms FROM event_stats
               ORDER BY interval, range_start_ms, event_type""")
    ]
    written["device_counters.csv"] = _merge(
        out_dir / "device_counters.csv",
        ["interval", "window_start", "event", "event_type", "count", "total_time_ms",
         "last_event_at", "range_start_at", "range_end_at"],
        counters, key=("interval", "range_start_at", "event_type"), richer="total_time_ms",
    )

    # --- device configurations (orientation, night mode, locale) -----------
    configs = [
        _renamed({**dict(r),
                  "window_start": datetime.fromtimestamp(r["range_start_ms"] / 1000).strftime("%Y-%m-%d %H:%M")})
        for r in conn.execute(
            """SELECT interval, range_start_ms, range_end_ms, config, activations,
                      total_active_ms, last_active_ms
               FROM config_stats ORDER BY interval, range_start_ms""")
    ]
    written["device_configs.csv"] = _merge(
        out_dir / "device_configs.csv",
        ["interval", "window_start", "config", "activations", "total_active_ms",
         "last_active_at", "range_start_at", "range_end_at"],
        configs, key=("interval", "range_start_at", "config"), richer="total_active_ms",
    )

    # --- raw events, monthly partitions ------------------------------------
    written["events/*.csv"] = _archive_events(conn, out_dir)

    _relabel(out_dir, labels)

    return written
