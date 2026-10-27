"""Local Flask dashboard. Binds to localhost only -- this is personal data."""
from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

from . import (archive, db, export as export_mod, importer, inbox as inbox_mod, stats,
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
            "phone_warning": inbox_mod.staleness(inbox_mod.inbox_dir()),
            # In Docker the dashboard is always on and restarted if it exits,
            # so the page's Stop button would only bounce it.
            "can_stop": os.environ.get("DASHBOARD_ALWAYS_ON") != "1",
            "totals": {
                "ms": sum(d["ms"] for d in daily),
                "unlocks": sum(d["unlocks"] for d in daily),
                "notifications": sum(d["notifications"] for d in daily),
                "active_days": span,
            },
            "pickups": stats.notification_pickups(c, start, end, exclude=excluded),
            "pickup_quality": stats.pickup_quality(c, start, end),
            "pickup_summary": stats.pickup_summary(c, start, end, exclude=excluded),
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

    sync_lock = threading.Lock()

    @app.post("/api/sync")
    def do_sync():
        """Read what the phone uploaded to Drive; export only if something came in.

        The page calls this by itself on every load, in the background, so it
        has to be cheap when nothing is new: the full archive import (~20 s)
        runs only for an empty database, and the export (~10 s) only after new
        files. One at a time -- a second tab waits for the first.
        """
        c = conn()
        with sync_lock:
            try:
                box = inbox_mod.inbox_dir()
                if box is None or not box.is_dir():
                    raise FileNotFoundError(
                        f"no phone inbox at {box or 'My Drive/PhoneUsage/phone'} -- "
                        "has the phone app connected to Drive yet?")
                # A fresh install: create the archive in the phone's zone, and
                # pin it, since the server may have started before it existed.
                if inbox_mod.bootstrap_archive():
                    archive.pin_timezone()
                if not c.execute("SELECT 1 FROM events LIMIT 1").fetchone() \
                        and (archive.archive_dir() / "events").is_dir():
                    importer.import_archive(c)     # a new machine: start from the archive
                if inbox_mod.has_changes(c, box):
                    sync_mod.backup_db(c)          # only when there is something to write
                result = inbox_mod.ingest_inbox(c, box)
                written = {}
                if result["files"] or any(result["snapshots"].values()):
                    cov = stats.coverage(c)
                    written = export_mod.export_all(c, cov["days"][0], cov["days"][-1])
            except FileNotFoundError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({
            "ok": True,
            "events_added": result["events_added"],
            "files": len(result["files"]),
            "refused": result["refused"],
            "phone_collected_at_ms": result["device"].get("collected_at_ms"),
            "phone_warning": inbox_mod.staleness(box),
            "archive_rows_added": sum(added for _total, added in written.values()),
        })

    @app.post("/api/stop")
    def stop():
        """The page's Stop button: answer, then end the server process.

        Only the page itself may ask. It sends X-Dashboard, a header a form on
        another site cannot set, and a script on another site cannot add
        without a CORS preflight this server never approves -- so no web page
        open elsewhere can stop the dashboard.
        """
        if request.headers.get("X-Dashboard") != "1":
            return jsonify({"ok": False, "error": "not from the dashboard"}), 403
        if os.environ.get("DASHBOARD_ALWAYS_ON") == "1":
            return jsonify({"ok": False, "error": "runs in Docker: use Stop dashboard.bat"}), 409
        # Exit just after this response has gone out.
        threading.Timer(0.5, os._exit, args=(0,)).start()
        return jsonify({"ok": True})

    return app
