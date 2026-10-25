package com.shrey.usagedump;

import android.accounts.Account;
import android.accounts.AccountManager;
import android.accounts.AccountManagerFuture;
import android.accounts.AuthenticatorException;
import android.accounts.OperationCanceledException;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

/**
 * Google sign-in, two ways, both for the one scope drive.file: the app can see
 * and change the files it created, and nothing else in the Drive.
 *
 * The normal way uses the Google account already on the phone, through the
 * framework's AccountManager: pick the account, tap Allow, done. Google
 * recognises the app by package name and signing-key SHA-1 (the "Android"
 * OAuth client in the Cloud project), so nothing secret is in the APK, and
 * Android keeps and renews the token -- the app stores only the account name.
 *
 * The fallback is the OAuth device flow ("TVs and Limited Input devices"):
 * a code typed in at google.com/device, and a refresh token kept here. Plain
 * HTTPS; it needs the client in oauth.properties (DRIVE_SETUP.md).
 *
 * Both clients belong to the same Cloud project, and drive.file access is per
 * project, so either sign-in sees the files the other uploaded.
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

    static final String ACCOUNT_TYPE = "com.google";
    private static final String TOKEN_TYPE = "oauth2:" + SCOPE;

    /** The device-code fallback is available (this build has oauth.properties). */
    static boolean codeSignInAvailable() {
        return !Secrets.CLIENT_ID.isEmpty();
    }

    static boolean connected(Context c) {
        SharedPreferences p = State.get(c);
        return p.getString(State.ACCOUNT_NAME, null) != null
                || p.getString(State.REFRESH_TOKEN, null) != null;
    }

    /** Which account uploads go to, for the status screen; null for a code sign-in. */
    static String accountName(Context c) {
        return State.get(c).getString(State.ACCOUNT_NAME, null);
    }

    /** "Pick a Google account" -- the phone's own chooser. */
    static Intent chooseAccountIntent() {
        return AccountManager.newChooseAccountIntent(null, null, new String[] {ACCOUNT_TYPE},
                null, null, null, null);
    }

    /**
     * Interactive: ask for Drive access for the picked account. Passing the
     * activity lets Android show Google's "Allow" screen itself. Blocks until
     * the user answers, so call it off the main thread.
     */
    static void connectAccount(Activity a, String name) throws IOException, AuthException {
        AccountManagerFuture<Bundle> f = AccountManager.get(a).getAuthToken(
                new Account(name, ACCOUNT_TYPE), TOKEN_TYPE, null, a, null, null);
        String token = tokenFrom(f, 10 * 60);  // the user may take a while on the Allow screen
        if (token == null) throw new AuthException("Google didn't grant access");
        State.get(a).edit().putString(State.ACCOUNT_NAME, name).putString(State.ACCESS_TOKEN, token)
                .remove(State.REFRESH_TOKEN).remove(State.NEEDS_RECONNECT).apply();
    }

    /** Background: a token for the chosen account, or AuthException if it needs the user. */
    private static String accountToken(Context c, String name, boolean fresh) throws IOException, AuthException {
        SharedPreferences p = State.get(c);
        AccountManager am = AccountManager.get(c);
        String old = p.getString(State.ACCESS_TOKEN, null);
        if (fresh && old != null) am.invalidateAuthToken(ACCOUNT_TYPE, old);  // Drive said 401
        String token = tokenFrom(am.getAuthToken(new Account(name, ACCOUNT_TYPE), TOKEN_TYPE,
                null, false, null, null), 60);
        if (token == null) {
            // Android has an "Allow" screen to show, so the grant was withdrawn.
            p.edit().putBoolean(State.NEEDS_RECONNECT, true).apply();
            throw new AuthException("Google needs you to allow Drive access again");
        }
        p.edit().putString(State.ACCESS_TOKEN, token).apply();
        return token;
    }

    private static String tokenFrom(AccountManagerFuture<Bundle> f, int timeoutS)
            throws IOException, AuthException {
        try {
            return f.getResult(timeoutS, TimeUnit.SECONDS).getString(AccountManager.KEY_AUTHTOKEN);
        } catch (OperationCanceledException e) {
            throw new AuthException("sign-in cancelled");
        } catch (AuthenticatorException e) {
            // Also how an unregistered package or SHA-1 shows up.
            throw new IOException("Google sign-in: " + e.getMessage(), e);
        }
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
        String account = p.getString(State.ACCOUNT_NAME, null);
        if (account != null) return accountToken(c, account, forceRefresh);
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
        String access = p.getString(State.ACCESS_TOKEN, null);
        if (p.getString(State.ACCOUNT_NAME, null) != null && access != null) {
            // The grant itself stays listed at myaccount.google.com until removed there.
            AccountManager.get(c).invalidateAuthToken(ACCOUNT_TYPE, access);
        }
        SharedPreferences.Editor e = p.edit();
        // Folder and file ids may belong to an account that is about to change;
        // the uploader finds them again by name after the next sign-in.
        for (String k : p.getAll().keySet()) {
            if (k.startsWith(State.FOLDER_PREFIX) || k.startsWith(State.UPLOADED_PREFIX)) e.remove(k);
        }
        e.remove(State.REFRESH_TOKEN).remove(State.ACCESS_TOKEN).remove(State.NEEDS_RECONNECT)
                .remove(State.ACCOUNT_NAME)
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
