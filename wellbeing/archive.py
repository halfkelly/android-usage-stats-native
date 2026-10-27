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
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
LOCAL_FALLBACK = ROOT / "data" / "csv"
# Everything this project keeps in Drive lives under one folder:
#   My Drive/PhoneUsage/phone/    the phone app's uploads (inbox.py)
#   My Drive/PhoneUsage/archive/  this archive
#   My Drive/PhoneUsage/code/     the app's signing key backup (code/signing)
# The phone app creates PhoneUsage itself: its drive.file permission can only
# write into folders it made. The old top-level names are still found, so a
# machine keeps working until the folders are moved.
PROJECT_FOLDER = "PhoneUsage"
FOLDER_NAME = "archive"
LEGACY_FOLDER_NAME = "PhoneUsageBackup"
ENV_VAR = "PHONE_USAGE_ARCHIVE"


def _candidates(mnt: Path = Path("/mnt")) -> list[Path]:
    """Possible 'My Drive' roots of Google Drive for desktop.

    On Windows: a drive letter (G:\\My Drive, the default) or a folder in the
    user profile (mirror mode). Under WSL the same places appear under /mnt.
    `mnt` is a parameter only for tests.
    """
    out: list[Path] = []
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            out.append(Path(f"{letter}:\\") / "My Drive")
        profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        out += [profile / "My Drive", profile / "Google Drive" / "My Drive"]
        return out
    if mnt.exists():
        for drive in sorted(mnt.glob("[a-z]")):
            out.append(drive / "My Drive")
            out += sorted(drive.glob("Users/*/My Drive"))
            out += sorted(drive.glob("Users/*/Google Drive/My Drive"))
    return out


def drive_root(mnt: Path = Path("/mnt")) -> Path | None:
    for path in _candidates(mnt):
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


def project_path(root: Path, name: str, legacy: str) -> Path:
    """My Drive/PhoneUsage/<name>, or the old top-level <legacy> while only that exists."""
    current = root / PROJECT_FOLDER / name
    old = root / legacy
    return old if old.is_dir() and not current.is_dir() else current


_NOTED_MOVE = False


def archive_dir(create: bool = False) -> Path:
    """The archive directory, preferring Drive and falling back to local.

    `PHONE_USAGE_ARCHIVE` overrides everything, which is what the tests and any
    non-Drive setup use.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        path = Path(override).expanduser()
        moved = path.parent / PROJECT_FOLDER / FOLDER_NAME
        if path.name == LEGACY_FOLDER_NAME and not path.exists() and moved.is_dir():
            # A shell started before the move into PhoneUsage/ still carries the
            # old value. Only this exact case follows the move: any other missing
            # override must fail loudly rather than start a second archive.
            global _NOTED_MOVE
            if not _NOTED_MOVE:
                print(f"note: ${ENV_VAR} names the old {path}; using {moved}. "
                      f"Open a new terminal to pick up the new value.", file=sys.stderr)
                _NOTED_MOVE = True
            path = moved
    else:
        root = drive_root()
        path = project_path(root, FOLDER_NAME, LEGACY_FOLDER_NAME) if root else LOCAL_FALLBACK
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


class ZoneMismatchError(TimezoneError):
    """Windows' clock is in another zone than the archive's (see pin_timezone)."""


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

    Windows has no tzset: the process keeps the Windows clock's zone. There it
    is only checked -- every day and hour would otherwise be cut in the
    laptop's zone instead of the archive's, silently.
    """
    name = archive_timezone()
    if not _valid_zone(name):
        raise TimezoneError(f"Archive timezone {name!r} is not a known zone on this machine")
    if not hasattr(time, "tzset"):
        if not local_zone_matches(name):
            raise ZoneMismatchError(
                f"This computer's time zone isn't the archive's ({name}), so days would be "
                f"cut at the wrong midnight.\n"
                f"  Set it in Windows: Settings > Time & language > Date & time > Time zone, "
                f"to the zone of {name}.")
        return name
    os.environ["TZ"] = name
    time.tzset()
    return name


def local_zone_matches(name: str, now: float | None = None) -> bool:
    """Does this process's local time follow `name`, offsets and DST alike?

    Compared at the 15th of every month for two years either side of now:
    that tells a different zone apart, and a zone with other DST rules.
    """
    zone = ZoneInfo(name)
    now = time.time() if now is None else now
    for k in range(-24, 25):
        t = now + k * 30.44 * 86400
        local = datetime.fromtimestamp(t).astimezone().utcoffset()
        if local != datetime.fromtimestamp(t, zone).utcoffset():
            return False
    return True


def load_settings(root: Path | None = None) -> None:
    """Settings from the project's .env (written by windows\\setup.ps1).

    Only keys not already in the environment, so a real environment variable
    -- or the container's own -- always wins. PHONE_USAGE_DRIVE names the
    PhoneUsage folder; the archive and the phone's inbox are inside it.
    """
    env = (root or ROOT) / ".env"
    try:
        lines = env.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        m = re.match(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*"?(.*?)"?\s*$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)
    drive = os.environ.get("PHONE_USAGE_DRIVE")
    if drive and not os.environ.get(ENV_VAR) and os.name == "nt":
        os.environ[ENV_VAR] = str(Path(drive) / FOLDER_NAME)


def describe() -> str:
    path = archive_dir()
    if os.environ.get(ENV_VAR):
        return f"{path}  (from ${ENV_VAR})"
    if drive_root():
        return f"{path}  (Google Drive)"
    return f"{path}  (local only -- Google Drive not detected)"
