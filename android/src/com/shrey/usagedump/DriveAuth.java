package com.shrey.usagedump;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

/**
 * Google sign-in by the OAuth device flow ("TVs and Limited Input devices"):
 * the app shows a code, you enter it at google.com/device, and the app keeps a
 * refresh token. Plain HTTPS, so no Play services library -- the APK is built
 * without Gradle and has nowhere to put one.
 *
 * The only scope is drive.file: the app can see and change the files it
 * created, and nothing else in the Drive.
 */
final class DriveAuth {
    private DriveAuth() {}

    static final String SCOPE = "https://www.googleapis.com/auth/drive.file";
    private static final String DEVICE_URL = "https://oauth2.googleapis.com/device/code";
    private static final String TOKEN_URL = "https://oauth2.googleapis.com/token";
    private static final String REVOKE_URL = "https://oauth2.googleapis.com/revoke";

    /** The refresh token is gone or revoked; only a new sign-in fixes it. */
    static final class AuthException extends Exception {
        AuthException(String msg) {
            super(msg);
        }
    }

    static final class DeviceCode {
        final String deviceCode, userCode, verificationUrl;
        final int intervalS;
        final long expiresAtMs;

        DeviceCode(JSONObject o) throws JSONException {
            deviceCode = o.getString("device_code");
            userCode = o.getString("user_code");
            verificationUrl = o.optString("verification_url", "https://www.google.com/device");
            intervalS = o.optInt("interval", 5);
            expiresAtMs = System.currentTimeMillis() + o.optInt("expires_in", 1800) * 1000L;
        }
    }

    static boolean configured() {
        return !Secrets.CLIENT_ID.isEmpty();
    }

    static boolean connected(Context c) {
        return State.get(c).getString(State.REFRESH_TOKEN, null) != null;
    }

    static DeviceCode start() throws IOException {
        Http.Response r = Http.postForm(DEVICE_URL, "client_id", Secrets.CLIENT_ID, "scope", SCOPE);
        if (!r.ok()) throw new IOException("device code request failed: " + r.code + " " + r.body);
        try {
            return new DeviceCode(new JSONObject(r.body));
        } catch (JSONException e) {
            throw new IOException(e);
        }
    }

    /** Blocks until the user approves; AuthException if they deny or the code expires. */
    static void await(Context c, DeviceCode dc) throws IOException, AuthException, InterruptedException {
        long interval = dc.intervalS * 1000L;
        while (System.currentTimeMillis() < dc.expiresAtMs) {
            Thread.sleep(interval);
            Http.Response r = Http.postForm(TOKEN_URL,
                    "client_id", Secrets.CLIENT_ID, "client_secret", Secrets.CLIENT_SECRET,
                    "device_code", dc.deviceCode,
                    "grant_type", "urn:ietf:params:oauth:grant-type:device_code");
            JSONObject o = json(r);
            if (r.ok()) {
                store(c, o, true);
                return;
            }
            String err = o.optString("error");
            if ("authorization_pending".equals(err)) continue;
            if ("slow_down".equals(err)) {
                interval += 5000;
                continue;
            }
            throw new AuthException("sign-in " + (err.isEmpty() ? "failed (" + r.code + ")" : err));
        }
        throw new AuthException("the code expired before it was entered");
    }

    /** A valid access token, refreshed when it is within a minute of expiring. */
    static String accessToken(Context c, boolean forceRefresh) throws IOException, AuthException {
        SharedPreferences p = State.get(c);
        String refresh = p.getString(State.REFRESH_TOKEN, null);
        if (refresh == null) throw new AuthException("not connected");
        String token = p.getString(State.ACCESS_TOKEN, null);
        if (!forceRefresh && token != null
                && p.getLong(State.ACCESS_EXPIRES_MS, 0L) > System.currentTimeMillis() + 60000L) {
            return token;
        }
        Http.Response r = Http.postForm(TOKEN_URL,
                "client_id", Secrets.CLIENT_ID, "client_secret", Secrets.CLIENT_SECRET,
                "refresh_token", refresh, "grant_type", "refresh_token");
        JSONObject o = json(r);
        if (!r.ok()) {
            if ("invalid_grant".equals(o.optString("error"))) {
                // Revoked, expired (a consent screen left in "Testing" does this
                // after 7 days), or the Google password changed.
                p.edit().remove(State.REFRESH_TOKEN).remove(State.ACCESS_TOKEN)
                        .putBoolean(State.NEEDS_RECONNECT, true).apply();
                throw new AuthException("Drive access was revoked or expired");
            }
            throw new IOException("token refresh failed: " + r.code + " " + r.body);
        }
        store(c, o, false);
        return o.optString("access_token");
    }

    static void disconnect(Context c) {
        SharedPreferences p = State.get(c);
        String refresh = p.getString(State.REFRESH_TOKEN, null);
        SharedPreferences.Editor e = p.edit();
        // Folder and file ids may belong to an account that is about to change;
        // the uploader finds them again by name after the next sign-in.
        for (String k : p.getAll().keySet()) {
            if (k.startsWith(State.FOLDER_PREFIX) || k.startsWith(State.UPLOADED_PREFIX)) e.remove(k);
        }
        e.remove(State.REFRESH_TOKEN).remove(State.ACCESS_TOKEN).remove(State.NEEDS_RECONNECT)
                .remove(State.LAYOUT_V2).apply();
        if (refresh != null) {
            try {
                Http.postForm(REVOKE_URL, "token", refresh);
            } catch (IOException ignored) {
                // Offline: the grant stays listed in the Google account until removed there.
            }
        }
    }

    private static void store(Context c, JSONObject o, boolean withRefresh) {
        SharedPreferences.Editor e = State.get(c).edit()
                .putString(State.ACCESS_TOKEN, o.optString("access_token"))
                .putLong(State.ACCESS_EXPIRES_MS,
                        System.currentTimeMillis() + o.optLong("expires_in", 3600) * 1000L);
        if (withRefresh) {
            e.putString(State.REFRESH_TOKEN, o.optString("refresh_token")).remove(State.NEEDS_RECONNECT);
        }
        e.apply();
    }

    private static JSONObject json(Http.Response r) {
        try {
            return new JSONObject(r.body);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }
}
