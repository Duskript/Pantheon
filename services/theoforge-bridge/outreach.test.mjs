import test from "node:test";
import assert from "node:assert/strict";
import {
  approveDraftRecord,
  createDraftRecord,
  prepareSend,
  recordSendResult,
  rejectDraftRecord,
} from "./outreach.mjs";

const clock = () => "2026-08-31T18:00:00.000Z";
const idFactory = () => "draft-test-001";

function lead(overrides = {}) {
  return {
    leadId: "lead-test-001",
    lead_email: "jane@example.com",
    lead_name: "Jane Doe",
    pipeline_stage: "prospect",
    re_engagement_allowed: true,
    conversation: [],
    touch_sequence: [],
    ...overrides,
  };
}

function draftInput(overrides = {}) {
  return {
    to: "jane@example.com",
    from: "Sarah from TheoForge <sarah@theoforgesolutions.com>",
    reply_to: "konan@theoforgesolutions.com",
    subject: "Saw you stopped by theoforgesolutions.com",
    text: "Hey Jane — thanks for reaching out.",
    created_by: "system:form-intake",
    ...overrides,
  };
}

test("creates a pending draft without marking it sent", () => {
  const result = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });

  assert.equal(result.ok, true);
  assert.equal(result.draft.draft_id, "draft-test-001");
  assert.equal(result.draft.status, "draft");
  assert.equal(result.draft.approved_by, null);
  assert.equal(result.draft.sent_at, null);
  assert.equal(result.lead.outreach.drafts.length, 1);
  assert.equal(result.lead.conversation.length, 0);
});

test("reuses a draft for the same idempotency key", () => {
  const first = createDraftRecord(
    lead(),
    draftInput({ idempotency_key: "form:jane@example.com" }),
    { now: clock, idFactory },
  );
  const second = createDraftRecord(
    first.lead,
    draftInput({ idempotency_key: "form:jane@example.com", subject: "changed" }),
    { now: clock, idFactory: () => "draft-test-002" },
  );

  assert.equal(second.ok, true);
  assert.equal(second.idempotent, true);
  assert.equal(second.draft.draft_id, "draft-test-001");
  assert.equal(second.lead.outreach.drafts.length, 1);
  assert.equal(second.draft.subject, "Saw you stopped by theoforgesolutions.com");
});

test("requires explicit approval metadata before a draft can be sent", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const blocked = prepareSend(created.lead, created.draft.draft_id);

  assert.deepEqual(blocked, { ok: false, error: "approval_required" });
});

test("approves a draft and exposes only the approved send payload", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    {
      draft_id: created.draft.draft_id,
      approved_by: "konan",
      approval_version: "outreach-v1",
    },
    { now: clock },
  );
  const prepared = prepareSend(approved.lead, created.draft.draft_id);

  assert.equal(approved.ok, true);
  assert.equal(approved.draft.status, "approved");
  assert.equal(approved.draft.approved_by, "konan");
  assert.equal(prepared.ok, true);
  assert.deepEqual(prepared.payload, {
    from: draftInput().from,
    to: ["jane@example.com"],
    subject: draftInput().subject,
    text: draftInput().text,
    reply_to: draftInput().reply_to,
  });
});

test("suppressed leads cannot send even an approved draft", () => {
  const created = createDraftRecord(
    lead({ re_engagement_allowed: false }),
    draftInput(),
    { now: clock, idFactory },
  );
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );

  assert.deepEqual(prepareSend(approved.lead, created.draft.draft_id), {
    ok: false,
    error: "lead_suppressed",
  });
});

test("records provider success once and makes retries idempotent", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );
  const sent = recordSendResult(approved.lead, created.draft.draft_id, {
    ok: true,
    status: 200,
    data: { id: "re_123" },
  }, { now: clock });
  const retry = prepareSend(sent.lead, created.draft.draft_id);

  assert.equal(sent.ok, true);
  assert.equal(sent.draft.status, "sent");
  assert.equal(sent.draft.resend_id, "re_123");
  assert.equal(sent.lead.conversation[0].channel, "email_out");
  assert.equal(sent.lead.touch_sequence[0].resend_id, "re_123");
  assert.deepEqual(retry, { ok: true, idempotent: true, resend_id: "re_123" });
});

test("records provider failure without pretending the email was sent", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );
  const failed = recordSendResult(approved.lead, created.draft.draft_id, {
    ok: false,
    status: 422,
    data: { message: "invalid from address" },
  }, { now: clock });

  assert.equal(failed.ok, false);
  assert.equal(failed.draft.status, "send_failed");
  assert.equal(failed.draft.sent_at, null);
  assert.equal(failed.lead.conversation.length, 0);
});

// ─── Rejection (Fusion Phase B) ─────────────────────────────────────

const rejectInput = (overrides = {}) => ({
  draft_id: "draft-test-001",
  rejected_by: "operator-alice",
  rejection_reason: "Duplicate follow-up; prospect already booked a call.",
  ...overrides,
});

function pendingLead() {
  return createDraftRecord(lead(), draftInput(), { now: clock, idFactory }).lead;
}

test("requires draft_id, rejected_by, and rejection_reason before rejecting", () => {
  const result = rejectDraftRecord(pendingLead(), {});

  assert.equal(result.ok, false);
  assert.equal(result.error, "rejection_metadata_required");
  assert.deepEqual(result.fields, {
    draft_id: "required",
    rejected_by: "required",
    rejection_reason: "required",
  });
});

test("bounds rejected_by to 200 chars and rejection_reason to 500 chars", () => {
  const result = rejectDraftRecord(pendingLead(), rejectInput({
    rejected_by: "o".repeat(201),
    rejection_reason: "r".repeat(501),
  }));

  assert.equal(result.ok, false);
  assert.equal(result.error, "validation_failed");
  assert.deepEqual(result.fields, {
    rejected_by: "too_long",
    rejection_reason: "too_long",
  });
});

test("rejects a pending draft and records rejection metadata", () => {
  const result = rejectDraftRecord(pendingLead(), rejectInput(), { now: clock });

  assert.equal(result.ok, true);
  assert.equal(result.idempotent, false);
  assert.equal(result.draft.status, "rejected");
  assert.equal(result.draft.rejected_by, "operator-alice");
  assert.equal(result.draft.rejected_at, clock());
  assert.equal(result.draft.rejection_reason, "Duplicate follow-up; prospect already booked a call.");
  assert.equal(result.draft.approved_by, null);
  assert.equal(result.draft.sent_at, null);
  assert.equal(result.draft.resend_id, null);
});

test("rejects a send_failed draft and clears only the transient last_error", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );
  const failed = recordSendResult(approved.lead, created.draft.draft_id, {
    ok: false,
    status: 422,
    data: { message: "invalid from address" },
  }, { now: clock });
  assert.equal(failed.draft.last_error, "invalid from address");

  const rejected = rejectDraftRecord(failed.lead, rejectInput({
    draft_id: created.draft.draft_id,
    rejected_by: "operator-alice",
    rejection_reason: "Recipient address changed; do not retry.",
  }), { now: clock });

  assert.equal(rejected.ok, true);
  assert.equal(rejected.draft.status, "rejected");
  assert.equal(rejected.draft.last_error, null, "transient last_error cleared");
  assert.equal(rejected.draft.provider_status, 422, "provider send history preserved");
  assert.equal(rejected.draft.resend_id, null);
  assert.equal(rejected.lead.conversation.length, 0, "no outbound history invented");
});

test("repeating the exact same rejection is idempotent and leaves the draft unchanged", () => {
  const leadWithDraft = pendingLead();
  const first = rejectDraftRecord(leadWithDraft, rejectInput(), { now: clock });
  const snapshot = structuredClone(first.draft);

  const second = rejectDraftRecord(first.lead, rejectInput(), { now: clock });

  assert.equal(second.ok, true);
  assert.equal(second.idempotent, true);
  assert.deepEqual(second.draft, snapshot, "existing rejected draft unchanged");
});

test("rejection never mutates the caller's lead", () => {
  const original = pendingLead();
  const snapshot = structuredClone(original);

  const result = rejectDraftRecord(original, rejectInput(), { now: clock });

  assert.equal(result.ok, true);
  assert.equal(original.outreach.drafts[0].status, "draft", "caller's draft still pending");
  assert.deepEqual(original, snapshot);
});

test("guards rejection: sent drafts are already_sent", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );
  const sent = recordSendResult(approved.lead, created.draft.draft_id, {
    ok: true,
    status: 200,
    data: { id: "re_123" },
  }, { now: clock });

  const result = rejectDraftRecord(sent.lead, rejectInput(), { now: clock });

  assert.equal(result.ok, false);
  assert.equal(result.error, "already_sent");
  assert.equal(result.draft.status, "sent");
  assert.equal(result.draft.resend_id, "re_123", "provider send history untouched");
});

test("guards rejection: approved drafts are draft_not_rejectable", () => {
  const created = createDraftRecord(lead(), draftInput(), { now: clock, idFactory });
  const approved = approveDraftRecord(
    created.lead,
    { draft_id: created.draft.draft_id, approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );

  const result = rejectDraftRecord(approved.lead, rejectInput(), { now: clock });

  assert.equal(result.ok, false);
  assert.equal(result.error, "draft_not_rejectable");
  assert.equal(result.draft.status, "approved");
});

test("guards rejection: a differently-reasoned repeat of an existing rejection is draft_not_rejectable", () => {
  const first = rejectDraftRecord(pendingLead(), rejectInput(), { now: clock });

  const result = rejectDraftRecord(first.lead, rejectInput({
    rejection_reason: "A different reason.",
  }), { now: clock });

  assert.equal(result.ok, false);
  assert.equal(result.error, "draft_not_rejectable");
  assert.equal(result.draft.status, "rejected");
});

test("guards rejection: unknown draft is draft_not_found", () => {
  const result = rejectDraftRecord(pendingLead(), rejectInput({ draft_id: "draft-nope" }));

  assert.equal(result.ok, false);
  assert.equal(result.error, "draft_not_found");
});

test("a rejected draft can no longer be approved or sent", () => {
  const rejected = rejectDraftRecord(pendingLead(), rejectInput(), { now: clock });

  const approveAttempt = approveDraftRecord(
    rejected.lead,
    { draft_id: "draft-test-001", approved_by: "konan", approval_version: "outreach-v1" },
    { now: clock },
  );
  assert.equal(approveAttempt.ok, false);
  assert.equal(approveAttempt.error, "draft_not_approvable");

  const sendAttempt = prepareSend(rejected.lead, "draft-test-001");
  assert.deepEqual(sendAttempt, { ok: false, error: "approval_required" });
});
