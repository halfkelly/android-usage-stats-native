"""The phone app's CSV formats, and undoing a shift in the phone's clock.

The app (android/) writes what UsageStatsManager.queryEvents and
queryUsageStats return -- the persisted store, about ten days of events and
months of buckets -- as CSV; inbox.py ingests it. These parsers turn the CSV
into the same Event and PackageStat rows everything else uses.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .parse import Event, PackageStat

# android.app.usage.UsageEvents.Event constants. The CSV carries the ints, and
# the names are what the events table and every query use.
EVENT_TYPES = {
    1: "ACTIVITY_RESUMED", 2: "ACTIVITY_PAUSED", 3: "END_OF_DAY",
    4: "CONTINUE_PREVIOUS_DAY", 5: "CONFIGURATION_CHANGE", 6: "SYSTEM_INTERACTION",
    7: "USER_INTERACTION", 8: "SHORTCUT_INVOCATION", 9: "CHOOSER_ACTION",
    10: "NOTIFICATION_SEEN", 11: "STANDBY_BUCKET_CHANGED", 12: "NOTIFICATION_INTERRUPTION",
    13: "SLICE_PINNED_PRIV", 14: "SLICE_PINNED", 15: "SCREEN_INTERACTIVE",
    16: "SCREEN_NON_INTERACTIVE", 17: "KEYGUARD_SHOWN", 18: "KEYGUARD_HIDDEN",
    19: "FOREGROUND_SERVICE_START", 20: "FOREGROUND_SERVICE_STOP",
    21: "CONTINUING_FOREGROUND_SERVICE", 22: "ROLLOVER_FOREGROUND_SERVICE",
    23: "ACTIVITY_STOPPED", 24: "ACTIVITY_DESTROYED", 25: "FLUSH_TO_DISK",
    26: "DEVICE_SHUTDOWN", 27: "DEVICE_STARTUP", 28: "USER_UNLOCKED",
    29: "USER_STOPPED", 30: "LOCUS_ID_SET", 31: "APP_COMPONENT_USED",
}


def parse_events(path: Path) -> list[Event]:
    out = []
    with Path(path).open() as fh:
        for row in csv.DictReader(fh):
            try:
                ts, code = int(row["ts_ms"]), int(row["type"])
            except (KeyError, ValueError):
                continue
            out.append(Event(
                ts_ms=ts,
                type=EVENT_TYPES.get(code, f"TYPE_{code}"),
                package=row.get("package") or "",
                klass=row.get("class") or "",
            ))
    return out


def parse_buckets(path: Path) -> list[PackageStat]:
    out = []
    with Path(path).open() as fh:
        for row in csv.DictReader(fh):
            try:
                begin, end = int(row["begin_ms"]), int(row["end_ms"])
                total = int(row["total_foreground_ms"])
            except (KeyError, ValueError):
                continue
            def num(key):
                try:
                    v = int(row.get(key) or 0)
                except ValueError:
                    return None
                return v or None

            out.append(PackageStat(
                package=row["package"],
                interval=row["interval"],
                range_start_ms=begin,
                range_end_ms=end,
                total_ms=total,
                visible_ms=num("total_visible_ms"),
                fs_ms=num("total_fs_ms"),
                last_used_ms=num("last_used_ms"),
                last_component_ms=num("last_component_ms"),
            ))
    return out


def parse_event_stats(path: Path) -> list[dict]:
    out = []
    with Path(path).open() as fh:
        for row in csv.DictReader(fh):
            try:
                out.append({
                    "interval": row["interval"],
                    "range_start_ms": int(row["begin_ms"]),
                    "range_end_ms": int(row["end_ms"]),
                    "event_type": int(row["event_type"]),
                    "count": int(row["count"]),
                    "total_time_ms": int(row["total_time_ms"]),
                    "last_event_ms": int(row["last_event_ms"]),
                })
            except (KeyError, ValueError):
                continue
    return out


def parse_config_stats(path: Path) -> list[dict]:
    out = []
    with Path(path).open() as fh:
        for row in csv.DictReader(fh):
            try:
                out.append({
                    "interval": row["interval"],
                    "range_start_ms": int(row["begin_ms"]),
                    "range_end_ms": int(row["end_ms"]),
                    "config": row["config"],
                    "activations": int(row["activations"]),
                    "total_active_ms": int(row["total_active_ms"]),
                    "last_active_ms": int(row["last_active_ms"]),
                })
            except (KeyError, ValueError):
                continue
    return out


# Sparse, distinctive events: a few hundred a day, so every pairing within the
# search window can be scored without the cost exploding on ACTIVITY_* noise.
_ANCHOR_TYPES = ("SCREEN_INTERACTIVE", "SCREEN_NON_INTERACTIVE", "KEYGUARD_SHOWN", "KEYGUARD_HIDDEN")
SHIFT_WINDOW_MS = 6 * 3_600_000
SHIFT_MIN_VOTES = 10


def detect_clock_shift(conn, events: list[Event]) -> int:
    """How far the phone's timestamps have moved since they were stored, in ms.

    Android rewrites its whole stored usage history when the wall clock jumps by
    more than ~2 s (UserUsageStatsService checks on every access), so after an
    NTP correction every past event reports a different timestamp than it did
    at the last sync. Measured against the events already stored: the offset
    that most anchor events share with a stored twin of the same type and
    package. 0 when nothing overlaps or there is no clear consensus.
    """
    anchors = [e for e in events if e.type in _ANCHOR_TYPES]
    if not anchors:
        return 0
    lo = min(e.ts_ms for e in anchors) - SHIFT_WINDOW_MS
    hi = max(e.ts_ms for e in anchors) + SHIFT_WINDOW_MS
    stored: dict[tuple, list[int]] = {}
    for r in conn.execute(
            "SELECT ts_ms, type, package FROM events WHERE ts_ms BETWEEN ? AND ? AND type IN (%s)"
            % ",".join("?" * len(_ANCHOR_TYPES)), (lo, hi, *_ANCHOR_TYPES)):
        stored.setdefault((r[1], r[2]), []).append(r[0])
    if not stored:
        return 0
    newest = max(max(v) for v in stored.values())
    votes: Counter = Counter()
    overlapping = 0
    for e in anchors:
        if e.ts_ms > newest + SHIFT_WINDOW_MS:
            continue
        overlapping += 1
        for t in stored.get((e.type, e.package), ()):
            d = e.ts_ms - t
            if -SHIFT_WINDOW_MS <= d <= SHIFT_WINDOW_MS:
                votes[d] += 1
    if not votes:
        return 0
    shift, n = votes.most_common(1)[0]
    if n < SHIFT_MIN_VOTES or n < overlapping // 2:
        return 0
    return shift


def _shifted(v, shift):
    return v - shift if v else v


def apply_shift(shift: int, events, buckets, estats, configs) -> None:
    """Move a capture back into the frame of what is already stored, in place."""
    for e in events:
        e.ts_ms -= shift
    for b in buckets:
        for f in ("range_start_ms", "range_end_ms", "last_used_ms", "last_component_ms"):
            setattr(b, f, _shifted(getattr(b, f), shift))
    for rows, fields in ((estats, ("range_start_ms", "range_end_ms", "last_event_ms")),
                         (configs, ("range_start_ms", "range_end_ms", "last_active_ms"))):
        for r in rows:
            for f in fields:
                r[f] = _shifted(r[f], shift)
