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

import java.io.IOException;
import java.util.concurrent.TimeUnit;

/**
 * Google sign-in for the one scope drive.file: the app can see and change the
 * files it created, and nothing else in the Drive.
 *
 * It uses the Google account already on the phone, through the framework's
 * AccountManager: pick the account, tap Allow, done. Google recognises the app
 * by package name and signing-key SHA-1 (the "Android" OAuth client in the
 * Cloud project, DRIVE_SETUP.md), so nothing secret is in the APK -- anyone
 * can install it and sign in with their own account, into their own Drive.
 * Android keeps and renews the token; the app stores only the account name.
 */
final class DriveAuth {
    private DriveAuth() {}

    static final String SCOPE = "https://www.googleapis.com/auth/drive.file";
    static final String ACCOUNT_TYPE = "com.google";
    private static final String TOKEN_TYPE = "oauth2:" + SCOPE;

    /** The grant is gone or was refused; only signing in again fixes it. */
    static final class AuthException extends Exception {
        AuthException(String msg) {
            super(msg);
        }
    }

    static boolean connected(Context c) {
        return State.get(c).getString(State.ACCOUNT_NAME, null) != null;
    }

    /** Signed in, but Google wants Drive access allowed again (the grant was removed or expired). */
    static boolean needsReconnect(Context c) {
        return State.get(c).getBoolean(State.NEEDS_RECONNECT, false);
    }

    /** Which account uploads go to, for the status screen. */
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
        SharedPreferences p = State.get(a);
        SharedPreferences.Editor e = p.edit();
        // Reconnecting may pick another account, whose Drive has none of these ids.
        if (!name.equals(p.getString(State.ACCOUNT_NAME, name))) forgetDriveIds(p, e);
        // A new grant gets a day's grace, as a bad network does: until its first
        // upload, "Nothing uploaded since …" would be about the old one.
        if (p.getLong(State.LAST_UPLOAD_OK_MS, 0L) > 0) e.putLong(State.LAST_UPLOAD_OK_MS, System.currentTimeMillis());
        e.putString(State.ACCOUNT_NAME, name).putString(State.ACCESS_TOKEN, token)
                .remove(State.NEEDS_RECONNECT).apply();
    }

    /** A token for the chosen account; `fresh` after Drive said 401. Background only. */
    static String accessToken(Context c, boolean fresh) throws IOException, AuthException {
        SharedPreferences p = State.get(c);
        String name = p.getString(State.ACCOUNT_NAME, null);
        if (name == null) throw new AuthException("not connected");
        AccountManager am = AccountManager.get(c);
        String old = p.getString(State.ACCESS_TOKEN, null);
        if (fresh && old != null) am.invalidateAuthToken(ACCOUNT_TYPE, old);
        String token = tokenFrom(am.getAuthToken(new Account(name, ACCOUNT_TYPE), TOKEN_TYPE,
                null, false, null, null), 60);
        if (token == null) {
            // Android has an "Allow" screen to show, so the grant was withdrawn.
            p.edit().putBoolean(State.NEEDS_RECONNECT, true).apply();
            throw new AuthException("Google needs you to allow Drive access again");
        }
        // A token again (access was allowed some other way): nothing to reconnect.
        p.edit().putString(State.ACCESS_TOKEN, token).remove(State.NEEDS_RECONNECT).apply();
        return token;
    }

    private static String tokenFrom(AccountManagerFuture<Bundle> f, int timeoutS)
            throws IOException, AuthException {
        try {
            return f.getResult(timeoutS, TimeUnit.SECONDS).getString(AccountManager.KEY_AUTHTOKEN);
        } catch (OperationCanceledException e) {
            throw new AuthException("sign-in cancelled");
        } catch (AuthenticatorException e) {
            // Also how an unregistered package or SHA-1 shows up, or an account
            // that isn't a test user while the consent screen is in Testing.
            throw new IOException("Google sign-in: " + e.getMessage(), e);
        }
    }

    static void disconnect(Context c) {
        SharedPreferences p = State.get(c);
        String access = p.getString(State.ACCESS_TOKEN, null);
        // The grant itself stays listed at myaccount.google.com until removed there.
        if (access != null) AccountManager.get(c).invalidateAuthToken(ACCOUNT_TYPE, access);
        SharedPreferences.Editor e = p.edit();
        forgetDriveIds(p, e);   // the next sign-in may be another account
        e.remove(State.ACCESS_TOKEN).remove(State.NEEDS_RECONNECT).remove(State.ACCOUNT_NAME)
                .remove("refresh_token").remove("access_expires_ms")   // left by the old code sign-in
                .apply();
    }

    /**
     * Folder and file ids belong to one account's Drive. Without them the
     * uploader finds the folders again by name, or creates them in the new Drive.
     */
    private static void forgetDriveIds(SharedPreferences p, SharedPreferences.Editor e) {
        for (String k : p.getAll().keySet()) {
            if (k.startsWith(State.FOLDER_PREFIX) || k.startsWith(State.UPLOADED_PREFIX)) e.remove(k);
        }
        e.remove(State.LAYOUT_V2);
    }
}
