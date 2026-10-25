"""Usage events and per-package buckets, and turning events into sessions.

Events are the calendar-aligned source of truth: the phone's own "daily"
bucket rolls over whenever its usage service last restarted (18:29 on the
S22), not at midnight, so screen time per day and hour is rebuilt from the
ACTIVITY_* / screen / keyguard stream instead.
"""
from __future__ import annotations

from dataclasses import dataclass


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
