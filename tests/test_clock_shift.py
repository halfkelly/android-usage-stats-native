"""A phone whose clock was corrected must not duplicate the history already stored.

On 2026-10-01 a sync added 61,667 copies of archived events, every one exactly
2,375 ms late. Android shifts its whole stored usage history when the wall clock
jumps by more than ~2 s, so the same events came back with new timestamps, the
primary key saw nothing in common, and unlocks and notifications doubled for
every day the phone still held -- in the database and then in the shared archive.
"""
import csv
import os
import time

import pytest

os.environ["TZ"] = "Asia/Kolkata"
time.tzset()

from wellbeing import appdump, db
from wellbeing.parse import Event

T0 = 1_790_000_000_000
SHIFT = 2_375
MIN = 60_000


def _history(n=40, start=T0):
    """An hour-by-hour unlock pattern with app use in between."""
    out = []
    for i in range(n):
        t = start + i * 7 * MIN
        out += [
            Event(t, "SCREEN_INTERACTIVE"),
            Event(t + 1_000, "KEYGUARD_HIDDEN"),
            Event(t + 2_000, "ACTIVITY_RESUMED", "com.example.app", "Main"),
            Event(t + 3 * MIN, "ACTIVITY_PAUSED", "com.example.app", "Main"),
            Event(t + 3 * MIN + 500, "SCREEN_NON_INTERACTIVE"),
            Event(t + 3 * MIN + 600, "KEYGUARD_SHOWN"),
        ]
    return out


CODES = {v: k for k, v in appdump.EVENT_TYPES.items()}


def _write_capture(d, events, bucket_begin):
    d.mkdir()
    with (d / "events.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_ms", "type", "package", "class"])
        for e in events:
            w.writerow([e.ts_ms, CODES[e.type], e.package, e.klass])
    with (d / "buckets.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["interval", "begin_ms", "end_ms", "package", "total_foreground_ms",
                    "total_visible_ms", "total_fs_ms", "last_used_ms", "last_visible_ms",
                    "last_fs_ms", "last_component_ms"])
        w.writerow(["daily", bucket_begin, bucket_begin + 86_399_999, "com.example.app",
                    600_000, 0, 0, bucket_begin + 1000, 0, 0, 0])
    return d


def _count(conn, sql="SELECT COUNT(*) FROM events", *args):
    return conn.execute(sql, args).fetchone()[0]


def test_shift_is_measured_from_the_overlap(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, _history())
    shifted = [Event(e.ts_ms + SHIFT, e.type, e.package, e.klass) for e in _history()]
    assert appdump.detect_clock_shift(conn, shifted) == SHIFT


def test_no_shift_reads_as_zero(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, _history())
    assert appdump.detect_clock_shift(conn, _history()) == 0


def test_no_overlap_reads_as_zero(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, _history())
    later = _history(start=T0 + 30 * 86_400_000)
    assert appdump.detect_clock_shift(conn, later) == 0


def test_a_shifted_capture_adds_only_what_is_new(tmp_path):
    """The incident, replayed: same history, 2,375 ms late, plus genuinely new use."""
    conn = db.connect(tmp_path / "u.db")
    old = _history(40)
    db.insert_events(conn, old)
    db.insert_interval_stats(conn, appdump.parse_buckets(
        _write_capture(tmp_path / "first", old, T0 - 1000) / "buckets.csv"))
    stored = _count(conn)
    unlocks = _count(conn, "SELECT COUNT(*) FROM events WHERE type='KEYGUARD_HIDDEN'")

    new = _history(5, start=T0 + 40 * 7 * MIN)
    capture = [Event(e.ts_ms + SHIFT, e.type, e.package, e.klass) for e in old + new]
    result = appdump.ingest_files(conn, _write_capture(tmp_path / "second", capture, T0 - 1000 + SHIFT))

    assert result["clock_shift_ms"] == SHIFT
    assert result["events_added"] == len(new)
    assert _count(conn) == stored + len(new)
    assert _count(conn, "SELECT COUNT(*) FROM events WHERE type='KEYGUARD_HIDDEN'") == unlocks + 5
    # the day's bucket is the same window, not a second one 2,375 ms later
    assert _count(conn, "SELECT COUNT(*) FROM interval_stats") == 1


def test_a_capture_that_rewrites_history_is_refused_and_rolled_back(tmp_path):
    """The tripwire behind the correction: e.g. a shift the detector cannot see."""
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, _history(40))
    before = _count(conn)
    copies = [Event(e.ts_ms + 1_234, e.type, e.package, e.klass) for e in _history(40)]
    with pytest.raises(db.OverlapError):
        db.insert_phone_events(conn, copies)
    assert _count(conn) == before


def test_an_ordinary_capture_passes_the_tripwire(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, _history(40))
    again = _history(40) + _history(5, start=T0 + 40 * 7 * MIN)
    assert db.insert_phone_events(conn, again) == 30
