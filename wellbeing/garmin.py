"""Garmin Connect, over the cloud.

The watch itself serves no files on the network -- its Wi-Fi only talks to
Garmin's servers -- and the Garmin Connect app keeps its FIT cache in private
storage that adb cannot read without root. So the only wireless route to this
data is Garmin's own API, reached with the `garth` library.

Two things to know about that library. It is deprecated and pinned to 0.6.3:
from 0.7 it signs in through `sso.garmin.com/mobile/api/login`, which Garmin now
answers with a flat 429 for anything that is not the real Garmin app. 0.6.3 uses
the web SSO flow -- `/sso/embed` and `/sso/signin`, exactly what a browser at
connect.garmin.com goes through -- and that still answers, provided the
user-agent is a browser rather than garth's `GCM-iOS-...` default, which `login`
below takes care of. Verified 2026-09-24: web endpoints 200, mobile API 429.
And it is unofficial, so it can stop working whenever Garmin decides. Neither is
a reason not to use it -- the data is the user's own and there is no sanctioned
API for it -- but it is a reason to keep the archive append-only, exactly like
the phone data: whatever we fetch today survives the API breaking tomorrow.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import archive

ROOT = Path(__file__).resolve().parent.parent

# Tokens are credentials, so they stay on the machine that logged in -- not in
# the shared Drive archive. The other computer reads Garmin data from the CSVs
# like any other history, and only needs its own login if it is to sync too.
TOKEN_DIR = ROOT / "data" / "garth"

# Garmin broke garth's `GCM-iOS-...` user-agent. A browser string gets through.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class GarminError(RuntimeError):
    pass


def _garth():
    try:
        import garth
    except ImportError as exc:                                   # pragma: no cover
        raise GarminError("garth is not installed. Run: .venv/bin/pip install garth") from exc
    return garth


def _as_browser(garth) -> None:
    garth.client.sess.headers.update({"User-Agent": BROWSER_UA})


def login(email: str, password: str, prompt_mfa=None) -> Path:
    """Sign in and save the OAuth tokens. Returns where they were written."""
    garth = _garth()
    _as_browser(garth)
    try:
        if prompt_mfa is not None:
            garth.login(email, password, prompt_mfa=prompt_mfa)
        else:
            garth.login(email, password)
    except Exception as exc:                # garth raises a grab-bag of types
        raise GarminError(
            f"Garmin login failed: {exc}\n"
            "If this is a Cloudflare block rather than a wrong password, Garmin has "
            "tightened the flow again; the fallback is to sign in with a browser and "
            "copy the OAuth tokens into " + str(TOKEN_DIR)
        ) from exc
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    garth.save(str(TOKEN_DIR))
    return TOKEN_DIR


def resume():
    """Load saved tokens. Raises GarminError when there is no usable session."""
    garth = _garth()
    if not (TOKEN_DIR / "oauth2_token.json").exists():
        raise GarminError(
            "Not signed in to Garmin. Run:  .venv/bin/python -m wellbeing garmin-login"
        )
    try:
        garth.resume(str(TOKEN_DIR))
        _as_browser(garth)
        garth.client.username           # forces a refresh, so an expired token fails here
    except Exception as exc:
        raise GarminError(
            f"Garmin session could not be resumed ({exc}). Sign in again:  "
            ".venv/bin/python -m wellbeing garmin-login"
        ) from exc
    return garth


def _s2ms(seconds) -> int | None:
    return None if seconds is None else int(round(float(seconds) * 1000))


def _clock(epoch_ms) -> str:
    """Local wall-clock label, in the archive's timezone like every other one."""
    if not epoch_ms:
        return ""
    return datetime.fromtimestamp(epoch_ms / 1000).strftime("%H:%M")


def fetch(days: int = 28, end: date | None = None) -> list[dict]:
    """One row per calendar day: the daily summary joined to that night's sleep."""
    garth = resume()
    end = end or date.today()
    rows: dict[str, dict] = {}

    for summary in garth.DailySummary.list(end, days):
        day = str(summary.calendar_date)
        rows[day] = {
            "day": day,
            "steps": summary.total_steps,
            "distance_m": summary.total_distance_meters,
            "floors_up": summary.floors_ascended,
            "calories": summary.total_kilocalories,
            "active_calories": summary.active_kilocalories,
            "resting_hr": summary.resting_heart_rate,
            "min_hr": summary.min_heart_rate,
            "max_hr": summary.max_heart_rate,
            "avg_stress": summary.average_stress_level,
            "max_stress": summary.max_stress_level,
            "body_battery_wake": summary.body_battery_at_wake_time,
            "body_battery_high": summary.body_battery_highest_value,
            "body_battery_low": summary.body_battery_lowest_value,
            # Garmin's own weighting: vigorous minutes count double. Stays None
            # when neither was measured -- blank means "not measured" in the
            # archive, and 0 would claim the watch was worn and saw no movement.
            "intensity_minutes": None if summary.moderate_intensity_minutes is None
                                 and summary.vigorous_intensity_minutes is None
                                 else (summary.moderate_intensity_minutes or 0)
                                      + 2 * (summary.vigorous_intensity_minutes or 0),
            "active_ms": _s2ms(summary.active_seconds),
            "highly_active_ms": _s2ms(summary.highly_active_seconds),
            "sedentary_ms": _s2ms(summary.sedentary_seconds),
            "avg_spo2": summary.average_spo_2,
            "avg_respiration": summary.avg_waking_respiration_value,
        }

    # Sleep is fetched a day at a time; Garmin files a night under the date you
    # woke up on, which is what we want for joining to a phone-usage day.
    for offset in range(days):
        day = str(end - timedelta(days=offset))
        try:
            sleep = garth.SleepData.get(day)
        except Exception:
            continue                      # one bad night must not sink the sync
        if not sleep or not sleep.daily_sleep_dto:
            continue
        d = sleep.daily_sleep_dto
        row = rows.setdefault(day, {"day": day})
        scores = d.sleep_scores
        row.update({
            "sleep_ms": _s2ms(d.sleep_time_seconds),
            "deep_sleep_ms": _s2ms(d.deep_sleep_seconds),
            "light_sleep_ms": _s2ms(d.light_sleep_seconds),
            "rem_sleep_ms": _s2ms(d.rem_sleep_seconds),
            "awake_ms": _s2ms(d.awake_sleep_seconds),
            "awake_count": d.awake_count,
            "sleep_start_at": d.sleep_start_timestamp_gmt,
            "sleep_end_at": d.sleep_end_timestamp_gmt,
            "sleep_start": _clock(d.sleep_start_timestamp_gmt),
            "sleep_end": _clock(d.sleep_end_timestamp_gmt),
            "sleep_score": getattr(getattr(scores, "overall", None), "value", None),
            "sleep_stress": d.avg_sleep_stress,
        })

    # Days before the watch existed come back as a full set of Nones. An empty
    # row would archive a claim that the day was measured and was blank.
    return [rows[k] for k in sorted(rows)
            if any(v is not None and v != "" for f, v in rows[k].items() if f != "day")]


FIELDS = [
    "day", "steps", "distance_m", "floors_up", "calories", "active_calories",
    "resting_hr", "min_hr", "max_hr", "avg_stress", "max_stress",
    "body_battery_wake", "body_battery_high", "body_battery_low",
    "intensity_minutes", "active_ms", "highly_active_ms", "sedentary_ms",
    "avg_spo2", "avg_respiration",
    "sleep_ms", "deep_sleep_ms", "light_sleep_ms", "rem_sleep_ms", "awake_ms",
    "awake_count", "sleep_start_at", "sleep_end_at", "sleep_start", "sleep_end",
    "sleep_score", "sleep_stress",
]


def ingest(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert daily rows, never letting a blank overwrite a value already held."""
    cols = FIELDS[1:]
    sets = ", ".join(f"{c} = COALESCE(excluded.{c}, garmin_daily.{c})" for c in cols)
    conn.executemany(
        f"""INSERT INTO garmin_daily ({', '.join(FIELDS)})
            VALUES ({', '.join('?' * len(FIELDS))})
            ON CONFLICT(day) DO UPDATE SET {sets}""",
        [tuple(r.get(f) for f in FIELDS) for r in rows],
    )
    conn.commit()
    return len(rows)


def daily(conn: sqlite3.Connection, start: str = "", end: str = "") -> list[dict]:
    where, args = "", []
    if start and end:
        where, args = " WHERE day BETWEEN ? AND ?", [start, end]
    return [dict(r) for r in conn.execute(
        f"SELECT {', '.join(FIELDS)} FROM garmin_daily{where} ORDER BY day", args)]
