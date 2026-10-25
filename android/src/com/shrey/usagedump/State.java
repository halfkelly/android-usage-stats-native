package com.shrey.usagedump;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Everything the app remembers between runs, in one SharedPreferences file.
 * allowBackup is off in the manifest, so the Drive token never leaves the phone.
 */
final class State {
    private State() {}

    static final String LAST_COLLECT_MS = "last_collect_ms";       // last *successful* collect
    static final String LAST_COLLECT_RESULT = "last_collect_result";
    static final String LAST_COLLECT_AT = "last_collect_at";       // last attempt, success or not
    static final String LAST_UPLOAD_RESULT = "last_upload_result";
    static final String LAST_UPLOAD_AT = "last_upload_at";
    static final String REFRESH_TOKEN = "refresh_token";
    static final String ACCESS_TOKEN = "access_token";
    static final String ACCESS_EXPIRES_MS = "access_expires_ms";
    static final String NEEDS_RECONNECT = "needs_reconnect";
    static final String FOLDER_PREFIX = "folder:";   // folder:<rel dir> -> Drive id
    static final String UPLOADED_PREFIX = "up:";     // up:<rel path> -> id|mtime|size

    static SharedPreferences get(Context c) {
        return c.getSharedPreferences("state", Context.MODE_PRIVATE);
    }

    static void note(Context c, String atKey, String resultKey, String result) {
        get(c).edit().putLong(atKey, System.currentTimeMillis()).putString(resultKey, result).apply();
    }
}
