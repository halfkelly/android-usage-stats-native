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

## The goal, in one line

**Make this machine do everything the Mac does, unattended.** Same code, same
archive, same timezone, same dashboard, syncing on a schedule without anyone
being at the keyboard. When you are done, the two machines should be
interchangeable: sync from either, view the dashboard on either.

### Parity checklist — what "same as the Mac" means

| | Mac today | This machine |
|---|---|---|
| Code | git clone of `main`, matches the Drive bundle | task 1 |
| Archive | `PhoneUsageBackup/` in Google Drive | should already work; verify |
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

### 2. Remove the broken `/etc/fstab` line
A line `G: /mnt/g drvfs` was added and errors on every WSL start. Remove it. WSL
already mounts Windows drives automatically, so nothing is lost. Needs sudo.

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

### 5. Recover the other session's timezone edits
Another Claude Code session on this machine made timezone-related changes that
never reached Drive or git. Its transcript is under `~/.claude/projects/` in WSL.
An extraction script was written but never run. Check whether those edits are
already superseded by what is now in `main` before reapplying anything — the
timezone handling has been rewritten since.

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
