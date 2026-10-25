package com.shrey.usagedump;

import android.app.AppOpsManager;
import android.app.usage.ConfigurationStats;
import android.app.usage.EventStats;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.os.Build;
import android.os.Process;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Dumps everything UsageStatsManager will hand over, as CSV.
 *
 * `dumpsys usagestats` only prints the service's in-memory buckets (24h of
 * events plus the current rolling totals). queryUsageStats/queryEvents read the
 * persisted store behind them, which reaches further back -- but events only
 * about ten days, so the scheduled job writes them out long before that.
 *
 * Layout under getExternalFilesDir (mirrored as-is into Drive):
 *   events/events-YYYY-MM-DD.csv     one local day, complete once the day is over
 *   snapshots/<kind>-YYYY-MM-DD.csv  buckets, eventstats, configs as of that day's last run
 *   device.json                      timezone and device, read by `wellbeing ingest-phone`
 */
final class Collector {

    static final String TAG = "usagedump";
    static final long DAY_MS = 86400000L;
    // Far enough back to get every bucket the phone still holds.
    static final int BACKFILL_DAYS = 400;

    private static final int[] INTERVALS = {
        UsageStatsManager.INTERVAL_DAILY,
        UsageStatsManager.INTERVAL_WEEKLY,
        UsageStatsManager.INTERVAL_MONTHLY,
        UsageStatsManager.INTERVAL_YEARLY,
    };
    private static final String[] INTERVAL_NAMES = {"daily", "weekly", "monthly", "yearly"};

    // The job and the "Run now" button share a process; never write the same files twice at once.
    static final Object LOCK = new Object();

    private final Context ctx;
    private final UsageStatsManager usm;
    private final File root;

    Collector(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        this.usm = (UsageStatsManager) ctx.getSystemService(Context.USAGE_STATS_SERVICE);
        this.root = ctx.getExternalFilesDir(null);
    }

    File root() {
        return root;
    }

    static boolean hasUsageAccess(Context c) {
        AppOpsManager ops = (AppOpsManager) c.getSystemService(Context.APP_OPS_SERVICE);
        @SuppressWarnings("deprecation")
        int mode = ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(),
                c.getPackageName());
        return mode == AppOpsManager.MODE_ALLOWED;
    }

    /**
     * The scheduled collect: every local day from the start of yesterday (or of
     * the last successful run, if that is older) through now, plus today's
     * snapshots. Starting at a midnight is what makes each rewritten day file
     * complete rather than a tail.
     */
    String collect() throws IOException {
        synchronized (LOCK) {
            if (!hasUsageAccess(ctx)) {
                // Without access every query returns nothing; writing that out
                // would replace good day files with empty ones.
                throw new IOException("no usage access");
            }
            long now = System.currentTimeMillis();
            long last = State.get(ctx).getLong(State.LAST_COLLECT_MS, 0L);
            long from = last == 0L ? now - BACKFILL_DAYS * DAY_MS : Math.min(last, now - DAY_MS);
            long begin = startOfDay(from);

            File events = new File(root, "events");
            File snaps = new File(root, "snapshots");
            events.mkdirs();
            snaps.mkdirs();

            int[] ev = writeEventDays(events, begin, now);
            String today = dayKey(now);
            long bucketsBegin = now - BACKFILL_DAYS * DAY_MS;
            int buckets = commitTo(new File(snaps, "buckets-" + today + ".csv"),
                    tmp -> writeBuckets(tmp, bucketsBegin, now), false);
            int estats = commitTo(new File(snaps, "eventstats-" + today + ".csv"),
                    tmp -> writeEventStats(tmp, bucketsBegin, now), false);
            int configs = commitTo(new File(snaps, "configs-" + today + ".csv"),
                    tmp -> writeConfigurations(tmp, bucketsBegin, now), false);
            writeDeviceJson(now, ev[0]);

            String summary = ev[0] + " events over " + ev[1] + " days, " + buckets + " buckets, "
                    + estats + " counters, " + configs + " configs";
            State.get(ctx).edit().putLong(State.LAST_COLLECT_MS, now).apply();
            Log.i(TAG, "collect OK " + summary);
            return summary;
        }
    }

    /** The original adb path: four flat files that `wellbeing deep-sync` pulls. */
    String dumpFlat(int days) throws IOException {
        synchronized (LOCK) {
            long end = System.currentTimeMillis();
            long begin = end - days * DAY_MS;
            int buckets = writeBuckets(new File(root, "buckets.csv"), begin, end);
            int events = writeEvents(new File(root, "events.csv"), begin, end);
            int estats = writeEventStats(new File(root, "eventstats.csv"), begin, end);
            int configs = writeConfigurations(new File(root, "configs.csv"), begin, end);
            return "buckets=" + buckets + " events=" + events + " eventstats=" + estats
                    + " configs=" + configs + " dir=" + root;
        }
    }

    /** Events split into one file per local day. Returns {events, days}. */
    private int[] writeEventDays(File dir, long begin, long end) throws IOException {
        UsageEvents events = usm.queryEvents(begin, end);
        UsageEvents.Event e = new UsageEvents.Event();
        int total = 0, days = 0;
        String day = null;
        File tmp = null;
        Writer w = null;
        int rows = 0;
        try {
            while (events != null && events.hasNextEvent()) {
                events.getNextEvent(e);
                String d = dayKey(e.getTimeStamp());
                if (!d.equals(day)) {
                    if (w != null) {
                        w.close();
                        w = null;
                        commit(tmp, new File(dir, "events-" + day + ".csv"), rows, true);
                        days++;
                    }
                    day = d;
                    tmp = new File(dir, "events-" + day + ".csv.tmp");
                    w = writer(tmp);
                    w.write("ts_ms,type,package,class\n");
                    rows = 0;
                }
                w.write(e.getTimeStamp() + "," + e.getEventType() + ","
                        + csv(e.getPackageName()) + "," + csv(e.getClassName()) + "\n");
                rows++;
                total++;
            }
            if (w != null) {
                w.close();
                w = null;
                commit(tmp, new File(dir, "events-" + day + ".csv"), rows, true);
                days++;
            }
        } finally {
            if (w != null) w.close();
        }
        return new int[] {total, days};
    }

    private interface Body {
        int write(File tmp) throws IOException;
    }

    private int commitTo(File dest, Body body, boolean neverShrink) throws IOException {
        File tmp = new File(dest.getPath() + ".tmp");
        int rows = body.write(tmp);
        commit(tmp, dest, rows, neverShrink);
        return rows;
    }

    /**
     * Swap a finished temp file into place. An identical file is left untouched
     * so its mtime -- what the uploader keys on -- only moves when content does.
     * With neverShrink, a rewrite carrying fewer rows than the file it would
     * replace is dropped: the phone has started forgetting that day, and what we
     * already wrote is the better copy.
     */
    private static void commit(File tmp, File dest, int rows, boolean neverShrink) throws IOException {
        if (dest.exists()) {
            if (sameBytes(tmp, dest) || (neverShrink && rows < countRows(dest))) {
                tmp.delete();
                return;
            }
            dest.delete();
        }
        if (!tmp.renameTo(dest)) throw new IOException("could not write " + dest);
    }

    // Day files are well under a few MB, so comparing whole is simplest.
    private static boolean sameBytes(File a, File b) throws IOException {
        return a.length() == b.length() && Arrays.equals(readAll(a), readAll(b));
    }

    static byte[] readAll(File f) throws IOException {
        byte[] buf = new byte[(int) f.length()];
        try (DataInputStream in = new DataInputStream(new FileInputStream(f))) {
            in.readFully(buf);
        }
        return buf;
    }

    private static int countRows(File f) throws IOException {
        int n = -1;  // header
        try (BufferedReader r = new BufferedReader(new FileReader(f))) {
            while (r.readLine() != null) n++;
        }
        return Math.max(n, 0);
    }

    private void writeDeviceJson(long now, int events) throws IOException {
        String version = "";
        try {
            version = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).versionName;
        } catch (Exception ignored) {
        }
        File tmp = new File(root, "device.json.tmp");
        try (Writer w = writer(tmp)) {
            JSONObject o = new JSONObject();
            o.put("timezone", TimeZone.getDefault().getID());
            o.put("device", Build.MANUFACTURER + " " + Build.MODEL);
            o.put("android", Build.VERSION.RELEASE);
            o.put("app_version", version);
            o.put("collected_at_ms", now);
            o.put("events_this_run", events);
            w.write(o.toString(2));
            w.write("\n");
        } catch (org.json.JSONException ex) {
            throw new IOException(ex);
        }
        commit(tmp, new File(root, "device.json"), 0, false);
    }

    static String dayKey(long ms) {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        return f.format(new Date(ms));
    }

    static long startOfDay(long ms) {
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis(ms);
        c.set(Calendar.HOUR_OF_DAY, 0);
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        return c.getTimeInMillis();
    }

    private int writeBuckets(File out, long begin, long end) throws IOException {
        int rows = 0;
        Writer w = writer(out);
        try {
            w.write("interval,begin_ms,end_ms,package,total_foreground_ms,total_visible_ms,"
                    + "total_fs_ms,last_used_ms,last_visible_ms,last_fs_ms,last_component_ms\n");
            for (int i = 0; i < INTERVALS.length; i++) {
                List<UsageStats> stats = usm.queryUsageStats(INTERVALS[i], begin, end);
                if (stats == null) continue;
                for (UsageStats s : stats) {
                    // Every stored bucket is emitted as its own row, keyed by its
                    // own timestamps -- aggregating here would throw away the day
                    // boundaries that make this worth querying at all.
                    w.write(INTERVAL_NAMES[i] + "," + s.getFirstTimeStamp() + ","
                            + s.getLastTimeStamp() + "," + csv(s.getPackageName()) + ","
                            + s.getTotalTimeInForeground() + "," + totalVisible(s) + ","
                            + totalFs(s) + "," + s.getLastTimeUsed() + ","
                            + lastVisible(s) + "," + lastFs(s) + "," + lastComponent(s) + "\n");
                    rows++;
                }
            }
        } finally {
            w.close();
        }
        return rows;
    }

    private int writeEvents(File out, long begin, long end) throws IOException {
        UsageEvents events = usm.queryEvents(begin, end);
        int rows = 0;
        Writer w = writer(out);
        try {
            w.write("ts_ms,type,package,class\n");
            UsageEvents.Event e = new UsageEvents.Event();
            while (events != null && events.hasNextEvent()) {
                events.getNextEvent(e);
                w.write(e.getTimeStamp() + "," + e.getEventType() + ","
                        + csv(e.getPackageName()) + "," + csv(e.getClassName()) + "\n");
                rows++;
            }
        } finally {
            w.close();
        }
        return rows;
    }

    // Each of these arrived in a later API level than minSdk, and a vendor build
    // can omit one; a missing field must not lose the whole row.
    private static long totalVisible(UsageStats s) {
        try { return s.getTotalTimeVisible(); } catch (Throwable t) { return 0L; }
    }

    private static long totalFs(UsageStats s) {
        try { return s.getTotalTimeForegroundServiceUsed(); } catch (Throwable t) { return 0L; }
    }

    private static long lastVisible(UsageStats s) {
        try { return s.getLastTimeVisible(); } catch (Throwable t) { return 0L; }
    }

    private static long lastFs(UsageStats s) {
        try { return s.getLastTimeForegroundServiceUsed(); } catch (Throwable t) { return 0L; }
    }

    // getLastTimeAnyComponentUsed() is not in the public SDK even though the
    // field is populated and shows up in dumpsys, so it is read reflectively.
    private static long lastComponent(UsageStats s) {
        try {
            return (Long) UsageStats.class.getMethod("getLastTimeAnyComponentUsed").invoke(s);
        } catch (Throwable t) {
            return 0L;
        }
    }

    /**
     * Device-wide counters: screen on/off and keyguard, each with a count AND a
     * total duration. Screen-on time here is independent of app attribution, so
     * screen-on minus app-foreground gives idle screen time -- a figure the
     * per-package buckets cannot produce.
     */
    private int writeEventStats(File out, long begin, long end) throws IOException {
        int rows = 0;
        Writer w = writer(out);
        try {
            w.write("interval,begin_ms,end_ms,event_type,count,total_time_ms,last_event_ms\n");
            for (int i = 0; i < INTERVALS.length; i++) {
                List<EventStats> stats;
                try {
                    stats = usm.queryEventStats(INTERVALS[i], begin, end);
                } catch (Throwable t) {
                    continue;
                }
                if (stats == null) continue;
                for (EventStats s : stats) {
                    w.write(INTERVAL_NAMES[i] + "," + s.getFirstTimeStamp() + ","
                            + s.getLastTimeStamp() + "," + s.getEventType() + ","
                            + s.getCount() + "," + s.getTotalTime() + ","
                            + s.getLastEventTime() + "\n");
                    rows++;
                }
            }
        } finally {
            w.close();
        }
        return rows;
    }

    /** Time per device configuration -- orientation, night mode, locale, density. */
    private int writeConfigurations(File out, long begin, long end) throws IOException {
        int rows = 0;
        Writer w = writer(out);
        try {
            w.write("interval,begin_ms,end_ms,config,activations,total_active_ms,last_active_ms\n");
            for (int i = 0; i < INTERVALS.length; i++) {
                List<ConfigurationStats> stats;
                try {
                    stats = usm.queryConfigurations(INTERVALS[i], begin, end);
                } catch (Throwable t) {
                    continue;
                }
                if (stats == null) continue;
                for (ConfigurationStats s : stats) {
                    w.write(INTERVAL_NAMES[i] + "," + s.getFirstTimeStamp() + ","
                            + s.getLastTimeStamp() + "," + csv(String.valueOf(s.getConfiguration()))
                            + "," + s.getActivationCount() + "," + s.getTotalTimeActive()
                            + "," + s.getLastTimeActive() + "\n");
                    rows++;
                }
            }
        } finally {
            w.close();
        }
        return rows;
    }

    private static String csv(String v) {
        if (v == null) return "";
        return v.indexOf(',') >= 0 ? "\"" + v + "\"" : v;
    }

    private static Writer writer(File f) throws IOException {
        return new OutputStreamWriter(new FileOutputStream(f), "UTF-8");
    }
}
