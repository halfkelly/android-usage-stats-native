package com.shrey.usagedump;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Re-arms the jobs after an app update or a reboot, so neither needs the app
 * opened. An update otherwise leaves the app stopped, and a stopped app's jobs
 * do not run -- seen on the S22: after `adb install -r` the forced job did
 * nothing until the activity was launched.
 */
public class ScheduleReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent intent) {
        CollectorJob.schedule(c);
        CollectorJob.requestUpload(c);
    }
}
