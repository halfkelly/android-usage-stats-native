"""Where the shared CSV archive lives.

The archive is the single source of truth shared between machines: whichever
computer syncs the phone writes it, and every computer reads it. It is plain
append-only CSV, which is safe to put in a cloud-synced folder -- unlike
`usage.db`, where a half-synced SQLite file plus its write-ahead log is a real
corruption risk. Each machine therefore keeps its own local database, rebuilt
from this archive with `python -m wellbeing import`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FALLBACK = ROOT / "data" / "csv"
FOLDER_NAME = "PhoneUsageBackup"
ENV_VAR = "PHONE_USAGE_ARCHIVE"


def _candidates(home: Path | None = None, mnt: Path = Path("/mnt")) -> list[Path]:
    """Possible 'My Drive' roots, macOS and WSL/Windows.

    `home` and `mnt` are parameters only so the WSL layouts can be tested on a
    machine that isn't running WSL.
    """
    home = home or Path.home()
    out: list[Path] = []
    # macOS: Google Drive for desktop mounts under CloudStorage
    cloud = home / "Library" / "CloudStorage"
    if cloud.exists():
        out += sorted(cloud.glob("GoogleDrive-*/My Drive"))
    # WSL: the Windows side is mounted under /mnt. Drive is usually a lettered
    # mount (G:) but can also be a folder in the Windows user profile.
    if mnt.exists():
        for drive in sorted(mnt.glob("[a-z]")):
            out.append(drive / "My Drive")
            out += sorted(drive.glob("Users/*/My Drive"))
            out += sorted(drive.glob("Users/*/Google Drive/My Drive"))
    return out


def drive_root(home: Path | None = None, mnt: Path = Path("/mnt")) -> Path | None:
    for path in _candidates(home, mnt):
        if path.is_dir():
            return path
    return None


def _seed_from_local(dest: Path) -> int:
    """First use of a new archive location inherits the local one.

    Installing Google Drive moves the archive from `data/csv` to the Drive
    folder. Without this, the first export at the new location would start from
    an empty directory and the merge would preserve nothing -- silently losing
    every day the phone has already forgotten.
    """
    if dest == LOCAL_FALLBACK or not LOCAL_FALLBACK.exists():
        return 0
    if any(dest.glob("*.csv")):
        return 0
    copied = 0
    for src in sorted(LOCAL_FALLBACK.rglob("*.csv")):
        target = dest / src.relative_to(LOCAL_FALLBACK)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(src, target)
            copied += 1
    return copied


def archive_dir(create: bool = False) -> Path:
    """The archive directory, preferring Drive and falling back to local.

    `PHONE_USAGE_ARCHIVE` overrides everything, which is what the tests and any
    non-Drive setup use.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        path = Path(override).expanduser()
    else:
        root = drive_root()
        path = (root / FOLDER_NAME) if root else LOCAL_FALLBACK
    if create:
        path.mkdir(parents=True, exist_ok=True)
        seeded = _seed_from_local(path)
        if seeded:
            print(f"archive moved to {path} -- carried over {seeded} file(s) from {LOCAL_FALLBACK}")
    return path


META_FILE = "archive.json"
TZ_ENV = "PHONE_USAGE_TZ"


class TimezoneError(RuntimeError):
    pass


def _valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


# archive.json holds every setting shared between machines, so reads and writes
# go through these two helpers: writing one key must never drop the others.
def _read_meta() -> dict:
    meta = archive_dir() / META_FILE
    # FileNotFoundError means "no settings yet"; any other OSError means the
    # archive itself is unreachable. The callers must tell those apart, because
    # the advice is opposite -- one says record a timezone, the other must never
    # suggest writing anything.
    raw = meta.read_text()
    try:
        data = json.loads(raw)
    except ValueError:
        raise TimezoneError(f"{meta} is unreadable; expected a JSON object")
    if not isinstance(data, dict):
        raise TimezoneError(f"{meta} is unreadable; expected a JSON object")
    return data


def _write_meta(data: dict) -> Path:
    meta = archive_dir(create=True) / META_FILE
    tmp = meta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(meta)
    return meta


# Packages the user has chosen to leave out of screen time totals. Stored beside
# the timezone so both machines' dashboards agree; deliberately not applied to
# the CSV export, so editing the list never makes archived days incomparable.
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def excluded_apps() -> list[str]:
    try:
        value = _read_meta().get("excluded_apps", [])
    except (FileNotFoundError, TimezoneError):
        return []
    return sorted({p for p in value if isinstance(p, str) and PACKAGE_RE.match(p)})


def set_excluded_apps(packages) -> list[str]:
    cleaned = sorted({str(p).strip() for p in packages if str(p).strip()})
    bad = [p for p in cleaned if not PACKAGE_RE.match(p)]
    if bad:
        raise ValueError(f"not package names: {', '.join(bad[:3])}")
    try:
        data = _read_meta()
    except FileNotFoundError:
        data = {}
    data["excluded_apps"] = cleaned
    _write_meta(data)
    return cleaned


def archive_timezone() -> str:
    """The one timezone every calendar day and hour in this archive is cut in.

    Days and hours are derived from absolute timestamps using local time, and a
    shared archive is written by machines whose clocks can be set differently
    (WSL defaults to UTC). Recording the zone in the archive, rather than
    reading each machine's clock, is what keeps one machine from filing the same
    events under different days and hours than another.
    """
    meta = archive_dir() / META_FILE
    env = os.environ.get(TZ_ENV)
    try:
        stored = _read_meta()["timezone"]
    except FileNotFoundError:
        if env:
            return env
        raise TimezoneError(
            f"This archive has no timezone recorded ({meta}).\n"
            f"  Record it once with:  python -m wellbeing set-timezone <Area/City>"
        )
    except OSError as exc:
        # The directory resolved but the storage behind it did not. On WSL this
        # is a stale Google Drive mount: /mnt/g still looks like a directory
        # after Drive for Desktop stops, so every existence check passes and the
        # first real read fails with ENODEV. Deliberately does NOT fall back to
        # $PHONE_USAGE_TZ or suggest set-timezone -- either would start a second,
        # empty archive at a path that is merely broken.
        raise TimezoneError(
            f"The archive is not readable: {meta}\n"
            f"  {exc.strerror} (errno {exc.errno}). Nothing was read or written.\n"
            f"  If that is a stale Google Drive mount on WSL -- /mnt/g keeps looking "
            f"like a\n"
            f"  directory after Drive for Desktop stops, so every check passes and the "
            f"first\n"
            f"  real read fails -- start Drive on Windows, then either\n"
            f"      sudo umount /mnt/g && sudo mount -t drvfs G: /mnt/g\n"
            f"  or run  wsl --shutdown  in PowerShell and reopen Ubuntu."
        ) from exc
    except (ValueError, KeyError):
        raise TimezoneError(f"{meta} is unreadable; expected {{\"timezone\": \"Area/City\"}}")
    if env and env != stored:
        raise TimezoneError(
            f"${TZ_ENV}={env} disagrees with the archive's recorded timezone {stored}. "
            f"Unset ${TZ_ENV}; the archive's value is authoritative."
        )
    return stored


def set_archive_timezone(name: str) -> Path:
    """Record the archive's timezone. Refuses to change one already recorded."""
    if not _valid_zone(name):
        raise TimezoneError(f"Unknown timezone {name!r}; use an IANA name such as Asia/Kolkata")
    try:
        data = _read_meta()
    except FileNotFoundError:
        data = {}          # first setting recorded for a brand-new archive
    current = data.get("timezone")
    if current and current != name:
        raise TimezoneError(
            f"Archive already records {current}. Changing it would re-cut every "
            f"calendar day and hour, so it is not done in place."
        )
    data["timezone"] = name
    return _write_meta(data)


def pin_timezone() -> str:
    """Make this process behave as if its clock were set to the archive's zone.

    Setting TZ and calling tzset() moves Python's datetime conversions and
    SQLite's 'localtime' modifier together, including on connections already
    open, so every date calculation in the codebase follows it without edits.
    """
    name = archive_timezone()
    if not _valid_zone(name):
        raise TimezoneError(f"Archive timezone {name!r} is not a known zone on this machine")
    os.environ["TZ"] = name
    time.tzset()
    return name


def describe() -> str:
    path = archive_dir()
    if os.environ.get(ENV_VAR):
        return f"{path}  (from ${ENV_VAR})"
    if drive_root():
        return f"{path}  (Google Drive)"
    return f"{path}  (local only -- Google Drive not detected)"
