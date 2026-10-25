"""Deep history via the companion APK.

`dumpsys usagestats` only prints what the service holds in memory: 24h of
events and the current rolling buckets. `UsageStatsManager.queryEvents` and
`queryUsageStats` read the *persisted* store behind it, which on the test
device reaches back about ten days of events and months of aggregates.

Reaching those APIs needs an app holding PACKAGE_USAGE_STATS, so `android/`
contains a ~150 line APK that queries them and writes CSV. This module builds,
installs, runs and ingests it.
"""
from __future__ import annotations

import csv
from collections import Counter
import subprocess
import time
from pathlib import Path

from . import adb, db, labels
from .parse import Event, PackageStat

ROOT = Path(__file__).resolve().parent.parent
APK = ROOT / "android" / "build" / "usagedump.apk"
BUILD = ROOT / "android" / "build.sh"
PKG = "com.shrey.usagedump"
REMOTE_DIR = f"/sdcard/Android/data/{PKG}/files"

# android.app.usage.UsageEvents.Event constants. The CSV carries the ints, and
# the names must match what parse.py produces for a dumpsys dump so both
# sources land in one events table.
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


def build_apk() -> Path:
    if not APK.exists():
        subprocess.run(["bash", str(BUILD)], check=True, capture_output=True, text=True)
    return APK


def ensure_installed(serial: str) -> bool:
    """Install the APK and grant usage access. Returns True if it installed now."""
    installed = PKG in adb.shell(f"pm list packages {PKG}", serial)
    if not installed:
        build_apk()
        subprocess.run([adb.adb_path(), "-s", serial, "install", "-r", str(APK)],
                       check=True, capture_output=True, text=True)
    # appops is idempotent, and the grant does not survive a reinstall.
    adb.shell(f"appops set {PKG} GET_USAGE_STATS allow", serial)
    return not installed


FILES = ("buckets.csv", "events.csv", "eventstats.csv", "configs.csv")


def capture(serial: str, days: int = 400, out_dir: Path | None = None) -> Path:
    """Run the dump activity and pull its two CSVs."""
    ensure_installed(serial)
    adb.shell(f"rm -f {REMOTE_DIR}/*.csv", serial)
    adb.shell(f"am start -n {PKG}/.DumpActivity --ei days {days}", serial)

    out_dir = Path(out_dir or ROOT / "raw" / "app")
    out_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(30):  # the activity writes and finishes; poll rather than guess
        time.sleep(1)
        listing = adb.shell(f"ls {REMOTE_DIR}", serial)
        if all(name in listing for name in FILES):
            break
    else:
        raise adb.AdbError(
            f"{PKG} produced no output. Check that usage access is granted: "
            f"Settings > Apps > Special access > Usage data access."
        )

    paths = []
    for name in FILES:
        local = out_dir / name
        subprocess.run([adb.adb_path(), "-s", serial, "pull", f"{REMOTE_DIR}/{name}", str(local)],
                       check=True, capture_output=True, text=True)
        paths.append(local)
    return out_dir


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


def ingest_files(conn, out_dir: Path, *, fetch_labels: bool = False) -> dict:
    from .sync import rebuild

    out_dir = Path(out_dir)
    events = parse_events(out_dir / "events.csv")
    buckets = parse_buckets(out_dir / "buckets.csv")
    estats = parse_event_stats(out_dir / "eventstats.csv") if (out_dir / "eventstats.csv").exists() else []
    configs = parse_config_stats(out_dir / "configs.csv") if (out_dir / "configs.csv").exists() else []

    shift = detect_clock_shift(conn, events)
    if shift:
        apply_shift(shift, events, buckets, estats, configs)
    added = db.insert_phone_events(conn, events)
    db.insert_interval_stats(conn, buckets)
    db.insert_event_stats(conn, estats)
    db.insert_config_stats(conn, configs)

    if events:
        rebuild(conn, min(e.ts_ms for e in events), max(e.ts_ms for e in events))

    packages = {e.package for e in events if e.package} | {b.package for b in buckets}
    known = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    db.upsert_labels(conn, labels.resolve(sorted(packages), known=known, fetch=fetch_labels))

    db.record_sync(conn, device="companion-apk", android="", events_seen=len(events),
                   events_added=added,
                   first_ts_ms=min((e.ts_ms for e in events), default=None),
                   last_ts_ms=max((e.ts_ms for e in events), default=None))
    return {"events_seen": len(events), "events_added": added, "buckets": len(buckets),
            "event_stats": len(estats), "configs": len(configs), "clock_shift_ms": shift}
