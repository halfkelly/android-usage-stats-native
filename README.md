# android-usage-stats-native

Digital Wellbeing style usage statistics from a Samsung phone, shown as a
dashboard on the phone itself and on Windows (WSL, in Docker). No root. The phone collects and uploads on
its own; the computer never needs to connect to it.

## How it works

```
phone   Usage Dump app, every 6 h, no network needed to collect
          raw CSVs -> uploads changed files to My Drive/PhoneUsage/phone/
                      (drive.file: it can see only the files it created)
PC      Google Drive for desktop brings My Drive down as G:
          wellbeing ingest-phone -> data/usage.db -> PhoneUsage/archive/ -> dashboard
```

The phone keeps raw events for only about 10 days. Collecting on the phone
writes every day out within 6 hours, whether or not the computer is on.

**Everything in Drive is under `My Drive/PhoneUsage/`:**

| Folder | What | Written by |
|---|---|---|
| `phone/` | raw day files, snapshots, `device.json` | the phone app |
| `archive/` | the permanent CSV history, see [DATA.md](DATA.md) | `ingest-phone` / `export` |
| `code/signing/` | the app's signing key and OAuth client (backup) | you, once |

The app creates `PhoneUsage` itself: its `drive.file` permission can only
write into folders it made.

## Day to day

Nothing is needed. To see the numbers:

- **On the phone:** Usage Dump → **Open dashboard**. The same page, worked out
  on the phone from its own data (history from when the app was installed).
- **On the PC:** **Phone Usage Dashboard** on the Desktop (a copy of
  `Open dashboard.bat`) starts the dashboard container if it isn't running and
  opens http://127.0.0.1:5000. The page shows what's already here at once, then
  checks Drive for the phone's latest uploads in the background. **How to read
  this** explains every figure and assumption.
- To pull in the latest right now: tap **Run now** in the app, give Drive a
  minute, then **Get phone data** on the dashboard, or **Sync my phone.bat**.
- `./wb where` shows when the phone last uploaded.

The dashboard container keeps running until **Stop dashboard.bat** or a
reboot; closing the tab is fine. The Windows task **PhoneUsageAutosync** runs
at 03:00, 09:00, 15:00 and 21:00: it starts the dashboard container if needed
and runs the `sync` container once, which reads the phone's uploads into the
database and the archive.

If the phone stops uploading, the phone shows a notification (usage access
off, Drive sign-in expired, nothing uploaded for a day). The dashboard, `where`
and `ingest-phone` also warn once it has been quiet for a day.

## Setup

### The PC (WSL Ubuntu, Docker)

1. **Google Drive for desktop** on Windows, signed in to the same account.
   Right-click `PhoneUsage` → **Available offline**, so reads don't wait on
   downloads. WSL sees it as `/mnt/g/My Drive/PhoneUsage`, which
   `docker-compose.yml` mounts; if Drive is elsewhere, set `PHONE_USAGE_DRIVE`.
2. **Docker Engine in WSL**, with systemd on (`/etc/wsl.conf`: `[boot]
   systemd=true`) and your user in the `docker` group.
3. The code, in the Linux home (not under `/mnt/c`):
   ```bash
   git clone git@github.com:Shrey97/android-usage-stats-native.git ~/android-usage-stats-native
   cd ~/android-usage-stats-native
   docker compose build
   docker compose up -d dashboard
   ./wb where
   ```
   `where` should show the archive and `timezone: Asia/Kolkata`. Every day and
   hour is cut in the archive's zone, recorded in `archive.json`. An empty
   `data/` is filled from the archive on the first sync.
4. The scheduled task (Task Scheduler → PhoneUsageAutosync), action
   `wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd ~/android-usage-stats-native &&
   docker compose up -d dashboard && docker compose run --rm sync'`.

What's where: the images hold only code. `data/` (database, its backups, the
Garmin login, logs) and the Drive folder are mounted in, so rebuilding or
deleting a container loses nothing.

### The phone

1. Install the APK (see "Building the phone app"). Copy it to Drive and open it
   on the phone, or install it over the cable.
2. Open **Usage Dump** and tap the buttons it shows: **Grant usage access**,
   **Let it run in the background**, allow notifications, then
   **Connect Google Drive**. That opens the phone's own account picker: choose
   the account, then **Allow**. A "Google Drive connected ✓" notification
   confirms it.
3. **Run now** once. The status screen shows about 10 days of files and an
   upload.

The **Sign in with a code instead** button is a fallback (Google's device-code
sign-in). It needs the OAuth client in `android/oauth.properties`.

### Google Cloud (once)

The app's Drive access comes from a Cloud project; see
[android/DRIVE_SETUP.md](android/DRIVE_SETUP.md). Until the consent screen is
**published** (Branding page complete, then Audience → Publish app), Google ends
the sign-in after 7 days. Once published, it lasts.

## Building the phone app

```bash
docker compose run --rm apk                  # android/build/usagedump.apk
docker compose run --rm -e NO_OAUTH=1 apk    # the same, without the client secret
```

The `apk` image has JDK 17 and Android build-tools 34; `android/build.sh`
builds without Gradle (aapt2 → javac → d8 → zipalign → apksigner) and bundles
the dashboard page with `android/web/phone.js`, which answers its requests on
the phone. `android/web/check.html` runs phone.js on the PC so its figures can
be compared with the Python server's.

- **The signing key.** `android/debug.keystore` signs the app and is not in
  git. Its backup is in `My Drive/PhoneUsage/code/signing/`, with
  `oauth.properties`. On a new machine, copy both into `android/` **before**
  the first build. Otherwise `build.sh` makes a new key, and an APK signed with
  a different key can't update the installed app (that means an uninstall,
  then setting everything up again). The Google "Android" OAuth client is tied
  to this key's SHA-1 (`E6:6F:DB:DC:…:D9:53`), so a new key also breaks the
  normal sign-in.
- **Release vs. debuggable.** The everyday build is not debuggable.
  `docker compose run --rm -e DEBUGGABLE=1 apk` builds one whose private files
  `adb shell run-as` can read, which helps testing but exposes the Drive
  token, so put the release build back afterwards. Both use the same key, so
  `install -r` switches between them and keeps every setting.
- **The APK in git is built with `NO_OAUTH=1`**, so it never carries the client
  secret. The normal sign-in doesn't need it, only the code fallback does.
- **Installing over the cable** needs no sudo with a *Windows* adb: unzip
  https://dl.google.com/android/repository/platform-tools-latest-windows.zip
  into `tools/platform-tools-win/`, `chmod +x` its `.exe` files, copy the APK
  under `/mnt/c`, then
  `tools/platform-tools-win/adb.exe install -r --user 0 'C:\path\to\usagedump.apk'`.
  `--user 0` matters on Samsung: without it adb also installs into the Dual
  apps profile, where a second copy runs its own job for nothing.
  The phone needs USB debugging on (Developer options). An update re-arms the
  6-hourly job by itself; the app doesn't need opening.

## Leaving apps out of screen time

Open **Exclude apps from totals** under "Most used apps" and untick any app. It
then disappears from every statistic: screen time, the day blocks, the
waking-hours share, the app list, the pickup analysis and the switch chains.
Screen-on time, unlocks and notification counts are not app-based and never
change. The list is stored in the archive's `archive.json`. It is not applied
to the CSV export, so editing it never makes archived days incomparable.

## What the dashboard shows

1. **Summary block**: Total, A day, and Share rows for screen time, unlocks
   and notifications. The Share row carries the pickup analysis: share of a
   16h waking day, unlocks under 30s, unlocks with no notification behind them.
2. **Screen time per day**.
3. **Most used apps**: click any app for its drill-down.
4. **App drill-down**: time and opens per day, visit lengths, weekday vs
   weekend, first app on waking and last before sleep, hourly profile, and the
   apps it hands off to and from.
5. **Across the day**: six blocks plus an hour-by-hour profile.
6. **Table view**.

Range buttons: 1d / 3d / 7d / 14d / 30d / 90d / All. `WAKING_HOURS`
(dashboard.html), `BOOKEND_TOLERANCE_MS` and `DAY_BLOCKS` (stats.py) are the
assumptions worth knowing.

## The archive

`ingest-phone` exports to `My Drive/PhoneUsage/archive/` after every ingest.
**[DATA.md](DATA.md)** explains every file and column.

- Durations end in `_ms`, timestamps in `_at` (both milliseconds).
- **It is an archive, not a snapshot.** Each export merges: a day once written
  stays, even if a later export runs against a rebuilt database, and a number
  never goes down. Files are written via a temp file, so an interrupted export
  cannot truncate them.
- `events/events-YYYY-MM.csv` is the backstop. Every other file, and the
  database itself (`wellbeing import`), can be rebuilt from it.
- In `app_buckets.csv` the windows are the phone's (its "daily" rolls at about
  18:30), and the four intervals overlap: filter to one before summing.

## All commands

`./wb <command>` (runs it in the app's container)

| Command | Does |
|---|---|
| `ingest-phone [DIR]` | read the phone's uploads and update the archive (`--all`, `--no-export`) |
| `import` | rebuild this machine's database from the archive (`--source`) |
| `export` | write the archive CSVs (`--days`, `--out`) |
| `report` | terminal summary (`--days`, `--top`) |
| `serve` | run the dashboard (`--host`, `--port`) |
| `where` | which archive, inbox, timezone and database this machine uses |
| `set-timezone ZONE` | record the archive's timezone, once |
| `rebuild` | recompute derived tables from stored events |
| `garmin-login`, `garmin` | Garmin Connect daily health data |

Every command that writes copies `data/usage.db` to `data/usage.db.bak` first.
`--fetch-labels` looks unknown package names up on the Play Store; it is off by
default because it sends your package names to Google.

## Layout

```
wellbeing/
  inbox.py     the phone's uploads (PhoneUsage/phone) -> database
  archive.py   where the archive lives; its timezone
  export.py    database -> archive CSVs;  importer.py: the reverse
  sync.py      rebuild derived tables (sessions, hourly slices)
  parse.py     events -> sessions
  appdump.py   the app's CSV formats; clock-shift detection
  db.py        SQLite schema    stats.py: read-side queries
  server.py    Flask app        templates/dashboard.html
android/       the phone app: Collector (CSV), CollectorJob (6-hourly),
               DriveAuth + DriveUploader, Notifier, DRIVE_SETUP.md
data/usage.db  this machine's database (rebuildable from the archive)
```

`events` is the source of truth; `sessions` and `usage_slice` are derived and
can always be regenerated with `rebuild`.

## Caveats

- Only the primary user is read; Secure Folder and work profiles are skipped.
- Digital Wellbeing's own database is readable only by Samsung-signed apps, and
  `/data/system/usagestats/` only by root. About 10 days of events plus the
  rolling buckets is the ceiling without rooting.
- App names aren't in the data: a curated table, then `--fetch-labels`, then a
  prettified package name.

## Tests

```bash
docker compose run --rm sync python -m pytest -q
```

They check the invariants the archive must hold (a number never decreases, a
blank never erases, a day once archived survives a database that forgot it, a
gap is never counted as usage), clock-shift handling, and the phone inbox (days
in any order, rewrites, duplicates, refusals). Each exists because the thing it
checks has gone wrong before.
