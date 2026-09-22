# adb_usage_stats

Pulls Digital Wellbeing style usage statistics off a Samsung phone over USB and
serves them as a local dashboard. No root, and nothing installed on the phone.

## Where the numbers come from

`adb shell dumpsys usagestats` dumps Android's `UsageStatsManager` service —
the same system service Samsung Digital Wellbeing reads. The dump has two parts:

| Part | What it is | How it's used |
|---|---|---|
| **Last 24h event stream** | `ACTIVITY_RESUMED` / `ACTIVITY_PAUSED`, `SCREEN_INTERACTIVE`, `KEYGUARD_HIDDEN` (unlocks), `NOTIFICATION_INTERRUPTION` | Replayed into foreground sessions → screen time per app, per hour, per calendar day |
| **Rolling interval buckets** | the phone's own daily/weekly/monthly/yearly totals per package | Kept for cross-checking, not used for the calendar view |

The buckets can't drive a calendar dashboard: the "daily" bucket rolls over
whenever the usage service last restarted (**18:29** on the test device), not at
midnight. So the event stream is the source of truth, and because the phone only
keeps 24 hours of it, every sync appends into SQLite. **Sync at least once a day
and history accumulates; skip three days and that gap is gone for good.**

Screen time counts foreground app time and stops at screen-off, matching Digital
Wellbeing. (Android's own bucket keeps counting an app that stays resumed with
the screen off — which is why Maps during navigation reads higher there.)

## Install

Python 3.10+ and a USB cable are all you need.

```bash
cd ~/adb_usage_stats

# 1. adb (platform-tools) — already unpacked into ./platform-tools here.
#    To get it elsewhere:
#    curl -LO https://dl.google.com/android/repository/platform-tools-latest-darwin.zip
#    unzip platform-tools-latest-darwin.zip

# 2. Python deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### On the phone, once

1. **Settings → About phone → Software information** → tap **Build number** 7×.
2. **Settings → Developer options → USB debugging** → on.
3. Plug in with a **data** cable, then tap **Allow** on the *Allow USB debugging?*
   prompt and tick *Always allow from this computer*.

Check it took:

```bash
.venv/bin/python -m wellbeing devices
# RZCT914N6VM   device   (samsung SM-S901E, Android 16)
```

## Use

```bash
.venv/bin/python -m wellbeing sync      # pull from the phone into data/usage.db
.venv/bin/python -m wellbeing serve     # dashboard on http://127.0.0.1:5000
.venv/bin/python -m wellbeing report    # same numbers, in the terminal
```

The dashboard has a **Sync phone** button, so day to day you only need `serve`.

### Keep it current automatically

A daily pull, so no history is lost (runs only when the phone happens to be
plugged in; failures are harmless):

```bash
crontab -e
# 0 22 * * *  cd ~/adb_usage_stats && .venv/bin/python -m wellbeing sync >> data/sync.log 2>&1
```

### Two computers, one archive

The CSV archive is the shared source of truth and lives in Google Drive; each
machine keeps its own local `data/usage.db`, rebuilt from that archive. The
database is deliberately *not* in Drive -- a half-synced SQLite file plus its
write-ahead log is a real corruption risk, while append-only CSV is safe.

```
  phone ──USB──> whichever machine is handy
                      │  deep-sync + export
                      v
             My Drive/PhoneUsageBackup/        <- the shared archive
                      │  import
                      v
           any machine ──> local usage.db ──> dashboard
```

| Task | Command |
|---|---|
| Sync the phone and update the archive | `./sync.sh` |
| View the dashboard anywhere | `./dashboard.sh` |
| Where are things? | `.venv/bin/python -m wellbeing where` |

`dashboard.sh` runs `import` first, so a machine that has never seen the phone
still shows the full history. `sync.sh` writes straight into the archive -- there
is no separate backup step.

**Every machine cuts days and hours in the archive's timezone, not its own clock.**
The zone is recorded once in the archive's `archive.json` (`Asia/Kolkata`), and
every command pins itself to it before doing any date arithmetic. Without this, a
machine on a different clock files the same events under different days and
hours -- WSL defaults to UTC, 5h30m behind India -- and the shared calendar files
end up with shifted duplicates. `where` shows the recorded zone; a brand-new
archive gets one with `python -m wellbeing set-timezone <Area/City>`.

The archive location is found automatically (macOS `CloudStorage`, WSL `/mnt`).
Override it with `PHONE_USAGE_ARCHIVE=/path/to/dir`. The first export at a new
location carries the old archive across, so installing Drive does not lose the
days the phone has already forgotten.

#### Setting up the Windows machine (WSL Ubuntu)

**1. Google Drive for desktop on Windows**, signed in to the same account. In
its settings, right-click `PhoneUsageBackup` → **Available offline**, so reads
from WSL don't stall waiting on downloads.

**2. Get the code.** This folder is not a git repo; its code is bundled at
`My Drive/PhoneUsageCode/adb_usage_stats.zip`. Unpack it into the *Linux* home
directory, not under `/mnt/c` -- the database must not live on the Windows
filesystem, and the scripts need their executable bit:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip unzip curl wslu
cp "/mnt/g/My Drive/PhoneUsageCode/adb_usage_stats.zip" ~/   # adjust path, see step 3
cd ~ && unzip adb_usage_stats.zip && cd adb_usage_stats
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
chmod +x sync.sh dashboard.sh
```

**3. Check the archive is found:**

```bash
.venv/bin/python -m wellbeing where
```

It should say `(Google Drive)` and `timezone: Asia/Kolkata`. The WSL clock can stay on
UTC; the archive's timezone is what counts. Drive streams as a drive letter (usually `G:`,
seen as `/mnt/g`); in mirror mode it's `C:\Users\<you>\My Drive`. If `where`
says *local only*, either mount the drive letter:

```bash
sudo mkdir -p /mnt/g && sudo mount -t drvfs G: /mnt/g
```

or point at the folder directly, permanently:

```bash
echo 'export PHONE_USAGE_ARCHIVE="/mnt/g/My Drive/PhoneUsageBackup"' >> ~/.bashrc
source ~/.bashrc
```

**Don't run an export until `where` shows the Drive path.** Pointing at an
empty folder would start a new archive instead of using the shared one.

**4. View the dashboard:**

```bash
./dashboard.sh
```

It imports the archive and serves on http://127.0.0.1:5000, which opens in your
Windows browser too.

#### Syncing from Windows — every time

Plug in and unlock the phone, then in Ubuntu run `phonesync` (or
`~/adb_usage_stats/sync-windows.sh`). It finds and attaches the phone, syncs,
opens the dashboard, and hands the phone back to Windows. One-time setup below.

#### Syncing the phone from WSL (optional)

WSL2 has no USB access of its own, so the phone is passed through with
usbipd-win.

**One time, in Windows** — an **admin PowerShell**:

```powershell
winget install --interactive --exact dorssel.usbipd-win
usbipd list                        # note the phone's BUSID, e.g. 2-4
usbipd bind --busid 2-4            # one time only
```

**One time, in WSL** — Linux platform-tools, inside the project folder:

```bash
curl -LO https://dl.google.com/android/repository/platform-tools-latest-linux.zip
unzip -o platform-tools-latest-linux.zip && rm platform-tools-latest-linux.zip
```

**Every sync:**

1. Plug in and unlock the phone.
2. Admin PowerShell: `usbipd attach --wsl --busid 2-4`
3. On the phone, tap **Allow** on the USB debugging prompt. This computer has a
   different key from the Mac, so it asks once.
4. WSL: `./sync.sh`

The companion app is already on the phone, so WSL needs no Java or Android SDK.
If `sync.sh` reports *no permissions*, run
`./platform-tools/adb kill-server && sudo ./platform-tools/adb start-server` once.

**Only one machine should sync at a time.** Both write the same archive, and
Drive resolves simultaneous edits by leaving conflict copies.

### Leaving apps out of screen time

Open **Exclude apps from totals** under "Most used apps" and untick any app. It
then disappears from **every statistic**: screen time, the day blocks, the
waking-hours share, the app list, the pickup analysis and the switch chains. The
panel itself still lists every app, so you can tick one back on. Screen-on time,
unlocks and notification counts are not app-based and never change.

The list is stored in the archive's `archive.json`, so both computers use the same
one. It is **not** applied to the CSV export: `daily.csv` and `hourly.csv` keep the
same meaning they always had, so editing the list never makes archived days
incomparable. `app_daily.csv` still holds every app, so any total can be recomputed.

### What the dashboard shows

Locked as of 2026-09-14. Six sections, top to bottom:

1. **Summary block** — a 3x3 grid. Rows are *Total*, *A day* and *Share*;
   columns are screen time, unlocks and notifications. The Share row carries
   the pickup analysis: screen time as a share of a 16h waking day, the
   percentage of unlocks lasting under 30s, and the percentage with no
   notification behind them.
2. **Screen time per day** — one bar per day.
3. **Most used apps** — ranked; click any app to open its drill-down.
4. **App drill-down** — opens on WhatsApp by default. Time and opens per day,
   median vs mean visit length, weekday vs weekend, whether it is the first app
   on waking and the last before sleep, its hourly profile, and the apps it
   hands off to and from.
5. **Across the day** — the day split into six blocks (Night, Morning,
   Afternoon, Evening, Late, Pre-bed) plus an hour-by-hour profile with every
   hour labelled.
6. **Table view** — collapsed daily numbers.

Range buttons: 1d / 3d / 7d / 14d / 30d / 90d / All. Every section re-scopes.

`WAKING_HOURS` (dashboard.html) and `BOOKEND_TOLERANCE_MS`, `DAY_BLOCKS`
(stats.py) are the constants worth knowing if you want to adjust the
assumptions later.

### Deeper history: the companion APK

`dumpsys usagestats` only prints what the service holds **in memory** — 24h of
events. `UsageStatsManager.queryEvents` / `queryUsageStats` read the *persisted*
store behind it, which goes back about **10 days of events** and months of
aggregates. Those APIs need an app holding `PACKAGE_USAGE_STATS`, so `android/`
contains a ~150-line APK that queries them and writes CSV.

```bash
.venv/bin/python -m wellbeing deep-sync      # builds, installs, runs, ingests
```

First run installs `com.shrey.usagedump` and grants usage access over adb
(`appops set com.shrey.usagedump GET_USAGE_STATS allow`) — the same permission
you would grant by hand in *Settings → Apps → Special access → Usage data
access*. No root. The APK does nothing but read those two APIs and write two
CSVs to its own files directory; it has no network permission.

Building it needs the toolchain in `tools/` (JDK 17 + build-tools + android.jar,
downloaded once, ~300MB). `android/build.sh` builds without Gradle:
aapt2 → javac → d8 → zipalign → apksigner.

**`deep-sync` reaches back ~10 days; `sync` reaches back 24h.** Both write to
the same database, so run `deep-sync` if you have missed a few days, and either
one daily to keep history growing.

#### What is *not* reachable

Digital Wellbeing's own database holds more, but it is guarded by
`com.samsung.permission.READ_DW_DATA`, which is `signature|privileged` — only
apps signed with Samsung's platform key can read it. `/data/system/usagestats/`
is likewise root-only, and this phone is a `user` build (`ro.debuggable=0`), so
`adb root` is unavailable. Ten days of events plus the rolling aggregates is the
ceiling without rooting the device.

### CSV export

```bash
.venv/bin/python -m wellbeing export            # everything (the default)
.venv/bin/python -m wellbeing export --days 30  # limit to the last 30 days
```

Writes to the shared archive — `My Drive/PhoneUsageBackup/`, or `data/csv/` on a
machine without Google Drive. **See [DATA.md](DATA.md)** for what each file is for,
what every column means, and the traps worth knowing about.

| File | One row per | Notes |
|---|---|---|
| `app_daily.csv` | app x calendar day | time, opens, longest session, first/last use, foreground-service time, notifications, interactions |
| `app_hourly.csv` | app x hour | finest per-app resolution |
| `app_buckets.csv` | app x the phone's own window | `interval` is daily/weekly/monthly/yearly; reaches back to Feb 2025 |
| `daily.csv` | calendar day | screen time plus the coverage columns |
| `device_daily.csv` | calendar day | screen-on, app-foreground, idle screen, unlocked, sessions, interactions |
| `hourly.csv` | hour | all apps combined |
| `device_counters.csv` | phone window | screen on/off and lock/unlock, count *and* duration |
| `device_configs.csv` | phone window | orientation, night mode, locale |
| `events/events-YYYY-MM.csv` | single event | the backstop -- every file above can be recomputed from these |

**Column conventions.** Durations end in `_ms` (milliseconds); timestamps end in
`_at` (milliseconds since the epoch). There are no `minutes` columns: a rounded
second copy of each duration would drift from the exact one, so consumers divide
`_ms` by 60000.

**The CSVs are an archive, not a snapshot.** Each export merges into the existing
files: a day that has ever been written stays, even if a later export runs
against a rebuilt or restored database that no longer has it, and a fuller
reading of a day is never replaced by a thinner one. Files are written via a temp
file and renamed, so an interrupted export cannot truncate the archive.

That makes the archive a second, independent copy of your history alongside
each machine's `data/usage.db`.

**Off-machine by default.** When Google Drive for desktop is installed the
archive lives directly in `My Drive/PhoneUsageBackup/`, and Drive uploads it — there
is no separate backup step. Without Drive it falls back to `data/csv/`.

**Two traps in `app_buckets.csv`.** Its windows are the phone's, not calendar
days -- the "daily" ones roll at ~18:30. And the four intervals describe the same
usage at different resolutions, so filter to one `interval` before summing or you
will multiply your screen time.

### All commands

| Command | Does |
|---|---|
| `devices` | list attached devices and their state |
| `sync` | capture from the phone and ingest, last 24h (`--serial`, `--fetch-labels`, `--no-raw`) |
| `deep-sync` | pull ~10 days via the companion APK (`--days`, `--serial`) |

Every sync copies `data/usage.db` to `data/usage.db.bak` before writing.
| `ingest FILE` | ingest a previously saved dump from `raw/` |
| `report` | terminal summary (`--days`, `--top`) |
| `export` | write CSVs to the shared archive (`--all`, `--days`, `--out`) |
| `import` | rebuild this machine's database from the shared archive (`--source`) |
| `where` | show which archive, timezone and database this machine uses |
| `set-timezone ZONE` | record the archive's timezone, once; refuses to change it |
| `serve` | run the dashboard (`--host`, `--port`) |
| `rebuild` | recompute derived tables from stored events |

`--fetch-labels` looks unknown package names up on the Play Store to get real app
names. It is **off by default** because it sends your installed package names to
Google; without it, unknown apps fall back to a prettified package name.

## Layout

```
wellbeing/
  adb.py       device discovery and shell calls
  parse.py     dumpsys parser + session reconstruction
  db.py        SQLite schema
  sync.py      capture → ingest → rebuild derived tables
  stats.py     read-side queries
  labels.py    package id → app name
  server.py    Flask app and JSON API
  templates/dashboard.html
data/usage.db  the history (this is the thing to back up)
raw/           raw dumps, one per sync
```

`events` is the single source of truth; `sessions` and `usage_slice` are derived
and can always be regenerated with `rebuild`.

## Caveats

- Only the primary user (`user=0`) is read. Secure Folder and work profiles
  (`user=95`, `user=150`) are dumped too but deliberately skipped.
- App *names* aren't in the dump — see `--fetch-labels` above.
- The dump format is Android-version specific. It was written against
  Android 16 / One UI on an SM-S901E; the parser accepts several key spellings,
  but a very different version may need `parse.py` adjusted.
