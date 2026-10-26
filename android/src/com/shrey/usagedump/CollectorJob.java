package com.shrey.usagedump;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.os.Build;
import android.util.Log;

/**
 * Two jobs in one service.
 *
 * COLLECT runs every 6 h with no constraints -- a chain of one-off jobs, see
 * schedule() -- because collection must never wait for a network: the phone
 * forgets events after about ten days. Each run then asks for UPLOAD, a
 * one-shot that waits for any network and retries with backoff. A failed
 * upload loses nothing -- files stay pending until they go. Both are high
 * priority (so heat doesn't hold them back) and persisted (survive a reboot).
 */
public class CollectorJob extends JobService {

    static final int COLLECT = 1;
    static final int UPLOAD = 2;
    static final long PERIOD_MS = 6 * 3600_000L;
    // A chain that has to be (re)started -- first install, after an update from
    // the old repeating job, after a force-stop -- begins this soon.
    static final long START_MS = 15 * 60_000L;
    static final long BACKOFF_MS = 15 * 60_000L;

    /**
     * Make sure a collection is queued; never throws. Collection is a chain of
     * one-off jobs, each queuing the next 6 hours on when it finishes, rather
     * than one repeating job: Android refuses high priority for repeating jobs
     * ("Periodic jobs cannot be high priority"), and without it a warm phone
     * holds the job back for hours. Opening the app, an update or reboot
     * (ScheduleReceiver) and every upload call this, so a broken chain mends.
     */
    static void schedule(Context c) {
        try {
            JobInfo pending = c.getSystemService(JobScheduler.class).getPendingJob(COLLECT);
            if (pending != null && !pending.isPeriodic()) return;   // the chain is in place
            queueCollect(c, START_MS);                               // none, or a pre-2.7 repeating job
        } catch (RuntimeException e) {
            Log.e(Collector.TAG, "could not schedule collection", e);
        }
    }

    private static void queueCollect(Context c, long delayMs) {
        c.getSystemService(JobScheduler.class).schedule(
                highPriority(new JobInfo.Builder(COLLECT, new ComponentName(c, CollectorJob.class))
                        .setMinimumLatency(delayMs)
                        .setPersisted(true))
                        .build());
    }

    /**
     * When the phone is warm (thermal status "moderate", e.g. charging
     * overnight) Android 13+ holds back every regular job below high priority.
     * On the S22 that kept the 6-hourly collect pending from 23:27 to 10:18 --
     * 27 times ready, never run. High priority is still an ordinary background
     * job; only "severe" heat stops it.
     */
    private static JobInfo.Builder highPriority(JobInfo.Builder b) {
        if (Build.VERSION.SDK_INT >= 33) b.setPriority(JobInfo.PRIORITY_HIGH);
        return b;
    }

    /**
     * Never throws: this runs at the end of a collect, and an exception here
     * would crash the process after the files were written -- the job would
     * never finish, run again, and One UI counts the crashes against the app.
     * Files stay pending, so the next collect simply asks again.
     */
    static void requestUpload(Context c) {
        if (!DriveAuth.connected(c)) return;
        try {
            JobScheduler js = c.getSystemService(JobScheduler.class);
            js.schedule(highPriority(new JobInfo.Builder(UPLOAD, new ComponentName(c, CollectorJob.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setBackoffCriteria(BACKOFF_MS, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                    .setPersisted(true))
                    .build());
        } catch (RuntimeException e) {
            Log.e(Collector.TAG, "could not schedule upload", e);
            State.note(c, State.LAST_UPLOAD_AT, State.LAST_UPLOAD_RESULT,
                    "not scheduled: " + e.getMessage());
        }
    }

    static final String BY_SCHEDULE = "schedule", BY_RUN_NOW = "run now", BY_DASHBOARD = "dashboard";

    /** What the job, "Run now" and the dashboard all do. Call off the main thread. */
    static String collectNow(Context c, String trigger) {
        String result;
        try {
            result = new Collector(c).collect(trigger);
        } catch (Exception e) {
            Log.e(Collector.TAG, "collect FAILED", e);
            result = "failed: " + e.getMessage();
        }
        State.note(c, State.LAST_COLLECT_AT, State.LAST_COLLECT_RESULT, result + " (" + trigger + ")");
        requestUpload(c);
        notifySafely(c);
        return result;
    }

    static DriveUploader.Result uploadNow(Context c) {
        DriveUploader.Result r = DriveUploader.uploadAll(c, new Collector(c).root());
        String note = r.outcome == DriveUploader.Outcome.RETRY ? r.message + " (will retry)" : r.message;
        State.note(c, State.LAST_UPLOAD_AT, State.LAST_UPLOAD_RESULT, note);
        if (r.outcome == DriveUploader.Outcome.OK) {
            State.get(c).edit().putLong(State.LAST_UPLOAD_OK_MS, System.currentTimeMillis()).apply();
        }
        Log.i(Collector.TAG, "upload " + r.outcome + " " + r.message);
        notifySafely(c);
        schedule(c);   // mends the collection chain if anything broke it
        return r;
    }

    /** The warning must never be what breaks a run. */
    static void notifySafely(Context c) {
        try {
            Notifier.check(c);
        } catch (RuntimeException e) {
            Log.e(Collector.TAG, "notification check failed", e);
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            boolean retry = false;
            try {
                if (params.getJobId() == COLLECT) {
                    collectNow(this, BY_SCHEDULE);
                } else {
                    retry = uploadNow(this).outcome == DriveUploader.Outcome.RETRY;
                }
            } catch (RuntimeException e) {
                // Whatever went wrong, finish the job rather than crash the process.
                Log.e(Collector.TAG, "job " + params.getJobId() + " failed", e);
                retry = params.getJobId() == UPLOAD;
            }
            jobFinished(params, retry);
            if (params.getJobId() == COLLECT) {
                // Only now: queuing job 1 while job 1 runs would stop it.
                try {
                    queueCollect(this, PERIOD_MS);
                } catch (RuntimeException e) {
                    Log.e(Collector.TAG, "could not queue the next collection", e);
                }
            }
        }, "usagedump-job").start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        // The system cut the job short (network lost, quota). Run it again;
        // collect and upload are both safe to repeat.
        return true;
    }
}
