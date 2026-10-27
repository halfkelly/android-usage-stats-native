"""Every test gets a Drive of its own.

`docker compose run --rm sync python -m pytest` mounts the real Drive folder,
and the image points PHONE_USAGE_ARCHIVE at it: no test may read or write that.
A test that needs a particular layout sets its own paths over this.
"""
import pytest


@pytest.fixture(autouse=True)
def _not_the_real_drive(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_USAGE_ARCHIVE", str(tmp_path / "test-drive" / "PhoneUsage" / "archive"))
    monkeypatch.delenv("PHONE_USAGE_INBOX", raising=False)
