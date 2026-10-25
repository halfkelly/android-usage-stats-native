# Handoff: the Windows/WSL machine

Context for a Claude Code session running in **WSL Ubuntu on the Windows
machine**. Written from the Mac on 2026-09-24. The Mac side is healthy and
current; everything below is work parked on the Windows side.

## What this project is

Collects Android usage stats from a Samsung phone over adb (no root), keeps a
permanent CSV archive in Google Drive, and serves a local Flask dashboard. Two
computers — this Windows/WSL machine and a Mac — share **one archive in Drive**
and each keep their own derived SQLite database.

- Repo: `github.com/Shrey97/adb-usage-stats` (private)
- Archive: `My Drive/PhoneUsageBackup/` — shared, append-only, the source of truth
- Code bundle: `My Drive/PhoneUsageCode/adb_usage_stats.zip` — how this machine
  got its copy, and what task 1 replaces
- Read `DATA.md` for the archive format and `README.md` for setup

## Building the phone app (2026-10-25)

The phone now collects and uploads on its own (README, "How it works"). The
APK is built here, on WSL, without Gradle. The toolchain lives in `tools/`,
which is gitignored. It was set up without sudo:

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
bash android/build.sh
```

- `android/debug.keystore` is generated on the first build and is **not in
  git**. Keep it: an APK signed with a different key can't update the
  installed app, which means an uninstall and a fresh grant of usage access
  and Drive.
- `android/oauth.properties` (also not in git) holds the Drive OAuth client;
  see `android/DRIVE_SETUP.md`. Without it the build still works, the app just
  can't upload.

## Do these, then run the acceptance tests below

### Remaining work

1. **Restore the drive letter.** The folder-mount experiment failed -- Drive never
   created `C:\Users\shrey\Google`, and WSL's automount does not cover Drive's
   virtual `G:` (verified: `G:` exists and holds the archive, yet `/mnt/g` stays
   empty without the fstab line). So:

       sudo sed -i 's|^#G: /mnt/g drvfs|G: /mnt/g drvfs|' /etc/fstab
       sed -i 's|^export PHONE_USAGE_ARCHIVE=.*|export PHONE_USAGE_ARCHIVE="/mnt/g/My Drive/PhoneUsageBackup"|' ~/.bashrc
       sudo mount -t drvfs G: /mnt/g 2>/dev/null
       ls "/mnt/g/My Drive/PhoneUsageBackup/archive.json"

   **The `mount -a failed` popup at WSL start is accepted as cosmetic.** Do not
   spend more time on it. It appears only when WSL starts before Drive has
   published `G:`, and both sync paths already handle that: `autosync.sh` checks
   for `archive.json` as a file (a stale mount fails that) and logs a skip, and a
   manual command prints a clear "archive is not readable, nothing was read or
   written" error rather than a traceback.

2. **Clean this machine's database.** It imported 4,403 duplicate events from the
   archive before those were removed, so its dashboard currently overstates
   counts (92 unlocks on 2026-09-23 where the truth is 56). `import` now carries
   the dedup rule and `rebuild` recomputes with the whole-day guard, which also
   repairs the 24h rows this machine's own seven-day event gap produced:

       cd ~/adb_usage_stats && git pull
       .venv/bin/python -m wellbeing import
       .venv/bin/python -m wellbeing rebuild

### Acceptance tests -- run all of these and report each result

**A. Unit tests.** `.venv/bin/python -m pytest tests/ -q` -> expect `23 passed`.

**B. Configuration.** `.venv/bin/python -m wellbeing where` must report the
`/mnt/g/My Drive/PhoneUsageBackup` archive, `timezone: Asia/Kolkata`, and code
matching the bundle. `echo $PHONE_USAGE_TZ` must be empty.

**C. The two machines must agree, exactly.** This is the test that matters most,
because disagreement means the day boundaries differ. Run:

    .venv/bin/python -c "
    from wellbeing import db, archive, stats; archive.pin_timezone()
    c=db.connect('data/usage.db')
    for d in stats.daily_totals(c,'2026-09-22','2026-09-30'):
        print(f\"{d['day']}  {d['ms']:>9} ms  {d['unlocks']:>3} unlocks  {d['notifications']:>3} notifs  {d['apps']:>2} apps\")"

The Mac produced exactly this on 2026-10-01, from 159,532 events:

    2026-09-22   19182125 ms  124 unlocks  231 notifs  35 apps
    2026-09-23   15172546 ms   56 unlocks  255 notifs  43 apps
    2026-09-24   12906938 ms   78 unlocks  210 notifs  37 apps
    2026-09-25   20240485 ms  110 unlocks  298 notifs  45 apps
    2026-09-26   21484123 ms   86 unlocks  204 notifs  46 apps
    2026-09-27   19607938 ms   51 unlocks  154 notifs  41 apps
    2026-09-28   22983155 ms   67 unlocks  156 notifs  58 apps
    2026-09-29   20582561 ms   79 unlocks  106 notifs  37 apps
    2026-09-30   15113569 ms  120 unlocks   94 notifs  38 apps

Any difference is a real defect -- investigate before doing anything else. A
whole-column shift means a timezone problem; inflated counts mean duplicates;
one odd day usually means that day is still being captured.

**D. No fabricated values.** In the archive, both must be zero:

    grep -c ',86400000,' "$PHONE_USAGE_ARCHIVE/app_daily.csv"
    grep -c ',86400000,' "$PHONE_USAGE_ARCHIVE/device_daily.csv"

**E. A real sync from this machine.** Pair/connect the phone over Wi-Fi
(`wellbeing connect <ip:port>` -- the port changes after a phone reboot, read it
off the phone's Wireless debugging screen), then `./sync.sh`. Expect the archive
to gain rows and `+0 new` on a second run. Re-run test C afterwards and confirm
the overlapping days still match the Mac exactly.

**F. The dashboard.** `./dashboard.sh`, then open `http://localhost:5000` in the
**Windows** browser (WSL2 forwards localhost). Check: the tiles show numbers;
Today / Yesterday / the two calendar date fields all change the view; clicking a
bar in "Screen time per day" narrows to that day; the app exclusion panel lists
apps in descending time order and survives ticking several in a row; the Sync
button reports what it did.

**G. Unattended sync.** `Get-ScheduledTaskInfo -TaskName "PhoneUsageSync"` in
PowerShell should show `LastTaskResult 0` and a `NextRunTime` at one of
03/09/15/21. **Do not trust the exit code** -- read `data/autosync.log` and
confirm it says either a real sync or a clean skip. Then leave it and check the
next morning that it fired on its own.

**H. The double-click shortcuts.** From Windows Explorer at
`\\wsl.localhost\Ubuntu-24.04\home\shrey\adb_usage_stats`, run
`Sync my phone.bat` and `Open dashboard.bat`. Both should work without a terminal
already open.

Report every result, including the ones that pass. A silent pass is how two of
the bugs above survived for a week.

## Incident, 2026-09-30 — read before syncing again

The first export from this machine corrupted 292 rows of the shared archive. It
is repaired, and both causes are fixed in `main`, but **this machine must
`git pull` before its next scheduled run** or it will do it again.

What happened: this machine's database had a seven-day hole, because it synced
after the phone had already pruned 14-21 Sept. `stats.py` paired a screen-on at
09-14 17:02 with the next screen-off it could find at 09-21 18:36 and split that
span across midnights, giving six days 86,400,000 ms of screen-on -- exactly 24h,
with screen_on == idle == unlocked and zero app foreground. The archive merge
then let those rows win, because it picked a winner by comparing one column and
0 is not blank. Six good days of `device_daily.csv` were overwritten with zeros,
along with regressions in five other files.

Two fixes: an unclosed event pair is now dropped rather than attributed, and the
merge is cell-wise and never lets a number decrease. Sixteen tests cover both.

**Also rebuild this machine's database.** It still has the hole, so its own
dashboard is wrong for 14-21 Sept even though the archive is now right:

    .venv/bin/python -m wellbeing import

That rebuilds `data/usage.db` from the archive's `events/`, which is complete.

## Status — 2026-09-30

| Task | State |
|---|---|
| 1. Git clone | **done** — clone of `main`, `.venv`/`platform-tools`/`data` intact |
| 2. Reach the archive | **works** — `G:` resolves, `Asia/Kolkata` confirmed. Open: WSL still reports `mount -a failed` at start when `G:` is absent; `nofail` does not suppress it. Fix is to mount Drive as a **folder** under `C:` instead of a drive letter, then drop the fstab line |
| 3. Phone over Wi-Fi | **done** — paired and connected (`192.168.1.5`) |
| 4. adb without sudo | **dropped** — wireless needs no sudo, so the udev rule is moot |
| 5. Recover timezone edits | **struck** — nothing to recover |
| 6. Unattended sync | **done** — Task Scheduler `PhoneUsageSync`, 03/09/15/21, verified syncing and skipping |

Task 6 landed 2026-09-30: the scheduled task ran both branches for real -- a quiet
`phone not on this network; skipping`, and a full `syncing ... 204 new ... done`.
The distro is `Ubuntu-24.04`, not `Ubuntu`; naming it wrongly is what returned
`4294967295` (0xFFFFFFFF) from the task, with no other diagnostic.

First sync from this machine is done and verified: three overlapping days
(25-27 Sep) matched the Mac exactly, to the millisecond, which is what proves
days are being cut in `Asia/Kolkata` and not in this machine's UTC. The export
was pure addition -- every row count rose, none were rewritten, and Drive
produced no conflict copies.

`autosync.sh` also gained a real fix from this machine (`d25d9d8`): the lock-age
check ran `stat -f` before `stat -c`, and on GNU coreutils `-f` is
`--file-system` with `%m` meaning *mount point*, so the age arithmetic got a path
instead of a number and every lock was mis-read. Ordering is now GNU-first.

## The goal, in one line

**Make this machine do everything the Mac does, unattended.** Same code, same
archive, same timezone, same dashboard, syncing on a schedule without anyone
being at the keyboard. When you are done, the two machines should be
interchangeable: sync from either, view the dashboard on either.

### Parity checklist — what "same as the Mac" means

| | Mac today | This machine |
|---|---|---|
| Code | git clone of `main`, matches the Drive bundle | task 1 |
| Archive | `PhoneUsageBackup/` in Google Drive | works via `G:`; mark it Available offline |
| Timezone | `Asia/Kolkata`, pinned from `archive.json` | verify — this machine's clock is UTC |
| Excluded apps | 5 packages in `archive.json` | automatic, shared through Drive |
| Phone over Wi-Fi | paired, `wellbeing connect` works | task 3 — pairing is **per computer** |
| Unattended sync | launchd, every 6h + at login | task 6 |
| Dashboard | `localhost:5000` | works once tasks 1 and 2 are done |
| Garmin | working, tokens Mac-only | **not here** — see "Not your problem" |

Verify parity at the end with `.venv/bin/python -m wellbeing where` on both: the
archive path, the timezone and the code digest should match.

## Read this before running anything

**1. Do not run `export` or `sync` here until task 1 is done.** This machine's
copy came from the zip and is behind. An old `export.py` writing to the shared
Drive archive is how it was damaged once before — see the timezone note below.

**2. The archive's timezone is `Asia/Kolkata` and is not negotiable.** It lives
in `PhoneUsageBackup/archive.json`. Every `day`, `hour`, `first_use`/`last_use`
and window label in the archive is cut in that zone, so that both machines agree.
This machine's own clock is `Etc/UTC`, which is exactly the trap: a sync run here
once relabelled five calendar files and three window-label files in the shared
archive, and repairing it needed a pre-sync snapshot. The code now pins the
process timezone (`archive.pin_timezone()` sets `os.environ["TZ"]` + `time.tzset()`)
before doing anything date-shaped. Verify it is working before trusting output:

    .venv/bin/python -m wellbeing where        # must print timezone: Asia/Kolkata

**3. The database is derived; the archive is not.** `data/usage.db` can always be
rebuilt with `.venv/bin/python -m wellbeing import`. The Drive archive cannot be
rebuilt from anything. Never write to it casually, and never delete rows from it
to "clean up" — it is append-only on purpose because the phone discards raw
events after ~10 days.

**4. Never rename or move a SQLite file while a connection is open.** A database
was destroyed that way (the empty file's WAL checkpointed over it, losing raw
events for 30 Aug – 3 Sep permanently). Use `sync_mod.backup_db()` and put test
databases in a scratch directory, never in `data/`.

**5. Label every command block with the shell it runs in.** This machine has two
prompts and they are not interchangeable: **Administrator PowerShell** (`PS C:\>`)
and **Ubuntu** (`$`). Unlabeled blocks have caused "command not found" loops here
before. Give full invocations — `.venv/bin/python -m wellbeing where`, never a
bare `where`.

## The work, in order

### 1. Convert `~/adb_usage_stats` from the Drive zip to a git clone
It is currently an unpacked zip, so it drifts from the Mac and cannot be updated
with `git pull`. Convert in place, **keeping** `.venv/`, `platform-tools/` and
`data/` (the local database and any raw dumps). Roughly: `git init`, add the
remote, `git fetch`, then `git reset --hard origin/main` — but check `git status`
first and make sure nothing local is worth saving, and confirm `.gitignore`
already covers `data/` and `.venv/` so the reset does not delete them.
Afterwards `python -m wellbeing where` should report the code matches Drive.

### 2. Reach the archive without mirroring all of Drive
Two earlier versions of this task were wrong. First it said to delete the
`G: /mnt/g drvfs` fstab line — that would leave `/mnt/g` never mounted and break
task 6. Then it said to switch Drive for Desktop to **Mirror** — which would
work, but My Drive holds ~279 top-level items of unrelated personal files, and
mirroring downloads every one of them to this laptop to reach a 10 MB archive.
Not worth it.

**Keep streaming, and schedule the sync to run only while logged on.** The
objection to `G:` was that it exists only while Drive for Desktop is running,
i.e. while someone is logged in. But a sync also needs the *phone* reachable on
the same Wi-Fi with wireless debugging on, which is only true when the owner is
around — which is when they are logged in. The logged-out case Mirror was
protecting against is one where the sync would fail at the phone anyway.

So:
- **Leave `PHONE_USAGE_ARCHIVE` pointing at `/mnt/g/My Drive/PhoneUsageBackup`.**
  It already resolves and `wellbeing where` already reports `Asia/Kolkata`.
- **Keep the fstab line, but add `nofail`** so a WSL start before `G:` exists
  stops erroring instead of failing the boot.
- In Drive for Desktop on Windows, right-click **`PhoneUsageBackup` → Available
  offline**. This caches just that folder locally while everything else stays
  streamed, so reads from WSL do not stall on downloads. The Mac does the same.
- In task 6, set the Task Scheduler job to **"Run only when the user is logged
  on"**, and tick **"Run task as soon as possible after a scheduled start is
  missed"** so a laptop that was asleep at 03:00 still syncs when it wakes.

If the archive is ever unreachable when the job fires, nothing is damaged:
`wellbeing` pins the timezone from `archive.json` before any command that does
date arithmetic and exits 2 if it cannot read it, rather than falling back to
this machine's UTC clock.

### 3. Decide whether USB passthrough is still worth fixing
`phonesync` finds and attaches the phone but adb then reports it "not seen";
`/tmp/usbipd-attach.log` has the reason. **This may be entirely unnecessary now**
— wireless sync works, and `python -m wellbeing connect` reaches the phone over
Wi-Fi with no usbipd, no admin PowerShell and no USB passthrough. Try wireless
first; only debug usbipd if wireless cannot be made to work. Wireless needs the
phone and this machine on the same LAN, and pairing once per computer
(`python -m wellbeing pair <ip:port> <code>` from the phone's Wireless debugging
screen).

### 4. Stop adb needing `sudo` every time
A udev rule for the phone's vendor id fixes this. Only relevant if task 3 ends up
using USB; wireless adb does not need it.

### 5. ~~Recover the other session's timezone edits~~ — STRUCK 2026-09-24
There is nothing to recover. Checked on the machine: `~/.claude/projects/` holds
only the current session, no `-home-shrey-adb-usage-stats` directory ever
existed, `history.jsonl` starts at the current session, and no extraction script
exists on disk or anywhere in the repo's history. `~/.claude.json` still carries
an `/home/shrey/adb_usage_stats` entry, so a session did run there once, but its
artifacts are gone. Moot anyway: the timezone handling has been rewritten since,
and `archive.json` is now the single source of that value.

### 6. Schedule unattended sync — the headline requirement
The Mac runs `autosync.sh` from a launchd agent every 6h and at login. This
machine needs the same. `autosync.sh` is already in the repo and already
cross-machine safe: it takes `sync.lock` in the Drive archive and skips if
another host's lock is under 900s old, and it exits quietly when the phone is
not reachable, so being off the house Wi-Fi costs nothing.

Two ways to schedule it, and the choice matters:
- **cron inside WSL** is simpler, but only runs while a WSL instance is alive.
  WSL shuts down when the last shell closes, so a laptop that is never opened to
  a terminal never syncs. If you take this route you also need WSL to stay
  resident (`wsl.exe --exec dbus-launch true` on login, or a Task Scheduler entry
  that starts WSL at boot).
- **Windows Task Scheduler calling into WSL** is the reliable one:
  `wsl.exe -d Ubuntu -- bash -lc '~/adb_usage_stats/autosync.sh'`, every 6 hours,
  "run whether user is logged on or not", and with "start only if a network
  connection is available". This starts WSL itself if it is not running.

**Schedule it at 03:00/09:00/15:00/21:00.** The Mac runs at 00/06/12/18, and the
two must not coincide. `sync.lock` in the archive is not a real mutex -- it lives
in Drive and Drive propagates asynchronously, so a lock written on one machine
can be invisible on the other for a while. Staggering is what actually keeps them
apart; the lock is the backstop for a manual sync landing on a scheduled one. A
collision does not lose data (the merge is append-only and cell-safe) but leaves
Drive conflict copies that someone has to notice. See README, "Two computers".

Prefer Task Scheduler. Whichever you pick, prove it works unattended before
calling it done: trigger the task manually, confirm a fresh row appears in the
archive, then wait for one scheduled firing and confirm it fired on its own.

**Check the log, not just the exit code.** `autosync.sh` is deliberately quiet;
a run that skipped because the phone was unreachable and a run that synced look
similar from outside. Confirm the archive's newest day actually advanced.

## Not your problem

- **Garmin.** Working on the Mac, tokens are Mac-only in `data/garth/`, and the
  user has parked the integration until they decide what they want from it. Do
  not set it up here and do not touch the dashboard for it.
- **The dashboard.** The user dictates every stat on it. Do not add cards.
- **Archive storage reshape** (day-partitioning and gzipping `events/`). Agreed
  but unstarted, and it should be done once, from one machine, deliberately.

## How to know it worked

    .venv/bin/python -m wellbeing where

Should report: archive in Google Drive, `timezone: Asia/Kolkata`, and code
matching the bundle. Then a sync, and the dashboard on `localhost:5000` showing
the same days the Mac shows.
