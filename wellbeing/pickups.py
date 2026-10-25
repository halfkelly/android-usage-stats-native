"""Pick-ups: every time the screen came on, what it was for, and how long it lasted.

One row per screen-on stretch, from SCREEN_INTERACTIVE to SCREEN_NON_INTERACTIVE:

    glance        the screen came on and went off without an unlock -- the time,
                  a notification on the lock screen
    pick-up       it was unlocked (KEYGUARD_HIDDEN)
    micro         a pick-up shorter than MICRO_MS: unlocked, and put down again
                  before anything much could have been done
    triggered     a notification arrived during the locked stretch before it, at
                  most TRIGGER_WINDOW_MS earlier (the rule notification_pickups uses)
    impulse       a pick-up that was not triggered: you reached for the phone

Measured on this phone the lock follows screen-off by ~0.9 s, so ending at
screen-off and starting at screen-on gives honest durations.
"""
from __future__ import annotations

from datetime import datetime

from .parse import (LOCK, MAX_SESSION_MS, NOTIFICATION, RESUMED, SCREEN_OFF, SCREEN_ON, UNLOCK,
                    Event)

TRIGGER_WINDOW_MS = 120_000
MICRO_MS = 30_000
# A screen left on longer than this is missing its screen-off, not a pick-up.
MAX_PICKUP_MS = MAX_SESSION_MS

# Not "an app you went to": the keyboard, the permission dialog, the launcher.
# Mirrors stats.PASSTHROUGH; kept here so stats can import this module.
PASSTHROUGH = frozenset((
    "com.android.systemui",
    "com.google.android.permissioncontroller",
    "com.samsung.android.honeyboard",
    "com.google.android.inputmethod.latin",
    "com.samsung.android.app.cocktailbardervice",
    "com.sec.android.app.launcher",
    "com.samsung.android.app.launcher",
    "com.android.intentresolver",
    "android",
))

TYPES = (SCREEN_ON, SCREEN_OFF, UNLOCK, LOCK, NOTIFICATION, RESUMED)
FIELDS = ("day", "start_ms", "unlock_ms", "end_ms", "duration_ms", "unlocked", "first_package",
          "packages", "trigger_package", "trigger_delay_ms", "micro", "impulse")


def build(events: list[Event]) -> list[dict]:
    """Collapse an event stream into pick-up rows. A stretch still open at the
    end of the stream is left out: the next rebuild sees it whole."""
    ordered = sorted(events, key=lambda e: (e.ts_ms, e.type))
    out: list[dict] = []
    on_at = unlock_at = None
    apps: list[str] = []
    trigger = None
    pending: list[tuple[int, str]] = []   # notifications since the last lock

    def trigger_for(at: int):
        recent = [(t, p) for t, p in pending if 0 <= at - t <= TRIGGER_WINDOW_MS and p]
        return (recent[-1][1], at - recent[-1][0]) if recent else None

    for ev in ordered:
        if ev.type == NOTIFICATION:
            pending.append((ev.ts_ms, ev.package))
        elif ev.type == LOCK:
            pending.clear()
        elif ev.type == SCREEN_ON:
            # A second screen-on with no screen-off between: the first one's end
            # was never recorded. Dropped rather than guessed.
            on_at, unlock_at, apps = ev.ts_ms, None, []
            trigger = trigger_for(ev.ts_ms)
        elif ev.type == UNLOCK and on_at is not None and unlock_at is None:
            unlock_at = ev.ts_ms
            trigger = trigger_for(ev.ts_ms)
            pending.clear()
        elif ev.type == RESUMED and unlock_at is not None and ev.package \
                and ev.package not in PASSTHROUGH and ev.package not in apps:
            apps.append(ev.package)
        elif ev.type == SCREEN_OFF and on_at is not None:
            duration = ev.ts_ms - on_at
            if 0 <= duration <= MAX_PICKUP_MS:
                unlocked = unlock_at is not None
                out.append({
                    "day": datetime.fromtimestamp(on_at / 1000).strftime("%Y-%m-%d"),
                    "start_ms": on_at,
                    "unlock_ms": unlock_at,
                    "end_ms": ev.ts_ms,
                    "duration_ms": duration,
                    "unlocked": int(unlocked),
                    "first_package": apps[0] if apps else "",
                    "packages": ";".join(apps),
                    "trigger_package": trigger[0] if trigger else "",
                    "trigger_delay_ms": trigger[1] if trigger else None,
                    "micro": int(unlocked and duration < MICRO_MS),
                    "impulse": int(unlocked and trigger is None),
                })
            on_at = unlock_at = trigger = None
            apps = []
    return out
