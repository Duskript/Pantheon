// services/theoforge-bridge/operator.test.mjs
// HTTP contract tests for the Phase B operator surface:
//   - GET /operator, GET /operator/       → operator approval console HTML
//   - GET /outreach/queue                 → pending/failed queue, filtering, limit
//   - POST /outreach/reject               → rejection metadata + persistence
//   - existing approve/send routes stay approval-gated
//
// Runs server.mjs as an isolated child process with a temporary leads
// directory (same pattern as inbound-http.test.mjs): empty Resend env,
// missing Mercer profile, dry-run notify, dynamic loopback port. No real
// leads, credentials, inbox, or Resend calls are ever touched.

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
const OPERATOR_INDEX = path.join(__dirname, "operator", "index.html");

// ─── Fixture helpers ───────────────────────────────────────────────

function draftRecord(overrides = {}) {
  return {
    draft_id: "draft-x",
    status: "draft",
    to: "jane@example.com",
    from: "Sarah from TheoForge <sarah@theoforgesolutions.com>",
    reply_to: "konan@theoforgesolutions.com",
    subject: "Saw you stopped by theoforgesolutions.com",
    text: "Hey — thanks for reaching out.",
    html: null,
    created_by: "system:form-intake",
    created_at: "2026-08-02T12:00:00.000Z",
    idempotency_key: null,
    approved_by: null,
    approved_at: null,
    approval_version: null,
    rejected_by: null,
    rejected_at: null,
    rejection_reason: null,
    sent_at: null,
    resend_id: null,
    provider_status: null,
    last_error: null,
    ...overrides,
  };
}

function seedLeads(leadsDir) {
  // Jane: canonical lead with inbound email context + two pending drafts.
  const jane = {
    schema_version: 1,
    leadId: "lead-jane-001",
    lead_email: "jane@example.com",
    lead_name: "Jane Doe",
    alias: "Sarah",
    pipeline_stage: "prospect",
    re_engagement_allowed: true,
    touch_sequence: [],
    conversation: [
      { ts: "2026-08-02T10:00:00.000Z", channel: "form", direction: "in", subject: null, text: "Form submission: ops audit", alias: null, session_id: null },
      { ts: "2026-08-02T11:00:00.000Z", channel: "email_in", direction: "in", sender: "jane@example.com", subject: "Re: Your Ops Audit", text: "Yes, this looks great!", message_id: "resend-msg-001", in_reply_to: "out-001", references: "out-001", event_key: "resend-msg-001" },
    ],
    outreach: {
      version: 1,
      drafts: [
        draftRecord({
          draft_id: "d-jane-failed",
          status: "send_failed",
          created_at: "2026-08-02T09:00:00.000Z",
          last_error: "invalid from address",
          provider_status: 422,
        }),
        draftRecord({
          draft_id: "d-jane-draft",
          status: "draft",
          created_at: "2026-08-02T12:00:00.000Z",
        }),
      ],
    },
    updated_at: "2026-08-02T12:00:00.000Z",
  };
  fs.writeFileSync(path.join(leadsDir, "jane.json"), JSON.stringify(jane, null, 2) + "\n", { mode: 0o600 });

  // Carol: newest pending draft, plus sent and approved drafts.
  const carol = {
    schema_version: 1,
    leadId: "lead-carol-001",
    lead_email: "carol@example.com",
    lead_name: "Carol Smith",
    alias: "Maria",
    pipeline_stage: "qualified",
    re_engagement_allowed: true,
    touch_sequence: [],
    conversation: [],
    outreach: {
      version: 1,
      drafts: [
        draftRecord({
          draft_id: "d-carol-sent",
          status: "sent",
          created_at: "2026-08-01T00:00:00.000Z",
          sent_at: "2026-08-01T00:05:00.000Z",
          resend_id: "re_999",
          provider_status: 200,
        }),
        draftRecord({
          draft_id: "d-carol-approved",
          status: "approved",
          created_at: "2026-08-01T12:00:00.000Z",
          approved_by: "operator-bob",
          approved_at: "2026-08-01T13:00:00.000Z",
          approval_version: "outreach-v1",
        }),
        draftRecord({
          draft_id: "d-carol-draft",
          status: "draft",
          to: "carol@example.com",
          created_at: "2026-08-03T08:00:00.000Z",
        }),
      ],
    },
    updated_at: "2026-08-03T08:00:00.000Z",
  };
  fs.writeFileSync(path.join(leadsDir, "carol.json"), JSON.stringify(carol, null, 2) + "\n", { mode: 0o600 });

  // Bob: malformed lead file — must never crash a queue read.
  fs.writeFileSync(path.join(leadsDir, "bob.json"), "this is not json {{{", { mode: 0o600 });
}

function readLead(leadsDir, name) {
  return JSON.parse(fs.readFileSync(path.join(leadsDir, `${name}.json`), "utf8"));
}

// ─── Child-process scaffolding (inbound-http.test.mjs pattern) ────

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
    setTimeout(() => { try { child.kill("SIGKILL"); } catch (_) {} }, 3000);
  });
}

let child = null;
let baseUrl = "";
let leadsDir = "";
let tmpRoot = "";
let childOutput = "";

async function getJson(urlPath) {
  const res = await fetch(`${baseUrl}${urlPath}`);
  return { status: res.status, body: await res.json() };
}

async function postJson(urlPath, payload) {
  const res = await fetch(`${baseUrl}${urlPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: typeof payload === "string" ? payload : JSON.stringify(payload),
  });
  return { status: res.status, body: await res.json() };
}

before(async () => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "theoforge-operator-http-"));
  leadsDir = path.join(tmpRoot, "leads");
  fs.mkdirSync(leadsDir, { recursive: true, mode: 0o700 });
  seedLeads(leadsDir);

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

describe("Phase B operator surface (tailnet-only bridge)", () => {
  it("serves the operator console at /operator and /operator/", async () => {
    for (const p of ["/operator", "/operator/"]) {
      const res = await fetch(`${baseUrl}${p}`);
      assert.equal(res.status, 200);
      assert.match(res.headers.get("content-type") || "", /text\/html/);
      const html = await res.text();
      assert.match(html, /<title>TheoForge Approval Queue<\/title>/);
      assert.match(html, /Tailnet-only operator surface — no public campaign sending\./);
      assert.match(html, /\/outreach\/queue\?status=draft,send_failed/);
    }
    assert.ok(fs.existsSync(OPERATOR_INDEX), "operator/index.html exists beside server.mjs");
  });

  it("returns 404 JSON for paths outside the operator static file", async () => {
    const { status, body } = await getJson("/operator/nope");
    assert.equal(status, 404);
    assert.equal(body.error, "not_found");
  });

  it("returns the expected sorted pending queue with full draft fields", async () => {
    const { status, body } = await getJson("/outreach/queue");
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.count, 3);
    const ids = body.items.map((i) => i.draft.draft_id);
    assert.deepEqual(ids, ["d-carol-draft", "d-jane-draft", "d-jane-failed"], "newest draft first");

    const carol = body.items[0];
    assert.equal(carol.lead_email, "carol@example.com");
    assert.equal(carol.lead_name, "Carol Smith");
    assert.equal(carol.leadId, "lead-carol-001");
    assert.equal(carol.pipeline_stage, "qualified");
    assert.deepEqual(carol.latest_inbound, {}, "no inbound email context yet");
    assert.equal(carol.draft.to, "carol@example.com");
    assert.equal(carol.draft.status, "draft");

    const jane = body.items[1];
    assert.equal(jane.lead_email, "jane@example.com");
    assert.equal(jane.lead_name, "Jane Doe");
    assert.equal(jane.pipeline_stage, "prospect");
    assert.equal(jane.latest_inbound.channel, "email_in");
    assert.equal(jane.latest_inbound.subject, "Re: Your Ops Audit");
    assert.equal(jane.latest_inbound.text, "Yes, this looks great!");
    assert.equal(jane.draft.draft_id, "d-jane-draft");
    assert.equal(jane.draft.subject, "Saw you stopped by theoforgesolutions.com");
    assert.equal(jane.draft.text, "Hey — thanks for reaching out.");
    assert.equal(jane.draft.from, "Sarah from TheoForge <sarah@theoforgesolutions.com>");
    assert.equal(jane.draft.created_at, "2026-08-02T12:00:00.000Z");

    assert.equal(body.items[2].draft.status, "send_failed");
    assert.equal(body.items[2].draft.last_error, "invalid from address", "operator sees transient error");
  });

  it("filters by status and defaults to draft,send_failed", async () => {
    const onlyDraft = await getJson("/outreach/queue?status=draft");
    assert.equal(onlyDraft.status, 200);
    assert.deepEqual(onlyDraft.body.items.map((i) => i.draft.draft_id), ["d-carol-draft", "d-jane-draft"]);

    const onlySent = await getJson("/outreach/queue?status=sent");
    assert.equal(onlySent.body.count, 1);
    assert.equal(onlySent.body.items[0].draft.draft_id, "d-carol-sent");

    const multi = await getJson("/outreach/queue?status=draft,send_failed,sent");
    assert.equal(multi.body.count, 4);
    assert.deepEqual(multi.body.items.map((i) => i.draft.draft_id), ["d-carol-draft", "d-jane-draft", "d-jane-failed", "d-carol-sent"]);
  });

  it("applies limit with a hard maximum of 500", async () => {
    const one = await getJson("/outreach/queue?limit=1");
    assert.equal(one.status, 200);
    assert.equal(one.body.count, 1);
    assert.equal(one.body.items[0].draft.draft_id, "d-carol-draft");

    const big = await getJson("/outreach/queue?limit=500");
    assert.equal(big.status, 200);
    assert.equal(big.body.count, 3);

    const zero = await getJson("/outreach/queue?limit=0");
    assert.equal(zero.status, 400);
    assert.equal(zero.body.error, "invalid_limit");

    const nonsense = await getJson("/outreach/queue?limit=abc");
    assert.equal(nonsense.status, 400);
    assert.equal(nonsense.body.error, "invalid_limit");

    const over = await getJson("/outreach/queue?limit=501");
    assert.equal(over.status, 400);
    assert.equal(over.body.error, "invalid_limit");
  });

  it("returns 400 for unknown or empty requested statuses", async () => {
    const unknown = await getJson("/outreach/queue?status=bogus");
    assert.equal(unknown.status, 400);
    assert.equal(unknown.body.error, "invalid_status");

    const empty = await getJson("/outreach/queue?status=");
    assert.equal(empty.status, 400);
    assert.equal(empty.body.error, "invalid_status");

    const mixed = await getJson("/outreach/queue?status=draft,bogus");
    assert.equal(mixed.status, 400);
    assert.equal(mixed.body.error, "invalid_status");
  });

  it("ignores malformed lead files without crashing the queue read", async () => {
    assert.equal(fs.existsSync(path.join(leadsDir, "bob.json")), true, "malformed fixture present");
    const { status, body } = await getJson("/outreach/queue");
    assert.equal(status, 200);
    assert.equal(body.count, 3, "bob.json contributes nothing and breaks nothing");
  });

  it("records rejection metadata and persists it atomically", async () => {
    const { status, body } = await postJson("/outreach/reject", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
      rejected_by: "operator-alice",
      rejection_reason: "Duplicate follow-up; prospect already booked a call.",
    });
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.idempotent, false);
    assert.equal(body.draft.status, "rejected");
    assert.equal(body.draft.rejected_by, "operator-alice");
    assert.ok(body.draft.rejected_at, "rejected_at is recorded");
    assert.ok(!Number.isNaN(Date.parse(body.draft.rejected_at)), "rejected_at is a real timestamp");
    assert.equal(body.draft.rejection_reason, "Duplicate follow-up; prospect already booked a call.");

    const persisted = readLead(leadsDir, "jane");
    const saved = persisted.outreach.drafts.find((d) => d.draft_id === "d-jane-draft");
    assert.equal(saved.status, "rejected");
    assert.equal(saved.rejected_by, "operator-alice");
    assert.equal(saved.rejection_reason, "Duplicate follow-up; prospect already booked a call.");
    assert.equal(saved.approved_by, null, "approval metadata untouched");
    assert.equal(saved.sent_at, null);
  });

  it("is idempotent for the same rejection and rejects changed reasons", async () => {
    const repeat = await postJson("/outreach/reject", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
      rejected_by: "operator-alice",
      rejection_reason: "Duplicate follow-up; prospect already booked a call.",
    });
    assert.equal(repeat.status, 200);
    assert.equal(repeat.body.ok, true);
    assert.equal(repeat.body.idempotent, true);
    assert.equal(repeat.body.draft.status, "rejected");

    const changed = await postJson("/outreach/reject", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
      rejected_by: "operator-alice",
      rejection_reason: "A different reason.",
    });
    assert.equal(changed.status, 400);
    assert.equal(changed.body.error, "draft_not_rejectable");

    const noReason = await postJson("/outreach/reject", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
      rejected_by: "operator-alice",
    });
    assert.equal(noReason.status, 400);
    assert.equal(noReason.body.error, "rejection_metadata_required");
  });

  it("rejects a send_failed draft and clears only last_error", async () => {
    const { status, body } = await postJson("/outreach/reject", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-failed",
      rejected_by: "operator-alice",
      rejection_reason: "Recipient address changed; do not retry.",
    });
    assert.equal(status, 200);
    assert.equal(body.draft.status, "rejected");
    assert.equal(body.draft.last_error, null, "transient error cleared");
    assert.equal(body.draft.provider_status, 422, "provider send history preserved");
  });

  it("rejects unknown leads and drafts without writing", async () => {
    const noLead = await postJson("/outreach/reject", {
      lead_email: "ghost@example.com",
      draft_id: "d-x",
      rejected_by: "operator-alice",
      rejection_reason: "nope",
    });
    assert.equal(noLead.status, 404);
    assert.equal(noLead.body.error, "lead_not_found");
    assert.equal(fs.existsSync(path.join(leadsDir, "ghost.json")), false);

    const noDraft = await postJson("/outreach/reject", {
      lead_email: "carol@example.com",
      draft_id: "d-nope",
      rejected_by: "operator-alice",
      rejection_reason: "nope",
    });
    assert.equal(noDraft.status, 404);
    assert.equal(noDraft.body.error, "draft_not_found");
  });

  it("a rejected draft can no longer be approved or sent", async () => {
    const approve = await postJson("/outreach/approve", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
      approved_by: "operator-alice",
      approval_version: "outreach-v1",
    });
    assert.equal(approve.status, 400);
    assert.equal(approve.body.error, "draft_not_approvable");

    const send = await postJson("/outreach/send", {
      lead_email: "jane@example.com",
      draft_id: "d-jane-draft",
    });
    assert.equal(send.status, 409);
    assert.equal(send.body.error, "approval_required");
  });

  it("existing approval and send routes remain approval-gated", async () => {
    // Draft must not reach the provider without approval.
    const unapprovedSend = await postJson("/outreach/send", {
      lead_email: "carol@example.com",
      draft_id: "d-carol-draft",
    });
    assert.equal(unapprovedSend.status, 409);
    assert.equal(unapprovedSend.body.error, "approval_required");

    // Approve still requires complete approval metadata.
    const missingMetadata = await postJson("/outreach/approve", {
      lead_email: "carol@example.com",
      draft_id: "d-carol-draft",
      approved_by: "operator-alice",
    });
    assert.equal(missingMetadata.status, 400);
    assert.equal(missingMetadata.body.error, "approval_metadata_required");

    // After explicit approval the send route proceeds (and, with an empty
    // Resend env in this isolated fixture, fails at the provider boundary
    // rather than claiming success).
    const approved = await postJson("/outreach/approve", {
      lead_email: "carol@example.com",
      draft_id: "d-carol-draft",
      approved_by: "operator-alice",
      approval_version: "outreach-v1",
    });
    assert.equal(approved.status, 200);
    assert.equal(approved.body.draft.status, "approved");

    const sentAttempt = await postJson("/outreach/send", {
      lead_email: "carol@example.com",
      draft_id: "d-carol-draft",
    });
    assert.equal(sentAttempt.status, 502);
    assert.equal(sentAttempt.body.error, "send_failed");
    const persisted = readLead(leadsDir, "carol");
    const afterSend = persisted.outreach.drafts.find((d) => d.draft_id === "d-carol-draft");
    assert.equal(afterSend.status, "send_failed");
    assert.equal(afterSend.resend_id, null, "no provider id claimed");
  });

  it("never makes a Resend request during queue or reject tests", async () => {
    // Empty env file means getResendKey can never succeed; the child log must
    // show no key load and no api.resend.com call across the whole suite.
    assert.equal(childOutput.includes("key loaded"), false, "no Resend key ever loaded");
    assert.equal(childOutput.includes("api.resend.com"), false, "no Resend HTTP call attempted");
    const carol = readLead(leadsDir, "carol");
    assert.equal(carol.touch_sequence.length, 0, "no outbound touch recorded");
    const jane = readLead(leadsDir, "jane");
    for (const d of jane.outreach.drafts) {
      assert.equal(d.resend_id, null, "jane drafts never sent");
    }
  });
});