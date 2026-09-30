"""Read-side queries. Everything reads the derived tables, never the raw dump."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta

DAY_EXPR = "strftime('%Y-%m-%d', ts_ms/1000, 'unixepoch', 'localtime')"

UNLOCK_EVENT = "KEYGUARD_HIDDEN"
NOTIFICATION_EVENT = "NOTIFICATION_INTERRUPTION"

# Packages that are infrastructure rather than "an app you used". Foreground
# time for these is real, but counting the keyboard or the permission dialog as
# screen time makes every other number harder to read.
CHROME = (
    "com.android.systemui",
    "com.google.android.permissioncontroller",
    "com.samsung.android.honeyboard",
    "com.google.android.inputmethod.latin",
    "com.samsung.android.app.cocktailbardervice",
)


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def _exclusion(column: str, include_chrome: bool, exclude=()) -> tuple[str, tuple]:
    """SQL fragment leaving out system packages and the user's chosen apps."""
    pkgs = tuple(dict.fromkeys((() if include_chrome else CHROME) + tuple(exclude)))
    if not pkgs:
        return "", ()
    return f" AND {column} NOT IN ({_placeholders(len(pkgs))})", pkgs


def coverage(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT MIN(ts_ms) lo, MAX(ts_ms) hi, COUNT(*) n FROM events"
    ).fetchone()
    last = conn.execute(
        "SELECT ts_ms, device, android, events_added FROM syncs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    days = [r[0] for r in conn.execute("SELECT DISTINCT day FROM usage_slice ORDER BY day")]
    return {
        "first_event_ms": row["lo"],
        "last_event_ms": row["hi"],
        "event_count": row["n"],
        "days": days,
        "last_sync": dict(last) if last else None,
        "sync_count": conn.execute("SELECT COUNT(*) FROM syncs").fetchone()[0],
    }


def default_range(conn: sqlite3.Connection, span_days: int = 14) -> tuple[str, str]:
    days = [r[0] for r in conn.execute("SELECT DISTINCT day FROM usage_slice ORDER BY day")]
    if not days:
        today = date.today()
        return str(today - timedelta(days=span_days - 1)), str(today)
    end = days[-1]
    start = str(datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=span_days - 1))
    return max(start, days[0]), end


def daily_totals(conn: sqlite3.Connection, start: str, end: str,
                 include_chrome: bool = False, exclude=()) -> list[dict]:
    """Per-day screen time, app count, unlocks and notifications."""
    excl, args = _exclusion("package", include_chrome, exclude)
    usage = {
        r["day"]: r
        for r in conn.execute(
            f"""SELECT day, SUM(ms) AS ms, COUNT(DISTINCT package) AS apps
                FROM usage_slice WHERE day BETWEEN ? AND ?{excl}
                GROUP BY day""",
            (start, end, *args),
        )
    }
    counts = {
        (r["day"], r["type"]): r["n"]
        for r in conn.execute(
            f"""SELECT {DAY_EXPR} AS day, type, COUNT(*) AS n FROM events
                WHERE type IN (?, ?) AND {DAY_EXPR} BETWEEN ? AND ?
                GROUP BY day, type""",
            (UNLOCK_EVENT, NOTIFICATION_EVENT, start, end),
        )
    }
    out = []
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while cur <= last:
        d = str(cur)
        u = usage.get(d)
        out.append({
            "day": d,
            "ms": u["ms"] if u else 0,
            "apps": u["apps"] if u else 0,
            "unlocks": counts.get((d, UNLOCK_EVENT), 0),
            "notifications": counts.get((d, NOTIFICATION_EVENT), 0),
        })
        cur += timedelta(days=1)
    return out


def top_apps(conn: sqlite3.Connection, start: str, end: str, limit: int = 12,
             include_chrome: bool = False, exclude=()) -> list[dict]:
    excl, args = _exclusion("u.package", include_chrome, exclude)
    rows = conn.execute(
        f"""SELECT u.package,
                   COALESCE(a.label, u.package) AS label,
                   SUM(u.ms) AS ms,
                   (SELECT COUNT(*) FROM sessions s
                     WHERE s.package = u.package AND s.day BETWEEN ? AND ?) AS opens
            FROM usage_slice u LEFT JOIN apps a USING (package)
            WHERE u.day BETWEEN ? AND ?{excl}
            GROUP BY u.package ORDER BY ms DESC LIMIT ?""",
        (start, end, start, end, *args, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def hourly(conn: sqlite3.Connection, start: str, end: str,
           include_chrome: bool = False, exclude=()) -> list[dict]:
    """day x hour matrix of foreground milliseconds."""
    excl, args = _exclusion("package", include_chrome, exclude)
    rows = conn.execute(
        f"""SELECT day, hour, SUM(ms) AS ms FROM usage_slice
            WHERE day BETWEEN ? AND ?{excl}
            GROUP BY day, hour""",
        (start, end, *args),
    ).fetchall()
    return [dict(r) for r in rows]


def app_history(conn: sqlite3.Connection, package: str, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        """SELECT day, SUM(ms) AS ms FROM usage_slice
           WHERE package = ? AND day BETWEEN ? AND ? GROUP BY day ORDER BY day""",
        (package, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def phone_buckets(conn: sqlite3.Connection, interval: str = "daily", limit: int = 12) -> list[dict]:
    """The phone's own rolling totals -- shown when event history is still thin."""
    latest = conn.execute(
        "SELECT MAX(range_start_ms) FROM interval_stats WHERE interval = ?", (interval,)
    ).fetchone()[0]
    if latest is None:
        return []
    rows = conn.execute(
        """SELECT s.package, COALESCE(a.label, s.package) AS label,
                  s.total_ms AS ms, s.launches, s.range_start_ms, s.range_end_ms
           FROM interval_stats s LEFT JOIN apps a USING (package)
           WHERE s.interval = ? AND s.range_start_ms = ? AND COALESCE(s.total_ms, 0) > 0
           ORDER BY s.total_ms DESC LIMIT ?""",
        (interval, latest, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def app_daily(conn: sqlite3.Connection, start: str, end: str,
              include_chrome: bool = False) -> list[dict]:
    """One row per (day, app): foreground time and how often it was opened."""
    excl, args = _exclusion("u.package", include_chrome)
    rows = conn.execute(
        f"""SELECT u.day,
                   u.package,
                   COALESCE(a.label, u.package) AS label,
                   SUM(u.ms) AS ms,
                   (SELECT COUNT(*) FROM sessions s
                     WHERE s.package = u.package AND s.day = u.day) AS opens
            FROM usage_slice u LEFT JOIN apps a USING (package)
            WHERE u.day BETWEEN ? AND ?{excl}
            GROUP BY u.day, u.package
            ORDER BY u.day, ms DESC""",
        (start, end, *args),
    ).fetchall()
    return [dict(r) for r in rows]


def day_coverage(conn: sqlite3.Connection, start: str, end: str) -> dict[str, dict]:
    """First and last event actually recorded per day.

    The phone only retains 24h of events, so a day synced late is partial. A
    day whose coverage does not span 00:00 to 23:59 has usage the dump never
    saw, and its totals are a floor, not a measurement.
    """
    rows = conn.execute(
        f"""SELECT {DAY_EXPR} AS day, MIN(ts_ms) AS lo, MAX(ts_ms) AS hi
            FROM events WHERE {DAY_EXPR} BETWEEN ? AND ? GROUP BY day""",
        (start, end),
    ).fetchall()
    out = {}
    for r in rows:
        lo = datetime.fromtimestamp(r["lo"] / 1000)
        hi = datetime.fromtimestamp(r["hi"] / 1000)
        span_h = (r["hi"] - r["lo"]) / 3_600_000
        out[r["day"]] = {
            "covered_from": lo.strftime("%H:%M"),
            "covered_to": hi.strftime("%H:%M"),
            "covered_hours": round(span_h, 1),
            # A full day of events runs 00:00 to ~23:59; allow slack for a
            # quiet start or end to the day.
            "complete": lo.hour == 0 and hi.hour == 23,
        }
    return out


def hourly_rows(conn: sqlite3.Connection, start: str, end: str,
                include_chrome: bool = False) -> list[dict]:
    return sorted(hourly(conn, start, end, include_chrome), key=lambda r: (r["day"], r["hour"]))


# The phone keeps only 24h of events, but its rolling buckets reach much
# further back -- as one cumulative total per app, with no day breakdown.
BUCKET_LABELS = {
    "weekly": "This week",
    "monthly": "This month",
    "yearly": "Since the counter reset",
}


def long_history(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
    """The phone's own long-window totals, newest window per interval."""
    out = []
    for interval in ("weekly", "monthly", "yearly"):
        rows = phone_buckets(conn, interval, limit)
        if not rows:
            continue
        start_ms, end_ms = rows[0]["range_start_ms"], rows[0]["range_end_ms"]
        span_days = max(1, round((end_ms - start_ms) / 86_400_000))
        out.append({
            "interval": interval,
            "title": BUCKET_LABELS[interval],
            "start": datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d"),
            "end": datetime.fromtimestamp(end_ms / 1000).strftime("%Y-%m-%d"),
            "days": span_days,
            "apps": [
                {
                    "package": r["package"], "label": r["label"], "ms": r["ms"],
                    "launches": r["launches"] or 0,
                    "per_day_ms": round(r["ms"] / span_days),
                }
                for r in rows
            ],
        })
    return out


# How long after a notification an unlock still counts as "caused" by it.
# Past a couple of minutes the link is guesswork, not evidence.
PICKUP_WINDOW_MS = 120_000

# An unlock that ends this fast did not accomplish anything -- a reflex check.
JUNK_PICKUP_MS = 30_000

LOCK_EVENT = "KEYGUARD_SHOWN"


def notification_pickups(conn: sqlite3.Connection, start: str, end: str,
                         window_ms: int = PICKUP_WINDOW_MS, exclude=()) -> dict:
    """Split unlocks into notification-triggered and self-initiated.

    An unlock counts as triggered when a notification arrived *during the
    locked stretch immediately before it* and within `window_ms` of the unlock.
    Requiring it to land inside that stretch is what stops a notification you
    already saw, hours earlier, from being credited for a later pickup; the
    unlock is attributed to the most recent notifier.
    """
    rows = conn.execute(
        f"""SELECT ts_ms, type, package FROM events
            WHERE type IN (?, ?, ?) AND {DAY_EXPR} BETWEEN ? AND ?
            ORDER BY ts_ms""",
        (NOTIFICATION_EVENT, UNLOCK_EVENT, LOCK_EVENT, start, end),
    ).fetchall()

    triggered: dict[str, int] = defaultdict(int)
    sent: dict[str, int] = defaultdict(int)
    delays: list[int] = []
    unlocks = 0
    attributed = 0
    pending: list[tuple[int, str]] = []   # notifications since the last lock

    skip = set(exclude)
    for r in rows:
        if r["type"] == NOTIFICATION_EVENT:
            if r["package"] in skip:
                continue
            sent[r["package"]] += 1
            pending.append((r["ts_ms"], r["package"]))
        elif r["type"] == LOCK_EVENT:
            pending.clear()
        else:  # unlock
            unlocks += 1
            recent = [(t, p) for t, p in pending if r["ts_ms"] - t <= window_ms and p]
            if recent:
                ts, pkg = recent[-1]
                triggered[pkg] += 1
                delays.append(r["ts_ms"] - ts)
                attributed += 1
            pending.clear()

    labels = {row["package"]: row["label"] for row in
              conn.execute("SELECT package, label FROM apps")}
    apps = sorted(
        ({"package": p, "label": labels.get(p, p), "pickups": n,
          "notifications": sent.get(p, 0),
          "rate": round(100 * n / sent[p]) if sent.get(p) else 0}
         for p, n in triggered.items()),
        key=lambda a: -a["pickups"],
    )
    delays.sort()
    return {
        "unlocks": unlocks,
        "triggered": attributed,
        "self_initiated": unlocks - attributed,
        "pct_triggered": round(100 * attributed / unlocks) if unlocks else 0,
        "median_delay_s": round(delays[len(delays) // 2] / 1000) if delays else 0,
        "apps": apps,
        "notifiers": sorted(
            ({"package": p, "label": labels.get(p, p), "notifications": n,
              "pickups": triggered.get(p, 0)} for p, n in sent.items()),
            key=lambda a: -a["notifications"],
        )[:12],
    }


def pickup_quality(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Count unlocks that ended almost immediately -- reflex checks."""
    rows = conn.execute(
        f"""SELECT ts_ms, type FROM events
            WHERE type IN (?, ?) AND {DAY_EXPR} BETWEEN ? AND ?
            ORDER BY ts_ms""",
        (UNLOCK_EVENT, LOCK_EVENT, start, end),
    ).fetchall()
    junk = total = 0
    open_at = None
    for r in rows:
        if r["type"] == UNLOCK_EVENT:
            open_at = r["ts_ms"]
        elif open_at is not None:
            total += 1
            if r["ts_ms"] - open_at < JUNK_PICKUP_MS:
                junk += 1
            open_at = None
    return {"sessions": total, "junk": junk,
            "pct_junk": round(100 * junk / total) if total else 0}


def app_detail(conn: sqlite3.Connection, package: str, start: str, end: str,
               exclude=()) -> dict:
    """Everything known about one app over a date range.

    Session-derived figures (opens, longest sitting) come from `sessions`;
    minutes come from `usage_slice`, which is clipped to hour and day
    boundaries. The two agree on totals but only `sessions` can answer "how
    long was one sitting".
    """
    label = conn.execute(
        "SELECT COALESCE(label, ?) FROM apps WHERE package = ?", (package, package)
    ).fetchone()
    label = label[0] if label else package

    per_day = {
        r["day"]: dict(r) for r in conn.execute(
            """SELECT day, SUM(ms) AS ms FROM usage_slice
               WHERE package = ? AND day BETWEEN ? AND ? GROUP BY day""",
            (package, start, end),
        )
    }
    sess = {
        r["day"]: dict(r) for r in conn.execute(
            """SELECT day, COUNT(*) AS opens, MAX(end_ms - start_ms) AS longest_ms,
                      MIN(start_ms) AS first_ms, MAX(end_ms) AS last_ms
               FROM sessions WHERE package = ? AND day BETWEEN ? AND ? GROUP BY day""",
            (package, start, end),
        )
    }

    daily = []
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while cur <= last:
        d = str(cur)
        u, sv = per_day.get(d), sess.get(d)
        daily.append({
            "day": d,
            "ms": (u or {}).get("ms", 0),
            "opens": (sv or {}).get("opens", 0),
            "longest_ms": (sv or {}).get("longest_ms", 0),
            "first": datetime.fromtimestamp(sv["first_ms"] / 1000).strftime("%H:%M") if sv else "",
            "last": datetime.fromtimestamp(sv["last_ms"] / 1000).strftime("%H:%M") if sv else "",
        })
        cur += timedelta(days=1)

    hourly = [
        dict(r) for r in conn.execute(
            """SELECT hour, SUM(ms) AS ms FROM usage_slice
               WHERE package = ? AND day BETWEEN ? AND ? GROUP BY hour ORDER BY hour""",
            (package, start, end),
        )
    ]

    durations = [
        r[0] for r in conn.execute(
            """SELECT end_ms - start_ms FROM sessions
               WHERE package = ? AND day BETWEEN ? AND ? ORDER BY 1""",
            (package, start, end),
        )
    ]
    notifs = conn.execute(
        f"""SELECT COUNT(*) FROM events WHERE package = ? AND type = ?
            AND {DAY_EXPR} BETWEEN ? AND ?""",
        (package, NOTIFICATION_EVENT, start, end),
    ).fetchone()[0]

    active = [d for d in daily if d["ms"] > 0]
    total_ms = sum(d["ms"] for d in daily)
    total_opens = sum(d["opens"] for d in daily)
    sh_excl, sh_args = _exclusion("package", False, exclude)
    share = conn.execute(
        f"SELECT SUM(ms) FROM usage_slice WHERE day BETWEEN ? AND ?{sh_excl}",
        (start, end, *sh_args),
    ).fetchone()[0] or 0

    return {
        "package": package,
        "label": label,
        "excluded": package in set(exclude),
        "daily": daily,
        "hourly": hourly,
        "weekday_split": weekday_split(conn, package, start, end),
        "bookends": app_bookends(conn, package, start, end, exclude=exclude),
        "switch_chain": switch_chain(conn, package, start, end, exclude=exclude),
        "totals": {
            "ms": total_ms,
            "opens": total_opens,
            "active_days": len(active),
            "per_day_ms": round(total_ms / len(active)) if active else 0,
            "avg_session_ms": round(total_ms / total_opens) if total_opens else 0,
            "median_session_ms": durations[len(durations) // 2] if durations else 0,
            "longest_ms": max(durations) if durations else 0,
            "notifications": notifs,
            "share_pct": round(100 * total_ms / share, 1) if share else 0,
            "busiest_hour": max(hourly, key=lambda h: h["ms"])["hour"] if hourly else None,
        },
    }


SCREEN_ON, SCREEN_OFF_EV = "SCREEN_INTERACTIVE", "SCREEN_NON_INTERACTIVE"
FS_START, FS_STOP = "FOREGROUND_SERVICE_START", "FOREGROUND_SERVICE_STOP"
INTERACTION_EVENT = "USER_INTERACTION"


# A screen-on or unlock that never closes is a hole in the event stream, not a
# marathon. The events table can have gaps -- a machine that synced after the
# phone had already pruned days, a database rebuilt from a partial archive -- and
# pairing across one attributes the whole gap as usage. That is not hypothetical:
# a seven-day gap once paired 2026-09-14 17:02 with 2026-09-21 18:36 and handed
# six intermediate days a full 86,400,000 ms of screen-on with zero app time,
# which then won the archive merge and overwrote six good days. An unclosed pair
# is dropped rather than clamped: under-counting a gap is honest, inventing a
# day of screen time is not.
MAX_SCREEN_PAIR_MS = 12 * 60 * 60 * 1000       # no phone is interactive for 12h straight
MAX_SERVICE_PAIR_MS = 24 * 60 * 60 * 1000      # music and navigation legitimately run long


def _paired_ms_per_day(conn, start_type: str, stop_type: str, start: str, end: str,
                       by_package: bool = False,
                       max_pair_ms: int = MAX_SCREEN_PAIR_MS) -> dict:
    """Total milliseconds between start/stop event pairs, split at local midnight.

    Used for screen-on, unlocked, and foreground-service time -- all of which are
    open/close pairs in the event stream rather than stored durations. A pair
    longer than `max_pair_ms` is treated as a lost stop event and skipped.
    """
    rows = conn.execute(
        f"""SELECT ts_ms, type, package FROM events WHERE type IN (?, ?)
            AND {DAY_EXPR} BETWEEN ? AND ? ORDER BY ts_ms""",
        (start_type, stop_type, start, end),
    ).fetchall()
    out: dict = defaultdict(int)
    open_at: dict[str, int] = {}
    for r in rows:
        key = r["package"] if by_package else ""
        if r["type"] == start_type:
            open_at.setdefault(key, r["ts_ms"])
        elif key in open_at:
            a, b = open_at.pop(key), r["ts_ms"]
            if b - a > max_pair_ms:
                continue                       # stop event lost; do not invent the gap
            # Work the pair out before committing any of it, because the rule
            # that matters is about the RESULT, not the pair's length: no single
            # day may be credited with all 24 hours. A day can only receive
            # 86,400,000 ms if it sits wholly inside the pair, which means the
            # stop event was lost -- and a length cap alone does not catch it. A
            # pair running exactly midnight to midnight is 24h, passes any 24h
            # ceiling, touches one day, and hands that day the entire thing.
            # This is how Amazon Music came to show a full day of playback on
            # days the app was never opened.
            chunks = []
            t = a
            while t < b:
                d = datetime.fromtimestamp(t / 1000).date()
                edge = int(datetime(d.year, d.month, d.day).timestamp() * 1000) + 86_400_000
                stop = min(b, edge)
                chunks.append(((str(d), key) if by_package else str(d), stop - t))
                t = stop
            if any(ms >= 86_400_000 for _, ms in chunks):
                continue
            for slot, ms in chunks:
                out[slot] += ms
    return dict(out)


def device_daily(conn: sqlite3.Connection, start: str, end: str, exclude=()) -> list[dict]:
    """Device-wide metrics per calendar day."""
    screen = _paired_ms_per_day(conn, SCREEN_ON, SCREEN_OFF_EV, start, end)
    unlocked = _paired_ms_per_day(conn, UNLOCK_EVENT, LOCK_EVENT, start, end)
    base = {r["day"]: r for r in daily_totals(conn, start, end, exclude=exclude)}
    s_excl, s_args = _exclusion("package", True, exclude)
    sess = {
        r["day"]: r for r in conn.execute(
            f"""SELECT day, COUNT(*) AS sessions, MAX(end_ms - start_ms) AS longest_ms,
                       MIN(start_ms) AS first_ms, MAX(end_ms) AS last_ms
                FROM sessions WHERE day BETWEEN ? AND ?{s_excl} GROUP BY day""",
            (start, end, *s_args),
        )
    }
    counts = {
        (r["day"], r["type"]): r["n"] for r in conn.execute(
            f"""SELECT {DAY_EXPR} AS day, type, COUNT(*) AS n FROM events
                WHERE type IN (?, ?, ?) AND {DAY_EXPR} BETWEEN ? AND ?
                GROUP BY day, type""",
            (INTERACTION_EVENT, NOTIFICATION_EVENT, "NOTIFICATION_SEEN", start, end),
        )
    }
    out = []
    for day, row in sorted(base.items()):
        sv = sess.get(day)
        on = screen.get(day, 0)
        out.append({
            "day": day,
            "screen_on_ms": on,
            "app_foreground_ms": row["ms"],
            "idle_screen_ms": max(0, on - row["ms"]),
            "unlocked_ms": unlocked.get(day, 0),
            "unlocks": row["unlocks"],
            "notifications": row["notifications"],
            "notifications_seen": counts.get((day, "NOTIFICATION_SEEN"), 0),
            "interactions": counts.get((day, INTERACTION_EVENT), 0),
            "apps_used": row["apps"],
            "sessions": sv["sessions"] if sv else 0,
            "longest_session_ms": sv["longest_ms"] if sv else 0,
            "first_use": datetime.fromtimestamp(sv["first_ms"] / 1000).strftime("%H:%M") if sv else "",
            "last_use": datetime.fromtimestamp(sv["last_ms"] / 1000).strftime("%H:%M") if sv else "",
        })
    return out


def app_daily_full(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Per-app, per-calendar-day: every event-derived metric available."""
    fs = _paired_ms_per_day(conn, FS_START, FS_STOP, start, end, by_package=True,
                            max_pair_ms=MAX_SERVICE_PAIR_MS)
    labels = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    usage = {
        (r["day"], r["package"]): r["ms"] for r in conn.execute(
            "SELECT day, package, SUM(ms) AS ms FROM usage_slice WHERE day BETWEEN ? AND ?"
            " GROUP BY day, package", (start, end))
    }
    sess = {
        (r["day"], r["package"]): r for r in conn.execute(
            """SELECT day, package, COUNT(*) AS opens, MAX(end_ms - start_ms) AS longest_ms,
                      MIN(start_ms) AS first_ms, MAX(end_ms) AS last_ms
               FROM sessions WHERE day BETWEEN ? AND ? GROUP BY day, package""",
            (start, end))
    }
    counts = {
        (r["day"], r["package"], r["type"]): r["n"] for r in conn.execute(
            f"""SELECT {DAY_EXPR} AS day, package, type, COUNT(*) AS n FROM events
                WHERE type IN (?, ?, ?) AND {DAY_EXPR} BETWEEN ? AND ?
                GROUP BY day, package, type""",
            (NOTIFICATION_EVENT, "NOTIFICATION_SEEN", INTERACTION_EVENT, start, end))
    }
    keys = set(usage) | set(sess) | {(d, p) for (d, p) in fs}
    keys |= {(d, p) for (d, p, _t) in counts}
    out = []
    for day, pkg in sorted(keys):
        sv = sess.get((day, pkg))
        out.append({
            "day": day,
            "app": labels.get(pkg, pkg),
            "package": pkg,
            "ms": usage.get((day, pkg), 0),
            "opens": sv["opens"] if sv else 0,
            "longest_session_ms": sv["longest_ms"] if sv else 0,
            "first_use": datetime.fromtimestamp(sv["first_ms"] / 1000).strftime("%H:%M") if sv else "",
            "last_use": datetime.fromtimestamp(sv["last_ms"] / 1000).strftime("%H:%M") if sv else "",
            "foreground_service_ms": fs.get((day, pkg), 0),
            "notifications": counts.get((day, pkg, NOTIFICATION_EVENT), 0),
            "notifications_seen": counts.get((day, pkg, "NOTIFICATION_SEEN"), 0),
            "interactions": counts.get((day, pkg, INTERACTION_EVENT), 0),
        })
    return out


def app_hourly(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    labels = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    return [
        {"day": r["day"], "hour": r["hour"], "app": labels.get(r["package"], r["package"]),
         "package": r["package"], "ms": r["ms"]}
        for r in conn.execute(
            "SELECT day, hour, package, ms FROM usage_slice WHERE day BETWEEN ? AND ?"
            " ORDER BY day, hour, package", (start, end))
    ]


# Home screens and system surfaces are passed through between apps rather than
# "used", so a switch chain that includes them says only that you went via the
# launcher. Collapsing them turns "Gmail -> Home -> WhatsApp" into the real hop.
PASSTHROUGH = CHROME + (
    "com.sec.android.app.launcher",
    "com.samsung.android.app.launcher",
    "com.android.intentresolver",
    "android",
)

# How close to the phone's own first/last use of the day an app has to be for it
# to count as the thing you reached for on waking, or put down at night.
BOOKEND_TOLERANCE_MS = 10 * 60 * 1000


def weekday_split(conn: sqlite3.Connection, package: str, start: str, end: str) -> dict:
    """Weekday vs weekend usage for one app, averaged per day."""
    rows = conn.execute(
        """SELECT u.day, SUM(u.ms) AS ms,
                  (SELECT COUNT(*) FROM sessions s
                    WHERE s.package = u.package AND s.day = u.day) AS opens
           FROM usage_slice u WHERE u.package = ? AND u.day BETWEEN ? AND ?
           GROUP BY u.day""",
        (package, start, end),
    ).fetchall()

    groups = {"weekday": {"ms": 0, "opens": 0, "days": 0},
              "weekend": {"ms": 0, "opens": 0, "days": 0}}
    for r in rows:
        d = datetime.strptime(r["day"], "%Y-%m-%d").date()
        g = groups["weekend" if d.weekday() >= 5 else "weekday"]
        g["ms"] += r["ms"]
        g["opens"] += r["opens"]
        g["days"] += 1
    for g in groups.values():
        days = max(1, g["days"])
        g["ms_per_day"] = round(g["ms"] / days)
        g["opens_per_day"] = round(g["opens"] / days)
    return groups


def app_bookends(conn: sqlite3.Connection, package: str, start: str, end: str,
                 exclude=()) -> dict:
    """Is this the first app you open on waking, and the last before sleep?"""
    app = {
        r["day"]: r for r in conn.execute(
            """SELECT day, MIN(start_ms) AS first_ms, MAX(end_ms) AS last_ms
               FROM sessions WHERE package = ? AND day BETWEEN ? AND ? GROUP BY day""",
            (package, start, end))
    }
    p_excl, p_args = _exclusion("package", True, exclude)
    phone = {
        r["day"]: r for r in conn.execute(
            f"""SELECT day, MIN(start_ms) AS first_ms, MAX(end_ms) AS last_ms
                FROM sessions WHERE day BETWEEN ? AND ?{p_excl} GROUP BY day""",
            (start, end, *p_args))
    }
    days = []
    for day in sorted(phone):
        a, p = app.get(day), phone[day]
        if not a:
            continue
        days.append({
            "day": day,
            "app_first": datetime.fromtimestamp(a["first_ms"] / 1000).strftime("%H:%M"),
            "app_last": datetime.fromtimestamp(a["last_ms"] / 1000).strftime("%H:%M"),
            "phone_first": datetime.fromtimestamp(p["first_ms"] / 1000).strftime("%H:%M"),
            "phone_last": datetime.fromtimestamp(p["last_ms"] / 1000).strftime("%H:%M"),
            "is_first": a["first_ms"] - p["first_ms"] <= BOOKEND_TOLERANCE_MS,
            "is_last": p["last_ms"] - a["last_ms"] <= BOOKEND_TOLERANCE_MS,
        })
    n = len(days) or 1
    return {
        "days": days,
        "first_pct": round(100 * sum(d["is_first"] for d in days) / n),
        "last_pct": round(100 * sum(d["is_last"] for d in days) / n),
        "day_count": len(days),
    }


def switch_chain(conn: sqlite3.Connection, package: str, start: str, end: str,
                 limit: int = 6, exclude=()) -> dict:
    """Which apps hand off to this one, and which it hands off to."""
    skip = set(PASSTHROUGH) | set(exclude)
    seq = [
        r["package"] for r in conn.execute(
            "SELECT package FROM sessions WHERE day BETWEEN ? AND ? ORDER BY start_ms",
            (start, end))
        if r["package"] not in skip
    ]
    labels = {r["package"]: r["label"] for r in conn.execute("SELECT package, label FROM apps")}
    into: dict[str, int] = defaultdict(int)
    out: dict[str, int] = defaultdict(int)
    for a, b in zip(seq, seq[1:]):
        if b == package and a != package:
            into[a] += 1
        if a == package and b != package:
            out[b] += 1

    def top(counts):
        return [{"package": p, "label": labels.get(p, p), "count": n}
                for p, n in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]

    return {"into": top(into), "out": top(out),
            "into_total": sum(into.values()), "out_total": sum(out.values())}


# Logical parts of the day. Boundaries are half-open [start, end) in local
# hours; the first wraps past midnight. Together they cover all 24 hours, so
# every minute of use lands in exactly one block.
DAY_BLOCKS = (
    ("Night", 23.5, 7.0),
    ("Morning", 7.0, 12.0),
    ("Afternoon", 12.0, 17.0),
    ("Evening", 17.0, 20.0),
    ("Late", 20.0, 22.5),
    ("Pre-bed", 22.5, 23.5),
)


def _hhmm(hour: float) -> str:
    h, m = int(hour), round((hour - int(hour)) * 60)
    return f"{h:02d}:{m:02d}"


def day_blocks(conn: sqlite3.Connection, start: str, end: str,
               include_chrome: bool = False, exclude=()) -> list[dict]:
    """Foreground time split into named parts of the day.

    Clipped against the block boundaries directly rather than bucketed by hour:
    a boundary at 23:30 falls mid-hour, so hour-level bucketing would put the
    whole 23:00 hour on one side of it.
    """
    excl, args = _exclusion("package", include_chrome, exclude)
    rows = conn.execute(
        f"SELECT start_ms, end_ms FROM sessions WHERE day BETWEEN ? AND ?{excl}",
        (start, end, *args),
    ).fetchall()

    totals = {name: 0 for name, _, _ in DAY_BLOCKS}
    for r in rows:
        a, b = r["start_ms"], r["end_ms"]
        while a < b:
            d = datetime.fromtimestamp(a / 1000)
            hour = d.hour + d.minute / 60 + d.second / 3600
            # the block holding `a`, and the moment it ends
            for name, lo, hi in DAY_BLOCKS:
                inside = (lo <= hour < hi) if lo < hi else (hour >= lo or hour < hi)
                if inside:
                    midnight = d.replace(hour=0, minute=0, second=0, microsecond=0)
                    edge = midnight + timedelta(hours=hi)
                    if hi <= hour:                     # wrapped block: edge is tomorrow
                        edge += timedelta(days=1)
                    edge_ms = int(edge.timestamp() * 1000)
                    chunk = min(b, edge_ms)
                    totals[name] += max(0, chunk - a)
                    a = max(chunk, a + 1)              # never stall on a zero-width block
                    break
            else:
                break

    day_count = len({r[0] for r in conn.execute(
        "SELECT DISTINCT day FROM usage_slice WHERE day BETWEEN ? AND ?", (start, end))}) or 1
    grand = sum(totals.values()) or 1
    return [
        {"name": name, "from": _hhmm(lo), "to": _hhmm(hi),
         "ms": totals[name], "ms_per_day": round(totals[name] / day_count),
         "share": round(100 * totals[name] / grand, 1)}
        for name, lo, hi in DAY_BLOCKS
    ]
