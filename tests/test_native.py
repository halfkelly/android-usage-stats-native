"""Running without Docker: the timezone check that stands in for tzset on
Windows, settings from .env, and the scheduled sync."""
import json
import os
import time

import pytest

from wellbeing import archive, launch


@pytest.fixture
def zone():
    """Set this process's zone for a test, like a Windows clock setting."""
    old, tzset = os.environ.get("TZ"), time.tzset   # a test may remove time.tzset
    def set_(name):
        os.environ["TZ"] = name
        tzset()
    yield set_
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    tzset()


def test_the_local_zone_must_match_the_archive(zone):
    zone("Asia/Kolkata")
    assert archive.local_zone_matches("Asia/Kolkata")
    assert not archive.local_zone_matches("Europe/Berlin")


def test_same_offset_today_but_different_dst_does_not_match(zone):
    """UTC and London agree all winter; the summer months tell them apart."""
    zone("Europe/London")
    assert archive.local_zone_matches("Europe/London")
    assert not archive.local_zone_matches("UTC")


def test_without_tzset_a_mismatched_zone_is_refused(tmp_path, monkeypatch, zone):
    zone("Asia/Kolkata")                       # "Windows" is on India time
    monkeypatch.setenv("PHONE_USAGE_ARCHIVE", str(tmp_path / "archive"))
    archive.set_archive_timezone("Europe/Berlin")
    monkeypatch.delattr(time, "tzset")
    with pytest.raises(archive.ZoneMismatchError, match="Time zone"):
        archive.pin_timezone()
    archive_json = tmp_path / "archive" / "archive.json"
    archive_json.write_text(json.dumps({"timezone": "Asia/Kolkata"}))
    assert archive.pin_timezone() == "Asia/Kolkata"


def test_settings_come_from_dotenv_but_never_override(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('DASHBOARD_PORT="5099"\nPHONE_USAGE_TZ=Asia/Kolkata\n')
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    monkeypatch.setenv("PHONE_USAGE_TZ", "UTC")
    archive.load_settings(tmp_path)
    assert os.environ["DASHBOARD_PORT"] == "5099"
    assert os.environ["PHONE_USAGE_TZ"] == "UTC"              # the real environment wins
    monkeypatch.delenv("DASHBOARD_PORT")


def test_autosync_waits_quietly_for_the_phones_first_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "DATA", tmp_path / "data")
    monkeypatch.setenv("PHONE_USAGE_INBOX", str(tmp_path / "nothing-yet"))
    called = []
    assert launch.autosync(str(tmp_path / "u.db"), lambda db: called.append(db) or 0) == 0
    assert not called
    assert "no phone uploads" in (tmp_path / "data" / "autosync.log").read_text()


def test_autosync_runs_one_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".autosync.lock").write_text("123")      # a run in progress
    assert launch.autosync(str(tmp_path / "u.db"), lambda db: 1 / 0) == 0
    assert "already running" in (tmp_path / "data" / "autosync.log").read_text()


def test_stop_when_nothing_runs_is_fine(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "5987")
    assert launch.stop_dashboard() == 0
