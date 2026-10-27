package com.shrey.usagedump;

import android.accounts.AccountManager;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.format.DateUtils;
import android.util.Log;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;

/**
 * The status screen: what was collected and uploaded, and the one-time setup
 * (usage access, battery, Drive). The real work runs in CollectorJob; nothing
 * here needs to be opened for collection to happen.
 */
public class DumpActivity extends Activity {

    private static final String POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS";
    static final String EXTRA_CONNECT = "connect";
    private static final int REQ_ACCOUNT = 2;

    private TextView status, codeView;
    private Button access, battery, drive, runNow;
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        setContentView(buildUi());
        CollectorJob.schedule(this);
        if (getIntent().getBooleanExtra(EXTRA_CONNECT, false) && !DriveAuth.connected(this)) {
            pickAccount();
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

        codeView = new TextView(this);
        codeView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 28);
        codeView.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        codeView.setPadding(0, pad, 0, 0);
        codeView.setTextIsSelectable(true);
        codeView.setVisibility(View.GONE);
        col.addView(codeView);

        runNow = button(col, "Run now", v -> runNow());
        access = button(col, "Grant usage access",
                v -> startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)));
        battery = button(col, "Let it run in the background", v -> askBattery());
        drive = button(col, "Connect Google Drive", v -> onDrive());

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
        boolean unrestricted = getSystemService(PowerManager.class)
                .isIgnoringBatteryOptimizations(getPackageName());
        boolean connected = DriveAuth.connected(this);

        StringBuilder s = new StringBuilder();
        s.append("Collected: ").append(when(p, State.LAST_COLLECT_AT)).append('\n')
                .append("  ").append(p.getString(State.LAST_COLLECT_RESULT, "—")).append('\n')
                .append("Days on the phone: ").append(days == null ? 0 : days.length).append("\n\n");
        if (connected) {
            String account = DriveAuth.accountName(this);
            s.append("Drive: connected").append(account != null ? " as " + account : "")
                    .append(",\nuploading to ").append(DriveUploader.SHOWN_PATH).append('\n')
                    .append("Uploaded: ").append(when(p, State.LAST_UPLOAD_AT)).append('\n')
                    .append("  ").append(p.getString(State.LAST_UPLOAD_RESULT, "—")).append('\n')
                    .append("Waiting to upload: ").append(DriveUploader.pending(this, root))
                    .append(" files\n");
        } else if (p.getBoolean(State.NEEDS_RECONNECT, false)) {
            s.append("Drive: access expired — reconnect. Collection carries on meanwhile.\n");
        } else {
            s.append("Drive: not connected\n");
        }
        s.append('\n')
                .append(hasAccess ? "✓ Usage access granted\n" : "✗ Usage access missing — nothing can be collected\n")
                .append(unrestricted ? "✓ Allowed to run in the background\n"
                        : "✗ Battery-restricted — scheduled runs may be skipped\n");
        status.setText(s);

        access.setVisibility(hasAccess ? View.GONE : View.VISIBLE);
        battery.setVisibility(unrestricted ? View.GONE : View.VISIBLE);
        drive.setText(connected ? "Disconnect Google Drive" : "Connect Google Drive");
        runNow.setEnabled(!busy);
        drive.setEnabled(!busy);
    }

    private static String when(SharedPreferences p, String key) {
        long t = p.getLong(key, 0L);
        return t == 0L ? "never" : DateUtils.getRelativeTimeSpanString(t).toString();
    }

    private void runNow() {
        background("Collecting…", () -> {
            CollectorJob.collectNow(this, CollectorJob.BY_RUN_NOW);
            if (DriveAuth.connected(this)) {
                runOnUiThread(() -> runNow.setText("Uploading…"));
                CollectorJob.uploadNow(this);
            }
        });
    }

    private void askBattery() {
        Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:" + getPackageName()));
        startActivity(i);
    }

    private void onDrive() {
        if (DriveAuth.connected(this)) {
            background("Disconnecting…", () -> DriveAuth.disconnect(this));
            return;
        }
        pickAccount();
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
                toastStatus("Not connected: " + e.getMessage() + ".\nTap Connect Google Drive to try again.");
                return;
            }
            Notifier.announce(this, "Google Drive connected ✓", "Uploading to " + DriveUploader.SHOWN_PATH + ".");
            runOnUiThread(() -> {
                codeView.setText("✓ Connected to Google Drive as " + name + ".\nUploading your data now.");
                codeView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
                codeView.setVisibility(View.VISIBLE);
            });
            CollectorJob.uploadNow(this);
        });
    }

    private void toastStatus(String msg) {
        runOnUiThread(() -> {
            codeView.setText(msg);
            codeView.setVisibility(View.VISIBLE);
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
