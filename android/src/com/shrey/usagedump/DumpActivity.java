package com.shrey.usagedump;

import android.accounts.AccountManager;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.Html;
import android.text.TextUtils;
import android.text.format.DateUtils;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;

/**
 * The status screen: what was collected and uploaded, and the one-time setup
 * (usage access, battery, Drive). Until the first collection it is a "Getting
 * started" guide instead, for someone who has only just installed the app. The
 * real work runs in CollectorJob; nothing here needs to be opened for
 * collection to happen.
 */
public class DumpActivity extends Activity {

    private static final String POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS";
    static final String EXTRA_CONNECT = "connect";
    private static final int REQ_ACCOUNT = 2;

    private TextView status, message;
    private Button dashboard, access, appInfo, battery, drive, stopDrive, runNow;
    private boolean showsDisconnect;   // what the Drive button says, so a tap does what it read
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        setContentView(buildUi());
        CollectorJob.schedule(this);
        // From the "sign-in has expired" notification. Only on a fresh start: a
        // rotation runs onCreate again with the same intent.
        if (saved == null && getIntent().getBooleanExtra(EXTRA_CONNECT, false)) {
            getIntent().removeExtra(EXTRA_CONNECT);
            if (!driveUsable()) pickAccount();
        }
        // Android 13+ shows nothing until this is granted, and the one
        // notification is how a broken collection gets noticed.
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {POST_NOTIFICATIONS}, 1);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (status != null) {
            refresh();
            CollectorJob.notifySafely(this);  // clears it once the problem is fixed
        }
    }

    private View buildUi() {
        int pad = dp(16);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, pad, pad, pad);

        status = new TextView(this);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        status.setLineSpacing(0, 1.25f);
        col.addView(status);

        message = new TextView(this);   // the outcome of signing in
        message.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        message.setPadding(0, pad, 0, 0);
        message.setTextIsSelectable(true);
        message.setVisibility(View.GONE);
        col.addView(message);

        dashboard = button(col, "Open dashboard", v -> startActivity(new Intent(this, DashboardActivity.class)));
        runNow = button(col, "Run now", v -> runNow());
        access = button(col, "Grant usage access", v -> {
            State.get(this).edit().putBoolean(State.ASKED_USAGE_ACCESS, true).apply();
            startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
        });
        // Where "Allow restricted settings" lives, for when Android refuses usage access.
        appInfo = button(col, "Open App info", v -> startActivity(new Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", getPackageName(), null))));
        battery = button(col, "Let it run in the background", v -> askBattery());
        drive = button(col, "Connect Google Drive", v -> onDrive());
        stopDrive = button(col, "Disconnect Google Drive", v -> disconnectDrive());   // while expired

        ScrollView scroll = new ScrollView(this);
        scroll.addView(col);
        return scroll;
    }

    private Button button(LinearLayout parent, String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(12);
        parent.addView(b, lp);
        return b;
    }

    private void refresh() {
        SharedPreferences p = State.get(this);
        File root = new Collector(this).root();
        String[] days = new File(root, "events").list((d, n) -> n.endsWith(".csv"));
        boolean hasAccess = Collector.hasUsageAccess(this);
        // Granted: a later loss of access is not Android's restriction (below).
        if (hasAccess && p.contains(State.ASKED_USAGE_ACCESS)) p.edit().remove(State.ASKED_USAGE_ACCESS).apply();
        boolean unrestricted = getSystemService(PowerManager.class)
                .isIgnoringBatteryOptimizations(getPackageName());
        boolean connected = DriveAuth.connected(this);
        boolean expired = DriveAuth.needsReconnect(this);
        boolean firstRun = days == null || days.length == 0;   // nothing collected yet
        // Asked, came back, still no access: on Android 15+ most likely its
        // restriction on apps installed from a file ("App was denied access").
        // Earlier versions never refuse usage access. (35, not the constant:
        // the app is compiled against 34.)
        boolean blocked = Build.VERSION.SDK_INT >= 35
                && !hasAccess && p.getBoolean(State.ASKED_USAGE_ACCESS, false);

        StringBuilder s = new StringBuilder();
        s.append("Collected: ").append(when(p, State.LAST_COLLECT_AT)).append('\n')
                .append("  ").append(p.getString(State.LAST_COLLECT_RESULT, "—")).append('\n')
                .append("Days on the phone: ").append(days == null ? 0 : days.length).append("\n\n");
        if (expired) {
            String account = DriveAuth.accountName(this);
            s.append("Drive: access expired").append(account != null ? " for " + account : "")
                    .append(" — tap Reconnect below, or Disconnect to stop uploading.\n")
                    .append("Collection carries on meanwhile; nothing is lost.\n");
        } else if (connected) {
            String account = DriveAuth.accountName(this);
            s.append("Drive: connected").append(account != null ? " as " + account : "")
                    .append(",\nuploading to ").append(DriveUploader.SHOWN_PATH).append('\n')
                    .append("Uploaded: ").append(when(p, State.LAST_UPLOAD_AT)).append('\n')
                    .append("  ").append(p.getString(State.LAST_UPLOAD_RESULT, "—")).append('\n')
                    .append("Waiting to upload: ").append(DriveUploader.pending(this, root))
                    .append(" files\n");
        } else {
            s.append("Drive: not connected\n");
        }
        s.append('\n')
                .append(hasAccess ? "✓ Usage access granted\n" : "✗ Usage access missing — nothing can be collected\n")
                .append(unrestricted ? "✓ Allowed to run in the background\n"
                        : "✗ Battery-restricted — scheduled runs may be skipped\n");
        if (blocked) s.append('\n').append(RESTRICTED);
        if (firstRun) {
            // A first run that failed before writing any day file shows only here.
            String lastRun = hasAccess && p.getLong(State.LAST_COLLECT_AT, 0L) != 0L
                    ? when(p, State.LAST_COLLECT_AT) + ": " + p.getString(State.LAST_COLLECT_RESULT, "—") : null;
            status.setText(guide(hasAccess, unrestricted, connected && !expired, blocked, lastRun));
        } else {
            status.setText(s);
        }

        dashboard.setVisibility(firstRun ? View.GONE : View.VISIBLE);
        // Without usage access a run can only fail; while busy it shows what is going on.
        runNow.setVisibility(hasAccess || busy ? View.VISIBLE : View.GONE);
        access.setVisibility(hasAccess ? View.GONE : View.VISIBLE);
        appInfo.setVisibility(blocked ? View.VISIBLE : View.GONE);
        battery.setVisibility(unrestricted ? View.GONE : View.VISIBLE);
        showsDisconnect = connected && !expired;
        drive.setText(expired ? "Reconnect Google Drive"
                : showsDisconnect ? "Disconnect Google Drive" : "Connect Google Drive");
        stopDrive.setVisibility(expired ? View.VISIBLE : View.GONE);
        runNow.setEnabled(!busy);
        drive.setEnabled(!busy);
        stopDrive.setEnabled(!busy);
    }

    private static final String RESTRICTED = "Android blocked usage access? It does that for apps installed"
            + " from a file. Tap Open App info, then ⋮ (top right) → Allow restricted settings, and tap"
            + " Grant usage access again.\n";

    /** The first-run guide: the setup steps in order, each ticked once it is done. */
    private CharSequence guide(boolean hasAccess, boolean unrestricted, boolean driveOn, boolean blocked,
                               String lastRun) {
        StringBuilder g = new StringBuilder("<b>Getting started</b>");
        g.append(step(1, "Usage access", hasAccess))
                .append("Lets the app read Android's own record of which apps you use. Tap <b>Grant usage"
                        + " access</b>, find Usage Dump and switch it on.");
        if (blocked) g.append("<br><br>").append(TextUtils.htmlEncode(RESTRICTED.trim()));
        g.append(step(2, "Run in the background", unrestricted))
                .append("So it can collect every 6 hours on its own. Tap <b>Let it run in the background</b>,"
                        + " then <b>Allow</b>.");
        g.append(step(3, "Google Drive backup (optional)", driveOn))
                .append("Keeps your history in your own Google Drive, where only you can see it. Without it,"
                        + " everything stays on this phone: uninstalling the app or changing phones loses it."
                        + " You can connect any time; everything collected so far uploads then.");
        g.append(step(4, "Collect", false))
                .append(hasAccess ? "Tap <b>Run now</b>." : "Once usage access is on, tap <b>Run now</b>.")
                .append(" The first run reads back what the phone still remembers, usually about 10 days."
                        + " Then <b>Open dashboard</b> shows your numbers.");
        if (lastRun != null) g.append("<br><br>Last run ").append(TextUtils.htmlEncode(lastRun));
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            g.append("<br><br>Notifications are off, so the app can't tell you if collecting stops."
                    + " Turn them on in Settings → Apps → Usage Dump → Notifications.");
        }
        return Html.fromHtml(g.toString(), Html.FROM_HTML_MODE_COMPACT);
    }

    private static String step(int n, String title, boolean done) {
        return "<br><br><b>" + n + ". " + title + (done ? "  ✓" : "") + "</b><br>";
    }

    private static String when(SharedPreferences p, String key) {
        long t = p.getLong(key, 0L);
        return t == 0L ? "never" : DateUtils.getRelativeTimeSpanString(t).toString();
    }

    private void runNow() {
        background("Collecting…", () -> {
            CollectorJob.collectNow(this, CollectorJob.BY_RUN_NOW);
            if (DriveAuth.connected(this)) {
                // The day files are written: the dashboard needn't wait for the upload.
                runOnUiThread(() -> {
                    runNow.setText("Uploading…");
                    refresh();
                });
                CollectorJob.uploadNow(this);
            }
        });
    }

    private void askBattery() {
        Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:" + getPackageName()));
        startActivity(i);
    }

    /** Signed in and still allowed: an expired grant is for reconnecting, not disconnecting. */
    private boolean driveUsable() {
        return DriveAuth.connected(this) && !DriveAuth.needsReconnect(this);
    }

    private void onDrive() {
        if (showsDisconnect) disconnectDrive();
        else pickAccount();
    }

    private void disconnectDrive() {
        background("Disconnecting…", () -> {
            DriveAuth.disconnect(this);
            CollectorJob.notifySafely(this);   // a "sign-in has expired" warning goes with it
        });
    }

    /** The normal sign-in: the phone's account chooser, then Google's Allow screen. */
    private void pickAccount() {
        startActivityForResult(DriveAuth.chooseAccountIntent(), REQ_ACCOUNT);
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != REQ_ACCOUNT || result != RESULT_OK || data == null) return;
        String name = data.getStringExtra(AccountManager.KEY_ACCOUNT_NAME);
        if (name == null) return;
        background("Signing in…", () -> {
            try {
                DriveAuth.connectAccount(this, name);
            } catch (Exception e) {
                toastStatus("Not connected: " + e.getMessage() + ".\nTap "
                        + (DriveAuth.needsReconnect(this) ? "Reconnect" : "Connect") + " Google Drive to try again.");
                return;
            }
            CollectorJob.notifySafely(this);   // takes down "sign-in has expired" at once
            Notifier.announce(this, "Google Drive connected ✓", "Uploading to " + DriveUploader.SHOWN_PATH + ".");
            runOnUiThread(() -> {
                message.setText("✓ Connected to Google Drive as " + name + ".\nUploading your data now.");
                message.setVisibility(View.VISIBLE);
            });
            CollectorJob.uploadNow(this);
        });
    }

    private void toastStatus(String msg) {
        runOnUiThread(() -> {
            message.setText(msg);
            message.setVisibility(View.VISIBLE);
        });
    }

    /** Run off the main thread with the buttons disabled, then refresh. */
    private void background(String label, Runnable work) {
        busy = true;
        runNow.setText(label);
        refresh();
        new Thread(() -> {
            try {
                work.run();
            } finally {
                runOnUiThread(() -> {
                    busy = false;
                    runNow.setText("Run now");
                    refresh();
                });
            }
        }, "usagedump-ui").start();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
