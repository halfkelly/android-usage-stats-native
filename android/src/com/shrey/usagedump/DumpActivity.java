package com.shrey.usagedump;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.net.Uri;
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
 *
 * Launched by adb with `--ei days N` (`wellbeing deep-sync`, the legacy path)
 * it instead writes the four flat CSVs and exits, as it always did.
 */
public class DumpActivity extends Activity {

    private TextView status, codeView;
    private Button access, battery, drive, runNow;
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (getIntent().hasExtra("days")) {
            legacyDump(getIntent().getIntExtra("days", Collector.BACKFILL_DAYS));
            return;
        }
        setContentView(buildUi());
        CollectorJob.schedule(this);
    }

    private void legacyDump(int days) {
        try {
            Log.i(Collector.TAG, "OK " + new Collector(this).dumpFlat(days));
        } catch (Exception e) {
            Log.e(Collector.TAG, "FAILED", e);
        }
        finish();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (status != null) refresh();
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
        if (!DriveAuth.configured()) {
            s.append("Drive: not set up in this build (see android/DRIVE_SETUP.md)\n");
        } else if (connected) {
            s.append("Drive: connected, uploading to My Drive/").append(DriveUploader.INBOX).append('\n')
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
        drive.setVisibility(DriveAuth.configured() ? View.VISIBLE : View.GONE);
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
            CollectorJob.collectNow(this);
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
        background("Signing in…", () -> {
            DriveAuth.DeviceCode dc;
            try {
                dc = DriveAuth.start();
            } catch (Exception e) {
                toastStatus("Couldn't start sign-in: " + e.getMessage());
                return;
            }
            final DriveAuth.DeviceCode code = dc;
            runOnUiThread(() -> showCode(code));
            try {
                DriveAuth.await(this, code);
            } catch (Exception e) {
                toastStatus("Not connected: " + e.getMessage());
                return;
            }
            runOnUiThread(() -> codeView.setVisibility(View.GONE));
            CollectorJob.uploadNow(this);
        });
    }

    private void showCode(DriveAuth.DeviceCode dc) {
        ClipboardManager cb = getSystemService(ClipboardManager.class);
        cb.setPrimaryClip(ClipData.newPlainText("Google code", dc.userCode));
        codeView.setText("Enter this code at\n" + dc.verificationUrl + "\n\n" + dc.userCode
                + "\n\n(copied — sign in, allow access, then come back)");
        codeView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        codeView.setVisibility(View.VISIBLE);
        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(dc.verificationUrl)));
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
