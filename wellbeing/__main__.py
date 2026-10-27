"""Command line entry point: python -m wellbeing <command>."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import (archive as archive_mod, db, export as export_mod,
               importer as importer_mod, inbox as inbox_mod, launch, stats, sync as sync_mod)


def _fmt(ms: int) -> str:
    m = round(ms / 60000)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def cmd_report(args) -> int:
    conn = db.connect(args.db)
    cov = stats.coverage(conn)
    if not cov["days"]:
        print("No data yet. Run: python -m wellbeing sync")
        return 1
    start, end = stats.default_range(conn, args.days)
    print(f"{start} .. {end}   ({cov['event_count']:,} events, {cov['sync_count']} syncs)\n")
    print(f"{'day':12}{'screen':>10}{'apps':>7}{'unlocks':>9}{'notifs':>8}")
    for r in stats.daily_totals(conn, start, end):
        print(f"{r['day']:12}{_fmt(r['ms']):>10}{r['apps']:>7}{r['unlocks']:>9}{r['notifications']:>8}")
    print(f"\n{'top apps':30}{'time':>10}{'opens':>8}")
    for r in stats.top_apps(conn, start, end, limit=args.top):
        print(f"{r['label'][:29]:30}{_fmt(r['ms']):>10}{r['opens']:>8}")
    return 0


def cmd_ingest_phone(args) -> int:
    """Read the phone's own uploads (My Drive/PhoneUsage/phone) and update the archive."""
    inbox = Path(args.source).expanduser() if args.source else inbox_mod.inbox_dir()
    if inbox is None:
        print("error: Google Drive not found, so no phone inbox. Point at it with "
              f"${inbox_mod.ENV_VAR}=/path/to/PhoneUsage/phone", file=sys.stderr)
        return 1
    if not inbox.is_dir():
        print(f"error: No phone inbox at {inbox}", file=sys.stderr)
        return 1
    conn = db.connect(args.db)
    sync_mod.backup_db(conn)
    try:
        result = inbox_mod.ingest_inbox(conn, inbox, fetch_labels=args.fetch_labels,
                                        everything=args.all)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    device = result["device"]
    phone_tz, pinned = device.get("timezone", ""), os.environ.get("TZ", "")
    if phone_tz and pinned and phone_tz != pinned:
        print(f"note: phone timezone {phone_tz} differs from the archive's {pinned}; "
              f"calendar days follow the archive's zone.", file=sys.stderr)
    if result["clock_shift_ms"]:
        print(f"the phone's clock moved {result['clock_shift_ms']:+,} ms since the last capture; "
              f"timestamps realigned to the stored ones")
    for msg in result["refused"]:
        print(f"skipped {msg}", file=sys.stderr)
    collected = device.get("collected_at_ms")
    when = datetime.fromtimestamp(collected / 1000).strftime("%Y-%m-%d %H:%M") if collected else "?"
    snaps = result["snapshots"]
    print(f"{inbox}  (phone last collected {when})")
    stale = inbox_mod.staleness(inbox)
    if stale:
        print(f"WARNING: {stale}", file=sys.stderr)
    print(f"  {len(result['files'])} day file(s), {result['events_seen']:,} events, "
          f"{result['events_added']:,} new; {snaps['buckets']:,} bucket rows, "
          f"{snaps['eventstats']} counters, {snaps['configs']} configs")
    if args.no_export or not (result["files"] or any(snaps.values())
                              or inbox_mod.archive_incomplete(conn)):
        return 1 if result["refused"] else 0
    cov = stats.coverage(conn)
    if cov["days"]:
        written = export_mod.export_all(conn, cov["days"][0], cov["days"][-1])
        added = sum(a for _, a in written.values())
        print(f"  archive updated: {archive_mod.describe()} (+{added:,} rows)")
    return 1 if result["refused"] else 0


def cmd_export(args) -> int:
    conn = db.connect(args.db)
    cov = stats.coverage(conn)
    if not cov["days"]:
        print("No data yet. Run: python -m wellbeing sync")
        return 1
    start, end = stats.default_range(conn, args.days) if args.days else (cov["days"][0], cov["days"][-1])
    written = export_mod.export_all(conn, start, end,
                                    Path(args.out) if args.out else None, args.system)
    print(f"{start} .. {end} -> {args.out or archive_mod.describe()}")
    for name, (total, added) in written.items():
        print(f"  {name:16}{total:>7} rows total  (+{added} new)")
    return 0


def cmd_import(args) -> int:
    """Rebuild this machine's database from the shared archive."""
    conn = db.connect(args.db)
    try:
        result = importer_mod.import_archive(conn, Path(args.source) if args.source else None)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"imported from {result['source']}")
    added = result["events_added"]
    change = f"{added:,} new" if added >= 0 else f"{-added:,} duplicates removed"
    print(f"  {result['events']:,} events ({change}), "
          f"{result['buckets']:,} bucket rows, {result['counters']} counters, "
          f"{result['configs']} configs, {result['labels']} app names")
    days = [r[0] for r in conn.execute("SELECT DISTINCT day FROM usage_slice ORDER BY day")]
    if days:
        print(f"  history now covers {days[0]} .. {days[-1]} ({len(days)} days)")
    return 0


def cmd_where(args) -> int:
    print(f"archive:  {archive_mod.describe()}")
    try:
        print(f"timezone: {archive_mod.archive_timezone()}")
    except archive_mod.TimezoneError:
        print("timezone: NOT SET -- run: python -m wellbeing set-timezone <Area/City>")
    inbox = inbox_mod.inbox_dir()
    if inbox is None or not inbox.is_dir():
        print(f"inbox:    {inbox or 'no Google Drive'} — nothing from the phone yet")
    else:
        collected = inbox_mod.read_device(inbox).get("collected_at_ms")
        # `where` runs before the zone is pinned, so name it here: WSL's clock is UTC.
        try:
            zone = ZoneInfo(archive_mod.archive_timezone())
        except (archive_mod.TimezoneError, ZoneInfoNotFoundError):
            zone = None
        when = (datetime.fromtimestamp(collected / 1000, zone).strftime("%Y-%m-%d %H:%M")
                if collected else "unknown")
        trigger = inbox_mod.read_device(inbox).get("trigger")
        print(f"inbox:    {inbox} — phone last collected {when}" + (f" ({trigger})" if trigger else ""))
        stale = inbox_mod.staleness(inbox)
        if stale:
            print(f"          WARNING: {stale}")
    print(f"database: {args.db}")
    return 0


def cmd_set_timezone(args) -> int:
    try:
        path = archive_mod.set_archive_timezone(args.zone)
    except archive_mod.TimezoneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"recorded timezone {args.zone} in {path}")
    return 0


def cmd_garmin_login(args) -> int:
    """Interactive sign-in. The password is typed here and never stored."""
    import getpass
    from . import garmin
    # Needs a real terminal: the password prompt and the MFA prompt both read
    # from the tty, and a piped or captured stdin would echo the password into
    # whatever is doing the capturing.
    if not sys.stdin.isatty():
        print("garmin-login needs an interactive terminal.\n"
              "Open Terminal, cd to this project, and run:\n"
              "    ./wb garmin-login")
        return 1
    email = args.email or input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (not echoed, not stored): ")

    def prompt_mfa():
        return input("Garmin sent a code. Enter it: ").strip()

    try:
        where = garmin.login(email, password, prompt_mfa=prompt_mfa)
    except garmin.GarminError as exc:
        print(exc)
        return 1
    print(f"Signed in. Tokens saved to {where} (this machine only, not Drive).")
    return 0


def cmd_garmin(args) -> int:
    from . import garmin
    conn = db.connect(args.db)
    try:
        rows = garmin.fetch(days=args.days)
    except garmin.GarminError as exc:
        print(exc)
        return 1
    garmin.ingest(conn, rows)
    got = [r["day"] for r in rows]
    print(f"{len(rows)} days from Garmin: {got[0] if got else '-'} .. {got[-1] if got else '-'}")
    if not args.no_export:
        n, added = export_mod.export_garmin(conn)
        print(f"  garmin_daily.csv   {n} rows total  (+{added} new)")
    return 0


def cmd_serve(args) -> int:
    from .server import create_app
    args.port = args.port or launch.port()
    app = create_app(args.db)
    print(f"Dashboard on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_open(args) -> int:
    """The Desktop shortcut: start the dashboard if it isn't running, open it."""
    return launch.open_dashboard(args.db, browser=not args.no_browser)


def cmd_stop(args) -> int:
    return launch.stop_dashboard()


def cmd_autosync(args) -> int:
    """The scheduled sync (also what autosync.sh runs in Docker)."""
    def ingest(db_path: str) -> int:
        return cmd_ingest_phone(argparse.Namespace(
            db=db_path, source=None, fetch_labels=False, all=False, no_export=False))
    return launch.autosync(args.db, ingest)


def cmd_rebuild(args) -> int:
    conn = db.connect(args.db)
    lo = conn.execute("SELECT MIN(ts_ms) FROM events").fetchone()[0]
    if lo is None:
        print("No events stored.")
        return 1
    hi = conn.execute("SELECT MAX(ts_ms) FROM events").fetchone()[0]
    days = sync_mod.rebuild(conn, lo, hi)
    print(f"Rebuilt {len(days)} day(s): {days[0]} .. {days[-1]}" if days else "Nothing to rebuild.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m wellbeing",
                                description="Digital Wellbeing style usage stats, collected by the phone app.")
    p.add_argument("--db", default=str(db.DEFAULT_DB), help="SQLite file (default: data/usage.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("report", help="print a summary to the terminal")
    sp.add_argument("--days", type=int, default=14)
    sp.add_argument("--top", type=int, default=12)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("ingest-phone",
                        help="read what the phone uploaded to Drive (My Drive/PhoneUsage/phone) and update the archive")
    sp.add_argument("source", nargs="?", help=f"inbox directory (default: My Drive/{archive_mod.PROJECT_FOLDER}/{inbox_mod.FOLDER_NAME})")
    sp.add_argument("--all", action="store_true", help="re-read every file, not just changed ones")
    sp.add_argument("--no-export", action="store_true", help="database only, skip the archive")
    sp.add_argument("--fetch-labels", action="store_true",
                    help="look up unknown app names on the Play Store (sends package names to Google)")
    sp.set_defaults(func=cmd_ingest_phone)

    sp = sub.add_parser("export", help="write the history to CSV files")
    sp.add_argument("--out", help="output directory (default: the shared archive)")
    sp.add_argument("--days", type=int, default=None,
                    help="limit the export to the last N days (default: everything)")
    sp.add_argument("--all", action="store_true",
                    help="accepted for compatibility; exporting everything is the default")
    sp.add_argument("--system", action="store_true", help="include system UI packages")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="rebuild this machine's database from the shared archive")
    sp.add_argument("--source", help="archive directory (default: the shared archive)")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("where", help="show where the archive and database are")
    sp.set_defaults(func=cmd_where)

    sp = sub.add_parser("set-timezone", help="record the archive's timezone (one time)")
    sp.add_argument("zone", help="IANA name, e.g. Asia/Kolkata")
    sp.set_defaults(func=cmd_set_timezone)

    sp = sub.add_parser("garmin-login", help="sign in to Garmin Connect, once per machine")
    sp.add_argument("--email", help="skip the email prompt")
    sp.set_defaults(func=cmd_garmin_login)

    sp = sub.add_parser("garmin", help="pull daily health data from Garmin Connect")
    sp.add_argument("--days", type=int, default=28, help="how far back to fetch (default 28)")
    sp.add_argument("--db", default=str(db.DEFAULT_DB))
    sp.add_argument("--no-export", action="store_true", help="database only, skip the archive")
    sp.set_defaults(func=cmd_garmin)

    sp = sub.add_parser("serve", help="run the dashboard")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=None, help="default: DASHBOARD_PORT, else 5000")
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("open", help="start the dashboard if needed and open it in the browser")
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("stop", help="stop a running dashboard")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("autosync", help="the scheduled sync: read the phone's uploads, log to data/autosync.log")
    sp.set_defaults(func=cmd_autosync)

    sp = sub.add_parser("rebuild", help="recompute sessions and hourly slices from stored events")
    sp.set_defaults(func=cmd_rebuild)

    archive_mod.load_settings()
    args = p.parse_args(argv)
    # Everything that turns instants into days or hours must agree on a zone,
    # so pin it before the command runs. These never do date arithmetic, or
    # (open, autosync) handle a missing or mismatched zone themselves.
    if args.cmd not in ("where", "set-timezone", "open", "stop", "autosync"):
        try:
            zone = inbox_mod.bootstrap_archive()
            if zone:
                print(f"note: new archive at {archive_mod.archive_dir()}, in the phone's "
                      f"timezone {zone}", file=sys.stderr)
            archive_mod.pin_timezone()
        except archive_mod.TimezoneError as exc:
            # A mismatched zone would cut every day at the wrong midnight: never serve that.
            if args.cmd != "serve" or isinstance(exc, archive_mod.ZoneMismatchError):
                print(f"error: {exc}", file=sys.stderr)
                return 2
            # A fresh install whose phone hasn't uploaded yet: serve the empty
            # dashboard; its first sync sets the archive up (server.do_sync).
            print(f"note: {exc}\n  serving anyway; it sets itself up on the phone's first upload",
                  file=sys.stderr)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
