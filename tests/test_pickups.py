"""Pick-ups: glance or unlock, micro or not, impulse or triggered, and which app."""
import os
import time

os.environ["TZ"] = "Asia/Kolkata"
time.tzset()

from wellbeing import db, pickups
from wellbeing.parse import Event
from wellbeing.sync import rebuild

T = 1_792_464_000_000  # 2026-10-20 08:10 Asia/Kolkata
S = 1_000


def _pickup(at, length_ms, apps=("com.example.app",), unlock=True):
    out = [Event(at, "SCREEN_INTERACTIVE")]
    if unlock:
        out.append(Event(at + 500, "KEYGUARD_HIDDEN"))
        for i, pkg in enumerate(apps):
            out.append(Event(at + 1_000 + i * 10, "ACTIVITY_RESUMED", pkg, "Main"))
    out += [Event(at + length_ms, "SCREEN_NON_INTERACTIVE"),
            Event(at + length_ms + 900, "KEYGUARD_SHOWN")]
    return out


def test_a_screen_on_without_unlock_is_a_glance():
    [g] = pickups.build(_pickup(T, 5 * S, unlock=False))
    assert g["unlocked"] == 0 and g["micro"] == 0 and g["impulse"] == 0
    assert g["duration_ms"] == 5 * S and g["first_package"] == ""


def test_micro_is_under_thirty_seconds():
    a, b = pickups.build(_pickup(T, 29 * S) + _pickup(T + 600 * S, 31 * S))
    assert (a["micro"], b["micro"]) == (1, 0)


def test_a_notification_in_the_locked_stretch_triggers_the_pickup():
    ev = [Event(T - 40 * S, "NOTIFICATION_INTERRUPTION", "com.whatsapp")] + _pickup(T, 60 * S)
    [p] = pickups.build(ev)
    assert p["trigger_package"] == "com.whatsapp" and p["impulse"] == 0
    assert p["trigger_delay_ms"] == 40 * S + 500  # to the unlock, as notification_pickups measures


def test_a_notification_already_seen_before_the_last_lock_does_not():
    # Arrived during the previous pick-up: you saw it then; this one is on impulse.
    ev = (_pickup(T - 100 * S, 30 * S)
          + [Event(T - 90 * S, "NOTIFICATION_INTERRUPTION", "com.whatsapp")]
          + _pickup(T, 60 * S))
    first, second = pickups.build(ev)
    assert second["trigger_package"] == "" and second["impulse"] == 1


def test_a_notification_older_than_the_window_does_not():
    ev = [Event(T - 121 * S, "NOTIFICATION_INTERRUPTION", "com.whatsapp")] + _pickup(T, 60 * S)
    [p] = pickups.build(ev)
    assert p["impulse"] == 1


def test_first_app_skips_the_launcher_and_keyboard():
    apps = ("com.sec.android.app.launcher", "com.samsung.android.honeyboard",
            "com.instagram.android", "com.whatsapp", "com.instagram.android")
    [p] = pickups.build(_pickup(T, 90 * S, apps=apps))
    assert p["first_package"] == "com.instagram.android"
    assert p["packages"] == "com.instagram.android;com.whatsapp"


def test_a_stretch_still_open_is_left_for_the_next_rebuild():
    ev = _pickup(T, 30 * S) + [Event(T + 600 * S, "SCREEN_INTERACTIVE"),
                               Event(T + 601 * S, "KEYGUARD_HIDDEN")]
    assert len(pickups.build(ev)) == 1


def test_a_screen_on_missing_its_screen_off_is_dropped_not_stretched():
    ev = [Event(T, "SCREEN_INTERACTIVE"), Event(T + S, "KEYGUARD_HIDDEN")] + _pickup(T + 3_600 * S, 20 * S)
    [p] = pickups.build(ev)
    assert p["start_ms"] == T + 3_600 * S and p["duration_ms"] == 20 * S


def test_rebuild_materialises_the_table(tmp_path):
    conn = db.connect(tmp_path / "u.db")
    ev = _pickup(T, 20 * S) + _pickup(T + 600 * S, 120 * S) + _pickup(T + 900 * S, 4 * S, unlock=False)
    db.insert_events(conn, ev)
    rebuild(conn, T, T + 3_600 * S)
    rows = conn.execute("SELECT unlocked, micro, impulse FROM pickups ORDER BY start_ms").fetchall()
    assert [tuple(r) for r in rows] == [(1, 1, 1), (1, 0, 1), (0, 0, 0)]
    rebuild(conn, T, T + 3_600 * S)  # idempotent
    assert conn.execute("SELECT COUNT(*) FROM pickups").fetchone()[0] == 3
