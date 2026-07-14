/* TheoForge Bridge — Pantheon side of the relay7→Pantheon trust boundary.
 *
 * One Node service, single port, Tailscale-only binding. Exposes:
 *
 *   GET  /healthz              → { ok, uptime_s, deps: {...} }
 *   POST /ingest/lead          → write ~/athenaeum/Codex-God-Mercer/leads/{slug}.json
 *   POST /ingest/prospect      → same, full unified schema
 *   POST /mercer/chat          → spawn hermes chat with Mercer profile
 *   POST /mercer/reset         → clear session from the map
 *   GET  /mercer/health        → { sessions, uptime_s }
 *   POST /resend/send          → send email via Resend (key from ~/.hermes/profiles/theoforge/.env)
 *   GET  /scout/due-touches    → list leads needing day_before or morning_of touch
 *   GET  /scout/silent-leads   → list leads silent for N+ days (no-show follow-up)
 *   GET  /lead/lookup?email=***  → fetch one lead file by email
 *   POST /lead/append-touch    → append a touch_entry + conversation_entry to a lead
 *   POST /format/touch         → build subject + text for a touch (replaces Code node)
 *
 * Architecture:
 *   - relay7 v9 server → POST /ingest/lead     (capture)
 *   - relay7 v9 server → POST /mercer/chat     (chat widget)
 *   - relay7 v9 server → POST /resend/send     (confirmation email)
 *   - n8n touch-seq   → GET  /scout/due-touches → POST /resend/send → POST /lead/append-touch
 *   - n8n no-show     → GET  /scout/silent-leads → POST /resend/send → POST /lead/append-touch
 *   - n8n inbound     → POST /lead/lookup?email=*** → POST /mercer/chat → POST /resend/send
 *
 * Why a single service:
 *   - One process, one systemd unit, one place to log, one auth surface.
 *   - All endpoints are tied to a single config (paths, env vars, hermes profile).
 *   - Easy to test end-to-end with a single /healthz call.
 *
 * Tailscale binding:
 *   - Binds to 127.0.0.1:4323 by default (loopback) — only reachable on Pantheon
 *   - v9 server on relay7 reaches it via the Tailnet IP 100.68.106.59:4323
 *   - Override with BRIDGE_HOST / BRIDGE_PORT env vars
 *
 * Hard rules:
 *   - No auth: this is tailnet-internal. Don't expose to 0.0.0.0.
 *   - File mode 0o600 for any lead JSON we write.
 *   - No external HTTP egress except: api.resend.com, localhost (hermes chat).
 */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── Config ────────────────────────────────────────────────────────
const PORT = Number(process.env.BRIDGE_PORT || 4323);
const HOST = process.env.BRIDGE_HOST || "127.0.0.1";
const LEADS_DIR = process.env.THEOFORGE_LEADS_DIR
  || path.join(os.homedir(), "athenaeum", "Codex-God-Mercer", "leads");
const RESEND_ENV_PATH = process.env.RESEND_ENV_PATH
  || path.join(os.homedir(), ".hermes", "profiles", "theoforge", ".env");
const MERCER_PROFILE_DIR = process.env.MERCER_PROFILE_DIR
  || path.join(os.homedir(), ".hermes", "profiles", "mercer");

// ─── MIME ──────────────────────────────────────────────────────────
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js":   "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};


// ─── Notification + inbox helpers (added 2026-06-09) ─────────────────
//
// notifyTelegram(level, source, body)  — async fire-and-forget to chat_id 1460056890
// appendInbox(level, source, body)     — synchronous write to ~/pantheon/inbox/marvin.md
// looksLikeLeak(text)                  — permissive gate for prospect-facing chat replies
//
// Cooldown: 5 min per (level, source) pair to prevent spam from a tight error loop.
// Dry-run: BRIDGE_NOTIFY_DRY_RUN=1 makes notifyTelegram log but skip the HTTP call.

const NOTIFY_ENV_PATH = process.env.BRIDGE_NOTIFY_ENV
  || path.join(os.homedir(), ".hermes", "theoforge-bridge", ".env");
const INBOX_PATH = process.env.BRIDGE_INBOX_PATH
  || path.join(os.homedir(), "pantheon", "shared", "active", "marvin-inbox.md");
const NOTIFY_COOLDOWN_MS = 5 * 60 * 1000;
const NOTIFY_DRY_RUN = process.env.BRIDGE_NOTIFY_DRY_RUN === "1";

let _notifyEnvCache = null;
let _cooldowns = new Map();

function loadNotifyEnv() {
  if (_notifyEnvCache) return _notifyEnvCache;
  if (!fs.existsSync(NOTIFY_ENV_PATH)) {
    console.error(`[notify] env file not found at ${NOTIFY_ENV_PATH}`);
    return _notifyEnvCache = {};
  }
  const out = {};
  for (const raw of fs.readFileSync(NOTIFY_ENV_PATH, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const eq = line.indexOf("=");
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim().replace(/^['"]|['"]$/g, "");
  }
  _notifyEnvCache = out;
  return out;
}

function _cooldownOk(level, source) {
  const key = `${level}|${source}`;
  const last = _cooldowns.get(key) || 0;
  if (Date.now() - last < NOTIFY_COOLDOWN_MS) return false;
  _cooldowns.set(key, Date.now());
  return true;
}

function appendInbox(level, source, body) {
  try {
    fs.mkdirSync(path.dirname(INBOX_PATH), { recursive: true, mode: 0o700 });
    const line = `[${new Date().toISOString()}] [${level}] [${source}] ${body}\n`;
    fs.appendFileSync(INBOX_PATH, line, { mode: 0o600 });
  } catch (err) {
    console.error(`[inbox] write failed: ${err.message}`);
  }
}

function notifyTelegram(level, source, body) {
  appendInbox(level, source, body);
  if (NOTIFY_DRY_RUN) {
    console.log(`[notify] DRY_RUN ${level}/${source}: ${body}`);
    return;
  }
  if (!_cooldownOk(level, source)) return;
  const env = loadNotifyEnv();
  const token = env.TELEGRAM_BOT_TOKEN;
  const chatId = env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) {
    console.error(`[notify] missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in ${NOTIFY_ENV_PATH}`);
    return;
  }
  const text = `🔔 [theoforge-bridge] ${level}/${source}\n${body}`;
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, disable_notification: level === "warn" }),
  })
    .then((r) => { if (!r.ok) console.error(`[notify] telegram HTTP ${r.status}`); })
    .catch((err) => console.error(`[notify] telegram fetch failed: ${err.message}`));
}

const LEAK_PATTERNS = [
  { name: "unclosed_code_block", re: /```[^`]*$/m },
  { name: "tool_call_json",      re: /\{[\s\S]*"(?:name|function|arguments)"[\s\S]*\}/ },
  { name: "exception_trace",     re: /(?:^|\s)(?:Error|Traceback|Exception):\s/m },
  { name: "calling_tool",        re: /Calling tool:/i },
  { name: "model_name_leak",     re: /\b(?:opencode|deepseek|hermes|gpt-4|gpt-3\.5|claude|gemini|llama|qwen)\b/i },
];

function looksLikeLeak(text) {
  if (!text) return { leak: false, reason: null };
  for (const { name, re } of LEAK_PATTERNS) {
    if (re.test(text)) return { leak: true, reason: name };
  }
  return { leak: false, reason: null };
}


// ─── Personas (mirror of the v9.2 page's AGENTS list, 2026-06-09) ────
//
// 15 chat-side personas. Each has a name (used for "from" name + alias
// in the lead file + persona voice), an email handle (lowercased name
// at the verified theoforgesolutions.com domain), and a brief opener
// in the persona's voice.
//
// Resend does NOT require the from-address to "exist" — verified domain
// is enough. The reply-to is konan@theoforgesolutions.com so when the
// prospect hits Reply, it lands in the human's real inbox.

const PERSONAS = [
  { name: "Sarah",   opener: "Hey {name} — saw you stopped by the site. Want me to put together that ops audit?" },
  { name: "James",   opener: "Hi {name} — picking up where you left off. Got a few questions that'll help me put something useful together for you." },
  { name: "Maria",   opener: "Hi {name} — thanks for reaching out. I saw your note and I'm pulling together a quick read on your situation." },
  { name: "David",   opener: "Hey {name} — I noticed you stopped by. Mind if I ask a couple of things so I can be useful?" },
  { name: "Emily",   opener: "Hi {name} — I saw you filled out the form. A couple of quick questions and I'll have something for you." },
  { name: "Michael", opener: "Hey {name} — I see you stopped by. Want to walk through what's eating your hours?" },
  { name: "Rachel",  opener: "Hi {name} — I saw your note on the form. I'm pulling together a quick read on the workflow stuff." },
  { name: "Andrew",  opener: "Hey {name} — saw you on the site. Want to spend 5 minutes on the back-and-forth?" },
  { name: "Jessica", opener: "Hi {name} — I see you reached out. Quick questions to start so I can be useful fast." },
  { name: "Thomas",  opener: "Hey {name} — I see you on the form. Want to walk through where the hours are going?" },
  { name: "Lauren",  opener: "Hi {name} — saw you stopped by. Got a few questions that'll help me put something together for you." },
  { name: "Ryan",    opener: "Hey {name} — I see you filled out the form. Mind if I ask a couple of things to start?" },
  { name: "Amanda",  opener: "Hi {name} — I noticed you stopped by. Want me to put together that ops audit?" },
  { name: "Kevin",   opener: "Hey {name} — I see you on the site. Want to walk through what's eating your hours?" },
  { name: "Nicole",  opener: "Hi {name} — I saw your note on the form. Quick questions to start so I can be useful." },
];

const DOMAIN = "theoforgesolutions.com";
const REPLY_TO = process.env.MERCER_REPLY_TO || "konan@theoforgesolutions.com";

function pickPersona() {
  return PERSONAS[Math.floor(Math.random() * PERSONAS.length)];
}

function buildFormIntakeEmail({ persona, lead_name, lead_email, challenge }) {
  const handle = persona.name.toLowerCase();
  const from = `${persona.name} from TheoForge <${handle}@${DOMAIN}>`;
  const subject = "Saw you stopped by theoforgesolutions.com";
  const opener = persona.opener.replace("{name}", lead_name || "there");
  const challengeLine = challenge
    ? `

You wrote: "${challenge.slice(0, 280)}${challenge.length > 280 ? "..." : ""}"
That's helpful. I'll fold that in.`
    : "";
  const text = `${opener}${challengeLine}

If you want to talk it through, just hit reply on this email — I'll get back to you same day.

— ${persona.name}
TheoForge`;
  return { from, subject, text, reply_to: REPLY_TO };
}

// Send form-intake email and append conversation entry. Async fire-and-forget
// (the HTTP response has already returned to the caller by the time this runs,
// since handleIngestLead is synchronous and the caller is the v9 server).
//
// Errors are logged + appended to the lead's conversation so the v9 server
// can see the failure when it polls /lead/lookup.
function sendFormIntakeEmail({ lead_file_path, lead_email, lead_name, challenge, alias, resend_id_field }) {
  const persona = pickPersona();
  const { from, subject, text, reply_to } = buildFormIntakeEmail({ persona, lead_name, lead_email, challenge });
  const key = getResendKey();
  if (!key) {
    console.error(`[form-intake] resend key missing — cannot send intro for ${lead_email}`);
    return;
  }
  fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TheoForge-Bridge/1.0",
    },
    body: JSON.stringify({ from, to: [lead_email], reply_to, subject, text, tags: [{ name: "channel", value: "form_intake" }] }),
  })
    .then((r) => r.json().then((j) => ({ status: r.status, body: j })))
    .then((res) => {
      if (res.status >= 200 && res.status < 300) {
        const resendId = res.body?.id || null;
        console.log(`[form-intake] sent from=${from} to=${lead_email} resend_id=${resendId}`);
        // Append conversation entry to the lead file (best-effort, may have been re-written since).
        try {
          const cur = readLeadFile(lead_email) || {};
          const conv = Array.isArray(cur.conversation) ? cur.conversation : [];
          conv.push({
            channel: "email_out",
            direction: "out",
            subject,
            text: text.slice(0, 1000),
            alias: persona.name,
            session_id: null,
            at: nowIso(),
          });
          const updated = {
            ...cur,
            alias: cur.alias || persona.name,
            pipeline_stage: cur.pipeline_stage === "prospect" ? "engaged" : cur.pipeline_stage,
            channel: cur.channel || "form",
            last_contact_at: nowIso(),
            last_contact_channel: "email_out",
            conversation: conv,
            updated_at: nowIso(),
          };
          atomicWriteJSON(leadFilePath(lead_email), updated);
        } catch (e) {
          console.error(`[form-intake] post-send lead update failed: ${e.message}`);
        }
      } else {
        console.error(`[form-intake] resend send failed: ${res.status} ${JSON.stringify(res.body).slice(0, 300)}`);
      }
    })
    .catch((err) => console.error(`[form-intake] fetch failed: ${err.message}`));
}

// ─── Helpers ───────────────────────────────────────────────────────
function sendJson(res, code, body) {
  const bodyStr = JSON.stringify(body);
  res.writeHead(code, {
    "Content-Type": MIME[".json"],
    "Content-Length": Buffer.byteLength(bodyStr),
  });
  res.end(bodyStr);
}

function readBody(req, maxBytes = 1024 * 256) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on("data", (c) => {
      total += c.length;
      if (total > maxBytes) {
        req.destroy();
        return reject(new Error("body_too_large"));
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function slugFromEmail(email) {
  const local = normalizeEmail(email).split("@")[0] || "anon";
  return local.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "anon";
}

function leadFilePath(email) {
  return path.join(LEADS_DIR, `${slugFromEmail(email)}.json`);
}

function nowIso() { return new Date().toISOString(); }
function epochSeconds() { return Math.floor(Date.now() / 1000); }

function ensureLeadsDir() {
  fs.mkdirSync(LEADS_DIR, { recursive: true, mode: 0o700 });
}

function atomicWriteJSON(filepath, obj) {
  const tmp = `${filepath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + "\n", { mode: 0o600 });
  fs.renameSync(tmp, filepath);
  try { fs.chmodSync(filepath, 0o600); } catch (_) {}
}

function readLeadFile(email) {
  const fp = leadFilePath(email);
  if (!fs.existsSync(fp)) return null;
  try {
    return JSON.parse(fs.readFileSync(fp, "utf8"));
  } catch (err) {
    console.error(`[lead] corrupt file at ${fp}: ${err.message}`);
    notifyTelegram("warn", "corrupt_lead_file", `${fp}: ${err.message}`);
    return null;
  }
}

// ─── Resend (lazy-loaded key from .env) ────────────────────────────
//
// The Resend API key lives in ~/.hermes/profiles/theoforge/.env alongside
// other LLM API keys. We read it lazily on first use, then cache it in
// memory so we don't re-read the file on every email send.
//
// .env format: KEY=VALUE per line, # for comments, optional 'export '
// prefix, optional single or double quotes around the value. Same parser
// as the rest of the Pantheon stack.
let RESEND_KEY_CACHE = null;
function getResendKey() {
  if (RESEND_KEY_CACHE) return RESEND_KEY_CACHE;
  if (!fs.existsSync(RESEND_ENV_PATH)) {
    console.warn(`[resend] env file not found at ${RESEND_ENV_PATH}`);
  notifyTelegram("error", "resend_env_missing", `env path=${RESEND_ENV_PATH} -- email pipeline cannot send`);
    return null;
  }
  const content = fs.readFileSync(RESEND_ENV_PATH, "utf8");
  for (const raw of content.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const eq = line.indexOf("=");
    const key = line.slice(0, eq).trim();
    if (key !== "RESEND_API_KEY") continue;
    const value = line.slice(eq + 1).trim().replace(/^['"]|['"]$/g, "");
    if (value) {
      RESEND_KEY_CACHE = value;
      console.log(`[resend] key loaded from ${RESEND_ENV_PATH} (len=${value.length})`);
      return RESEND_KEY_CACHE;
    }
  }
  console.warn(`[resend] RESEND_API_KEY not found in ${RESEND_ENV_PATH}`);
  notifyTelegram("error", "resend_key_missing", `env path=${RESEND_ENV_PATH} -- Resend API key not set`);
  return null;
}

async function resendSend({ from, to, subject, text, html, reply_to, lead_email, touch_type, alias, lead_name, appt_time_iso }) {
  const key = getResendKey();
  if (!key) return { ok: false, error: "resend_key_missing" };
  const body = {
    from,
    to: Array.isArray(to) ? to : [to],
    subject,
  };
  if (text) body.text = text;
  if (html) body.html = html;
  if (reply_to) body.reply_to = reply_to;
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TheoForge-Bridge/1.0",
    },
    body: JSON.stringify(body),
  });
  const out = await resp.json().catch(() => ({}));
  const result = { ok: resp.ok, status: resp.status, data: out };

  // Optional: if lead_email is provided, append a touch_entry to the
  // lead record so the cron can dedupe next time. This is the n8n
  // workflow's idempotency hook — by having the bridge write the
  // sent_at timestamp after a successful Resend, we avoid the n8n
  // node-graph plumbing that would otherwise be needed to thread
  // lead_email + touch_type through Send -> Log Touch.
  if (result.ok && lead_email) {
    try {
      const touchEntry = {
        type: touch_type || "unspecified",
        sent_at: new Date().toISOString(),
        resend_id: out?.id || null,
        subject: subject || null,
      };
      handleAppendTouch({
        lead_email,
        touch_entry: touchEntry,
        conversation_entry: {
          channel: "email_out",
          direction: "out",
          subject: subject || null,
          text: text || html || null,
          alias: alias || null,
          session_id: null,
        },
      });
      // Echo back the touch_entry so n8n's downstream nodes can read it
      result.touch_entry = touchEntry;
    } catch (err) {
      console.error(`[resend] failed to append touch for ${lead_email}: ${err.message}`);
      notifyTelegram("warn", "touch_log_failed", `lead_email=${lead_email} err=${err.message.slice(0, 200)}`);
      // Don't fail the whole send — the email went out, that's the important part.
    }
  }
  return result;
}

// ─── Mercer (subprocess pool, like server.mjs/lib/mercer.mjs) ─────
const SESSIONS = new Map();
const MAX_SESSIONS = 50;
const TTL_MS = 30 * 60 * 1000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;

function evictStale() {
  const now = Date.now();
  for (const [k, v] of SESSIONS) {
    if (now - v.lastUsedAt > TTL_MS) SESSIONS.delete(k);
  }
  if (SESSIONS.size > MAX_SESSIONS) {
    const sorted = [...SESSIONS.entries()].sort((a, b) => a[1].lastUsedAt - b[1].lastUsedAt);
    const drop = SESSIONS.size - MAX_SESSIONS;
    for (let i = 0; i < drop; i++) SESSIONS.delete(sorted[i][0]);
  }
}
const _sweeper = setInterval(evictStale, SWEEP_INTERVAL_MS);
if (typeof _sweeper.unref === "function") _sweeper.unref();

function callHermes({ query, resumeSid, timeoutMs = 60_000 }) {
  return new Promise((resolve) => {
    // hermes chat CLI: -q takes its value as the next arg, --resume SID
    // takes two args. Order matters — query must follow -q directly.
    const args = ["chat", "-q", query];
    if (resumeSid) args.push("--resume", resumeSid);
    args.push("-Q"); // quiet: suppress banner + tool previews
    // Use opencode-go provider (API key in profile auth pool) for DeepSeek,
    // NOT the bare "deepseek" provider which routes through Codex/ChatGPT
    // and rejects non-OpenAI models. Fix 2026-06-08.
    args.push("-m", "opencode-go/deepseek-v4-flash");
    // CRITICAL: clear HERMES_HOME so the spawned hermes doesn't inherit
    // the parent process's profile home (e.g. marvin's). Set BOTH
    // HERMES_PROFILE=mercer (selects the profile) and
    // HERMES_HOME=<mercer profile dir> (resolves config + auth.json + state.db).
    // Without HERMES_HOME explicitly set, hermes falls back to the parent's
    // home and loads the wrong profile's auth — which routes through
    // Codex/ChatGPT for unknown models instead of opencode-go.
    // Fix 2026-06-08.
    const MERCER_HOME = process.env.MERCER_PROFILE_DIR
      || path.join(os.homedir(), ".hermes", "profiles", "mercer");
    const proc = spawn("hermes", args, {
      env: {
        ...process.env,
        HERMES_PROFILE: "mercer",
        HERMES_HOME: MERCER_HOME,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "", stderr = "";
    proc.stdout.on("data", (c) => { stdout += c.toString(); });
    proc.stderr.on("data", (c) => { stderr += c.toString(); });
    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      resolve({ code: -1, stdout, stderr: stderr + "\n[killed: timeout]" });
    }, timeoutMs);
    proc.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
    proc.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: err.message });
    });
  });
}

function parseHermesOutput({ stdout, stderr }) {
  // session_id is on stderr (line starting with "Session: " or similar)
  let sid = null;
  for (const line of stderr.split("\n")) {
    const m = line.match(/Session(?:\s+ID)?:\s*([a-zA-Z0-9_-]+)/i);
    if (m) { sid = m[1]; break; }
  }
  return { sid, reply: stdout.trim() };
}

function stripToolArtifacts(s) {
  if (!s) return s;
  // Drop leading tool-call artifacts, JSON function_call blocks, emoji banners
  let out = s
    .replace(/^[\s\S]*?(?=```json|```python|>\s|")/, "") // crude: drop everything before quoted reply
    .replace(/🔧.*$/gm, "")
    .replace(/Calling tool:.*$/gm, "")
    .trim();
  // Strip leading system warnings/notices that hermes prints to stdout.
  // The 'Normalized model ...' warning is the most common offender — it
  // leaks the provider/model name to the prospect-facing chat.
  // Other hermes banners also land here (Loading model, Notice, etc.).
  out = out
    .replace(/^\s*(?:⚠\ufe0f?)\s*Normalized model[\s\S]*?for\s*\n\s*\S+\.\s*$/gm, "")
    .replace(/^\s*(?:⚠\ufe0f?|Warning|Notice|Note|Info|Hint|Deprecated)[:\s].*?\n/gm, "")
    .replace(/^\s*Loading model.*$/gm, "")
    .replace(/^\s*Resolving provider.*$/gm, "")
    .replace(/^\s*Provider normalized.*$/gm, "")
    .replace(/^\s*for\s*\n\s*\S+\.\s*$/gm, "")
    .trim();
  return out;
}

function buildWrappedTurn({ turn, alias, message, isFirstEver }) {
  const lines = [
    `[bridge context] turn=${turn} alias=${alias || "theoforge-lead"}`,
    `[identity] You are speaking as ${alias || "theoforge-lead"}, a TheoForge prospect-facing agent. Persona, voice, and Challenger rules from the Mercer profile apply unchanged. Do not break character. Do not name the LLM, the engine, or the bridge.`,
    `[prospect message] ${message}`,
  ];
  if (isFirstEver) {
    lines.splice(1, 0, "[first turn of session] Open with a brief warm hello using the alias. Do not introduce yourself. Do not list services.");
  }
  return lines.join("\n");
}

async function handleMercerChat(body) {
  const sessionId = String(body?.session_id || "").trim() || randomUUID();
  const alias = String(body?.alias || "").trim() || null;
  const message = String(body?.message || "").trim();
  if (!message) return { ok: false, error: "empty_message" };

  const existing = SESSIONS.get(sessionId);
  const turn = existing ? (existing.turnCount || 0) + 1 : 1;
  const wrapped = existing
    ? buildWrappedTurn({ turn, alias: alias || existing.alias, message })
    : buildWrappedTurn({ turn: 1, alias: alias || "theoforge-lead", message, isFirstEver: true });

  const t0 = Date.now();
  let res;
  try {
    res = await callHermes({ query: wrapped, resumeSid: existing?.hermesSid, timeoutMs: 60_000 });
  } catch (err) {
    notifyTelegram("error", "mercer_unavailable", `session=${sessionId} err=${err.message.slice(0, 200)}`);
    return { ok: false, error: "mercer_unavailable", message: err.message };
  }
  if (res.code !== 0 && existing && /Session not found/i.test(res.stderr)) {
    SESSIONS.delete(sessionId);
    res = await callHermes({
      query: buildWrappedTurn({ turn: 1, alias, message, isFirstEver: true }),
      resumeSid: null,
      timeoutMs: 60_000,
    });
  }
  if (res.code !== 0) {
    notifyTelegram("error", "mercer_failed", `session=${sessionId} code=${res.code} stderr=${res.stderr.slice(0, 300)}`);
    return { ok: false, error: "mercer_failed", code: res.code, stderr: res.stderr.slice(0, 500) };
  }
  const { sid, reply } = parseHermesOutput({ stdout: res.stdout, stderr: res.stderr });
  const clean = stripToolArtifacts(reply);
  const gate = looksLikeLeak(clean);
  if (gate.leak) {
    notifyTelegram("error", "leak_detected", `session=${sessionId} turn=${turn} reason=${gate.reason}\n---blocked reply (first 400 chars)---\n${(clean || "").slice(0, 400)}`);
    return {
      ok: false,
      error: "leak_suppressed",
      reason: gate.reason,
      reply: "Let me think on that for a moment — give me a sec to put it together.",
      session_id: sid,
      elapsed_ms: Date.now() - t0,
    };
  }
  if (!clean) {
    notifyTelegram("warn", "empty_reply", `session=${sessionId} turn=${turn} raw=${(reply || "").slice(0, 200)}`);
    return { ok: false, error: "empty_reply", raw: reply.slice(0, 200) };
  }
  if (sid) {
    SESSIONS.set(sessionId, {
      hermesSid: sid,
      alias: alias || existing?.alias || "theoforge-lead",
      createdAt: existing?.createdAt || Date.now(),
      lastUsedAt: Date.now(),
      turnCount: turn,
    });
  }
  return { ok: true, reply: clean, session_id: sid, elapsed_ms: Date.now() - t0 };
}

function handleMercerReset(body) {
  const sessionId = String(body?.session_id || "").trim();
  if (!sessionId) return { ok: false, error: "missing_session_id" };
  return { ok: true, cleared: SESSIONS.delete(sessionId) };
}

function mercerHealth() {
  evictStale();
  return { ok: true, sessions: SESSIONS.size, max: MAX_SESSIONS, uptime_s: Math.floor(process.uptime()) };
}

// ─── Lead ingest (form capture) ────────────────────────────────────
function handleIngestLead(body) {
  const errors = {};
  const name = String(body?.lead_name || body?.name || "").trim();
  if (name.length < 2) errors.lead_name = "required";
  const email = normalizeEmail(body?.lead_email || body?.email);
  if (!email) errors.lead_email = "required";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.lead_email = "invalid";
  const challenge = body?.challenge != null ? String(body.challenge).trim() : "";
  if (Object.keys(errors).length > 0) {
    return { ok: false, error: "validation_failed", fields: errors };
  }
  ensureLeadsDir();
  const fp = leadFilePath(email);
  const existing = readLeadFile(email) || {};
  const leadId = existing.leadId || `lead-${epochSeconds()}-${randomBytes(3).toString("hex")}`;
  const conversation = Array.isArray(existing.conversation) ? existing.conversation : [];
  conversation.push({
    channel: "form",
    direction: "in",
    subject: null,
    text: challenge ? `Form submission: ${challenge.slice(0, 200)}` : "Form submission (no challenge provided)",
    alias: null,
    session_id: null,
    at: nowIso(),
  });
  const touches = Array.isArray(existing.touch_sequence) ? existing.touch_sequence : [];
  const updated = {
    ...existing,
    schema_version: existing.schema_version || 1,
    leadId,
    lead_email: email,
    lead_name: name,
    alias: existing.alias || "TheoForge Web",
    pipeline_stage: existing.pipeline_stage || "prospect",
    channel: "form",
    tags: Array.from(new Set([...(existing.tags || []), "form-capture"])),
    touch_sequence: touches,
    conversation,
    updated_at: nowIso(),
  };
  atomicWriteJSON(fp, updated);
  // Fire persona-voiced intro email. Async, fire-and-forget — the HTTP
  // response goes back to the caller (v9 server) immediately. The email
  // send is logged + a conversation entry is appended on success.
  sendFormIntakeEmail({
    lead_file_path: fp,
    lead_email: email,
    lead_name: name,
    challenge,
    alias: updated.alias,
  });
  return { ok: true, leadId, pipeline_stage: updated.pipeline_stage, alias: updated.alias };
}

function handleIngestProspect(body) {
  // Full unified schema, used by the v9 chat widget for richer captures
  const email = normalizeEmail(body?.lead_email);
  if (!email) return { ok: false, error: "lead_email_required" };
  ensureLeadsDir();
  const fp = leadFilePath(email);
  const existing = readLeadFile(email) || {};
  const leadId = existing.leadId || body.leadId || `lead-${epochSeconds()}-${randomBytes(3).toString("hex")}`;
  const conv = Array.isArray(existing.conversation) ? existing.conversation : [];
  if (body.conversation_entry) conv.push({ ...body.conversation_entry, at: nowIso() });
  const touches = Array.isArray(existing.touch_sequence) ? existing.touch_sequence : [];
  if (body.touch_entry) touches.push({ ...body.touch_entry, recorded_at: nowIso() });
  const updated = {
    schema_version: existing.schema_version || 1,
    ...existing,
    ...body,
    leadId,
    lead_email: email,
    conversation: conv,
    touch_sequence: touches,
    updated_at: nowIso(),
  };
  // Don't let the caller overwrite the leadId with their own random value
  updated.leadId = leadId;
  atomicWriteJSON(fp, updated);
  if (body?.notify === true || body?.category === "team_request") {
    const summary = [
      `category=${body?.category || "team_request"}`,
      `page=${body?.page || body?.pagePath || "unknown"}`,
      `name=${updated.lead_name || "(missing)"}`,
      `email=${updated.lead_email}`,
      updated.company ? `company=${updated.company}` : null,
      body?.challenge ? `note=${String(body.challenge).slice(0, 300)}` : null,
    ].filter(Boolean).join("\n");
    notifyTelegram("warn", `team_request_${leadId}`, summary);
  }
  // Form-intake email fires only on first form-capture (channel=form and
  // pipeline_stage was prospect before this upsert). Chat-channel updates
  // do NOT fire — the chat widget hits /ingest/prospect on every turn for
  // prospect bookkeeping, and we don't want to spam the prospect.
  const isFormIntake = (body?.channel === "form" || (Array.isArray(body?.tags) && body.tags.includes("form-capture"))) && body?.pipeline_stage !== "engaged" && body?.pipeline_stage !== "appointment" && body?.pipeline_stage !== "close";
  if (isFormIntake) {
    sendFormIntakeEmail({
      lead_file_path: fp,
      lead_email: email,
      lead_name: updated.lead_name || "",
      challenge: body?.challenge || "",
      alias: updated.alias,
    });
  }
  return { ok: true, leadId, pipeline_stage: updated.pipeline_stage, lead_file: fp, email_intake_fired: isFormIntake };
}

// ─── Scout endpoints (for n8n workflows) ───────────────────────────
function scoutDueTouches() {
  ensureLeadsDir();
  const now = new Date();
  const out = [];
  for (const f of fs.readdirSync(LEADS_DIR).filter((x) => x.endsWith(".json"))) {
    const fp = path.join(LEADS_DIR, f);
    let data;
    try { data = JSON.parse(fs.readFileSync(fp, "utf8")); } catch { continue; }
    if (!["appointment", "close"].includes(data.pipeline_stage)) continue;
    if (!data.booked_slot) continue;
    if (data.re_engagement_allowed === false) continue;
    const apptMs = Date.parse(String(data.booked_slot).replace("Z", "+00:00"));
    if (!Number.isFinite(apptMs)) continue;
    const hoursUntil = (apptMs - now.getTime()) / 3_600_000;
    const sentTypes = new Set((data.touch_sequence || []).map((t) => t.type).filter(Boolean));
    const baseItem = {
      lead_file: fp,
      lead_email: data.lead_email,
      lead_name: data.lead_name || "there",
      alias: data.alias || "Sarah",
      appt_time: data.booked_slot,
      hours_until: Math.round(hoursUntil * 10) / 10,
    };
    if (hoursUntil >= 23 && hoursUntil < 26 && !sentTypes.has("day_before")) {
      out.push({ ...baseItem, touch_type: "day_before" });
    }
    if (hoursUntil >= 0 && hoursUntil < 3 && !sentTypes.has("morning_of")) {
      out.push({ ...baseItem, touch_type: "morning_of" });
    }
  }
  return out;
}

function scoutSilentLeads({ silentDays = 7 } = {}) {
  ensureLeadsDir();
  const cutoff = Date.now() - silentDays * 24 * 3600 * 1000;
  const out = [];
  for (const f of fs.readdirSync(LEADS_DIR).filter((x) => x.endsWith(".json"))) {
    const fp = path.join(LEADS_DIR, f);
    let data;
    try { data = JSON.parse(fs.readFileSync(fp, "utf8")); } catch { continue; }
    if (data.re_engagement_allowed === false) continue;
    if (data.pipeline_stage === "departed" || data.pipeline_stage === "customer") continue;
    const lastTouchAt = Math.max(
      Date.parse(data.updated_at || 0) || 0,
      ...((data.touch_sequence || []).map((t) => Date.parse(t.sent_at || t.recorded_at || 0) || 0)),
    );
    if (lastTouchAt < cutoff) {
      out.push({
        lead_file: fp,
        lead_email: data.lead_email,
        lead_name: data.lead_name || "there",
        alias: data.alias || "Sarah",
        pipeline_stage: data.pipeline_stage,
        last_touch_at: new Date(lastTouchAt).toISOString(),
        silent_days: Math.round((Date.now() - lastTouchAt) / (24 * 3600 * 1000)),
      });
    }
  }
  return out;
}

// ─── Lead lookup (used by n8n inbound-reply) ──────────────────────
function handleLeadLookup(url) {
  const email = normalizeEmail(url.searchParams.get("email"));
  if (!email) return { ok: false, error: "email_required" };
  const data = readLeadFile(email);
  if (!data) return { ok: false, error: "not_found", email };
  return { ok: true, lead: data, lead_file: leadFilePath(email) };
}

// ─── Append touch (used by n8n after sending) ────────────────────
function handleAppendTouch(body) {
  const email = normalizeEmail(body?.lead_email);
  if (!email) return { ok: false, error: "lead_email_required" };
  const data = readLeadFile(email);
  if (!data) return { ok: false, error: "not_found", email };
  const touches = Array.isArray(data.touch_sequence) ? data.touch_sequence : [];
  if (body.touch_entry) touches.push({ ...body.touch_entry, recorded_at: nowIso() });
  const conv = Array.isArray(data.conversation) ? data.conversation : [];
  if (body.conversation_entry) conv.push({ ...body.conversation_entry, at: nowIso() });
  const updated = { ...data, touch_sequence: touches, conversation: conv, updated_at: nowIso() };
  atomicWriteJSON(leadFilePath(email), updated);
  return { ok: true, leadId: data.leadId, touches: touches.length, conversation: conv.length };
}

// ─── Format touch (replaces the Code node "Generate Email Content") ─
function formatTouch(body) {
  const lead_name = body?.lead_name || "there";
  const alias = body?.alias || "Sarah";
  const appt_time = body?.appt_time || "";
  const touch_type = body?.touch_type || "generic";
  let dt;
  try { dt = new Date(String(appt_time).replace("Z", "+00:00")); } catch (_) { dt = null; }
  const formattedTime = dt && !isNaN(dt)
    ? dt.toLocaleString("en-US", { weekday: "long", hour: "numeric", minute: "2-digit", hour12: true, timeZone: "UTC" }) + " UTC"
    : appt_time;
  const shortTime = formattedTime.split(" at ").slice(-1)[0] || formattedTime;
  let subject, text;
  if (touch_type === "day_before") {
    subject = `Quick reminder — you're set for tomorrow at ${shortTime}`;
    text = `Hey ${lead_name},\n\nQuick reminder — you're all set to meet with Konan tomorrow at ${formattedTime}. Looking forward to it.\n\nIf anything changes on your end, just reply to this email.\n\nTalk soon,\n${alias}`;
  } else if (touch_type === "morning_of") {
    subject = `See you today at ${shortTime}`;
    text = `Hey ${lead_name},\n\nJust confirming — you're meeting with Konan today at ${formattedTime}. I've filled him in on everything we talked about, so no need to re-explain anything. He'll take good care of you.\n\nTalk soon,\n${alias}`;
  } else if (touch_type === "value_add") {
    subject = "Something that reminded me of your situation";
    text = `Hey ${lead_name},\n\nBeen thinking about what you mentioned regarding your workflow. Came across something that made me think of your setup.\n\nWorth keeping in the back of your mind before the meeting with Konan.\n\nChat soon,\n${alias}`;
  } else {
    subject = "Checking in";
    text = `Hey ${lead_name}, just checking in. See you at ${formattedTime}. — ${alias}`;
  }
  return { ok: true, subject, text, formatted_time: formattedTime };
}

// ─── randomBytes helper ───────────────────────────────────────────
import { randomBytes } from "node:crypto";

// ─── HTTP server ───────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const startedAt = Date.now();
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const pathname = url.pathname;
  const method = req.method || "GET";

  try {
    if (method === "GET" && pathname === "/healthz") {
      const deps = {
        leads_dir_writable: (() => { try { ensureLeadsDir(); fs.accessSync(LEADS_DIR, fs.constants.W_OK); return true; } catch { return false; } })(),
        resend_key_present: !!getResendKey(),
        mercer_profile_exists: fs.existsSync(MERCER_PROFILE_DIR),
      };
      return sendJson(res, 200, {
        ok: true,
        uptime_s: Math.floor(process.uptime()),
        service: "theoforge-bridge",
        version: "1.0.0",
        pid: process.pid,
        host: HOST,
        port: PORT,
        leads_dir: LEADS_DIR,
        deps,
      });
    }

    // POST routes need body
    if (method === "POST") {
      const raw = await readBody(req);
      let body = {};
      try { body = raw ? JSON.parse(raw) : {}; } catch { return sendJson(res, 400, { ok: false, error: "invalid_json" }); }

      if (pathname === "/ingest/lead")        return sendJson(res, 200, handleIngestLead(body));
      if (pathname === "/ingest/prospect")    return sendJson(res, 200, handleIngestProspect(body));
      if (pathname === "/mercer/chat")        return sendJson(res, 200, await handleMercerChat(body));
      if (pathname === "/mercer/reset")       return sendJson(res, 200, handleMercerReset(body));
      if (pathname === "/resend/send")        return sendJson(res, 200, await resendSend(body));
      if (pathname === "/resend/send-and-log") return sendJson(res, 200, await resendSend(body));
      if (pathname === "/lead/append-touch")  return sendJson(res, 200, handleAppendTouch(body));
      if (pathname === "/format/touch")       return sendJson(res, 200, formatTouch(body));
    }

    // GET routes
    if (method === "GET") {
      if (pathname === "/mercer/health")      return sendJson(res, 200, mercerHealth());
      if (pathname === "/scout/due-touches")  return sendJson(res, 200, { ok: true, items: scoutDueTouches() });
      if (pathname === "/scout/silent-leads") {
        const days = Number(url.searchParams.get("days") || 7);
        return sendJson(res, 200, { ok: true, items: scoutSilentLeads({ silentDays: days }) });
      }
      if (pathname === "/lead/lookup")        return sendJson(res, 200, handleLeadLookup(url));
    }

    return sendJson(res, 404, { ok: false, error: "not_found", path: pathname });
  } catch (err) {
    console.error(`[bridge] unhandled ${method} ${pathname}: ${err.message}`);
    notifyTelegram("error", "unhandled", `${method} ${pathname}: ${err.message.slice(0, 300)}`);
    return sendJson(res, 500, { ok: false, error: "server_error", message: err.message });
  } finally {
    console.log(`[bridge] ${method} ${pathname} ${Date.now() - startedAt}ms`);
  }
});

server.listen(PORT, HOST, () => {
  console.log(`TheoForge Bridge`);
  console.log(`  PID:     ${process.pid}`);
  console.log(`  Host:    ${HOST}`);
  console.log(`  Port:    ${PORT}`);
  console.log(`  Leads:   ${LEADS_DIR}`);
  console.log(`  Resend:  ${RESEND_ENV_PATH}`);
  console.log(`  Mercer:  ${MERCER_PROFILE_DIR}`);
  console.log(`  Health:  http://${HOST}:${PORT}/healthz`);
  console.log(`  Endpoints:`);
  console.log(`    POST /ingest/lead, /ingest/prospect`);
  console.log(`    POST /mercer/chat, /mercer/reset, GET /mercer/health`);
  console.log(`    POST /resend/send`);
  console.log(`    GET  /scout/due-touches, /scout/silent-leads`);
  console.log(`    GET  /lead/lookup?email=***`);
  console.log(`    POST /lead/append-touch`);
  console.log(`    POST /format/touch`);
});

process.on("SIGTERM", () => { console.log("SIGTERM"); server.close(() => process.exit(0)); });
process.on("SIGINT",  () => { console.log("SIGINT");  server.close(() => process.exit(0)); });
