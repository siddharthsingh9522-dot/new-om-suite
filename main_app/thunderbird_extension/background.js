const DEFAULTS = {
  apiBase: "http://127.0.0.1:5000",
  token: "",
  username: "",
  enabled: true,
  autoSend: false,
  pollMinutes: 1,          // WebExtension alarms can't reliably fire faster than 1 min, so we poll every N minutes instead of the old (silently-clamped) 5-second setting.
  matchLimit: 250,
  searchDays: 365,
  searchFolders: [],
  notifyOnJob: true        // desktop notification when a match/send job finishes (uses the already-declared "notifications" permission)
};

// Runtime status the popup reads to show *why* nothing happened, instead of
// staying blank forever when config is incomplete or the API is unreachable.
const STATE_DEFAULTS = {
  lastPollAt: 0,
  lastOkAt: 0,
  lastError: "",
  lastJobCount: 0,
  lastCycleSummary: "",
  connected: null // null = never tried, true/false = last known result
};

async function settings() {
  return { ...DEFAULTS, ...(await messenger.storage.local.get(DEFAULTS)) };
}

async function getState() {
  return { ...STATE_DEFAULTS, ...(await messenger.storage.local.get(STATE_DEFAULTS)) };
}

async function setState(patch) {
  const cur = await getState();
  const next = { ...cur, ...patch };
  await messenger.storage.local.set(next);
  return next;
}

async function notify(title, message) {
  try {
    const s = await settings();
    if (!s.notifyOnJob) return;
    await messenger.notifications.create({
      type: "basic",
      title,
      message,
      iconUrl: "icon.png"
    });
  } catch (_) { /* notifications permission granted but icon/platform issue — never fatal */ }
}

function norm(v) {
  return String(v || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function emails(list) {
  return (list || []).map(x => {
    const m = String(x).match(/<([^>]+)>/);
    return (m ? m[1] : String(x)).trim().toLowerCase();
  }).filter(x => x.includes("@"));
}

function unique(a) { return [...new Set(a || [])]; }

function words(v) {
  return norm(v).replace(/[^a-z0-9@._-]+/g, " ").split(/\s+/).filter(x => x.length > 2);
}

function extractNumbers(v) {
  return (String(v || "").match(/\b\d{3,}\b/g) || []);
}

function folderIsSent(folder) {
  const n = norm(folder?.name);
  const t = norm(folder?.type);
  return t === "sent" || n === "sent" || n.includes("sent items") || n.includes("sent mail") || n.includes("sent");
}

function flattenFolders(folder, out = []) {
  if (!folder) return out;
  out.push(folder);
  for (const child of (folder.subFolders || [])) flattenFolders(child, out);
  return out;
}

async function sentFolders() {
  const accounts = await messenger.accounts.list(true);
  const folders = [];
  for (const account of accounts) {
    for (const f of flattenFolders(account.rootFolder, [])) {
      if (folderIsSent(f)) folders.push(f);
    }
  }
  return folders;
}

async function targetFolders() {
  // Agar user ne Options mein specific folders select ki hain, unhi mein search karo.
  // Warna purana default behaviour: auto-detected "Sent" folders (har account mein).
  const s = await settings();
  if (s.searchFolders && s.searchFolders.length) {
    return s.searchFolders.map(f => ({ id: f.id, name: f.name }));
  }
  return await sentFolders();
}

async function queryCandidates(folderId, job) {
  const days = Number(job.match_days || (await settings()).searchDays || 365);
  const fromDate = new Date(Date.now() - days * 86400000);
  const base = {
    folderId,
    fromMe: true,
    fromDate,
    messagesPerPage: 100,
    autoPaginationTimeout: 500
  };
  const terms = [];
  const subjectPrefix = String(job.subject || "").split(":-")[0].trim();
  if (subjectPrefix) terms.push({ ...base, subject: subjectPrefix });
  for (const party of (job.party_names || []).slice(0, 2)) {
    if (party.length >= 4) terms.push({ ...base, fullText: party });
  }
  if (!terms.length) terms.push(base);

  const seen = new Map();
  for (const q of terms) {
    try {
      const result = await messenger.messages.query(q);
      let page = result;
      for (const m of (page.messages || [])) {
        if (!seen.has(m.id)) seen.set(m.id, m);
        if (seen.size >= Number((await settings()).matchLimit || 250)) break;
      }
      if (seen.size >= Number((await settings()).matchLimit || 250)) break;
      while (page.id && seen.size < Number((await settings()).matchLimit || 250)) {
        page = await messenger.messages.continueList(page.id);
        for (const m of (page.messages || [])) {
          if (!seen.has(m.id)) seen.set(m.id, m);
          if (seen.size >= Number((await settings()).matchLimit || 250)) break;
        }
      }
    } catch (e) {
      console.warn("Query failed", e);
    }
  }
  return [...seen.values()];
}

async function messageBody(messageId) {
  try {
    const full = await messenger.messages.getFull(messageId, { decodeContent: true, decodeHeaders: true });
    const parts = [];
    function walk(p) {
      if (!p) return;
      if (typeof p.body === "string" && String(p.contentType || "").startsWith("text/")) parts.push(p.body);
      for (const c of (p.parts || [])) walk(c);
    }
    walk(full);
    return parts.join("\n").slice(0, 20000);
  } catch (_) { return ""; }
}

function scoreMessage(message, body, job) {
  const subject = norm(message.subject);
  const bodyN = norm(body);
  const branch = norm(job.branch_code);
  const branchName = norm(job.branch_name);
  const parties = (job.party_names || []).map(norm).filter(Boolean);
  const partyCodes = (job.party_codes || []).map(norm).filter(Boolean);
  const bills = (job.bill_nos || []).map(norm).filter(Boolean);
  let score = 0;
  const evidence = {};

  const partyHits = parties.filter(p => subject.includes(p) || bodyN.includes(p));
  if (partyHits.length) { score += Math.min(35, 20 + partyHits.length * 7); evidence.party = partyHits; }
  const codeHits = partyCodes.filter(p => subject.includes(p) || bodyN.includes(p));
  if (codeHits.length) { score += Math.min(20, codeHits.length * 10); evidence.party_code = codeHits; }
  const billHits = bills.filter(n => subject.includes(n) || bodyN.includes(n));
  if (billHits.length) { score += Math.min(30, 10 + billHits.length * 8); evidence.bill_numbers = billHits; }
  if (subject.includes("scm retail express")) { score += 10; evidence.subject_pattern = true; }
  if (subject.includes("auto generated freight bill")) { score += 5; evidence.freight_pattern = true; }
  if (bodyN.includes("auto generated tax invoice")) { score += 5; evidence.body_pattern = true; }
  if (branch && (subject.includes(branch) || bodyN.includes(branch))) { score += 5; evidence.branch_code = true; }
  if (branchName && (subject.includes(branchName) || bodyN.includes(branchName))) { score += 5; evidence.branch_name = true; }
  score = Math.min(100, score);
  return { score, evidence };
}

async function getHeaderEmails(messageId, name) {
  try {
    const h = await messenger.messages.getHeaders(messageId, { decodeHeaders: true });
    const values = h?.[name] || h?.[name.toLowerCase()] || [];
    return emails(values);
  } catch (_) { return []; }
}

async function bestMatch(job) {
  const folders = await targetFolders();
  const candidates = [];
  for (const folder of folders) {
    const msgs = await queryCandidates(folder.id, job);
    for (const m of msgs) {
      const body = await messageBody(m.id);
      const scored = scoreMessage(m, body, job);
      if (scored.score < 40) continue;
      candidates.push({ message: m, body, ...scored, folder: folder.name });
    }
  }
  candidates.sort((a, b) => b.score - a.score || new Date(b.message.date) - new Date(a.message.date));
  const best = candidates[0];
  if (!best) {
    return { profile: { to: [], cc: [], bcc: [], confidence: 0, evidence: { candidates: 0 } }, candidates: [] };
  }

  // Sent copies expose Bcc when Thunderbird has retained it. If not, leave it empty.
  const toFallback = await getHeaderEmails(best.message.id, "to");
  const ccFallback = await getHeaderEmails(best.message.id, "cc");
  const bccFallback = await getHeaderEmails(best.message.id, "bcc");
  const profile = {
    to: unique(emails(best.message.recipients).concat(toFallback)),
    cc: unique(emails(best.message.ccList).concat(ccFallback)),
    bcc: unique(emails(best.message.bccList).concat(bccFallback)),
    confidence: best.score,
    source_subject: best.message.subject || "",
    source_message_id: best.message.headerMessageId || "",
    source_date: best.message.date ? new Date(best.message.date).toISOString() : "",
    evidence: {
      ...best.evidence,
      folder: best.folder,
      candidates: candidates.slice(0, 5).map(c => ({ subject: c.message.subject, score: c.score, date: c.message.date }))
    }
  };
  return { profile, candidates: candidates.slice(0, 5).map(c => ({ subject: c.message.subject, score: c.score, date: c.message.date, folder: c.folder })) };
}

async function api(path, options = {}) {
  const s = await settings();
  const url = new URL(path, s.apiBase).toString();
  const headers = { ...(options.headers || {}), "X-Thunderbird-Token": s.token, "X-Thunderbird-User": s.username };
  const r = await fetch(url, { ...options, headers });
  if (!r.ok) throw new Error(`Bridge HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

async function report(jobId, result) {
  return api(`/api/bridge/job/${jobId}/result`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ result }) });
}

async function reportError(jobId, error) {
  try { await api(`/api/bridge/job/${jobId}/result`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "error", error: String(error) }) }); } catch (_) {}
}

async function findIdentity(email) {
  if (!email) return undefined;
  const target = norm(email);
  const accounts = await messenger.accounts.list(false);
  for (const account of accounts) {
    for (const identity of (account.identities || [])) {
      if (norm(identity.email) === target) return identity.id;
    }
  }
  return undefined;
}

async function sendJob(job) {
  const p = job.payload || {};
  const s = await settings();
  if (!s.autoSend) throw new Error("Auto-send disabled in Thunderbird extension. Enable it in extension Options after reviewing matches.");
  const attachment = p.attachment;
  // Thunderbird's compose.addAttachment API needs a real File object — an
  // object with {name, url, type} (what this used to send) fails schema
  // validation with "Type error for parameter attachment... must contain
  // the required 'id' property" because {url, type} isn't a valid shape
  // for current Thunderbird versions. Build an actual File from the
  // fetched bytes instead.
  let attachmentFile;
  if (attachment?.url) {
    const rr = await fetch(new URL(attachment.url, s.apiBase), { headers: { "X-Thunderbird-Token": s.token, "X-Thunderbird-User": s.username } });
    if (!rr.ok) throw new Error(`Attachment HTTP ${rr.status}`);
    const blob = await rr.blob();
    attachmentFile = new File(
      [blob],
      attachment.name || "Auto_Bill.csv",
      { type: attachment.content_type || blob.type || "text/csv" }
    );
  }
  const identityId = await findIdentity(p.identity_email);
  const tab = await messenger.compose.beginNew(undefined, {
    to: p.to || [], cc: p.cc || [], bcc: p.bcc || [],
    subject: p.subject || "", plainTextBody: p.plain_text || "", body: p.html || undefined,
    isPlainText: false,
    deliveryFormat: "both",
    ...(identityId ? { identityId } : {})
  });
  if (attachmentFile) {
    await messenger.compose.addAttachment(tab.id, { file: attachmentFile });
  }
  const sent = await messenger.compose.sendMessage(tab.id, { mode: "sendNow" });
  return {
    to: p.to || [], cc: p.cc || [], bcc: p.bcc || [],
    headerMessageId: sent?.headerMessageId || "",
    mode: sent?.mode || "sendNow"
  };
}

async function processJobs() {
  const s = await settings();
  const pollAt = Date.now();

  // Previously this silently returned with NO trace anywhere if config was
  // incomplete — the extension looked "dead" with zero clue why. Now we
  // record *why* so the popup can tell the user exactly what's missing.
  if (!s.enabled) {
    await setState({ lastPollAt: pollAt, connected: null, lastError: "Bridge is disabled in Options.", lastCycleSummary: "" });
    return;
  }
  if (!s.token || !s.username) {
    const missing = [!s.username && "App Username", !s.token && "Bridge Token"].filter(Boolean).join(" & ");
    await setState({ lastPollAt: pollAt, connected: false, lastError: `${missing} not set in Options — open Options and fill these in.`, lastCycleSummary: "" });
    return;
  }

  try {
    const data = await api(`/api/bridge/poll?limit=5`);
    const jobs = data.jobs || [];
    let done = 0, failed = 0;
    for (const job of jobs) {
      try {
        if (job.job_type === "match") {
          const result = await bestMatch(job.payload || {});
          await report(job.id, result);
          done++;
          const conf = result?.profile?.confidence ?? 0;
          if (conf > 0) {
            await notify("Auto Bill — Match found", `Confidence ${conf}% · ${(result.profile.to || []).join(", ") || "no recipient"}`);
          } else {
            await notify("Auto Bill — No match", `No historical mail matched job #${job.id}.`);
          }
        } else if (job.job_type === "send") {
          const result = await sendJob(job);
          await report(job.id, result);
          done++;
          await notify("Auto Bill — Mail sent", `To: ${(result.to || []).join(", ") || "(unknown)"}`);
        } else {
          await report(job.id, { ignored: true });
        }
      } catch (e) {
        failed++;
        await reportError(job.id, e);
        await notify("Auto Bill — Job failed", String(e).slice(0, 180));
      }
    }
    const summary = jobs.length ? `${done} done, ${failed} failed (of ${jobs.length})` : "No pending jobs.";
    await setState({ lastPollAt: pollAt, lastOkAt: Date.now(), connected: true, lastError: "", lastJobCount: jobs.length, lastCycleSummary: summary });
  } catch (e) {
    console.warn("Auto Bill bridge poll failed", e);
    await setState({ lastPollAt: pollAt, connected: false, lastError: String(e), lastCycleSummary: "" });
  }
}

async function scheduleAlarm() {
  const s = await settings();
  // Firefox/Thunderbird clamp non-persistent background alarms to a 1-minute
  // minimum — the old hardcoded periodInMinutes: 1/12 (5s) was silently
  // rounded up, so the configured "5 second" poll never actually happened
  // that fast. We now use a real, user-configurable minutes value.
  const minutes = Math.max(1, Number(s.pollMinutes) || 1);
  await messenger.alarms.create("autoBillPoll", { periodInMinutes: minutes });
}

messenger.runtime.onInstalled.addListener(async () => {
  const existing = await messenger.storage.local.get(Object.keys(DEFAULTS));
  await messenger.storage.local.set({ ...DEFAULTS, ...existing });
  await scheduleAlarm();
  processJobs();
});

messenger.runtime.onStartup.addListener(async () => {
  await scheduleAlarm();
  processJobs();
});

messenger.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "autoBillPoll") processJobs();
});

// Also allow popup/options to trigger an immediate cycle, and to read back
// the last-known status without hitting the network again.
messenger.runtime.onMessage.addListener(async message => {
  if (message?.type === "pollNow") { await processJobs(); return { ok: true, state: await getState() }; }
  if (message?.type === "getState") { return await getState(); }
  if (message?.type === "reschedule") { await scheduleAlarm(); return { ok: true }; }
  if (message?.type === "testConnection") {
    try {
      const r = await api("/api/bridge/status");
      await setState({ connected: true, lastOkAt: Date.now(), lastError: "" });
      return r;
    }
    catch (e) {
      const msg = String(e);
      let hint = "";
      if (/NetworkError|Failed to fetch|TypeError/i.test(msg)) {
        hint = " — Web app tak connection nahi bana. Check karein: (1) Flask app chal raha hai kya (python app.py), " +
               "(2) Options mein Web App URL bilkul http://127.0.0.1:5000 hi hai (extra slash/space nahi), " +
               "(3) extension Reload/Load Temporary Add-on dobara karein manifest change ke baad.";
      } else if (/401|unauthorized/i.test(msg)) {
        hint = " — Bridge Token ya Username galat hai. Web app ke /bridge page se sahi Token copy karein.";
      }
      await setState({ connected: false, lastError: msg + hint });
      return { error: msg + hint };
    }
  }
  return undefined;
});
