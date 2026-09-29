// services/theoforge-bridge/inbound.test.mjs
// Contract tests for the pure inbound reply state machine (Fusion Phase A).
// Coverage: validation, all five classifications, unsubscribe suppression,
// actionable draft creation, no-send status, duplicate event idempotency,
// deterministic event keys, and immutability of the caller's lead.

import test from "node:test";
import assert from "node:assert/strict";
import {
  applyInboundReply,
  classifyInboundReply,
  REPLY_DRAFT_BODY,
} from "./inbound.mjs";
import { prepareSend } from "./outreach.mjs";

const clock = () => "2026-08-31T18:00:00.000Z";
const idFactory = () => "draft-inbound-001";

function lead(overrides = {}) {
  return {
    leadId: "lead-test-001",
    lead_email: "jane@example.com",
    lead_name: "Jane Doe",
    pipeline_stage: "prospect",
    re_engagement_allowed: true,
    conversation: [],
    touch_sequence: [],
    updated_at: "2026-08-01T10:00:00.000Z",
    ...overrides,
  };
}

function reply(overrides = {}) {
  return {
    from: " JANE@Example.COM ",
    to: "Sarah@TheoForgeSolutions.com",
    subject: "Re: Your Ops Audit",
    text: "Yes, this looks great!",
    message_id: "msg-001",
    in_reply_to: "out-001",
    references: "out-001 msg-000",
    ...overrides,
  };
}

// ── validation ──────────────────────────────────────────────────────────────

test("validation: requires a sender email", () => {
  const result = classifyInboundReply({ from: "", text: "hi" });
  assert.equal(result.ok, false);
  assert.equal(result.error, "validation_failed");
  assert.equal(result.fields.from, "required");
});

test("validation: rejects a malformed sender email", () => {
  const result = classifyInboundReply({ from: "not-an-email", text: "hi" });
  assert.equal(result.ok, false);
  assert.equal(result.fields.from, "invalid");
});

test("validation: requires a non-empty body", () => {
  const result = classifyInboundReply({ from: "jane@example.com", text: "   " });
  assert.equal(result.ok, false);
  assert.equal(result.fields.text, "required");
});

test("validation: applyInboundReply propagates validation failures", () => {
  const result = applyInboundReply(lead(), reply({ from: "", text: "hi" }), { now: clock });
  assert.equal(result.ok, false);
  assert.equal(result.error, "validation_failed");
  assert.deepEqual(result.fields, { from: "required" });
});

test("applyInboundReply: rejects a missing lead without side effects", () => {
  const result = applyInboundReply(null, reply(), { now: clock });
  assert.equal(result.ok, false);
  assert.equal(result.error, "lead_required");
});

// ── classification ──────────────────────────────────────────────────────────

test("classification: positive", () => {
  const result = classifyInboundReply(reply());
  assert.equal(result.ok, true);
  assert.equal(result.classification, "positive");
  assert.equal(result.is_actionable, true);
  assert.equal(result.is_unsubscribe, false);
  assert.equal(result.normalized.from, "jane@example.com");
  assert.equal(result.normalized.to, "sarah@theoforgesolutions.com");
});

test("classification: question (with and without a question mark)", () => {
  assert.equal(classifyInboundReply(reply({ text: "How much does this cost?" })).classification, "question");
  assert.equal(classifyInboundReply(reply({ text: "What are the next steps" })).classification, "question");
});

test("classification: negative", () => {
  const result = classifyInboundReply(reply({ text: "No thanks, not interested." }));
  assert.equal(result.classification, "negative");
  assert.equal(result.is_actionable, false);
});

test("classification: neutral", () => {
  const result = classifyInboundReply(reply({ text: "Thanks for your help." }));
  assert.equal(result.classification, "neutral");
  assert.equal(result.is_actionable, false);
});

test("classification: unsubscribe phrases are detected case-insensitively", () => {
  const phrases = [
    "Please unsubscribe me from these emails",
    "Remove me from your list",
    "Stop emailing me",
    "Do not contact me again",
    "Don't contact me anymore",
    "Please take me off your list",
  ];
  for (const phrase of phrases) {
    const result = classifyInboundReply(reply({ text: phrase, message_id: undefined }));
    assert.equal(result.classification, "unsubscribe", `phrase: ${phrase}`);
    assert.equal(result.is_unsubscribe, true, `phrase: ${phrase}`);
    assert.equal(result.is_actionable, false, `phrase: ${phrase}`);
  }
});

test("classification: unsubscribe wins over positive wording", () => {
  const result = classifyInboundReply(reply({ text: "Yes! Great product, but please unsubscribe me." }));
  assert.equal(result.classification, "unsubscribe");
});

test("classification: deterministic event_key from message_id and from digest", () => {
  const withMid = classifyInboundReply(reply({ message_id: "msg-xyz" }));
  assert.equal(withMid.event_key, "msg-xyz");

  const a = classifyInboundReply(reply({ message_id: undefined }));
  const b = classifyInboundReply(reply({ message_id: undefined }));
  const c = classifyInboundReply(reply({ message_id: undefined, text: "different body" }));
  assert.equal(a.event_key, b.event_key);
  assert.match(a.event_key, /^inb-[0-9a-f]{64}$/);
  assert.notEqual(a.event_key, c.event_key);
});

test("classification: preserves bounded inbound fields", () => {
  const longSubject = "S".repeat(1000);
  const longText = "T".repeat(5000);
  const result = classifyInboundReply(reply({ subject: longSubject, text: longText }));
  assert.equal(result.normalized.subject.length, 500);
  assert.equal(result.normalized.text.length, 2000);
  assert.equal(result.normalized.message_id, "msg-001");
  assert.equal(result.normalized.in_reply_to, "out-001");
  assert.equal(result.normalized.references, "out-001 msg-000");
});

// ── applyInboundReply: conversation + timestamps ────────────────────────────

test("apply: appends exactly one email_in conversation entry and updates contact timestamps", () => {
  const original = lead();
  const result = applyInboundReply(original, reply(), { now: clock, idFactory });

  assert.equal(result.ok, true);
  assert.equal(result.idempotent, false);
  assert.equal(result.lead.conversation.length, 1);
  assert.deepEqual(result.lead.conversation[0], {
    ts: clock(),
    channel: "email_in",
    direction: "in",
    sender: "jane@example.com",
    subject: "Re: Your Ops Audit",
    text: "Yes, this looks great!",
    message_id: "msg-001",
    in_reply_to: "out-001",
    references: "out-001 msg-000",
    event_key: "msg-001",
  });
  assert.equal(result.lead.last_contact_at, clock());
  assert.equal(result.lead.last_contact_channel, "email_in");
  assert.equal(result.lead.updated_at, clock());
});

// ── applyInboundReply: actionable drafts ────────────────────────────────────

test("apply: positive reply creates exactly one pending, unsent reply draft", () => {
  const result = applyInboundReply(lead(), reply(), { now: clock, idFactory });

  assert.equal(result.ok, true);
  assert.equal(result.classification, "positive");
  assert.equal(result.suppressed, false);
  assert.equal(result.lead.outreach.drafts.length, 1);
  const draft = result.lead.outreach.drafts[0];
  assert.equal(draft.draft_id, "draft-inbound-001");
  assert.equal(draft.status, "draft");
  assert.equal(draft.created_by, "system:inbound-reply");
  assert.equal(draft.approved_by, null);
  assert.equal(draft.approved_at, null);
  assert.equal(draft.sent_at, null);
  assert.equal(draft.resend_id, null);
  assert.equal(draft.to, "jane@example.com");
  assert.equal(draft.from, "sarah@theoforgesolutions.com");
  assert.equal(draft.subject, "Re: Your Ops Audit");
  assert.equal(draft.text, REPLY_DRAFT_BODY);
  assert.equal(draft.idempotency_key, "inbound:reply:msg-001");
  assert.equal(result.draft.draft_id, "draft-inbound-001");
});

test("apply: question reply also creates exactly one pending draft", () => {
  const result = applyInboundReply(lead(), reply({ text: "When can we hop on a call?" }), { now: clock, idFactory });
  assert.equal(result.ok, true);
  assert.equal(result.classification, "question");
  assert.equal(result.lead.outreach.drafts.length, 1);
  assert.equal(result.lead.outreach.drafts[0].status, "draft");
});

test("apply: the reply draft can never be sent without approval", () => {
  const result = applyInboundReply(lead(), reply(), { now: clock, idFactory });
  const blocked = prepareSend(result.lead, result.draft.draft_id);
  assert.deepEqual(blocked, { ok: false, error: "approval_required" });
});

test("apply: negative and neutral replies record the conversation but create no draft", () => {
  for (const text of ["No thanks, not interested.", "Thanks for your help."]) {
    const result = applyInboundReply(lead(), reply({ text, message_id: `mid-${text.length}` }), { now: clock, idFactory });
    assert.equal(result.ok, true, text);
    assert.equal(result.lead.conversation.length, 1, text);
    assert.equal(result.lead.outreach?.drafts ?? 0, 0, text);
    assert.equal(result.draft, null, text);
  }
});

test("apply: actionable reply without a recipient is fail-closed, no draft, nothing persisted", () => {
  const result = applyInboundReply(lead(), reply({ to: undefined, message_id: "msg-norecipient" }), { now: clock, idFactory });
  assert.equal(result.ok, false);
  assert.equal(result.error, "draft_creation_failed");
  assert.equal(result.lead, undefined);
});

// ── applyInboundReply: unsubscribe suppression ──────────────────────────────

test("apply: unsubscribe suppresses the lead and never creates a draft", () => {
  const result = applyInboundReply(lead(), reply({ text: "Please unsubscribe me.", message_id: "msg-unsub" }), { now: clock, idFactory });

  assert.equal(result.ok, true);
  assert.equal(result.classification, "unsubscribe");
  assert.equal(result.suppressed, true);
  assert.equal(result.draft, null);
  assert.equal(result.lead.suppressed, true);
  assert.equal(result.lead.re_engagement_allowed, false);
  assert.equal(result.lead.outreach.suppressed, true);
  assert.equal(result.lead.conversation.length, 1);
  assert.equal(result.lead.last_contact_channel, "email_in");
  assert.equal(result.lead.outreach.drafts?.length ?? 0, 0);
});

// ── applyInboundReply: idempotency + immutability ───────────────────────────

test("apply: re-applying the same message_id is a deterministic no-op", () => {
  const first = applyInboundReply(lead(), reply(), { now: clock, idFactory });
  const second = applyInboundReply(first.lead, reply(), { now: clock, idFactory: () => "draft-should-not-exist" });

  assert.equal(second.ok, true);
  assert.equal(second.idempotent, true);
  assert.equal(second.lead.conversation.length, 1);
  assert.equal(second.lead.outreach.drafts.length, 1);
  assert.equal(second.draft.draft_id, "draft-inbound-001");
  assert.deepEqual(second.lead.conversation, first.lead.conversation);
});

test("apply: digest-based event_key deduplicates identical replies without a message_id", () => {
  const inbound = () => reply({ message_id: undefined });
  const first = applyInboundReply(lead(), inbound(), { now: clock, idFactory });
  const second = applyInboundReply(first.lead, inbound(), { now: clock, idFactory });

  assert.equal(second.ok, true);
  assert.equal(second.idempotent, true);
  assert.equal(second.lead.conversation.length, 1);
  assert.equal(second.lead.outreach.drafts.length, 1);
});

test("apply: re-applying an unsubscribe event stays suppressed and adds nothing", () => {
  const first = applyInboundReply(lead(), reply({ text: "Remove me.", message_id: "msg-unsub-2" }), { now: clock, idFactory });
  const second = applyInboundReply(first.lead, reply({ text: "Remove me.", message_id: "msg-unsub-2" }), { now: clock, idFactory });

  assert.equal(second.idempotent, true);
  assert.equal(second.suppressed, true);
  assert.equal(second.lead.conversation.length, 1);
  assert.equal(second.lead.outreach.drafts?.length ?? 0, 0);
});

test("apply: never mutates the caller's lead object", () => {
  const original = lead();
  const snapshot = structuredClone(original);
  applyInboundReply(original, reply(), { now: clock, idFactory });
  applyInboundReply(original, reply({ text: "Please unsubscribe me." }), { now: clock, idFactory });
  assert.deepEqual(original, snapshot);
});

test("apply: an unsubscribe on an existing suppressed lead also never creates a draft", () => {
  const suppressedLead = lead({ suppressed: true, re_engagement_allowed: false, outreach: { suppressed: true, drafts: [] } });
  const result = applyInboundReply(suppressedLead, reply({ text: "Unsubscribe please.", message_id: "msg-unsub-3" }), { now: clock, idFactory });
  assert.equal(result.ok, true);
  assert.equal(result.suppressed, true);
  assert.equal(result.draft, null);
  assert.equal(result.lead.conversation.length, 1);
});