package com.shrey.usagedump;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.regex.Pattern;

/**
 * The PC's dashboard, on the phone. It is the same dashboard.html, bundled in
 * the APK; android/web/phone.js answers its requests from the app's own day
 * files instead of a server. This class is only the window and the `Bridge`
 * phone.js reads through.
 */
public class DashboardActivity extends Activity {

    private WebView web;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // The page and phone.js come from the APK's assets; nothing is loaded
        // from the network, and the bridge is the only way out.
        web.addJavascriptInterface(new Bridge(getApplicationContext()), "Bridge");
        setContentView(web);
        web.loadUrl("file:///android_asset/dashboard.html");
    }

    @Override
    public void onBackPressed() {
        finish();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** What phone.js may ask the app for. Called on a background thread. */
    static final class Bridge {
        private static final Pattern DAY_FILE = Pattern.compile("events-\\d{4}-\\d{2}-\\d{2}\\.csv");
        private static final String EXCLUDED = "excluded_apps";
        private final Context c;

        Bridge(Context c) {
            this.c = c;
        }

        private File eventsDir() {
            return new File(new Collector(c).root(), "events");
        }

        @JavascriptInterface
        public String dayFiles() {
            JSONArray out = new JSONArray();
            String[] names = eventsDir().list();
            if (names != null) for (String n : names) if (DAY_FILE.matcher(n).matches()) out.put(n);
            return out.toString();
        }

        @JavascriptInterface
        public String readEvents(String name) {
            if (name == null || !DAY_FILE.matcher(name).matches()) return "";  // day files only
            try {
                return new String(Collector.readAll(new File(eventsDir(), name)), "UTF-8");
            } catch (IOException e) {
                return "";
            }
        }

        /** Real app names, from the phone itself. */
        @JavascriptInterface
        public String labels(String packagesJson) {
            JSONObject out = new JSONObject();
            PackageManager pm = c.getPackageManager();
            try {
                JSONArray pkgs = new JSONArray(packagesJson);
                for (int i = 0; i < pkgs.length(); i++) {
                    String p = pkgs.optString(i);
                    try {
                        ApplicationInfo ai = pm.getApplicationInfo(p, 0);
                        out.put(p, pm.getApplicationLabel(ai).toString());
                    } catch (PackageManager.NameNotFoundException ignored) {
                        // uninstalled since: the page shows the package id
                    }
                }
            } catch (JSONException ignored) {
            }
            return out.toString();
        }

        private SharedPreferences prefs() {
            return c.getSharedPreferences("dashboard", Context.MODE_PRIVATE);
        }

        @JavascriptInterface
        public String excluded() {
            return prefs().getString(EXCLUDED, "[]");
        }

        @JavascriptInterface
        public void setExcluded(String json) {
            try {
                prefs().edit().putString(EXCLUDED, new JSONArray(json).toString()).apply();
            } catch (JSONException ignored) {
            }
        }

        @JavascriptInterface
        public String lastCollectedMs() {
            return String.valueOf(State.get(c).getLong(State.LAST_COLLECT_MS, 0L));
        }

        /** "Collect now" on the page: the same collect as the job, which also queues an upload. */
        @JavascriptInterface
        public String collectNow() {
            String result = CollectorJob.collectNow(c, CollectorJob.BY_DASHBOARD);
            JSONObject o = new JSONObject();
            try {
                o.put("ok", !result.startsWith("failed")).put("message", result);
            } catch (JSONException ignored) {
            }
            return o.toString();
        }
    }
}
