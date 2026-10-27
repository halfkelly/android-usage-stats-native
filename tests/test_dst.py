"""Days that aren't 24 hours long.

On 2026-10-25 Europe/Berlin turned the clocks back: that day had 25 hours.
Splitting a screen-on at "midnight + 24 h" put the edge at 23:00 the same day,
and the export looped forever on the first span after it -- found by setting
up a fresh archive in a friend's timezone.
"""
import os
import signal
import time
from datetime import datetime

import pytest

from wellbeing import db, stats
from wellbeing.parse import Event


@pytest.fixture
def berlin():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    yield
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture
def deadline():
    """Fail instead of hanging: the bug was an endless loop."""
    def boom(*_):
        raise TimeoutError("took over 10 s -- the DST loop is back")
    signal.signal(signal.SIGALRM, boom)
    signal.alarm(10)
    yield
    signal.alarm(0)


def ms(*args):
    return int(datetime(*args).timestamp() * 1000)


def test_screen_time_on_the_day_the_clocks_go_back(tmp_path, berlin, deadline):
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, [
        Event(ms(2026, 10, 25, 22, 30), "SCREEN_INTERACTIVE"),
        Event(ms(2026, 10, 25, 23, 40), "SCREEN_NON_INTERACTIVE"),
        Event(ms(2026, 10, 25, 23, 50), "SCREEN_INTERACTIVE"),       # across midnight
        Event(ms(2026, 10, 26, 0, 20), "SCREEN_NON_INTERACTIVE"),
    ])
    out = stats._paired_ms_per_day(conn, "SCREEN_INTERACTIVE", "SCREEN_NON_INTERACTIVE",
                                   "2026-10-25", "2026-10-26")
    assert out == {"2026-10-25": (70 + 10) * 60_000, "2026-10-26": 20 * 60_000}


def test_a_lost_stop_across_a_25_hour_day_is_still_not_counted(tmp_path, berlin, deadline):
    """The 'never credit a whole day' rule must hold for 25-hour days too."""
    conn = db.connect(tmp_path / "u.db")
    db.insert_events(conn, [
        Event(ms(2026, 10, 24, 23, 0), "FOREGROUND_SERVICE_START", "com.x"),
        Event(ms(2026, 10, 26, 0, 30), "FOREGROUND_SERVICE_STOP", "com.x"),
    ])
    out = stats._paired_ms_per_day(conn, "FOREGROUND_SERVICE_START", "FOREGROUND_SERVICE_STOP",
                                   "2026-10-24", "2026-10-26", by_package=True,
                                   max_pair_ms=48 * 3_600_000)
    assert out == {}
