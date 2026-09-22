"""Parser for `adb shell dumpsys usagestats`.

Two kinds of payload matter:

* the **last-24h event stream** -- ACTIVITY_RESUMED/PAUSED/STOPPED, screen and
  keyguard transitions, notifications. This is the only calendar-aligned source
  of truth: the phone's own "daily" bucket rolls over whenever the usage
  service last restarted (18:29 on the test device), not at midnight.
* the **in-memory interval buckets** (daily/weekly/monthly/yearly) -- rolling
  totals per package. Useful to show something on day one, before enough event
  history has accumulated.

Formats are version dependent, so key names are matched with alternatives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Timestamps before this are the epoch-zero placeholder the dump uses for
# "never" (printed in local time, e.g. 1970-01-01 05:30:00 for IST).
_EPOCH_FLOOR_MS = 365 * 24 * 3600 * 1000

_ABS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_DUR = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$")


def _mk(y: int, mo: int, d: int, h: int, mi: int, s: int, ms: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, s).timestamp() * 1000) + ms


def parse_timestamp(raw: str) -> int | None:
    """Epoch milliseconds for a dumpsys timestamp, or None for absent/never."""
    raw = raw.strip().strip('"')
    if not raw or raw in {"0", "<None>"}:
        return None
    if raw.isdigit():
        v = int(raw)
        return v if v > _EPOCH_FLOOR_MS else None
    m = _ABS.match(raw)
    if m:
        y, mo, d, h, mi, s, ms = m.groups()
        v = _mk(int(y), int(mo), int(d), int(h), int(mi), int(s), int((ms or "0").ljust(3, "0")))
        return v if v > _EPOCH_FLOOR_MS else None
    # `6/9/2026, 16:18` -- day/month/year, as printed by the interval headers
    m = _SLASH.match(raw)
    if m:
        d, mo, y, h, mi, s = m.groups()
        return _mk(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    return None


def parse_duration(raw: str) -> int | None:
    """Milliseconds for `MM:SS`, `H:MM:SS` or a bare millisecond count."""
    raw = raw.strip().strip('"')
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    m = _DUR.match(raw)
    if not m:
        return None
    h, a, b, ms = m.groups()
    if h is None:  # MM:SS
        total = int(a) * 60 + int(b)
    else:  # H:MM:SS
        total = int(h) * 3600 + int(a) * 60 + int(b)
    return total * 1000 + int((ms or "0").ljust(3, "0"))


_KV = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|\S+)')


def kv(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _KV.findall(line)}


def _first(d: dict[str, str], *names: str) -> str | None:
    for n in names:
        if n in d:
            return d[n]
    return None


# --- data holders -----------------------------------------------------------


@dataclass
class PackageStat:
    package: str
    interval: str
    range_start_ms: int | None
    range_end_ms: int | None
    total_ms: int | None = None
    visible_ms: int | None = None
    fs_ms: int | None = None
    launches: int | None = None
    last_used_ms: int | None = None
    last_component_ms: int | None = None


@dataclass
class Event:
    ts_ms: int
    type: str
    package: str = ""
    klass: str = ""
    instance_id: str = ""


@dataclass
class Dump:
    user: int = 0
    device_now_ms: int | None = None
    events: list[Event] = field(default_factory=list)
    stats: list[PackageStat] = field(default_factory=list)


_USER = re.compile(r"^user=(\d+)\s*$")
_EVENTS_HDR = re.compile(r"^\s*Last \d+ hour events\b")
_INTERVAL_HDR = re.compile(r"^\s*In-memory (daily|weekly|monthly|yearly) stats\s*$")
_TIME_RANGE = re.compile(r'timeRange="([^"]+)"')

# End-of-packages markers inside an interval section.
_SUBSECTION = re.compile(r"^\s*(packages|configurations|event aggregations|chooser counts)\s*$")


def _parse_range(raw: str) -> tuple[int | None, int | None]:
    """`5/9/2026, 18:29 – 6/9/2026, 16:18` or the compact `6/9/2026, 01:59–16:18`."""
    parts = re.split(r"\s*[–—-]\s*", raw.strip())
    # A date half contains slashes; rejoin so a stray split inside one is undone.
    halves: list[str] = []
    for part in parts:
        if halves and "/" not in part and not _CLOCK.match(part):
            halves[-1] = f"{halves[-1]}-{part}"
        else:
            halves.append(part)
    if len(halves) != 2:
        return None, None
    start = parse_timestamp(halves[0])
    end = parse_timestamp(halves[1])
    if end is None and start is not None:
        # compact form: the end half is a bare clock time on the start's date
        m = _CLOCK.match(halves[1].strip())
        if m:
            d = datetime.fromtimestamp(start / 1000)
            h, mi, s = m.groups()
            end = _mk(d.year, d.month, d.day, int(h), int(mi), int(s or 0))
    return start, end


def parse_dump(text: str, user: int = 0) -> Dump:
    """Parse one user's slice of a `dumpsys usagestats` dump."""
    dump = Dump(user=user)
    cur_user: int | None = None
    section: str | None = None       # 'events' | interval name
    in_packages = False
    r_start = r_end = None

    for line in text.splitlines():
        if not line.strip():
            continue

        m = _USER.match(line.rstrip())
        if m:
            cur_user = int(m.group(1))
            section, in_packages = None, False
            continue

        if cur_user != user:
            continue

        if _EVENTS_HDR.match(line):
            section, in_packages = "events", False
            m = _TIME_RANGE.search(line)
            if m:
                _, dump.device_now_ms = _parse_range(m.group(1))
            continue

        m = _INTERVAL_HDR.match(line)
        if m:
            section, in_packages = m.group(1), False
            r_start = r_end = None
            continue

        if section is None:
            continue

        stripped = line.strip()

        if section != "events":
            if stripped.startswith("timeRange="):
                m = _TIME_RANGE.search(stripped)
                if m:
                    r_start, r_end = _parse_range(m.group(1))
                continue
            m = _SUBSECTION.match(line)
            if m:
                in_packages = m.group(1) == "packages"
                continue
            if not in_packages or not stripped.startswith("package="):
                continue
            d = kv(stripped)
            pkg = d.get("package")
            if not pkg:
                continue
            dump.stats.append(
                PackageStat(
                    package=pkg,
                    interval=section,
                    range_start_ms=r_start,
                    range_end_ms=r_end,
                    total_ms=parse_duration(_first(d, "totalTimeUsed", "totalTime", "totalTimeInForeground") or ""),
                    visible_ms=parse_duration(d.get("totalTimeVisible", "")),
                    fs_ms=parse_duration(d.get("totalTimeFS", "")),
                    launches=int(d["appLaunchCount"]) if d.get("appLaunchCount", "").isdigit() else None,
                    last_used_ms=parse_timestamp(_first(d, "lastTimeUsed", "lastTime") or ""),
                )
            )
            continue

        # events section
        if not stripped.startswith("time="):
            # a non-event line ends the stream (e.g. mDumpInitLastTimeSaved=...)
            if "type=" not in stripped:
                section = None
            continue
        d = kv(stripped)
        ts = parse_timestamp(d.get("time", ""))
        etype = d.get("type")
        if ts is None or not etype:
            continue
        dump.events.append(
            Event(
                ts_ms=ts,
                type=etype,
                package=d.get("package", ""),
                klass=d.get("class", ""),
                instance_id=d.get("instanceId", ""),
            )
        )

    return dump


# --- session reconstruction -------------------------------------------------

RESUMED = "ACTIVITY_RESUMED"
PAUSED = "ACTIVITY_PAUSED"
STOPPED = "ACTIVITY_STOPPED"
SCREEN_ON = "SCREEN_INTERACTIVE"
SCREEN_OFF = "SCREEN_NON_INTERACTIVE"
UNLOCK = "KEYGUARD_HIDDEN"
LOCK = "KEYGUARD_SHOWN"
NOTIFICATION = "NOTIFICATION_INTERRUPTION"

# Guards against an app that is resumed and never paused (crash, force-stop,
# or a dump that simply ends mid-session) reporting an unbounded session.
MAX_SESSION_MS = 6 * 60 * 60 * 1000

# Moving between two activities of the same app emits PAUSED(a) then
# RESUMED(b) milliseconds apart. Treating that as two sessions would report
# WhatsApp as "opened 780 times" when the phone counted 116 launches, so a
# same-package reopen within this gap continues the session it interrupted.
MERGE_GAP_MS = 5_000


def foreground_sessions(events: list[Event], until_ms: int | None = None) -> list[tuple[str, int, int]]:
    """Collapse the event stream into [(package, start_ms, end_ms)].

    Only one activity is foreground at a time, so a RESUMED for a different
    package implicitly ends the previous one. Screen-off and keyguard end
    whatever is open: an app left paused should not accrue time overnight.
    """
    ordered = sorted(events, key=lambda e: (e.ts_ms, e.type))
    out: list[list] = []          # [package, start, end], mutated to merge
    pkg: str | None = None
    start = 0

    def close(at: int) -> None:
        nonlocal pkg
        if pkg is None:
            return
        end = min(at, start + MAX_SESSION_MS)
        if end > start:
            if out and out[-1][0] == pkg and start - out[-1][2] <= MERGE_GAP_MS:
                out[-1][2] = end
            else:
                out.append([pkg, start, end])
        pkg = None

    def open_(package: str, at: int) -> None:
        nonlocal pkg, start
        pkg, start = package, at

    for ev in ordered:
        if ev.type == RESUMED and ev.package:
            if pkg != ev.package:
                close(ev.ts_ms)
                open_(ev.package, ev.ts_ms)
        elif ev.type == PAUSED and ev.package:
            # A pause only matters for the app currently holding the
            # foreground; pauses for background activities are noise.
            if pkg == ev.package:
                close(ev.ts_ms)
        elif ev.type in (SCREEN_OFF, LOCK):
            close(ev.ts_ms)

    close(until_ms if until_ms is not None else (ordered[-1].ts_ms if ordered else 0))
    return [(p, a, b) for p, a, b in out]
