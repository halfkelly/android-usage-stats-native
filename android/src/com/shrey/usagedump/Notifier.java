package com.shrey.usagedump;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.text.format.DateUtils;

/**
 * One notification, shown only when something needs you, and cleared as soon
 * as it doesn't. Without it a problem shows only on the status screen, and the
 * phone keeps raw events for about ten days -- a week of not looking is data
 * gone. Checked at the end of every collect and upload, and when the app opens.
 *
 * It cannot report a job that has stopped running at all; the computer's
 * "phone last collected" warning covers that.
 */
final class Notifier {
    private Notifier() {}

    private static final String CHANNEL = "problems";
    private static final int ID = 1;
    // A run or two can fail on a bad network without anyone needing to know.
    static final long STALE_MS = 24 * 3600_000L;

    static void check(Context c) {
        String problem = problem(c);
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (problem == null) {
            nm.cancel(ID);
            return;
        }
        boolean reconnect = State.get(c).getBoolean(State.NEEDS_RECONNECT, false)
                && problem.startsWith("The Google Drive sign-in");
        nm.notify(ID, build(c, "Usage Dump needs attention", problem, reconnect)
                .setSmallIcon(android.R.drawable.stat_notify_error)
                .setOnlyAlertOnce(true)
                .build());
    }

    /** A one-off "it worked" message, e.g. after connecting Drive from the browser. */
    static void announce(Context c, String title, String text) {
        c.getSystemService(NotificationManager.class).notify(ID, build(c, title, text, false)
                .setSmallIcon(android.R.drawable.stat_sys_upload_done)
                .setAutoCancel(true)
                .setTimeoutAfter(10 * 60_000L)
                .build());
    }

    /** Tapping opens the app; for an expired sign-in, straight into connecting. */
    private static Notification.Builder build(Context c, String title, String text, boolean connect) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(
                CHANNEL, "Usage Dump status", NotificationManager.IMPORTANCE_DEFAULT));
        Intent i = new Intent(c, DumpActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra(DumpActivity.EXTRA_CONNECT, connect);
        PendingIntent open = PendingIntent.getActivity(c, connect ? 1 : 0, i,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(c, CHANNEL)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(open);
    }

    /** What is wrong, in a sentence, or null when nothing is. */
    static String problem(Context c) {
        SharedPreferences p = State.get(c);
        long now = System.currentTimeMillis();
        if (!Collector.hasUsageAccess(c)) {
            return "Usage access is off, so nothing is being collected. Tap to turn it back on.";
        }
        long collected = p.getLong(State.LAST_COLLECT_MS, 0L);
        if (collected > 0 && now - collected > STALE_MS) {
            return "Nothing collected since " + ago(collected) + ": "
                    + p.getString(State.LAST_COLLECT_RESULT, "unknown error");
        }
        if (DriveAuth.configured() && p.getBoolean(State.NEEDS_RECONNECT, false)) {
            return "The Google Drive sign-in has expired. Tap to reconnect; nothing is lost meanwhile.";
        }
        long uploaded = p.getLong(State.LAST_UPLOAD_OK_MS, 0L);
        if (DriveAuth.connected(c) && uploaded > 0 && now - uploaded > STALE_MS
                && DriveUploader.pending(c, new Collector(c).root()) > 0) {
            return "Nothing uploaded since " + ago(uploaded) + ": "
                    + p.getString(State.LAST_UPLOAD_RESULT, "unknown error");
        }
        return null;
    }

    private static String ago(long ms) {
        return DateUtils.getRelativeTimeSpanString(ms).toString();
    }
}
