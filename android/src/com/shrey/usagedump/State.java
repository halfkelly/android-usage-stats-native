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
    static final String LAST_UPLOAD_OK_MS = "last_upload_ok_ms";   // last upload that fully succeeded, or sign-in
    static final String ACCOUNT_NAME = "account_name";   // the phone's Google account, when signed in that way
    static final String ACCESS_TOKEN = "access_token";
    static final String NEEDS_RECONNECT = "needs_reconnect";
    static final String ASKED_USAGE_ACCESS = "asked_usage_access";   // Grant usage access tapped since access was last on
    static final String FOLDER_PREFIX = "folder:";   // folder:<rel dir> -> Drive id; folder:@top = PhoneUsage
    static final String LAYOUT_V2 = "layout_v2";     // the inbox is PhoneUsage/phone, not top-level
    static final String UPLOADED_PREFIX = "up:";     // up:<rel path> -> id|mtime|size

    static SharedPreferences get(Context c) {
        return c.getSharedPreferences("state", Context.MODE_PRIVATE);
    }

    static void note(Context c, String atKey, String resultKey, String result) {
        get(c).edit().putLong(atKey, System.currentTimeMillis()).putString(resultKey, result).apply();
    }
}
