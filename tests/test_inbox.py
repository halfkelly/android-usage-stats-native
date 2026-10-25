"""The phone's Drive inbox: day files arriving in any order, rewritten, duplicated.

The app rewrites yesterday's and today's files on every run, Drive for desktop
delivers them in no promised order, and Drive itself saves a second upload of a
name as "name (1).csv". None of that may change a single stored count.
"""
import csv
import json
import os
import time

os.environ["TZ"] = "Asia/Kolkata"
time.tzset()

from wellbeing import appdump, db, inbox
from wellbeing.parse import Event

MIN = 60_000
DAY = 86_400_000
# 2026-10-20 00:00 Asia/Kolkata
D0 = 1_792_434_600_000
CODES = {v: k for k, v in appdump.EVENT_TYPES.items()}


def _day(start, n=30):
    """n pick-ups through one day, each an unlock with some app use."""
    out = []
    for i in range(n):
        t = start + 8 * 3_600_000 + i * 20 * MIN
        out += [
            Event(t, "SCREEN_INTERACTIVE"),
            Event(t + 1_000, "KEYGUARD_HIDDEN"),
            Event(t + 2_000, "ACTIVITY_RESUMED", "com.example.app", "Main"),
            Event(t + 3 * MIN, "ACTIVITY_PAUSED", "com.example.app", "Main"),
            Event(t + 3 * MIN + 500, "SCREEN_NON_INTERACTIVE"),
            Event(t + 3 * MIN + 600, "KEYGUARD_SHOWN"),
        ]
    return out


def _write(root, name, events):
    d = root / "events"
    d.mkdir(parents=True, exist_ok=True)
    with (d / name).open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_ms", "type", "package", "class"])
        for e in events:
            w.writerow([e.ts_ms, CODES[e.type], e.package, e.klass])


def _inbox(tmp_path):
    root = tmp_path / "PhoneUsageInbox"
    root.mkdir()
    (root / "device.json").write_text(json.dumps(
        {"timezone": "Asia/Kolkata", "device": "samsung SM-S901E", "android": "16",
         "collected_at_ms": D0 + 2 * DAY}))
    return root


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_day_files_go_in_exactly_once(tmp_path):
    root = _inbox(tmp_path)
    _write(root, "events-2026-10-20.csv", _day(D0))
    _write(root, "events-2026-10-21.csv", _day(D0 + DAY))
    conn = db.connect(tmp_path / "u.db")

    r = inbox.ingest_inbox(conn, root)
    assert r["events_added"] == 2 * 180 == _count(conn)
    assert r["files"] == ["events-2026-10-20.csv", "events-2026-10-21.csv"]
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 60
    assert conn.execute("SELECT device FROM syncs").fetchone()[0] == "samsung SM-S901E"

    again = inbox.ingest_inbox(conn, root)
    assert again["files"] == [] and again["events_added"] == 0


def test_a_rewritten_day_adds_only_its_new_tail(tmp_path):
    root = _inbox(tmp_path)
    full = _day(D0)
    _write(root, "events-2026-10-20.csv", full[:90])     # the 2 pm upload
    conn = db.connect(tmp_path / "u.db")
    inbox.ingest_inbox(conn, root)
    _write(root, "events-2026-10-20.csv", full)          # the evening rewrite
    os.utime(root / "events" / "events-2026-10-20.csv", ns=(1, 1))  # mtime surely moved

    r = inbox.ingest_inbox(conn, root)
    assert r["events_added"] == 90 and _count(conn) == 180


def test_drives_duplicate_copy_is_harmless(tmp_path):
    root = _inbox(tmp_path)
    _write(root, "events-2026-10-20.csv", _day(D0))
    _write(root, "events-2026-10-20 (1).csv", _day(D0))
    conn = db.connect(tmp_path / "u.db")
    inbox.ingest_inbox(conn, root)
    assert _count(conn) == 180


def test_an_earlier_day_arriving_late_is_accepted(tmp_path):
    root = _inbox(tmp_path)
    _write(root, "events-2026-10-21.csv", _day(D0 + DAY))
    conn = db.connect(tmp_path / "u.db")
    inbox.ingest_inbox(conn, root)
    _write(root, "events-2026-10-20.csv", _day(D0))      # Drive delivered it second

    r = inbox.ingest_inbox(conn, root)
    assert r["refused"] == [] and r["events_added"] == 180 and _count(conn) == 360


def test_a_rewrite_after_a_clock_correction_is_realigned(tmp_path):
    root = _inbox(tmp_path)
    _write(root, "events-2026-10-20.csv", _day(D0))
    conn = db.connect(tmp_path / "u.db")
    inbox.ingest_inbox(conn, root)

    shift = 2_375  # the 2026-10-01 incident: Android moved every stored event
    moved = [Event(e.ts_ms + shift, e.type, e.package, e.klass) for e in _day(D0)]
    _write(root, "events-2026-10-20.csv", moved)
    os.utime(root / "events" / "events-2026-10-20.csv", ns=(1, 1))
    _write(root, "events-2026-10-21.csv",
           [Event(e.ts_ms + shift, e.type, e.package, e.klass) for e in _day(D0 + DAY)])

    r = inbox.ingest_inbox(conn, root)
    assert r["clock_shift_ms"] == shift
    assert r["events_added"] == 180 and _count(conn) == 360  # only the new day
    # The new day, which had nothing to measure against, was moved too.
    first_new = conn.execute("SELECT MIN(ts_ms) FROM events WHERE ts_ms >= ?",
                             (D0 + DAY,)).fetchone()[0]
    assert first_new == _day(D0 + DAY)[0].ts_ms


def test_a_day_that_would_rewrite_history_is_refused_alone(tmp_path):
    root = _inbox(tmp_path)
    _write(root, "events-2026-10-20.csv", _day(D0))
    conn = db.connect(tmp_path / "u.db")
    inbox.ingest_inbox(conn, root)

    # 200 events nobody stored, inside the stored day: not a shift, still wrong.
    extra = [Event(D0 + 8 * 3_600_000 + i * 997 + 13, "NOTIFICATION_INTERRUPTION", "com.x", "")
             for i in range(200)]
    _write(root, "events-2026-10-20.csv", sorted(_day(D0) + extra, key=lambda e: e.ts_ms))
    os.utime(root / "events" / "events-2026-10-20.csv", ns=(1, 1))
    _write(root, "events-2026-10-21.csv", _day(D0 + DAY))

    r = inbox.ingest_inbox(conn, root)
    assert len(r["refused"]) == 1 and "events-2026-10-20.csv" in r["refused"][0]
    assert r["files"] == ["events-2026-10-21.csv"]
    assert _count(conn) == 360
    # Not marked, so it is looked at again next time rather than forgotten.
    assert inbox.ingest_inbox(conn, root)["refused"]


def test_only_the_newest_snapshot_is_read(tmp_path):
    root = _inbox(tmp_path)
    snaps = root / "snapshots"
    snaps.mkdir()
    header = ("interval,begin_ms,end_ms,package,total_foreground_ms,total_visible_ms,"
              "total_fs_ms,last_used_ms,last_visible_ms,last_fs_ms,last_component_ms\n")
    (snaps / "buckets-2026-10-20.csv").write_text(
        header + f"daily,{D0},{D0 + DAY - 1},com.old,1,0,0,0,0,0,0\n")
    (snaps / "buckets-2026-10-21.csv").write_text(
        header + f"daily,{D0 + DAY},{D0 + 2 * DAY - 1},com.new,1,0,0,0,0,0,0\n")
    conn = db.connect(tmp_path / "u.db")
    r = inbox.ingest_inbox(conn, root)
    assert r["snapshots"]["buckets"] == 1
    assert [x[0] for x in conn.execute("SELECT package FROM interval_stats")] == ["com.new"]
