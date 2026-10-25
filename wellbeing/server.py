"""Local Flask dashboard. Binds to localhost only -- this is personal data."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

from . import (adb, archive, db, export as export_mod, importer, inbox as inbox_mod, stats,
               sync as sync_mod)

RANGES = {"1": 1, "3": 3, "7": 7, "14": 14, "30": 30, "90": 90}


def create_app(db_path: str | Path = db.DEFAULT_DB) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path)

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    def resolve_range(c):
        """Read `range` / `start` / `end` off the query string."""
        days_avail = [r[0] for r in c.execute("SELECT DISTINCT day FROM usage_slice ORDER BY day")]
        start, end = request.args.get("start"), request.args.get("end")
        if start and end:
            return start, end
        span = request.args.get("range", "today")
        # "today" means the calendar day in the archive's timezone, not the last
        # day that happens to hold data -- a day with nothing in it yet is a true
        # answer, and says the phone has not synced.
        if span in ("today", "yesterday"):
            day = str(date.today() - timedelta(days=1 if span == "yesterday" else 0))
            return day, day
        if span == "all" and days_avail:
            return days_avail[0], days_avail[-1]
        return stats.default_range(c, RANGES.get(span, 14))

    @app.get("/")
    def index():
        return render_template("dashboard.html")

    @app.get("/api/summary")
    def summary():
        c = conn()
        include_chrome = request.args.get("system") == "1"
        start, end = resolve_range(c)
        excluded = archive.excluded_apps()
        daily = stats.daily_totals(c, start, end, include_chrome, exclude=excluded)
        apps = stats.top_apps(c, start, end, limit=15, include_chrome=include_chrome,
                              exclude=excluded)
        cov = stats.coverage(c)
        span = max(1, len([d for d in daily if d["ms"] > 0]))
        return jsonify({
            "start": start,
            "end": end,
            "daily": daily,
            "apps": apps,
            "hourly": stats.hourly(c, start, end, include_chrome, exclude=excluded),
            "day_blocks": stats.day_blocks(c, start, end, include_chrome, exclude=excluded),
            "excluded_apps": excluded,
            # the panel must list every app, or an excluded one could never be
            # ticked back on
            "app_choices": stats.top_apps(c, start, end, limit=500,
                                          include_chrome=include_chrome),
            "coverage": cov,
            "totals": {
                "ms": sum(d["ms"] for d in daily),
                "unlocks": sum(d["unlocks"] for d in daily),
                "notifications": sum(d["notifications"] for d in daily),
                "active_days": span,
            },
            "pickups": stats.notification_pickups(c, start, end, exclude=excluded),
            "pickup_quality": stats.pickup_quality(c, start, end),
        })

    @app.get("/api/app/<package>")
    def app_detail(package):
        c = conn()
        start, end = resolve_range(c)
        return jsonify(stats.app_detail(c, package, start, end,
                                        exclude=archive.excluded_apps()))

    @app.post("/api/excluded")
    def set_excluded():
        """Save the shared list of apps left out of screen time totals."""
        packages = (request.json or {}).get("packages", [])
        if not isinstance(packages, list):
            return jsonify({"ok": False, "error": "packages must be a list"}), 400
        try:
            saved = archive.set_excluded_apps(packages)
        except (ValueError, archive.TimezoneError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "excluded_apps": saved})

    @app.post("/api/sync")
    def do_sync():
        """Read what the phone uploaded to Drive and write the shared archive.

        The phone collects and uploads on its own (android/DRIVE_SETUP.md), so
        nothing here talks to it: this ingests PhoneUsageInbox, then exports,
        exactly like `wellbeing ingest-phone`. The old adb pull is still there
        as `wellbeing deep-sync`.
        """
        c = conn()
        pulled = None
        try:
            sync_mod.backup_db(c)
            # Pull in whatever the other machine archived first, so pressing this
            # converges the dashboard even when the inbox has nothing new.
            pulled = importer.import_archive(c)
            box = inbox_mod.inbox_dir()
            if box is None or not box.is_dir():
                raise FileNotFoundError(
                    f"no phone inbox at {box or 'My Drive/' + inbox_mod.FOLDER_NAME} -- "
                    "has the phone app connected to Drive yet?")
            result = inbox_mod.ingest_inbox(c, box)
            cov = stats.coverage(c)
            written = export_mod.export_all(c, cov["days"][0], cov["days"][-1]) if cov["days"] else {}
        except FileNotFoundError as exc:
            # The import above still happened, so say what did land rather than
            # reporting a flat failure.
            return jsonify({"ok": False, "error": str(exc),
                            "imported": (pulled or {}).get("events_added", 0)}), 409
        collected = result["device"].get("collected_at_ms")
        return jsonify({
            "ok": True,
            "events_added": result["events_added"],
            "files": len(result["files"]),
            "refused": result["refused"],
            "phone_collected_at_ms": collected,
            "days": len(cov["days"]),
            "archive_rows_added": sum(added for _total, added in written.values()),
        })

    @app.get("/api/devices")
    def devices():
        try:
            return jsonify({"ok": True, "devices": [
                {"serial": s, "state": st} for s, st in adb.devices()
            ]})
        except adb.AdbError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    return app
