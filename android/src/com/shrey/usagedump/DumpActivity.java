package com.shrey.usagedump;

import android.app.Activity;
import android.app.usage.ConfigurationStats;
import android.app.usage.EventStats;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.os.Bundle;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.util.List;

/**
 * Dumps everything UsageStatsManager will hand over, as CSV, then exits.
 *
 * `dumpsys usagestats` only prints the service's in-memory buckets (24h of
 * events plus the current rolling totals). queryUsageStats/queryEvents read the
 * persisted store behind them, which reaches further back.
 */
public class DumpActivity extends Activity {

    private static final String TAG = "usagedump";

    private static final int[] INTERVALS = {
        UsageStatsManager.INTERVAL_DAILY,
        UsageStatsManager.INTERVAL_WEEKLY,
        UsageStatsManager.INTERVAL_MONTHLY,
        UsageStatsManager.INTERVAL_YEARLY,
    };
    private static final String[] INTERVAL_NAMES = {"daily", "weekly", "monthly", "yearly"};

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        int days = getIntent().getIntExtra("days", 400);
        try {
            File dir = getExternalFilesDir(null);
            long end = System.currentTimeMillis();
            long begin = end - days * 86400000L;
            int buckets = writeBuckets(new File(dir, "buckets.csv"), begin, end);
            int events = writeEvents(new File(dir, "events.csv"), begin, end);
            int estats = writeEventStats(new File(dir, "eventstats.csv"), begin, end);
            int configs = writeConfigurations(new File(dir, "configs.csv"), begin, end);
            Log.i(TAG, "OK buckets=" + buckets + " events=" + events
                    + " eventstats=" + estats + " configs=" + configs + " dir=" + dir);
        } catch (Exception e) {
            Log.e(TAG, "FAILED", e);
        }
        finish();
    }

    private int writeBuckets(File out, long begin, long end) throws IOException {
        UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
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
        UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
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
        UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
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
        UsageStatsManager usm = (UsageStatsManager) getSystemService(Context.USAGE_STATS_SERVICE);
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
