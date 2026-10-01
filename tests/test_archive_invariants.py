"""Invariants the shared archive must hold.

These exist because of a real incident: a machine whose event stream had a
seven-day hole produced device_daily rows reading 86,400,000 ms of screen-on
with zero app foreground, and the archive merge let them overwrite six good
days. The archive is the only copy of most of this data -- the phone discards
raw events after ~10 days -- so a silent overwrite is unrecoverable.
"""
import csv
import os
import sqlite3
import time

import pytest

# Days and hours are cut in the archive's zone, never the machine's clock.
os.environ["TZ"] = "Asia/Kolkata"
time.tzset()

from wellbeing import archive, stats
from wellbeing.export import _keep_larger, _merge


# --- the merge may never lose information ----------------------------------

@pytest.mark.parametrize("new, old, prefer_new, want, why", [
    ("0", "79", True, "79", "a zero must not replace a real count"),
    ("55", "255", True, "255", "a thinner reading must not win"),
    ("300", "255", True, "300", "a fuller reading still wins"),
    ("", "23:27", True, "23:27", "blank must not erase"),
    ("19:31", "", True, "19:31", "blank is filled"),
    ("yes", "no", True, "yes", "text follows the fuller row"),
    ("no", "yes", False, "yes", "text keeps the old when the old row is fuller"),
    ("abc", "def", True, "abc", "non-numeric follows prefer_new"),
    ("", "", True, "", "two blanks stay blank"),
])
def test_keep_larger(new, old, prefer_new, want, why):
    assert _keep_larger(new, old, prefer_new) == want, why


def _read(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


FIELDS = ["day", "screen_on_ms", "app_foreground_ms", "unlocks", "notifications", "last_use"]
GOOD = {"day": "2026-09-15", "screen_on_ms": "13257999", "app_foreground_ms": "11358295",
        "unlocks": "79", "notifications": "127", "last_use": "23:27"}


def test_the_incident_cannot_recur(tmp_path):
    """A 24h-screen-on row of zeros must not overwrite a real day.

    This is the exact shape that destroyed six days: screen_on_ms is larger, so
    under the old single-column rule the whole row won and every other field was
    replaced by 0. 0 is not blank, so the blank-guard never fired.
    """
    path = tmp_path / "device_daily.csv"
    _merge(path, FIELDS, [GOOD], key=("day",), richer="screen_on_ms")

    poisoned = {"day": "2026-09-15", "screen_on_ms": "86400000", "app_foreground_ms": "0",
                "unlocks": "0", "notifications": "0", "last_use": ""}
    _merge(path, FIELDS, [poisoned], key=("day",), richer="screen_on_ms")

    row = _read(path)[0]
    assert row["unlocks"] == "79", "unlocks were zeroed -- the incident recurred"
    assert row["notifications"] == "127"
    assert row["app_foreground_ms"] == "11358295"
    assert row["last_use"] == "23:27", "a blank erased a real clock label"


def test_merge_never_decreases_any_number(tmp_path):
    path = tmp_path / "daily.csv"
    _merge(path, FIELDS, [GOOD], key=("day",), richer="screen_on_ms")
    thinner = {**GOOD, "unlocks": "56", "notifications": "100", "screen_on_ms": "13257000"}
    _merge(path, FIELDS, [thinner], key=("day",), richer="screen_on_ms")
    row = _read(path)[0]
    assert row["unlocks"] == "79"
    assert row["notifications"] == "127"
    assert row["screen_on_ms"] == "13257999"


def test_merge_keeps_a_genuinely_fuller_reading(tmp_path):
    """The flip side: real enrichment must still land."""
    path = tmp_path / "daily.csv"
    partial = {**GOOD, "screen_on_ms": "5000000", "app_foreground_ms": "4000000",
               "unlocks": "20", "notifications": "30", "last_use": "19:31"}
    _merge(path, FIELDS, [partial], key=("day",), richer="screen_on_ms")
    _merge(path, FIELDS, [GOOD], key=("day",), richer="screen_on_ms")
    row = _read(path)[0]
    assert row["screen_on_ms"] == "13257999"
    assert row["unlocks"] == "79"
    assert row["last_use"] == "23:27"


def test_a_day_already_archived_survives_a_database_that_forgot_it(tmp_path):
    """The whole point of the archive: the phone prunes, the archive does not."""
    path = tmp_path / "daily.csv"
    _merge(path, FIELDS, [GOOD], key=("day",), richer="screen_on_ms")
    _merge(path, FIELDS, [{**GOOD, "day": "2026-09-16"}], key=("day",), richer="screen_on_ms")
    days = {r["day"] for r in _read(path)}
    assert days == {"2026-09-15", "2026-09-16"}, "an earlier day fell out of the archive"


# --- a gap in the event stream is not usage --------------------------------

def _conn(rows):
    """A real in-memory events table, so the day expression is exercised too."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE events (ts_ms INTEGER, type TEXT, package TEXT, class TEXT)")
    c.executemany("INSERT INTO events (ts_ms, type, package) VALUES (?, ?, '')", rows)
    return c


def _ms(day, hour):
    import datetime
    return int(datetime.datetime(2026, 9, day, hour).timestamp() * 1000)


def test_unclosed_screen_on_is_dropped_not_smeared():
    """The bug itself: a screen-on whose screen-off is seven days away."""
    conn = _conn([(_ms(14, 17), stats.SCREEN_ON), (_ms(21, 18), stats.SCREEN_OFF_EV)])
    out = stats._paired_ms_per_day(conn, stats.SCREEN_ON, stats.SCREEN_OFF_EV,
                                  "2026-09-14", "2026-09-21")
    assert out == {}, f"a 7-day gap was attributed as screen time: {out}"
    assert not any(v >= 86_400_000 for v in out.values())


def test_a_normal_screen_on_still_counts():
    conn = _conn([(_ms(15, 9), stats.SCREEN_ON), (_ms(15, 10), stats.SCREEN_OFF_EV)])
    out = stats._paired_ms_per_day(conn, stats.SCREEN_ON, stats.SCREEN_OFF_EV,
                                  "2026-09-15", "2026-09-15")
    assert out == {"2026-09-15": 3_600_000}


def test_a_session_crossing_midnight_is_split():
    conn = _conn([(_ms(15, 23), stats.SCREEN_ON), (_ms(16, 1), stats.SCREEN_OFF_EV)])
    out = stats._paired_ms_per_day(conn, stats.SCREEN_ON, stats.SCREEN_OFF_EV,
                                  "2026-09-15", "2026-09-16")
    assert out == {"2026-09-15": 3_600_000, "2026-09-16": 3_600_000}


# --- the two capture paths must not double-count -----------------------------

class _Ev:
    def __init__(self, ts_ms, type, package, klass="", instance_id=""):
        self.ts_ms, self.type, self.package = ts_ms, type, package
        self.klass, self.instance_id = klass, instance_id


def _events_db():
    from wellbeing import db as dbmod
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(dbmod.SCHEMA)
    return c


def test_the_same_event_from_both_sources_is_stored_once():
    """dumpsys reports whole seconds, the companion app milliseconds.

    The same unlock arrives as 1789823111000 and 1789823111107 -- different
    primary keys, so INSERT OR IGNORE keeps both and every COUNT(*) doubles.
    """
    from wellbeing import db as dbmod
    c = _events_db()
    dbmod.insert_events(c, [_Ev(1789823111107, "KEYGUARD_HIDDEN", "android")])
    dbmod.insert_events(c, [_Ev(1789823111000, "KEYGUARD_HIDDEN", "android", instance_id="7")])
    n = c.execute("SELECT COUNT(*) FROM events WHERE type='KEYGUARD_HIDDEN'").fetchone()[0]
    assert n == 1, f"the same unlock is stored {n} times"
    kept = c.execute("SELECT ts_ms FROM events").fetchone()[0]
    assert kept == 1789823111107, "the millisecond-precise copy should be the survivor"


def test_a_second_aligned_event_with_no_twin_is_kept():
    """About one real event in a thousand lands on a second boundary by chance."""
    from wellbeing import db as dbmod
    c = _events_db()
    dbmod.insert_events(c, [_Ev(1789823111000, "KEYGUARD_HIDDEN", "android")])
    assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


# --- a pair may never swallow a whole day ------------------------------------

def test_a_pair_spanning_three_days_is_rejected():
    """A 34h music session contains one whole calendar day."""
    conn = _conn([(_ms(14, 20), stats.FS_START), (_ms(16, 6), stats.FS_STOP)])
    out = stats._paired_ms_per_day(conn, stats.FS_START, stats.FS_STOP,
                                  "2026-09-14", "2026-09-16",
                                  max_pair_ms=stats.MAX_SERVICE_PAIR_MS)
    assert out == {}, f"a pair containing a whole day should be dropped, got {out}"


def test_an_exactly_24h_pair_cannot_hand_a_day_the_whole_day():
    """The case a length cap cannot catch, and the first fix missed.

    Midnight to midnight is exactly 24h, so it passes any 24h ceiling; it
    touches a single calendar day, so it passes a two-day rule; and that one day
    is then credited with all 86,400,000 ms. Only a rule about the RESULT stops
    it. This is the exact shape Amazon Music showed on six days.
    """
    conn = _conn([(_ms(15, 0), stats.FS_START), (_ms(16, 0), stats.FS_STOP)])
    out = stats._paired_ms_per_day(conn, stats.FS_START, stats.FS_STOP,
                                  "2026-09-15", "2026-09-16",
                                  max_pair_ms=stats.MAX_SERVICE_PAIR_MS)
    assert 86_400_000 not in out.values(), f"a day was handed all 24 hours: {out}"
    assert out == {}


def test_an_overnight_service_still_counts():
    """Music from 22:00 to 07:00 crosses one midnight and is perfectly real."""
    conn = _conn([(_ms(14, 22), stats.FS_START), (_ms(15, 7), stats.FS_STOP)])
    out = stats._paired_ms_per_day(conn, stats.FS_START, stats.FS_STOP,
                                  "2026-09-14", "2026-09-15",
                                  max_pair_ms=stats.MAX_SERVICE_PAIR_MS)
    assert out == {"2026-09-14": 2 * 3_600_000, "2026-09-15": 7 * 3_600_000}


# --- an unreachable archive must refuse, not improvise ----------------------

def test_an_unreadable_archive_refuses_instead_of_starting_a_new_one(tmp_path, monkeypatch):
    """A stale Drive mount looks like a directory but fails on first read.

    The danger is not the error -- it is "recovering" from it. Falling back to
    $PHONE_USAGE_TZ, or inviting set-timezone, would start a second empty
    archive at a path that is merely broken, and the two machines would then
    disagree about every day boundary.
    """
    (tmp_path / "archive.json").mkdir()          # a directory where a file belongs
    monkeypatch.setenv("PHONE_USAGE_ARCHIVE", str(tmp_path))
    monkeypatch.setenv("PHONE_USAGE_TZ", "Etc/UTC")   # must NOT be used as a fallback
    with pytest.raises(archive.TimezoneError) as e:
        archive.archive_timezone()
    assert "Nothing was read or written" in str(e.value)
    assert "Etc/UTC" not in str(e.value), "fell back to the env var on an unreachable archive"


def test_a_missing_archive_json_still_invites_set_timezone(tmp_path, monkeypatch):
    """The other case, which needs the opposite advice."""
    monkeypatch.setenv("PHONE_USAGE_ARCHIVE", str(tmp_path))
    monkeypatch.delenv("PHONE_USAGE_TZ", raising=False)
    with pytest.raises(archive.TimezoneError) as e:
        archive.archive_timezone()
    assert "set-timezone" in str(e.value)
