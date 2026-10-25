# android-usage-stats-native

Digital Wellbeing style usage statistics from a Samsung phone, shown as a
local dashboard on Windows (WSL). No root. The phone collects and uploads on
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

- **Phone Usage Dashboard** on the Desktop (a copy of `Open dashboard.bat`),
  or `./dashboard.sh`: the page opens in about 3 seconds on what's already
  here, then checks Drive for the phone's latest uploads in the background and
  updates itself. **How to read this** explains every figure and assumption;
  **Stop dashboard** shuts the server down (closing the tab is fine too).
- To pull in the latest right now: tap **Run now** in the Usage Dump app, give
  Drive a minute, then click **Get phone data** on the dashboard, or
  double-click **Sync my phone.bat**.
- `.venv/bin/python -m wellbeing where` shows when the phone last uploaded.

If the phone stops uploading, the phone shows a notification (usage access
off, Drive sign-in expired, nothing uploaded for a day). The dashboard, `where`
and `ingest-phone` also warn once it has been quiet for a day.

The Windows task **PhoneUsageAutosync** runs `autosync.sh` at 03:00, 09:00, 15:00 and 21:00:
it imports the archive and ingests the phone's uploads, so the dashboard is
current even if you never press anything.

## Setup

### The PC (WSL Ubuntu)

1. **Google Drive for desktop** on Windows, signed in to the same account.
   Right-click `PhoneUsage` → **Available offline**, so WSL reads don't wait on
   downloads. WSL sees Drive as `/mnt/g/My Drive`. If not, mount it with
   `sudo mkdir -p /mnt/g && sudo mount -t drvfs G: /mnt/g`, or set
   `PHONE_USAGE_ARCHIVE="/mnt/g/My Drive/PhoneUsage/archive"`.
2. The code, in the Linux home (not under `/mnt/c`):
   ```bash
   sudo apt install -y python3-venv git
   git clone git@github.com:Shrey97/android-usage-stats-native.git ~/android-usage-stats-native
   cd ~/android-usage-stats-native && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
3. `.venv/bin/python -m wellbeing where` should show the archive in Drive and
   `timezone: Asia/Kolkata`. Every day and hour is cut in the archive's zone,
   recorded in `archive.json`, never the machine's clock (WSL runs on UTC).

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

`bash android/build.sh` builds without Gradle (aapt2 → javac → d8 → zipalign
→ apksigner). The toolchain lives in `tools/` (gitignored), set up once
without sudo:

```bash
mkdir -p tools/dl && cd tools/dl
curl -sSfL -o jdk.tar.gz "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
curl -sSfL -o cmdline.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
cd .. && mkdir -p jdk-linux sdk/cmdline-tools
tar -xzf dl/jdk.tar.gz -C jdk-linux --strip-components=1
unzip -q dl/cmdline.zip -d sdk/cmdline-tools && mv sdk/cmdline-tools/cmdline-tools sdk/cmdline-tools/latest
JAVA_HOME=$PWD/jdk-linux yes | sdk/cmdline-tools/latest/bin/sdkmanager --sdk_root=$PWD/sdk \
  "build-tools;34.0.0" "platforms;android-34"
rm -rf dl && cd ..
```

- **The signing key.** `android/debug.keystore` signs the app and is not in
  git. Its backup is in `My Drive/PhoneUsage/code/signing/`, with
  `oauth.properties`. On a new machine, copy both into `android/` **before**
  the first build. Otherwise `build.sh` makes a new key, and an APK signed with
  a different key can't update the installed app (that means an uninstall,
  then setting everything up again). The Google "Android" OAuth client is tied
  to this key's SHA-1 (`E6:6F:DB:DC:…:D9:53`), so a new key also breaks the
  normal sign-in.
- **Release vs. debuggable.** `bash android/build.sh` builds the everyday app.
  `DEBUGGABLE=1 bash android/build.sh` builds one whose private files
  `adb shell run-as` can read, which helps testing but exposes the Drive
  token, so put the release build back afterwards. Both use the same key, so
  `install -r` switches between them and keeps every setting.
- **The APK in git is built without `oauth.properties`**, so it never carries
  the client secret. The normal sign-in doesn't need it, only the code
  fallback does.
- **Installing over the cable** needs no sudo with a *Windows* adb: unzip
  https://dl.google.com/android/repository/platform-tools-latest-windows.zip
  into `tools/platform-tools-win/`, `chmod +x` its `.exe` files, copy the APK
  under `/mnt/c`, then
  `tools/platform-tools-win/adb.exe install -r 'C:\path\to\usagedump.apk'`.
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

`.venv/bin/python -m wellbeing <command>`

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
.venv/bin/python -m pytest tests/ -q
```

They check the invariants the archive must hold (a number never decreases, a
blank never erases, a day once archived survives a database that forgot it, a
gap is never counted as usage), clock-shift handling, and the phone inbox (days
in any order, rewrites, duplicates, refusals). Each exists because the thing it
checks has gone wrong before.
