package com.shrey.usagedump;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Mirrors the collector's folder into My Drive/PhoneUsageInbox/.
 *
 * Only files whose mtime or size changed since their last upload are sent, so a
 * run normally uploads today's events and snapshots and device.json. Drive
 * cannot append: a changed file has its whole content replaced. Nothing in
 * Drive is ever deleted from here.
 */
final class DriveUploader {
    private DriveUploader() {}

    static final String INBOX = "PhoneUsageInbox";
    private static final String[] SUBDIRS = {"events", "snapshots"};
    private static final String FOLDER_MIME = "application/vnd.google-apps.folder";
    private static final String API = "https://www.googleapis.com/drive/v3/files";
    private static final String UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";

    enum Outcome { OK, RETRY, FAILED }

    static final class Result {
        final Outcome outcome;
        final String message;

        Result(Outcome outcome, String message) {
            this.outcome = outcome;
            this.message = message;
        }
    }

    /** A Drive call that failed in a way worth retrying later (network, 429, 5xx). */
    private static final class RetryException extends Exception {
        RetryException(String msg) {
            super(msg);
        }
    }

    private static final Object LOCK = new Object();

    /** Local files in upload order: oldest first, device.json last. */
    static List<String> localFiles(File root) {
        List<String> out = new ArrayList<>();
        for (String sub : SUBDIRS) {
            String[] names = new File(root, sub).list();
            if (names == null) continue;
            Arrays.sort(names);
            for (String n : names) if (n.endsWith(".csv")) out.add(sub + "/" + n);
        }
        // Sorting by name is date order within each kind; put events and snapshots
        // of the same day together, oldest day first.
        Collections.sort(out, (a, b) -> {
            int c = dayOf(a).compareTo(dayOf(b));
            return c != 0 ? c : a.compareTo(b);
        });
        if (new File(root, "device.json").exists()) out.add("device.json");
        return out;
    }

    /** "events/events-2026-10-25.csv" -> "2026-10-25". */
    private static String dayOf(String rel) {
        return rel.length() >= 14 ? rel.substring(rel.length() - 14, rel.length() - 4) : "";
    }

    static int pending(Context c, File root) {
        SharedPreferences p = State.get(c);
        int n = 0;
        for (String rel : localFiles(root)) if (!upToDate(p, root, rel)) n++;
        return n;
    }

    private static boolean upToDate(SharedPreferences p, File root, String rel) {
        String[] s = stored(p, rel);
        File f = new File(root, rel);
        return s != null && s[1].equals(String.valueOf(f.lastModified()))
                && s[2].equals(String.valueOf(f.length()));
    }

    private static String[] stored(SharedPreferences p, String rel) {
        String v = p.getString(State.UPLOADED_PREFIX + rel, null);
        if (v == null) return null;
        String[] parts = v.split("\\|");
        return parts.length == 3 ? parts : null;
    }

    static Result uploadAll(Context c, File root) {
        synchronized (LOCK) {
            if (!DriveAuth.connected(c)) return new Result(Outcome.FAILED, "Drive not connected");
            Session s = new Session(c);
            int sent = 0, failed = 0;
            String lastError = null;
            try {
                for (String rel : localFiles(root)) {
                    if (upToDate(State.get(c), root, rel)) continue;
                    try {
                        s.upload(root, rel);
                        sent++;
                    } catch (IOException e) {
                        // A 4xx on one file (not auth, not rate) is that file's problem;
                        // carry on with the rest and report it.
                        failed++;
                        lastError = rel + ": " + e.getMessage();
                        Log.w(Collector.TAG, "upload failed " + lastError);
                    }
                }
            } catch (RetryException e) {
                return new Result(Outcome.RETRY, sent + " uploaded, then: " + e.getMessage());
            } catch (DriveAuth.AuthException e) {
                return new Result(Outcome.FAILED, e.getMessage());
            }
            if (failed > 0) return new Result(Outcome.FAILED, sent + " uploaded, " + failed + " failed (" + lastError + ")");
            return new Result(Outcome.OK, sent == 0 ? "nothing new" : sent + " files uploaded");
        }
    }

    /** One upload run: a token, and the folder listings looked up so far. */
    private static final class Session {
        private final Context c;
        private final SharedPreferences p;
        private String token;
        private final Map<String, Map<String, String>> children = new HashMap<>();

        Session(Context c) {
            this.c = c;
            this.p = State.get(c);
        }

        void upload(File root, String rel) throws IOException, RetryException, DriveAuth.AuthException {
            File f = new File(root, rel);
            int slash = rel.lastIndexOf('/');
            String dir = slash < 0 ? "" : rel.substring(0, slash);
            String name = rel.substring(slash + 1);
            long mtime = f.lastModified(), size = f.length();
            byte[] content = Collector.readAll(f);
            String mime = name.endsWith(".json") ? "application/json" : "text/csv";

            String[] s = stored(p, rel);
            String id = s != null ? s[0] : null;
            if (id == null) {
                // After a reinstall or a reconnect the ids are gone, but the
                // files are still in Drive under the same names.
                id = children(folder(dir)).get(name);
            }
            Http.Response r = null;
            if (id != null) {
                r = call("PATCH", UPLOAD + "/" + id + "?uploadType=media&fields=id", mime, content);
                if (r.code == 404) id = null;  // deleted or trashed in Drive: create it again
            }
            if (id == null) {
                r = create(folder(dir), name, mime, content);
            }
            if (!r.ok()) throw new IOException(r.code + " " + r.body);
            String newId = parse(r).optString("id", id);
            p.edit().putString(State.UPLOADED_PREFIX + rel, newId + "|" + mtime + "|" + size).apply();
        }

        /** Drive id of PhoneUsageInbox ("") or one of its subfolders, created if missing. */
        String folder(String dir) throws IOException, RetryException, DriveAuth.AuthException {
            String key = State.FOLDER_PREFIX + dir;
            String id = p.getString(key, null);
            if (id != null) return id;
            String parent = dir.isEmpty() ? "root" : folder("");
            String name = dir.isEmpty() ? INBOX : dir;
            id = findFolder(parent, name);
            if (id == null) {
                JSONObject meta = new JSONObject();
                try {
                    meta.put("name", name).put("mimeType", FOLDER_MIME)
                            .put("parents", new JSONArray().put(parent));
                } catch (JSONException e) {
                    throw new IOException(e);
                }
                Http.Response r = call("POST", API + "?fields=id", "application/json; charset=UTF-8",
                        meta.toString().getBytes("UTF-8"));
                if (!r.ok()) throw new IOException("create folder " + name + ": " + r.code + " " + r.body);
                id = parse(r).optString("id");
            }
            p.edit().putString(key, id).apply();
            return id;
        }

        private String findFolder(String parent, String name)
                throws IOException, RetryException, DriveAuth.AuthException {
            String q = "name = '" + name + "' and mimeType = '" + FOLDER_MIME + "' and '" + parent
                    + "' in parents and trashed = false";
            Http.Response r = call("GET", API + "?fields=files(id)&q=" + Http.enc(q), null, null);
            if (!r.ok()) throw new IOException("find folder " + name + ": " + r.code + " " + r.body);
            JSONArray files = parse(r).optJSONArray("files");
            return files != null && files.length() > 0 ? files.optJSONObject(0).optString("id") : null;
        }

        /** name -> id of the files this app already has in a folder. drive.file sees only those. */
        private Map<String, String> children(String folderId)
                throws IOException, RetryException, DriveAuth.AuthException {
            Map<String, String> m = children.get(folderId);
            if (m != null) return m;
            m = new HashMap<>();
            String q = "'" + folderId + "' in parents and trashed = false";
            String page = null;
            do {
                String url = API + "?pageSize=1000&fields=nextPageToken,files(id,name)&q=" + Http.enc(q)
                        + (page == null ? "" : "&pageToken=" + Http.enc(page));
                Http.Response r = call("GET", url, null, null);
                if (!r.ok()) throw new IOException("list folder: " + r.code + " " + r.body);
                JSONObject o = parse(r);
                JSONArray files = o.optJSONArray("files");
                for (int i = 0; files != null && i < files.length(); i++) {
                    JSONObject f = files.optJSONObject(i);
                    m.put(f.optString("name"), f.optString("id"));
                }
                page = o.optString("nextPageToken", null);
            } while (page != null && !page.isEmpty());
            children.put(folderId, m);
            return m;
        }

        private Http.Response create(String parent, String name, String mime, byte[] content)
                throws IOException, RetryException, DriveAuth.AuthException {
            String boundary = "usagedump" + System.nanoTime();
            JSONObject meta = new JSONObject();
            try {
                meta.put("name", name).put("parents", new JSONArray().put(parent));
            } catch (JSONException e) {
                throw new IOException(e);
            }
            ByteArrayOutputStream b = new ByteArrayOutputStream(content.length + 512);
            b.write(("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                    + meta + "\r\n--" + boundary + "\r\nContent-Type: " + mime + "\r\n\r\n")
                    .getBytes("UTF-8"));
            b.write(content);
            b.write(("\r\n--" + boundary + "--\r\n").getBytes("UTF-8"));
            Http.Response r = call("POST", UPLOAD + "?uploadType=multipart&fields=id",
                    "multipart/related; boundary=" + boundary, b.toByteArray());
            if (r.ok()) children(parent).put(name, parse(r).optString("id"));
            return r;
        }

        /** One authorised call: refreshes the token once on 401, maps retryable failures. */
        private Http.Response call(String method, String url, String type, byte[] body)
                throws RetryException, DriveAuth.AuthException {
            try {
                if (token == null) token = DriveAuth.accessToken(c, false);
                Http.Response r = send(method, url, type, body);
                if (r.code == 401) {
                    token = DriveAuth.accessToken(c, true);
                    r = send(method, url, type, body);
                }
                if (r.retryable()) throw new RetryException("Drive said " + r.code);
                return r;
            } catch (IOException e) {
                throw new RetryException("network: " + e.getMessage());
            }
        }

        private Http.Response send(String method, String url, String type, byte[] body) throws IOException {
            Map<String, String> h = new HashMap<>();
            h.put("Authorization", "Bearer " + token);
            return Http.request(method, url, h, type, body);
        }
    }

    private static JSONObject parse(Http.Response r) {
        try {
            return new JSONObject(r.body);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }
}
