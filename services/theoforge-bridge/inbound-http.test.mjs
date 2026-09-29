// services/theoforge-bridge/inbound-http.test.mjs
// HTTP contract tests for POST /inbound/reply (Fusion Phase A.1).
//
// Runs server.mjs as a child process with a fully isolated environment:
//   - THEOFORGE_LEADS_DIR   → temp directory (one seeded lead)
//   - BRIDGE_HOST=127.0.0.1 → loopback only
//   - BRIDGE_PORT           → collision-free dynamic port
//   - RESEND_ENV_PATH       → empty temp file (no Resend key → no send possible)
//   - MERCER_PROFILE_DIR    → non-existent temp path (health reports false)
//   - BRIDGE_NOTIFY_DRY_RUN=1 + BRIDGE_INBOX_PATH/BRIDGE_NOTIFY_ENV → temp
//     paths so no real inbox or notify env is touched
//
// Coverage: health, Resend + normalized payload shapes, positive reply →
// exactly one pending draft, duplicate event idempotency, unsubscribe
// suppression without a draft, unknown sender → 404 without writing, malformed
// input → 400 with structured fields, and proof that no Resend request was
// attempted. Child process and temp files are cleaned up afterwards.

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { once } from "node:events";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SERVER_PATH = path.join(__dirname, "server.mjs");

const LEAD_EMAIL = "jane@example.com";       // sender == canonical lead
const AGENT_EMAIL = "sarah@theoforgesolutions.com"; // recipient → draft.from

// ─── Fixture helpers ───────────────────────────────────────────────

const resendEvent = (overrides = {}) => ({
  type: "email.received",
  data: {
    email_id: "resend-msg-001",
    from: "Jane Doe <jane@example.com>",
    to: ["Sarah <sarah@theoforgesolutions.com>"],
    subject: "Re: Your Ops Audit",
    text: "Yes, this looks great!",
    in_reply_to: "out-001",
    references: "out-001",
    ...overrides,
  },
});

const normalizedReply = (overrides = {}) => ({
  from: "jane@example.com",
  to: "sarah@theoforgesolutions.com",
  subject: "Re: Your Ops Audit",
  text: "Yes, this looks great!",
  message_id: "resend-msg-001",
  ...overrides,
});

function seedLead(leadsDir) {
  const lead = {
    schema_version: 1,
    leadId: "lead-jane-001",
    lead_email: LEAD_EMAIL,
    lead_name: "Jane Doe",
    alias: "Sarah",
    pipeline_stage: "prospect",
    channel: "form",
    re_engagement_allowed: true,
    tags: ["form-capture"],
    touch_sequence: [],
    conversation: [],
    updated_at: "2026-08-01T10:00:00.000Z",
  };
  const fp = path.join(leadsDir, "jane.json");
  fs.writeFileSync(fp, JSON.stringify(lead, null, 2) + "\n", { mode: 0o600 });
  return fp;
}

function readLead(leadsDir) {
  return JSON.parse(fs.readFileSync(path.join(leadsDir, "jane.json"), "utf8"));
}

// ─── Child-process scaffolding ─────────────────────────────────────

async function freePort() {
  const srv = net.createServer();
  srv.listen(0, "127.0.0.1");
  await once(srv, "listening");
  const port = srv.address().port;
  srv.close();
  await once(srv, "close");
  return port;
}

async function waitForHealth(baseUrl, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/healthz`);
      if (res.ok) return await res.json();
    } catch (err) {
      lastErr = err;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`bridge did not become healthy: ${lastErr?.message || "timeout"}`);
}

function stopChild(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve();
    child.once("exit", () => resolve());
    try { child.kill("SIGTERM"); } catch (_) { resolve(); }
    // Fallback so the suite never hangs on a wedged child.
    setTimeout(() => { try { child.kill("SIGKILL"); } catch (_) {} }, 3000);
  });
}

let child = null;
let baseUrl = "";
let leadsDir = "";
let tmpRoot = "";
let childOutput = "";

async function postJson(urlPath, payload) {
  const res = await fetch(`${baseUrl}${urlPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: typeof payload === "string" ? payload : JSON.stringify(payload),
  });
  return { status: res.status, body: await res.json() };
}

before(async () => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "theoforge-bridge-http-"));
  leadsDir = path.join(tmpRoot, "leads");
  fs.mkdirSync(leadsDir, { recursive: true, mode: 0o700 });
  seedLead(leadsDir);

  // Isolated config surface: empty Resend env, missing Mercer profile, dry-run
  // notify with temp inbox/notify paths so the real marvin inbox is untouched.
  const resendEnvPath = path.join(tmpRoot, "resend.env");
  fs.writeFileSync(resendEnvPath, "", { mode: 0o600 });
  const mercerDir = path.join(tmpRoot, "mercer-does-not-exist");
  const notifyEnvPath = path.join(tmpRoot, "notify.env");
  fs.writeFileSync(notifyEnvPath, "", { mode: 0o600 });
  const inboxPath = path.join(tmpRoot, "inbox.md");

  const port = await freePort();
  baseUrl = `http://127.0.0.1:${port}`;

  child = spawn(process.execPath, [SERVER_PATH], {
    env: {
      ...process.env,
      THEOFORGE_LEADS_DIR: leadsDir,
      BRIDGE_HOST: "127.0.0.1",
      BRIDGE_PORT: String(port),
      RESEND_ENV_PATH: resendEnvPath,
      MERCER_PROFILE_DIR: mercerDir,
      BRIDGE_NOTIFY_DRY_RUN: "1",
      BRIDGE_NOTIFY_ENV: notifyEnvPath,
      BRIDGE_INBOX_PATH: inboxPath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (c) => { childOutput += c.toString(); });
  child.stderr.on("data", (c) => { childOutput += c.toString(); });

  await waitForHealth(baseUrl);
});

after(async () => {
  if (child) await stopChild(child);
  if (tmpRoot) fs.rmSync(tmpRoot, { recursive: true, force: true });
});

// ─── Tests ─────────────────────────────────────────────────────────

describe("POST /inbound/reply (Fusion Phase A.1)", () => {
  it("serves /healthz on the loopback bridge", async () => {
    const res = await fetch(`${baseUrl}/healthz`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ok, true);
    assert.equal(body.service, "theoforge-bridge");
    assert.equal(body.deps.resend_key_present, false, "empty Resend env must yield no key");
    assert.equal(body.deps.mercer_profile_exists, false, "Mercer profile path must not exist in the isolated fixture");
    assert.match(childOutput, /Mercer:\s+.*mercer-does-not-exist/, "child uses the isolated Mercer path");
    assert.equal(body.host, "127.0.0.1");
  });

  it("accepts a Resend email.received event and creates exactly one pending draft", async () => {
    const { status, body } = await postJson("/inbound/reply", resendEvent());
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.classification, "positive");
    assert.equal(body.idempotent, false);
    assert.equal(body.suppressed, false);
    assert.equal(body.draft_created, true);
    assert.equal(body.draft.status, "draft");
    assert.equal(body.draft.created_by, "system:inbound-reply");
    assert.equal(body.draft.to, LEAD_EMAIL);
    assert.equal(body.draft.from, AGENT_EMAIL);
    assert.equal(body.draft.idempotency_key, "inbound:reply:resend-msg-001");
    assert.equal(body.draft.approved_by, null);
    assert.equal(body.draft.sent_at, null);
    assert.equal(body.draft.resend_id, null);

    const lead = readLead(leadsDir);
    assert.equal(lead.conversation.length, 1);
    assert.equal(lead.conversation[0].channel, "email_in");
    assert.equal(lead.conversation[0].event_key, "resend-msg-001");
    assert.equal(lead.conversation[0].sender, LEAD_EMAIL);
    assert.equal(lead.last_contact_channel, "email_in");
    assert.equal(lead.outreach.drafts.length, 1);
    assert.equal(lead.outreach.drafts[0].status, "draft");
    assert.equal(lead.outreach.drafts[0].created_by, "system:inbound-reply");
  });

  it("is idempotent for a repeated event (normalized shape, same message_id)", async () => {
    const { status, body } = await postJson("/inbound/reply", normalizedReply());
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.idempotent, true);
    assert.equal(body.classification, "positive");
    assert.equal(body.draft_created, false);
    assert.equal(body.draft.draft_id, readLead(leadsDir).outreach.drafts[0].draft_id);

    const lead = readLead(leadsDir);
    assert.equal(lead.conversation.length, 1, "no second conversation entry");
    assert.equal(lead.outreach.drafts.length, 1, "no second draft");
  });

  it("suppresses on unsubscribe and never creates a draft", async () => {
    const { status, body } = await postJson("/inbound/reply", normalizedReply({
      text: "Please unsubscribe me from these emails",
      message_id: "resend-msg-unsub",
    }));
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.classification, "unsubscribe");
    assert.equal(body.suppressed, true);
    assert.equal(body.draft, null);
    assert.equal(body.draft_created, false);

    const lead = readLead(leadsDir);
    assert.equal(lead.suppressed, true);
    assert.equal(lead.re_engagement_allowed, false);
    assert.equal(lead.outreach.suppressed, true);
    assert.equal(lead.conversation.length, 2, "unsubscribe also records the inbound event");
    assert.equal(lead.outreach.drafts.length, 1, "no new draft from unsubscribe");
  });

  it("returns 404 lead_not_found for an unknown sender without writing", async () => {
    const { status, body } = await postJson("/inbound/reply", normalizedReply({
      from: "stranger@example.com",
      to: AGENT_EMAIL,
      text: "Who is this?",
      message_id: "resend-msg-stranger",
    }));
    assert.equal(status, 404);
    assert.equal(body.ok, false);
    assert.equal(body.error, "lead_not_found");
    assert.equal(body.sender, "stranger@example.com");
    assert.equal(fs.existsSync(path.join(leadsDir, "stranger.json")), false, "nothing written");
  });

  it("returns 400 validation_failed with structured fields for malformed input", async () => {
    const invalidSender = await postJson("/inbound/reply", resendEvent({ from: "not-an-email", email_id: "resend-msg-bad-1" }));
    assert.equal(invalidSender.status, 400);
    assert.equal(invalidSender.body.ok, false);
    assert.equal(invalidSender.body.error, "validation_failed");
    assert.equal(invalidSender.body.fields.from, "invalid");

    const emptyText = await postJson("/inbound/reply", resendEvent({ text: "   ", email_id: "resend-msg-bad-2" }));
    assert.equal(emptyText.status, 400);
    assert.equal(emptyText.body.error, "validation_failed");
    assert.equal(emptyText.body.fields.text, "required");

    const badJson = await postJson("/inbound/reply", "{ not json ]");
    assert.equal(badJson.status, 400);
    assert.equal(badJson.body.error, "invalid_json");

    const lead = readLead(leadsDir);
    assert.equal(lead.conversation.length, 2, "nothing persisted for any 400");
    assert.equal(lead.outreach.drafts.length, 1);
  });

  it("never attempts a Resend request from the inbound route", async () => {
    // No API key exists (empty env file) and the route has no path to
    // resendSend; assert the child log carries no evidence of a key load
    // or any api.resend.com call.
    assert.equal(childOutput.includes("key loaded"), false, "no Resend key ever loaded");
    assert.equal(childOutput.includes("api.resend.com"), false, "no Resend HTTP call attempted");
    const lead = readLead(leadsDir);
    const drafts = lead.outreach.drafts || [];
    for (const d of drafts) assert.equal(d.resend_id, null, "draft never sent");
    assert.equal(lead.touch_sequence.length, 0, "no outbound touch recorded");
  });
});