# The data

Reference for everything in the shared CSV archive: `My Drive/PhoneUsage/archive/`
in Google Drive, or `data/csv/` on a machine without Drive. Run
`.venv/bin/python -m wellbeing where` to see which one this machine uses. Counts
and samples below were taken from the archive on 2026-09-14.

## Three layers

| Layer | What it is |
|---|---|
| **`My Drive/PhoneUsage/archive/`** | The permanent, shared archive. Append-only: a day that has ever been written stays, even if a database is later lost or rebuilt. Lives in Google Drive, so it is already off-machine and readable from every computer. Falls back to `data/csv/` where Drive isn't installed. Its `archive.json` records the timezone every day and hour is cut in. |
| **`data/usage.db`** | The working store the dashboard reads — one per machine. Derived: rebuilt from the archive's `events/` with `wellbeing import`. Deliberately *not* in Drive, because a half-synced SQLite file is a corruption risk. A copy is taken to `data/usage.db.bak` before every sync. |
| **`My Drive/PhoneUsage/phone/`** | Exactly what the phone uploaded: one `events-YYYY-MM-DD.csv` per day (today's is replaced by a fuller copy each upload), the newest bucket snapshots, and `device.json`. Read by `ingest-phone`; the archive above is what to rely on. |

The phone discards raw events after about 9–10 days. Anything not synced inside
that window is gone permanently, which is why sync cadence matters more than
anything else here.

---

## Per-app files

### `app_daily.csv`
**How much did I use each app, each day?** — 649 rows, 2026-08-30 → 2026-09-13.

One row per app per **calendar day** (midnight to midnight). The file you will
use most.

| Column | Meaning |
|---|---|
| `day` | Local calendar date |
| `app`, `package` | Display name and Android package id |
| `ms` | Foreground time |
| `opens` | Times brought to the foreground |
| `longest_session_ms` | Longest single uninterrupted sitting |
| `first_use`, `last_use` | Local clock time of first and last use |
| `foreground_service_ms` | Background service time — calls, music, navigation, with the screen off |
| `notifications` | Interruptive notifications the app sent |
| `notifications_seen` | Of those, how many you actually saw |
| `interactions` | Touch interactions |

```
2026-09-05,WhatsApp,com.whatsapp,9422943,206,1273983,07:33,23:50,5941901,22,26,30
```
157 min foreground, opened 206 times, longest sitting 21 min, first touched
07:33, last 23:50, 99 min of calls, 22 notifications sent, 26 seen, 30 touches.

Days 2026-08-30 → 2026-09-03 have only `ms` and `opens`; the rest is blank
because the underlying raw events were lost before the archive existed.

### `app_hourly.csv`
**What was I using at 11pm?** — 1,235 rows, 2026-09-04 → 2026-09-13.

Same usage as above, split into hourly slots. Finest resolution held.

`day` · `hour` (0–23, local) · `app` · `package` · `ms`

```
2026-09-04,19,WhatsApp,com.whatsapp,279444
```

### `app_buckets.csv`
**How has this app changed over months?** — 5,914 rows, 2025-02-26 → now.

Not computed by us — the phone's own counters, and the **only file with data
before 2026-08-30**.

**What a "window" is.** Android runs four counters for every app at once, like
four trip meters that reset at different intervals: one daily, one weekly, one
monthly, one yearly. A *window* is the span one counter covers before it resets.
When a window closes the phone stores that finished bucket and opens a new one,
keeping the last few. This file is one row per **window x app**:

| interval | windows kept | apps | rows |
|---|---|---|---|
| `daily` | 10 | ~271 | 2,065 |
| `weekly` | 4 | ~311 | 1,084 |
| `monthly` | 6 | ~380 | 1,824 |
| `yearly` | 2 | ~595 | 941 |

**Windows do not start at midnight.** The daily ones run 18:30 to 18:30 on this
device — Android fixes the boundary whenever its usage service last restarted
and schedules the next rollover 24h later. Monthly windows roll on the 27th to
29th for the same reason, not on the 1st. So a row labelled
`daily, 2026-09-12 18:31 -> 2026-09-13 18:31` is the evening of the 12th plus the
daytime of the 13th, not "12 September". For true calendar days use
`app_daily.csv`, which is rebuilt from raw events.

**All four counters measure the same usage.** One evening of WhatsApp is counted
in that day's daily bucket, that week's weekly bucket, that month's monthly and
that year's yearly. Summing across intervals counts the same minutes four times
over — always filter to one `interval` first.

| Column | Meaning |
|---|---|
| `interval` | `daily`, `weekly`, `monthly` or `yearly` |
| `window_start`, `window_end` | Readable window bounds. On the newest (still open) window of each interval, `window_end` is "now as of when that row was last written", so it varies slightly between apps |
| `app`, `package` | Display name and package id |
| `total_ms` | Foreground time in that window |
| `visible_ms` | Visible time, including multi-window and picture-in-picture |
| `fs_ms` | Foreground-service time |
| `launches` | Launch count — **empty on most rows**, see Traps |
| `last_used_at` | Timestamp of last use |
| `last_component_at` | Timestamp any part of the app last ran, including in the background |
| `range_start_at` | Window start as a timestamp; the row's identity |
| `range_end_at` | Exact window end as a timestamp. `window_end` is this, rounded to the minute |

```
monthly,2026-06-27 12:26,2026-07-27 12:46,WhatsApp,com.whatsapp,200011965,206390183,291573751,,1785129975811,1785129976585,1782543418244,1785136601909
```
June–July: 55.6 h foreground, 57.3 h visible, 81 h of calls.

---

## Device-wide files

### `device_daily.csv`
**What did my whole day look like?** — 10 rows, 2026-09-04 → 2026-09-13.

| Column | Meaning |
|---|---|
| `day` | Local calendar date |
| `screen_on_ms` | Screen on, regardless of which app |
| `app_foreground_ms` | Of that, time attributed to an app |
| `idle_screen_ms` | Screen on with nothing in the foreground |
| `unlocked_ms` | Time past the lock screen |
| `unlocks` | Times unlocked |
| `notifications`, `notifications_seen` | Sent, and seen |
| `interactions` | Touch interactions |
| `apps_used` | Distinct apps that day |
| `sessions` | Foreground stretches across all apps |
| `longest_session_ms` | Longest single sitting in any app |
| `first_use`, `last_use` | First and last app use — wake and bedtime proxies |

```
2026-09-05,22410325,20013267,2397058,18310784,125,227,176,166,38,901,1273983,00:01,23:50
```
Screen on 6h 13m, 5h 33m in apps, **40 min idle**, unlocked 5h 05m, 125 unlocks,
901 sessions, awake on the phone 00:01 → 23:50.

### `daily.csv`
**Can I trust this day's numbers?** — 15 rows, 2026-08-30 → 2026-09-13.

Overlaps `device_daily.csv` on totals but carries the **coverage columns**, and
reaches 5 days further back.

`day` · `screen_ms` · `apps_used` · `unlocks` · `notifications` ·
`covered_from` · `covered_to` · `covered_hours` · `complete_day`

```
2026-08-30,11422705,46,61,157,13:30,23:40,10.2,no
```
Not a quiet day — only 10.2 hours of it were ever captured. `complete_day` is
`no`, so its 190 min is a floor, not a measurement.

### `hourly.csv`
**When am I on my phone?** — 226 rows, 2026-08-30 → 2026-09-13.

All apps combined, per hour. Powers the dashboard's hour-by-hour profile.

`day` · `hour` · `ms` — e.g. `2026-08-30,14,898467`

### `device_counters.csv`
**How often, and for how long?** — 88 rows, 2025-02-26 → now.

Screen and lock counters straight from the phone, each with a count *and* a
duration.

`interval` · `window_start` · `event` · `event_type` · `count` ·
`total_time_ms` · `last_event_at` · `range_start_at` · `range_end_at`

```
daily,2026-09-04 18:29,SCREEN_INTERACTIVE,15,172,18131638,0,1788526789945,1788613189944
```
Screen turned on 172 times, on for 5h 02m. Also `SCREEN_NON_INTERACTIVE`,
`KEYGUARD_SHOWN`, `KEYGUARD_HIDDEN`. This is the independent cross-check behind
`idle_screen_ms`.

### `device_configs.csv`
**Portrait or landscape? Dark mode?** — 108 rows, 2025-02-26 → now.

`interval` · `window_start` · `config` · `activations` · `total_active_ms` ·
`last_active_at` · `range_start_at` · `range_end_at`

`config` is Android's raw configuration string. Grep it for `port`/`land`
(orientation), `night` (dark mode), locale and density. Landscape time is a
reasonable proxy for video and gaming.

---

### `garmin_daily.csv`
**What did my body do that day?** — from the Garmin watch, one row per calendar day.

Fetched from Garmin Connect's cloud, not the phone. Joins to every other file on
`day`. Only days the watch actually recorded appear — a day with no row means the
watch was not worn or did not exist yet, which is different from a row of zeros.

| Column | Meaning |
|---|---|
| `day` | Local calendar date |
| `steps`, `distance_m`, `floors_up` | Movement |
| `calories`, `active_calories` | Total and activity-only |
| `resting_hr`, `min_hr`, `max_hr` | Heart rate |
| `avg_stress`, `max_stress` | Garmin's stress score, 0-100 |
| `body_battery_wake`, `body_battery_high`, `body_battery_low` | Body Battery, 0-100 |
| `intensity_minutes` | Moderate + 2x vigorous, Garmin's own weighting |
| `active_ms`, `highly_active_ms`, `sedentary_ms` | How the day was spent |
| `avg_spo2`, `avg_respiration` | Blood oxygen, breaths per minute |
| `sleep_ms` | Time asleep |
| `deep_sleep_ms`, `light_sleep_ms`, `rem_sleep_ms`, `awake_ms` | The stages |
| `awake_count` | Times woken |
| `sleep_start_at`, `sleep_end_at` | Absolute timestamps -- use these to join against sessions |
| `sleep_start`, `sleep_end` | The same, as local clock labels |
| `sleep_score`, `sleep_stress` | Garmin's own scores |

**A night is filed under the date you woke up.** The night of the 20th appears as
`2026-09-21`, and its `sleep_start_at` falls on the 20th. Pair a bedtime with the
*previous* day's phone use.

**Use `sleep_start_at`/`sleep_end_at`, not `first_use`/`last_use`, to ask when
someone stopped using their phone.** `last_use` in `device_daily.csv` is clipped
at midnight, so a session running past midnight reports `00:00` and a real 03:36
bedtime looks like 23:08 the evening before.

## The backstop

### `events/events-YYYY-MM.csv`
**The raw truth** — 52,561 rows for September 2026, one file per month.

`ts_at` · `type` · `package` · `class` · `instance_id`

```
1788529994594,ACTIVITY_RESUMED,com.whatsapp,com.whatsapp.Main,
```

Every screen-on, app-resume, notification and unlock, unprocessed. **Every other
file here can be recomputed from this one**, which is exactly why it exists:
2026-08-30 → 2026-09-03 lost its hour- and session-level detail because this
archive did not yet exist when those events were pruned from the phone.

---

## Conventions

- **Days, hours and clock labels are in the archive's timezone**, recorded in
  `archive.json` (`Asia/Kolkata`) -- not the clock of whichever machine exported.
  That covers every `day` and `hour`, `first_use`/`last_use`, `covered_from`/
  `covered_to`, and `window_start`/`window_end`. The `_at` timestamps are
  absolute and need no zone.
- **Dashboard app exclusions do not affect these files.** Apps unticked in the
  dashboard's "Exclude apps from totals" panel are left out of the dashboard's
  totals only; every CSV here still counts them, so the archive stays comparable
  across days no matter how the list changes.
- **`_ms` is a duration** in milliseconds. Divide by 60000 for minutes.
- **`_at` is a timestamp** in milliseconds since 1970-01-01.
- **There are no `minutes` columns.** A rounded second copy of each duration
  would drift from the exact one — a month of summed minutes would disagree with
  the same month of summed milliseconds.
- **Blank means "not measured"; `0` means "measured, and it was none".** The gap
  matters: blanks in early `app_daily.csv` rows are unknown, not zero, and the
  import path preserves the distinction rather than coercing unknowns to `0`.
- **A number in the archive never goes down.** Every figure here is a count or a
  duration over a fixed period, so it can only grow as more of that period is
  captured. The export merges cell by cell and keeps the larger value, so a
  machine that saw less of a day cannot thin one that saw more -- whatever it
  sends. Before 2026-09-30 the merge picked a winner by comparing a single
  column, and a machine whose event stream had a seven-day hole overwrote six
  good days of `device_daily.csv` with rows reading 24h of screen-on and zero of
  everything else. Restored from a snapshot; the rule above is the fix.
- **The phone-window files round-trip losslessly.** `app_buckets.csv`,
  `device_counters.csv` and `device_configs.csv` carry exact `range_end_at` and
  last-seen timestamps, so a database rebuilt from the archive with `import`
  matches the original cell for cell.

---

## Traps

**Never sum across `interval` values in `app_buckets.csv`.** The daily, weekly,
monthly and yearly rows describe the *same* usage at different resolutions.
Adding them multiplies your screen time. Filter to one `interval` first.

**`app_buckets.csv` windows are not calendar days.** They roll at about 18:30,
whenever the phone's usage service last restarted. A row labelled
`2026-09-04 18:29 → 2026-09-05 18:29` spans two dates. For calendar days use
`app_daily.csv`.

**The newest window of each interval is still open.** `window_end` is "now", so
the current monthly row may cover 18 days rather than 30. Divide by the actual
window length before comparing.

**Check `complete_day` before comparing days.** The oldest day in any sync is
clipped by the phone's retention, and today is still in progress.

**`fs_ms` is not part of `total_ms`.** They are separate measures and
foreground-service time often exceeds foreground time — 48.6 h vs 102 h for
WhatsApp in July. Don't subtract one from the other.

**`launches` is empty on most `app_buckets.csv` rows.** `appLaunchCount` is not
exposed by the public API the companion app uses; only rows captured through the
older `dumpsys` path have it. Use `opens` in `app_daily.csv` instead.

---

## Which file for which question

| Question | File |
|---|---|
| App usage over days | `app_daily.csv` |
| App usage by hour | `app_hourly.csv` |
| App trend over months | `app_buckets.csv` |
| Whole-day totals | `device_daily.csv` |
| Is this day trustworthy? | `daily.csv` |
| Phone use by hour | `hourly.csv` |
| Screen-on independent of apps | `device_counters.csv` |
| Orientation, dark mode | `device_configs.csv` |
| Body, sleep, steps | `garmin_daily.csv` |
| Anything else | `events/` |

`daily.csv` and `device_daily.csv` genuinely overlap on daily totals. The split
is historical rather than principled: `daily.csv` came first and owns the
coverage columns, `device_daily.csv` added screen-on and idle time. Worth merging
at some point.
