# android-usage-stats-native

Digital Wellbeing style usage statistics from an Android phone: screen time per
app and per hour, unlocks, notifications, and pick-ups (glances, micro and
impulse). Shown as a dashboard in the phone app itself, and optionally on a
Windows laptop. No root. The phone collects every 6 hours and uploads to *your
own* Google Drive; the laptop never needs to connect to the phone.

**Download:**
[UsageDump.apk](https://github.com/halfkelly/android-usage-stats-native/releases/latest/download/UsageDump.apk) (the phone app) ·
[UsageStats-Windows.zip](https://github.com/halfkelly/android-usage-stats-native/releases/latest/download/UsageStats-Windows.zip)
(the Windows dashboard, optional) · [all releases](https://github.com/halfkelly/android-usage-stats-native/releases).
Then **[set it up](#set-it-up)**. The phone app alone is enough.

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
| `code/signing/` | the app's signing key (backup; only on the maintainer's Drive) | once |

The app creates `PhoneUsage` itself: its `drive.file` permission can only
write into folders it made.

## Day to day

Nothing is needed. To see the numbers:

- **On the phone:** Usage Dump → **Open dashboard**. The same page, worked out
  on the phone from its own data (history from when the app was installed).
- **On the PC:** **Phone Usage Dashboard** on the Desktop (made by setup)
  starts the dashboard if it isn't running and opens http://127.0.0.1:5000.
  The page shows what's already here at once, then checks Drive for the
  phone's latest uploads in the background. **How to read this** explains
  every figure and assumption.
- To pull in the latest right now: tap **Run now** in the app, give Drive a
  minute, then **Get phone data** on the dashboard, or **Sync my phone.bat** in
  the project folder, which also says when the phone last uploaded.

The dashboard runs in the background, without a window, until **Stop
dashboard.bat** or a restart; closing the tab is fine. The Windows task
**PhoneUsageAutosync** runs at 03:00, 09:00, 15:00 and 21:00, or as soon as the
PC is on again after missing one: it reads the phone's uploads into the
database and the archive, and logs to `data\autosync.log`.

If collecting or uploading goes wrong while the app still runs (usage access
off, Drive sign-in expired, nothing uploaded for a day), the phone shows a
notification. If the phone stops running the app in the background
altogether, nothing on the phone can say so until you open Usage Dump, which
shows when it last collected. The PC dashboard and **Sync my phone.bat** warn
once the phone has been quiet for a day.

## Set it up

### 1. The phone (everyone)

1. **Get the app:** on the phone, tap
   [UsageDump.apk](https://github.com/halfkelly/android-usage-stats-native/releases/latest/download/UsageDump.apk) and open the
   downloaded file.
   - Allow **Install unknown apps** for the app you opened it from (the
     browser, or My Files).
   - Samsung: if it's blocked, turn off **Auto Blocker** (Settings → Security
     and privacy) for the install, then back on.
   - Play Protect may warn that it doesn't know the app: **More details →
     Install anyway**. It's not from the Play Store, that's all.
2. Open **Usage Dump** and allow notifications when it asks. Then tap the
   setup buttons below **Run now**, top to bottom:
   **Grant usage access** (find Usage Dump, switch it on, come back),
   **Let it run in the background** (Allow), then, if you want a backup,
   **Connect Google Drive**: pick your Google account, then **Allow**. If Google
   says it hasn't verified the app, tap **Continue**.
   - If switching on usage access says **App was denied access** or
     **Restricted setting**: Android does that for apps installed from a file.
     Open **Settings → Apps → Usage Dump**, tap **⋮** (top right) → **Allow
     restricted settings**, confirm, then switch usage access on again.
   - **Google Drive is optional.** Without it everything stays on the phone,
     and the app and its dashboard work just the same. But there's no backup
     (uninstalling the app or changing phones loses the history) and no PC
     dashboard. Connecting later uploads everything collected until then.
3. Tap **Run now**. After a few seconds the status screen shows the days
   collected (and, with Drive, an upload); **Open dashboard** shows your
   numbers. The first run reads back what the phone still remembers, usually
   about 10 days: pick dates in the boxes at the top to see them all.

From then on it collects every 6 hours and, with Drive connected, uploads to
`My Drive/PhoneUsage/` in *your* Drive. The app can only see the files it creates there: not the rest of
your Drive, and nobody else's data, the maintainer's included.

Anyone can connect: the Google app is published (home page and privacy policy:
<https://halfkelly.github.io/>). Google shows "hasn't verified this app" once,
because nobody has paid for Google's verification; that's expected.

### 2. A Windows laptop (optional)

A bigger dashboard, plus a permanent CSV archive in your Drive. Do the phone
first: the laptop reads what the phone uploads. Nothing else to install: setup
puts its own Python inside the project folder (no admin rights, nothing
system-wide).

1. Install **[Google Drive for desktop](https://www.google.com/drive/download/)**
   and sign in with **the same Google account as the phone**. Wait until
   `My Drive\PhoneUsage\phone` shows up in it (a minute or two after the phone's
   first upload), then right-click `PhoneUsage` → **Available offline**.
2. Download **[UsageStats-Windows.zip](https://github.com/halfkelly/android-usage-stats-native/releases/latest/download/UsageStats-Windows.zip)**,
   right-click it → **Extract All…**, put your user folder in the box
   (`C:\Users\<you>`) → **Extract**. That makes
   `C:\Users\<you>\Phone Usage Dashboard`. Not Documents or the Desktop:
   Windows often keeps those in OneDrive, and the app's database must not sync
   to the cloud (setup refuses such a folder).
3. In that folder, double-click **Set up (Windows).bat**. If Windows says it
   protected your PC: **More info → Run anyway**. In a few minutes setup puts
   Python and the app's libraries in the folder (about 65 MB), reads the
   phone's uploads, creates your archive (in the phone's time zone), registers
   a sync at 03:00, 09:00, 15:00 and 21:00, puts **Phone Usage Dashboard** on
   your Desktop and opens it. Running it again is safe and repairs anything
   missing.

The PC's time zone has to be the phone's, because days are cut at the
archive's midnight; setup says so if they differ.

Afterwards: **Phone Usage Dashboard** on the Desktop opens it; **Stop
dashboard.bat** stops it; **Sync my phone.bat** reads the latest uploads now.
To remove it: right-click `windows\uninstall.ps1` → **Run with PowerShell**.
That removes the task, the shortcut and the app's Python, and keeps `data\`
and everything in Drive; then delete the folder.

**Updating.** The phone: install the new APK over the old one, the same way;
every setting stays. The laptop: extract the new ZIP to the same place
(**Replace the files in the destination**), then run **Set up (Windows).bat**
again. Your history is in Drive and in `data\`, which the ZIP doesn't touch. A
fresh folder works too: its setup reads the history back from the Drive
archive.

**Good to know:**
- Tested on Samsung (Android 16). Other brands can be stricter with apps in
  the background, and an app that isn't allowed to run can't warn you: there,
  open Usage Dump every few days and check that **Collected** is recent (the
  phone forgets after about 10 days).
- History starts when the app is installed, plus the ~10 days the phone still
  remembers.
- The laptop part is Windows only.
- Nothing updates itself: a new version is a new download from the links
  above.

### The maintainer's PC (Docker in WSL)

When the project lives inside WSL, **Set up (Windows).bat** run from its
`\\wsl.localhost\...` folder uses Docker there instead of a Python of its own:
Docker Engine in WSL (`/etc/wsl.conf`: `[boot] systemd=true`, your user in the
`docker` group). The dashboard is then a container that restarts by itself (so
the page has no Stop button), and the scheduled task runs the `sync`
container. `./wb <command>` runs any command in the container.

What's where: the images hold only code. `data\` (database, backups, logs) and
the Drive folder are mounted in, so rebuilding or deleting a container loses
nothing. A brand-new laptop either imports an existing archive or starts one.

### Making a release (the maintainer)

1. If the app changed: raise `versionCode` and `versionName` in
   `android/AndroidManifest.xml`, `docker compose run --rm apk`, try it on the
   phone, commit the APK. Commit and push everything else too.
2. `./release.sh` makes `dist/UsageDump.apk` and `dist/UsageStats-Windows.zip`
   from the last commit. DATA.md stays out: its examples are the maintainer's
   own days.
3. On GitHub: **Releases → Draft a new release** → **Choose a tag**, type
   `v` and the app's version (`v2.10`) → **Create new tag** → a title → drag
   both files into the box → **Publish release**. Keep the two file names: the
   download links at the top of this page fetch the newest release's files by
   name.

### Google Cloud (the maintainer, once)

The app signs in through a Google Cloud project that knows the app's package
name and signing key: [android/DRIVE_SETUP.md](android/DRIVE_SETUP.md). Free,
no billing. It is published; its home page and privacy policy are on
<https://halfkelly.github.io/> (repo halfkelly/halfkelly.github.io), which Google
requires before publishing.

## Building the phone app

```bash
docker compose run --rm apk                  # android/build/usagedump.apk
```

The `apk` image has JDK 17 and Android build-tools 34; `android/build.sh`
builds without Gradle (aapt2 → javac → d8 → zipalign → apksigner) and bundles
the dashboard page with `android/web/phone.js`, which answers its requests on
the phone. `android/web/check.html` runs phone.js on the PC so its figures can
be compared with the Python server's.

- **The signing key.** `android/debug.keystore` signs the app and is not in
  git. Its backup is in `My Drive/PhoneUsage/code/signing/`. On a new
  machine, copy it into `android/` **before**
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
- **The APK carries no secret.** Sign-in is the phone's own Google account,
  which Google ties to the package name and the signing key's fingerprint.
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

Open **Exclude apps from totals** under "Most used apps" and untick any app
(the list holds the apps used in the range on screen). It then disappears from
every statistic: screen time, the day blocks, the
waking-hours share, the app list, the pickup analysis and the switch chains.
Screen-on time, unlocks and notification counts are not app-based and never
change. The PC's list is stored in the archive's `archive.json` and is not
applied to the CSV export, so editing it never makes archived days
incomparable. The phone's dashboard keeps a separate list, on the phone.

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

Range: **Today**, **Yesterday**, or any span with the two date boxes; click a
bar in Screen time per day to see that day alone. `WAKING_HOURS`
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

`./wb <command>` in WSL (runs it in the app's container), or on a laptop set up
without Docker, `python\python.exe -m wellbeing <command>` in the project folder.

| Command | Does |
|---|---|
| `ingest-phone [DIR]` | read the phone's uploads and update the archive (`--all`, `--no-export`) |
| `import` | rebuild this machine's database from the archive (`--source`) |
| `export` | write the archive CSVs (`--days`, `--out`) |
| `report` | terminal summary (`--days`, `--top`) |
| `serve` | run the dashboard (`--host`, `--port`) |
| `where` | which archive, inbox, timezone and database this machine uses |
| `open` | start the dashboard if needed and open it in the browser (`--no-browser`) |
| `stop` | stop the dashboard |
| `autosync` | the scheduled sync: `ingest-phone`, logged to `data/autosync.log` |
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
  pickups.py   pick-ups: glances, micro and impulse
  launch.py    open, stop and the scheduled sync without Docker
android/       the phone app: Collector (CSV), CollectorJob (6-hourly),
               DriveAuth + DriveUploader, Notifier, DRIVE_SETUP.md
windows/       setup, uninstall, and the scripts behind the .bat files
release.sh     the files a GitHub release carries (dist/)
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
checks has gone wrong before. Every test gets a Drive folder of its own
(`tests/conftest.py`), so the real one is never touched.
