/*
 * The dashboard's server, in the phone.
 *
 * The app shows the very same dashboard.html the PC serves. On the PC its five
 * requests (/api/summary, /api/app/<pkg>, /api/sync, /api/excluded, /api/stop)
 * go to Python; here this file answers them, computing the same figures from
 * the app's own day files. It is a port of wellbeing/parse.py
 * (foreground_sessions), sync.py (the day/hour splits), pickups.py and the
 * parts of stats.py the page uses -- keep them in step. android/web/check.html
 * runs it on the PC so its numbers can be compared with Python's.
 *
 * `Bridge` is the app (DashboardActivity), or a stand-in when checking on the PC:
 *   dayFiles()        JSON list of "events-YYYY-MM-DD.csv" names
 *   readEvents(name)  that file's CSV text
 *   labels(json)      JSON {package: app name} for a JSON list of packages
 *   excluded()        JSON list of excluded packages;  setExcluded(json)
 *   lastCollectedMs() when the app last collected
 *   collectNow()      runs a collection; JSON {ok, message}
 */
(function () {
  "use strict";

  // --- constants, as in the Python ------------------------------------------
  const EVENT_TYPES = {
    1: "ACTIVITY_RESUMED", 2: "ACTIVITY_PAUSED", 7: "USER_INTERACTION",
    10: "NOTIFICATION_SEEN", 12: "NOTIFICATION_INTERRUPTION", 15: "SCREEN_INTERACTIVE",
    16: "SCREEN_NON_INTERACTIVE", 17: "KEYGUARD_SHOWN", 18: "KEYGUARD_HIDDEN",
    19: "FOREGROUND_SERVICE_START", 20: "FOREGROUND_SERVICE_STOP", 23: "ACTIVITY_STOPPED",
  };
  const RESUMED = "ACTIVITY_RESUMED", PAUSED = "ACTIVITY_PAUSED";
  const SCREEN_ON = "SCREEN_INTERACTIVE", SCREEN_OFF = "SCREEN_NON_INTERACTIVE";
  const UNLOCK = "KEYGUARD_HIDDEN", LOCK = "KEYGUARD_SHOWN", NOTIFICATION = "NOTIFICATION_INTERRUPTION";
  const MAX_SESSION_MS = 6 * 3600000, MERGE_GAP_MS = 5000;           // parse.py
  const TRIGGER_WINDOW_MS = 120000, MICRO_MS = 30000;                // pickups.py
  const MAX_PICKUP_MS = MAX_SESSION_MS;
  const JUNK_PICKUP_MS = 30000, PICKUP_WINDOW_MS = 120000;           // stats.py
  const BOOKEND_TOLERANCE_MS = 10 * 60 * 1000;
  const CHROME = ["com.android.systemui", "com.google.android.permissioncontroller",
    "com.samsung.android.honeyboard", "com.google.android.inputmethod.latin",
    "com.samsung.android.app.cocktailbardervice"];
  const PASSTHROUGH = new Set(CHROME.concat(["com.sec.android.app.launcher",
    "com.samsung.android.app.launcher", "com.android.intentresolver", "android"]));
  const DAY_BLOCKS = [["Night", 23.5, 7.0], ["Morning", 7.0, 12.0], ["Afternoon", 12.0, 17.0],
    ["Evening", 17.0, 20.0], ["Late", 20.0, 22.5], ["Pre-bed", 22.5, 23.5]];
  const PICKUP_BANDS = [["<10s", 10000], ["10-30s", 30000], ["30s-1m", 60000], ["1-3m", 180000],
    ["3-10m", 600000], ["10-30m", 1800000], ["30m+", null]];
  const RANGES = { "1": 1, "3": 3, "7": 7, "14": 14, "30": 30, "90": 90 };
  const STALE_MS = 24 * 3600000;

  // --- dates, in the phone's own zone ----------------------------------------
  const pad = n => String(n).padStart(2, "0");
  const dayStr = ms => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const hhmm = ms => { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const nextMidnight = ms => { const d = new Date(ms); return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime(); };
  const nextHour = ms => { const d = new Date(ms); return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours() + 1).getTime(); };
  const addDays = (day, n) => { const [y, m, d] = day.split("-").map(Number); return dayStr(new Date(y, m - 1, d + n).getTime()); };
  const daysIn = (start, end) => { const out = []; for (let d = start; d <= end; d = addDays(d, 1)) out.push(d); return out; };
  const blockHH = h => `${pad(Math.floor(h))}:${pad(Math.round((h - Math.floor(h)) * 60))}`;

  // --- the data, read once and derived once ---------------------------------
  let D = null;           // {events, sessions, slices, pickups, days, labels}
  const fileCache = {};
  let rereadFrom = "";    // day files from this one on may be rewritten by the next collection

  function readAll(force) {
    const from = rereadFrom;
    // A collection rewrites every day from the start of yesterday, or from its
    // last successful run if that is older (Collector.collect); never run: all.
    rereadFrom = `events-${dayStr(Math.min(Number(Bridge.lastCollectedMs()), Date.now() - 86400000))}`;
    const names = JSON.parse(Bridge.dayFiles()).sort();
    const keyed = new Map();
    for (const name of names) {
      if (force && name >= from) delete fileCache[name];
      if (!(name in fileCache)) fileCache[name] = parseCsv(Bridge.readEvents(name));
      for (const e of fileCache[name]) keyed.set(`${e.ts}|${e.type}|${e.pkg}|${e.cls}`, e);
    }
    // Sorted as Python sorts them: by time, then type name.
    return [...keyed.values()].sort((a, b) => a.ts - b.ts || (a.type < b.type ? -1 : a.type > b.type ? 1 : 0));
  }

  function parseCsv(text) {
    const out = [];
    const lines = text.split("\n");
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (!line) continue;
      const f = splitCsv(line);
      const type = EVENT_TYPES[+f[1]];
      if (!type || !f[0]) continue;     // types no figure uses are skipped
      out.push({ ts: +f[0], type, pkg: f[2] || "", cls: f[3] || "" });
    }
    return out;
  }

  function splitCsv(line) {
    if (line.indexOf('"') < 0) return line.split(",");
    const out = []; let cur = "", q = false;
    for (const ch of line) {
      if (ch === '"') q = !q;
      else if (ch === "," && !q) { out.push(cur); cur = ""; }
      else cur += ch;
    }
    out.push(cur);
    return out;
  }

  // parse.foreground_sessions
  function foregroundSessions(events, untilMs) {
    const out = [];
    let pkg = null, start = 0;
    const close = at => {
      if (pkg === null) return;
      const end = Math.min(at, start + MAX_SESSION_MS);
      if (end > start) {
        const last = out[out.length - 1];
        if (last && last[0] === pkg && start - last[2] <= MERGE_GAP_MS) last[2] = end;
        else out.push([pkg, start, end]);
      }
      pkg = null;
    };
    for (const ev of events) {
      if (ev.type === RESUMED && ev.pkg) {
        if (pkg !== ev.pkg) { close(ev.ts); pkg = ev.pkg; start = ev.ts; }
      } else if (ev.type === PAUSED && ev.pkg) {
        if (pkg === ev.pkg) close(ev.ts);
      } else if (ev.type === SCREEN_OFF || ev.type === LOCK) {
        close(ev.ts);
      }
    }
    close(untilMs !== undefined ? untilMs : (events.length ? events[events.length - 1].ts : 0));
    return out;
  }

  function* boundaries(a, b, step) {
    let cur = a;
    while (cur < b) {
      const nxt = Math.min(step(cur), b);
      if (nxt <= cur) break;
      yield [cur, nxt];
      cur = nxt;
    }
  }

  // pickups.build
  function buildPickups(events) {
    const out = [];
    let onAt = null, unlockAt = null, apps = [], trigger = null, pending = [];
    const triggerFor = at => {
      let hit = null;
      for (const [t, p] of pending) if (at - t >= 0 && at - t <= TRIGGER_WINDOW_MS && p) hit = [p, at - t];
      return hit;
    };
    for (const ev of events) {
      if (ev.type === NOTIFICATION) pending.push([ev.ts, ev.pkg]);
      else if (ev.type === LOCK) pending = [];
      else if (ev.type === SCREEN_ON) { onAt = ev.ts; unlockAt = null; apps = []; trigger = triggerFor(ev.ts); }
      else if (ev.type === UNLOCK && onAt !== null && unlockAt === null) {
        unlockAt = ev.ts; trigger = triggerFor(ev.ts); pending = [];
      } else if (ev.type === RESUMED && unlockAt !== null && ev.pkg && !PASSTHROUGH.has(ev.pkg) && !apps.includes(ev.pkg)) {
        apps.push(ev.pkg);
      } else if (ev.type === SCREEN_OFF && onAt !== null) {
        const duration = ev.ts - onAt;
        if (duration >= 0 && duration <= MAX_PICKUP_MS) {
          const unlocked = unlockAt !== null;
          out.push({
            day: dayStr(onAt), start_ms: onAt, unlock_ms: unlockAt, end_ms: ev.ts,
            duration_ms: duration, unlocked: unlocked ? 1 : 0,
            first_package: apps[0] || "", packages: apps.join(";"),
            trigger_package: trigger ? trigger[0] : "", trigger_delay_ms: trigger ? trigger[1] : null,
            micro: unlocked && duration < MICRO_MS ? 1 : 0, impulse: unlocked && !trigger ? 1 : 0,
          });
        }
        onAt = unlockAt = trigger = null; apps = [];
      }
    }
    return out;
  }

  function derive(force) {
    const events = readAll(force);
    const sessionTypes = new Set([RESUMED, PAUSED, "ACTIVITY_STOPPED", SCREEN_ON, SCREEN_OFF, LOCK, UNLOCK]);
    const sess = foregroundSessions(events.filter(e => sessionTypes.has(e.type)));
    const sessions = [], slices = new Map();          // slices: "day|hour|pkg" -> ms
    for (const [pkg, a, b] of sess) {
      for (const [x, y] of boundaries(a, b, nextMidnight)) sessions.push({ day: dayStr(x), pkg, start: x, end: y });
      for (const [x, y] of boundaries(a, b, nextHour)) {
        const k = `${dayStr(x)}|${new Date(x).getHours()}|${pkg}`;
        slices.set(k, (slices.get(k) || 0) + (y - x));
      }
    }
    const sliceRows = [...slices].map(([k, ms]) => { const [day, hour, pkg] = k.split("|"); return { day, hour: +hour, pkg, ms }; });
    const pickTypes = new Set([SCREEN_ON, SCREEN_OFF, UNLOCK, LOCK, NOTIFICATION, RESUMED]);
    const pickups = buildPickups(events.filter(e => pickTypes.has(e.type)));
    const days = [...new Set(sliceRows.map(r => r.day))].sort();
    const pkgs = [...new Set(sliceRows.map(r => r.pkg).concat(events.filter(e => e.pkg).map(e => e.pkg)))];
    let labels = {};
    try { labels = JSON.parse(Bridge.labels(JSON.stringify(pkgs))); } catch (_) { /* fall back to ids */ }
    D = { events, sessions, slices: sliceRows, pickups, days, labels };
  }
  const label = p => D.labels[p] || p;
  const eventDay = e => (e._day || (e._day = dayStr(e.ts)));

  // --- stats.py ---------------------------------------------------------------
  const skipSet = (includeChrome, exclude) => new Set((includeChrome ? [] : CHROME).concat(exclude || []));
  const inRange = (day, s, e) => day >= s && day <= e;

  function dailyTotals(s, e, inclChrome, exclude) {
    const skip = skipSet(inclChrome, exclude);
    const usage = {};
    for (const r of D.slices) {
      if (!inRange(r.day, s, e) || skip.has(r.pkg)) continue;
      const u = usage[r.day] || (usage[r.day] = { ms: 0, apps: new Set() });
      u.ms += r.ms; u.apps.add(r.pkg);
    }
    const counts = {};
    for (const ev of D.events) {
      if (ev.type !== UNLOCK && ev.type !== NOTIFICATION) continue;
      const d = eventDay(ev);
      if (!inRange(d, s, e)) continue;
      const k = d + "|" + ev.type; counts[k] = (counts[k] || 0) + 1;
    }
    return daysIn(s, e).map(d => ({
      day: d, ms: usage[d] ? usage[d].ms : 0, apps: usage[d] ? usage[d].apps.size : 0,
      unlocks: counts[d + "|" + UNLOCK] || 0, notifications: counts[d + "|" + NOTIFICATION] || 0,
    }));
  }

  function topApps(s, e, limit, inclChrome, exclude) {
    const skip = skipSet(inclChrome, exclude);
    const ms = {}, opens = {};
    for (const r of D.slices) if (inRange(r.day, s, e) && !skip.has(r.pkg)) ms[r.pkg] = (ms[r.pkg] || 0) + r.ms;
    for (const x of D.sessions) if (inRange(x.day, s, e)) opens[x.pkg] = (opens[x.pkg] || 0) + 1;
    return Object.keys(ms).sort((a, b) => ms[b] - ms[a]).slice(0, limit)
      .map(p => ({ package: p, label: label(p), ms: ms[p], opens: opens[p] || 0 }));
  }

  function hourly(s, e, inclChrome, exclude) {
    const skip = skipSet(inclChrome, exclude), m = {};
    for (const r of D.slices) {
      if (!inRange(r.day, s, e) || skip.has(r.pkg)) continue;
      const k = r.day + "|" + r.hour; m[k] = (m[k] || 0) + r.ms;
    }
    return Object.entries(m).map(([k, ms]) => { const [day, hour] = k.split("|"); return { day, hour: +hour, ms }; });
  }

  function dayBlocks(s, e, inclChrome, exclude) {
    const skip = skipSet(inclChrome, exclude);
    const totals = Object.fromEntries(DAY_BLOCKS.map(([n]) => [n, 0]));
    for (const x of D.sessions) {
      if (!inRange(x.day, s, e) || skip.has(x.pkg)) continue;
      let a = x.start; const b = x.end;
      while (a < b) {
        const d = new Date(a);
        const hour = d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
        let moved = false;
        for (const [name, lo, hi] of DAY_BLOCKS) {
          const inside = lo < hi ? (hour >= lo && hour < hi) : (hour >= lo || hour < hi);
          if (!inside) continue;
          // Wall-clock edges, as Python's naive datetimes give: midnight plus
          // hi hours of absolute time is an hour off on a daylight-saving day,
          // and the loop would then creep on a millisecond at a time.
          const hh = Math.floor(hi), mm = Math.round((hi - hh) * 60);
          let edge = new Date(d.getFullYear(), d.getMonth(), d.getDate(), hh, mm).getTime();
          if (hi <= hour) edge = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1, hh, mm).getTime();
          const chunk = Math.min(b, edge);
          if (chunk <= a) break;                  // never creep, whatever the clock does
          totals[name] += chunk - a;
          a = chunk;
          moved = true;
          break;
        }
        if (!moved) break;
      }
    }
    const dayCount = new Set(D.slices.filter(r => inRange(r.day, s, e)).map(r => r.day)).size || 1;
    const grand = Object.values(totals).reduce((x, y) => x + y, 0) || 1;
    return DAY_BLOCKS.map(([name, lo, hi]) => ({
      name, from: blockHH(lo), to: blockHH(hi), ms: totals[name],
      ms_per_day: Math.round(totals[name] / dayCount), share: Math.round(1000 * totals[name] / grand) / 10,
    }));
  }

  function notificationPickups(s, e, exclude) {
    const skip = new Set(exclude || []);
    const triggered = {}, sent = {}, delays = [];
    let unlocks = 0, attributed = 0, pending = [];
    for (const ev of D.events) {
      if (ev.type !== NOTIFICATION && ev.type !== UNLOCK && ev.type !== LOCK) continue;
      if (!inRange(eventDay(ev), s, e)) continue;
      if (ev.type === NOTIFICATION) {
        if (skip.has(ev.pkg)) continue;
        sent[ev.pkg] = (sent[ev.pkg] || 0) + 1; pending.push([ev.ts, ev.pkg]);
      } else if (ev.type === LOCK) pending = [];
      else {
        unlocks++;
        const recent = pending.filter(([t, p]) => ev.ts - t <= PICKUP_WINDOW_MS && p);
        if (recent.length) {
          const [ts, pkg] = recent[recent.length - 1];
          triggered[pkg] = (triggered[pkg] || 0) + 1; delays.push(ev.ts - ts); attributed++;
        }
        pending = [];
      }
    }
    delays.sort((a, b) => a - b);
    return {
      unlocks, triggered: attributed, self_initiated: unlocks - attributed,
      pct_triggered: unlocks ? Math.round(100 * attributed / unlocks) : 0,
      median_delay_s: delays.length ? Math.round(delays[Math.floor(delays.length / 2)] / 1000) : 0,
      apps: Object.entries(triggered).map(([p, n]) => ({ package: p, label: label(p), pickups: n,
        notifications: sent[p] || 0, rate: sent[p] ? Math.round(100 * n / sent[p]) : 0 }))
        .sort((a, b) => b.pickups - a.pickups),
      notifiers: Object.entries(sent).map(([p, n]) => ({ package: p, label: label(p), notifications: n,
        pickups: triggered[p] || 0 })).sort((a, b) => b.notifications - a.notifications).slice(0, 12),
    };
  }

  function pickupQuality(s, e) {
    let junk = 0, total = 0, openAt = null;
    for (const ev of D.events) {
      if (ev.type !== UNLOCK && ev.type !== LOCK) continue;
      if (!inRange(eventDay(ev), s, e)) continue;
      if (ev.type === UNLOCK) openAt = ev.ts;
      else if (openAt !== null) { total++; if (ev.ts - openAt < JUNK_PICKUP_MS) junk++; openAt = null; }
    }
    return { sessions: total, junk, pct_junk: total ? Math.round(100 * junk / total) : 0 };
  }

  const quantile = (v, q) => v.length ? v[Math.min(v.length - 1, Math.floor(q * v.length))] : 0;

  function pickupDaily(s, e) {
    const m = {};
    for (const p of D.pickups) {
      if (!inRange(p.day, s, e)) continue;
      const r = m[p.day] || (m[p.day] = { day: p.day, pickups: 0, glances: 0, micro: 0, impulse: 0, impulse_micro: 0, pickup_ms: 0, glance_ms: 0 });
      r.pickups += p.unlocked; r.glances += 1 - p.unlocked; r.micro += p.micro; r.impulse += p.impulse;
      r.impulse_micro += p.micro * p.impulse;
      if (p.unlocked) r.pickup_ms += p.duration_ms; else r.glance_ms += p.duration_ms;
    }
    return Object.values(m).sort((a, b) => (a.day < b.day ? -1 : 1));
  }

  function pickupSummary(s, e, exclude) {
    const rows = D.pickups.filter(p => inRange(p.day, s, e));
    const ups = rows.filter(p => p.unlocked);
    const durations = ups.map(p => p.duration_ms).sort((a, b) => a - b);
    const nDays = new Set(rows.map(p => p.day)).size || 1;
    const bands = []; let lo = 0;
    for (const [name, hi] of PICKUP_BANDS) {
      bands.push({ band: name, count: durations.filter(d => d >= lo && (hi === null || d < hi)).length });
      lo = hi || lo;
    }
    const byHour = Array.from({ length: 24 }, (_, h) => ({ hour: h, pickups: 0, impulse: 0 }));
    for (const p of ups) { const h = new Date(p.start_ms).getHours(); byHour[h].pickups++; byHour[h].impulse += p.impulse; }
    const skip = new Set(exclude || []), perApp = {};
    for (const p of ups) {
      const k = p.first_package;
      if (!k || skip.has(k)) continue;
      const a = perApp[k] || (perApp[k] = { package: k, label: label(k), pickups: 0, impulse: 0, micro: 0, impulse_micro: 0 });
      a.pickups++; a.impulse += p.impulse; a.micro += p.micro; a.impulse_micro += p.micro * p.impulse;
    }
    const top = key => Object.values(perApp).filter(a => a[key]).sort((a, b) => b[key] - a[key]).slice(0, 10);
    const total = ups.length, impulse = ups.reduce((x, p) => x + p.impulse, 0), micro = ups.reduce((x, p) => x + p.micro, 0);
    return {
      pickups: total, glances: rows.length - total, micro, impulse,
      impulse_micro: ups.reduce((x, p) => x + p.micro * p.impulse, 0),
      per_day: Math.round(10 * total / nDays) / 10,
      pct_impulse: total ? Math.round(100 * impulse / total) : 0, pct_micro: total ? Math.round(100 * micro / total) : 0,
      median_ms: quantile(durations, 0.5), p25_ms: quantile(durations, 0.25), p75_ms: quantile(durations, 0.75),
      bands, by_hour: byHour, daily: pickupDaily(s, e), top_impulse: top("impulse"), top_micro: top("micro"),
    };
  }

  function weekdaySplit(pkg, s, e) {
    const perDay = {};
    for (const r of D.slices) if (r.pkg === pkg && inRange(r.day, s, e)) perDay[r.day] = (perDay[r.day] || 0) + r.ms;
    const opens = {};
    for (const x of D.sessions) if (x.pkg === pkg) opens[x.day] = (opens[x.day] || 0) + 1;
    const g = { weekday: { ms: 0, opens: 0, days: 0 }, weekend: { ms: 0, opens: 0, days: 0 } };
    for (const [day, ms] of Object.entries(perDay)) {
      const [y, m, d] = day.split("-").map(Number);
      const wd = new Date(y, m - 1, d).getDay();          // 0 = Sunday, 6 = Saturday
      const x = g[wd === 0 || wd === 6 ? "weekend" : "weekday"];
      x.ms += ms; x.opens += opens[day] || 0; x.days++;
    }
    for (const x of Object.values(g)) {
      const n = Math.max(1, x.days);
      x.ms_per_day = Math.round(x.ms / n); x.opens_per_day = Math.round(x.opens / n);
    }
    return g;
  }

  function appBookends(pkg, s, e, exclude) {
    const skip = new Set(exclude || []);
    const app = {}, phone = {};
    for (const x of D.sessions) {
      if (!inRange(x.day, s, e)) continue;
      if (x.pkg === pkg) {
        const a = app[x.day] || (app[x.day] = { first: x.start, last: x.end });
        a.first = Math.min(a.first, x.start); a.last = Math.max(a.last, x.end);
      }
      if (!skip.has(x.pkg)) {
        const p = phone[x.day] || (phone[x.day] = { first: x.start, last: x.end });
        p.first = Math.min(p.first, x.start); p.last = Math.max(p.last, x.end);
      }
    }
    const days = [];
    for (const day of Object.keys(phone).sort()) {
      const a = app[day], p = phone[day];
      if (!a) continue;
      days.push({ day, app_first: hhmm(a.first), app_last: hhmm(a.last), phone_first: hhmm(p.first),
        phone_last: hhmm(p.last), is_first: a.first - p.first <= BOOKEND_TOLERANCE_MS,
        is_last: p.last - a.last <= BOOKEND_TOLERANCE_MS });
    }
    const n = days.length || 1;
    return { days, first_pct: Math.round(100 * days.filter(d => d.is_first).length / n),
      last_pct: Math.round(100 * days.filter(d => d.is_last).length / n), day_count: days.length };
  }

  function switchChain(pkg, s, e, exclude, limit = 6) {
    const skip = new Set([...PASSTHROUGH, ...(exclude || [])]);
    const seq = D.sessions.filter(x => inRange(x.day, s, e)).sort((a, b) => a.start - b.start)
      .map(x => x.pkg).filter(p => !skip.has(p));
    const into = {}, out = {};
    for (let i = 0; i + 1 < seq.length; i++) {
      const a = seq[i], b = seq[i + 1];
      if (b === pkg && a !== pkg) into[a] = (into[a] || 0) + 1;
      if (a === pkg && b !== pkg) out[b] = (out[b] || 0) + 1;
    }
    const top = c => Object.entries(c).sort((x, y) => y[1] - x[1]).slice(0, limit)
      .map(([p, n]) => ({ package: p, label: label(p), count: n }));
    const sum = c => Object.values(c).reduce((x, y) => x + y, 0);
    return { into: top(into), out: top(out), into_total: sum(into), out_total: sum(out) };
  }

  function appDetail(pkg, s, e, exclude) {
    const perDay = {}, hours = {}, sess = {};
    for (const r of D.slices) {
      if (r.pkg !== pkg || !inRange(r.day, s, e)) continue;
      perDay[r.day] = (perDay[r.day] || 0) + r.ms; hours[r.hour] = (hours[r.hour] || 0) + r.ms;
    }
    const durations = [];
    for (const x of D.sessions) {
      if (x.pkg !== pkg || !inRange(x.day, s, e)) continue;
      const v = sess[x.day] || (sess[x.day] = { opens: 0, longest: 0, first: x.start, last: x.end });
      v.opens++; v.longest = Math.max(v.longest, x.end - x.start);
      v.first = Math.min(v.first, x.start); v.last = Math.max(v.last, x.end);
      durations.push(x.end - x.start);
    }
    durations.sort((a, b) => a - b);
    const daily = daysIn(s, e).map(d => ({ day: d, ms: perDay[d] || 0, opens: sess[d] ? sess[d].opens : 0,
      longest_ms: sess[d] ? sess[d].longest : 0, first: sess[d] ? hhmm(sess[d].first) : "", last: sess[d] ? hhmm(sess[d].last) : "" }));
    const hourly = Object.keys(hours).map(Number).sort((a, b) => a - b).map(h => ({ hour: h, ms: hours[h] }));
    const notifs = D.events.filter(ev => ev.pkg === pkg && ev.type === NOTIFICATION && inRange(eventDay(ev), s, e)).length;
    const active = daily.filter(d => d.ms > 0);
    const totalMs = daily.reduce((x, d) => x + d.ms, 0), totalOpens = daily.reduce((x, d) => x + d.opens, 0);
    const skip = skipSet(false, exclude);
    const share = D.slices.filter(r => inRange(r.day, s, e) && !skip.has(r.pkg)).reduce((x, r) => x + r.ms, 0);
    return {
      package: pkg, label: label(pkg), excluded: (exclude || []).includes(pkg), daily, hourly,
      weekday_split: weekdaySplit(pkg, s, e), bookends: appBookends(pkg, s, e, exclude),
      switch_chain: switchChain(pkg, s, e, exclude),
      totals: {
        ms: totalMs, opens: totalOpens, active_days: active.length,
        per_day_ms: active.length ? Math.round(totalMs / active.length) : 0,
        avg_session_ms: totalOpens ? Math.round(totalMs / totalOpens) : 0,
        median_session_ms: durations.length ? durations[Math.floor(durations.length / 2)] : 0,
        longest_ms: durations.length ? durations[durations.length - 1] : 0,
        notifications: notifs, share_pct: share ? Math.round(1000 * totalMs / share) / 10 : 0,
        busiest_hour: hourly.length ? hourly.reduce((a, b) => (b.ms > a.ms ? b : a)).hour : null,
      },
    };
  }

  // --- the five requests --------------------------------------------------
  function resolveRange(q) {
    if (q.get("start") && q.get("end")) return [q.get("start"), q.get("end")];
    const span = q.get("range") || "today";
    const today = dayStr(Date.now());
    if (span === "today") return [today, today];
    if (span === "yesterday") { const y = addDays(today, -1); return [y, y]; }
    if (span === "all" && D.days.length) return [D.days[0], D.days[D.days.length - 1]];
    const n = RANGES[span] || 14;
    if (!D.days.length) return [addDays(today, -(n - 1)), today];
    const end = D.days[D.days.length - 1];
    const start = addDays(end, -(n - 1));
    return [start > D.days[0] ? start : D.days[0], end];
  }

  function excluded() { try { return JSON.parse(Bridge.excluded()); } catch (_) { return []; } }

  function phoneWarning() {
    const last = Number(Bridge.lastCollectedMs());
    if (!last) return "the app hasn't collected anything yet -- tap Collect now";
    const age = Date.now() - last;
    return age > STALE_MS ? `the app hasn't collected for ${Math.floor(age / 3600000)} hours -- check Usage Dump's status screen` : null;
  }

  function summary(q) {
    const [s, e] = resolveRange(q), sys = q.get("system") === "1", excl = excluded();
    const daily = dailyTotals(s, e, sys, excl);
    return {
      start: s, end: e, daily, apps: topApps(s, e, 15, sys, excl),
      hourly: hourly(s, e, sys, excl), day_blocks: dayBlocks(s, e, sys, excl),
      excluded_apps: excl, app_choices: topApps(s, e, 500, sys, []),
      coverage: {
        first_event_ms: D.events.length ? D.events[0].ts : null,
        last_event_ms: D.events.length ? D.events[D.events.length - 1].ts : null,
        event_count: D.events.length, days: D.days, last_sync: null, sync_count: null,
      },
      phone_warning: phoneWarning(),
      totals: { ms: daily.reduce((x, d) => x + d.ms, 0), unlocks: daily.reduce((x, d) => x + d.unlocks, 0),
        notifications: daily.reduce((x, d) => x + d.notifications, 0),
        active_days: Math.max(1, daily.filter(d => d.ms > 0).length) },
      pickups: notificationPickups(s, e, excl), pickup_quality: pickupQuality(s, e),
      pickup_summary: pickupSummary(s, e, excl),
    };
  }

  function answer(url, opts) {
    const u = new URL(url, "https://phone.local/");
    const path = u.pathname;
    if (path === "/api/summary") { if (!D) derive(false); return [200, summary(u.searchParams)]; }
    if (path.startsWith("/api/app/")) {
      if (!D) derive(false);
      const [s, e] = resolveRange(u.searchParams);
      return [200, appDetail(decodeURIComponent(path.slice(9)), s, e, excluded())];
    }
    if (path === "/api/sync") {
      const before = D ? D.events.length : 0;
      const r = JSON.parse(Bridge.collectNow());
      derive(true);
      if (!r.ok) return [409, { ok: false, error: r.message }];
      return [200, { ok: true, events_added: Math.max(0, D.events.length - before), files: 0, refused: [],
        phone_collected_at_ms: Number(Bridge.lastCollectedMs()), phone_warning: phoneWarning(), archive_rows_added: 0 }];
    }
    if (path === "/api/excluded") {
      const body = JSON.parse((opts && opts.body) || "{}");
      // With `shown`, only those apps change; the other exclusions stay (archive.py does the same).
      const shown = new Set(body.shown || []);
      const packages = (body.shown ? excluded().filter(p => !shown.has(p)) : []).concat(body.packages || []);
      Bridge.setExcluded(JSON.stringify(packages));
      return [200, { ok: true, excluded_apps: packages }];
    }
    return [404, { ok: false, error: "not on the phone: " + path }];
  }

  // The page's fetch() calls to /api/ land here instead of a server.
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (url, opts) {
    if (typeof url === "string" && url.startsWith("/api/")) {
      return new Promise(resolve => setTimeout(() => {      // let the page paint first
        let status, body;
        try { [status, body] = answer(url, opts); } catch (err) { status = 500; body = { ok: false, error: String(err) }; }
        resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
      }, 0));
    }
    return realFetch(url, opts);
  };

  // What differs on the phone: no server to stop, and "sync" means collect now.
  window.PHONE = true;
  document.addEventListener("DOMContentLoaded", () => {
    const stop = document.getElementById("stop");
    if (stop) stop.hidden = true;
    const sync = document.getElementById("sync");
    if (sync) sync.textContent = "Collect now";
    const scope = document.getElementById("exclude-scope");
    if (scope) scope.textContent = "Kept on this phone; a PC's dashboard has its own list.";
    const collection = [...document.querySelectorAll("#help dt")].find(dt => dt.textContent === "Collection");
    if (collection) collection.nextElementSibling.innerHTML =
      "Worked out on the phone from the app's own records, which it collects every 6 hours. " +
      "<b>Collect now</b> brings it up to the minute. A PC's dashboard, if you use one, works the " +
      "figures out the same way from what the app uploads to Google Drive.";
  });

  // For check.html: the computations, without the fetch layer.
  window.__phoneApi = { derive, answer };
})();
