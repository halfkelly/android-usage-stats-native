package com.shrey.usagedump;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.util.Log;

/**
 * Two jobs in one service.
 *
 * COLLECT runs every 6 h with no constraints: collection must never wait for a
 * network, because the phone forgets events after about ten days. Each run
 * then asks for UPLOAD, a one-shot that waits for any network and retries with
 * backoff. A failed upload loses nothing -- files stay pending until they go.
 * Both are persisted, so they survive a reboot.
 */
public class CollectorJob extends JobService {

    static final int COLLECT = 1;
    static final int UPLOAD = 2;
    static final long PERIOD_MS = 6 * 3600_000L;
    static final long FLEX_MS = 3600_000L;
    static final long BACKOFF_MS = 15 * 60_000L;

    /** Idempotent: an already scheduled COLLECT is left alone, keeping its timing. */
    static void schedule(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (js.getPendingJob(COLLECT) != null) return;
        js.schedule(new JobInfo.Builder(COLLECT, new ComponentName(c, CollectorJob.class))
                .setPeriodic(PERIOD_MS, FLEX_MS)
                .setPersisted(true)
                .build());
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
            js.schedule(new JobInfo.Builder(UPLOAD, new ComponentName(c, CollectorJob.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setBackoffCriteria(BACKOFF_MS, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                    .setPersisted(true)
                    .build());
        } catch (RuntimeException e) {
            Log.e(Collector.TAG, "could not schedule upload", e);
            State.note(c, State.LAST_UPLOAD_AT, State.LAST_UPLOAD_RESULT,
                    "not scheduled: " + e.getMessage());
        }
    }

    /** What both the job and the "Run now" button do. Call off the main thread. */
    static String collectNow(Context c) {
        String result;
        try {
            result = new Collector(c).collect();
        } catch (Exception e) {
            Log.e(Collector.TAG, "collect FAILED", e);
            result = "failed: " + e.getMessage();
        }
        State.note(c, State.LAST_COLLECT_AT, State.LAST_COLLECT_RESULT, result);
        requestUpload(c);
        return result;
    }

    static DriveUploader.Result uploadNow(Context c) {
        DriveUploader.Result r = DriveUploader.uploadAll(c, new Collector(c).root());
        String note = r.outcome == DriveUploader.Outcome.RETRY ? r.message + " (will retry)" : r.message;
        State.note(c, State.LAST_UPLOAD_AT, State.LAST_UPLOAD_RESULT, note);
        Log.i(Collector.TAG, "upload " + r.outcome + " " + r.message);
        return r;
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            boolean retry = false;
            try {
                if (params.getJobId() == COLLECT) {
                    collectNow(this);
                } else {
                    retry = uploadNow(this).outcome == DriveUploader.Outcome.RETRY;
                }
            } catch (RuntimeException e) {
                // Whatever went wrong, finish the job rather than crash the process.
                Log.e(Collector.TAG, "job " + params.getJobId() + " failed", e);
                retry = params.getJobId() == UPLOAD;
            }
            jobFinished(params, retry);
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
