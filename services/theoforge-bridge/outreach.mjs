import { randomUUID } from "node:crypto";

const OUTREACH_VERSION = 1;

function clone(value) {
  return structuredClone(value);
}

function nowIso(options = {}) {
  return options.now ? options.now() : new Date().toISOString();
}

function ensureOutreach(lead) {
  const outreach = lead?.outreach && typeof lead.outreach === "object"
    ? clone(lead.outreach)
    : {};
  outreach.version = outreach.version || OUTREACH_VERSION;
  outreach.drafts = Array.isArray(outreach.drafts) ? outreach.drafts : [];
  return outreach;
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function findDraft(lead, draftId) {
  return ensureOutreach(lead).drafts.find((draft) => draft.draft_id === draftId) || null;
}

function createDraftRecord(lead, input, options = {}) {
  if (!lead || !lead.lead_email) {
    return { ok: false, error: "lead_required" };
  }

  const to = normalizeEmail(input?.to || lead.lead_email);
  const fields = {};
  if (!to) fields.to = "required";
  else if (to !== normalizeEmail(lead.lead_email)) fields.to = "must_match_lead";
  if (!String(input?.from || "").trim()) fields.from = "required";
  if (!String(input?.subject || "").trim()) fields.subject = "required";
  else if (String(input.subject).trim().length > 200) fields.subject = "too_long";
  if (!String(input?.text || input?.html || "").trim()) fields.body = "required";
  if (!String(input?.created_by || "").trim()) fields.created_by = "required";
  if (Object.keys(fields).length > 0) {
    return { ok: false, error: "validation_failed", fields };
  }

  const current = ensureOutreach(lead);
  const idempotencyKey = input?.idempotency_key ? String(input.idempotency_key).trim().slice(0, 200) : null;
  if (idempotencyKey) {
    const existing = current.drafts.find((draft) => draft.idempotency_key === idempotencyKey);
    if (existing) {
      return { ok: true, idempotent: true, lead: clone(lead), draft: clone(existing) };
    }
  }

  const idFactory = options.idFactory || (() => `draft-${randomUUID()}`);
  const createdAt = nowIso(options);
  const draft = {
    draft_id: idFactory(),
    status: "draft",
    to,
    from: String(input.from).trim(),
    reply_to: input.reply_to ? String(input.reply_to).trim() : null,
    subject: String(input.subject).trim(),
    text: input.text ? String(input.text) : null,
    html: input.html ? String(input.html) : null,
    created_by: String(input.created_by).trim(),
    created_at: createdAt,
    idempotency_key: idempotencyKey,
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
  };

  const updatedLead = clone(lead);
  updatedLead.outreach = current;
  updatedLead.outreach.drafts.push(draft);
  updatedLead.updated_at = createdAt;
  return { ok: true, lead: updatedLead, draft: clone(draft) };
}

function approveDraftRecord(lead, input, options = {}) {
  const draftId = String(input?.draft_id || "").trim();
  const approvedBy = String(input?.approved_by || "").trim();
  const approvalVersion = String(input?.approval_version || "").trim();
  if (!draftId || !approvedBy || !approvalVersion) {
    return {
      ok: false,
      error: "approval_metadata_required",
      fields: {
        ...(!draftId ? { draft_id: "required" } : {}),
        ...(!approvedBy ? { approved_by: "required" } : {}),
        ...(!approvalVersion ? { approval_version: "required" } : {}),
      },
    };
  }

  const updatedLead = clone(lead);
  updatedLead.outreach = ensureOutreach(updatedLead);
  const draft = updatedLead.outreach.drafts.find((item) => item.draft_id === draftId);
  if (!draft) return { ok: false, error: "draft_not_found" };
  if (draft.status === "sent") return { ok: false, error: "already_sent", draft: clone(draft) };
  if (draft.status === "approved") {
    return { ok: true, idempotent: true, lead: updatedLead, draft: clone(draft) };
  }
  if (draft.status !== "draft" && draft.status !== "send_failed") {
    return { ok: false, error: "draft_not_approvable", draft: clone(draft) };
  }

  draft.status = "approved";
  draft.approved_by = approvedBy;
  draft.approved_at = nowIso(options);
  draft.approval_version = approvalVersion;
  draft.last_error = null;
  updatedLead.updated_at = nowIso(options);
  return { ok: true, lead: updatedLead, draft: clone(draft) };
}

function rejectDraftRecord(lead, input, options = {}) {
  const draftId = String(input?.draft_id || "").trim();
  const rejectedBy = String(input?.rejected_by || "").trim();
  const rejectionReason = String(input?.rejection_reason || "").trim();

  const fields = {};
  if (!draftId) fields.draft_id = "required";
  if (!rejectedBy) fields.rejected_by = "required";
  if (!rejectionReason) fields.rejection_reason = "required";
  if (Object.keys(fields).length > 0) {
    return { ok: false, error: "rejection_metadata_required", fields };
  }
  if (rejectedBy.length > 200) fields.rejected_by = "too_long";
  if (rejectionReason.length > 500) fields.rejection_reason = "too_long";
  if (Object.keys(fields).length > 0) {
    return { ok: false, error: "validation_failed", fields };
  }

  const updatedLead = clone(lead);
  updatedLead.outreach = ensureOutreach(updatedLead);
  const draft = updatedLead.outreach.drafts.find((item) => item.draft_id === draftId);
  if (!draft) return { ok: false, error: "draft_not_found" };
  if (draft.status === "sent") return { ok: false, error: "already_sent", draft: clone(draft) };
  if (draft.status === "rejected") {
    // Repeating the exact same rejection is a deterministic no-op.
    if (draft.rejected_by === rejectedBy && draft.rejection_reason === rejectionReason) {
      return { ok: true, idempotent: true, lead: updatedLead, draft: clone(draft) };
    }
    return { ok: false, error: "draft_not_rejectable", draft: clone(draft) };
  }
  if (draft.status !== "draft" && draft.status !== "send_failed") {
    return { ok: false, error: "draft_not_rejectable", draft: clone(draft) };
  }

  const timestamp = nowIso(options);
  draft.status = "rejected";
  draft.rejected_by = rejectedBy;
  draft.rejected_at = timestamp;
  draft.rejection_reason = rejectionReason;
  // Clear only the transient last_error. Provider send history
  // (resend_id, provider_status, sent_at, conversation entries) is untouched.
  draft.last_error = null;
  updatedLead.updated_at = timestamp;
  return { ok: true, idempotent: false, lead: updatedLead, draft: clone(draft) };
}

function isSuppressed(lead) {
  return lead?.re_engagement_allowed === false
    || lead?.suppressed === true
    || lead?.outreach?.suppressed === true;
}

function prepareSend(lead, draftId) {
  if (isSuppressed(lead)) return { ok: false, error: "lead_suppressed" };
  const draft = findDraft(lead, draftId);
  if (!draft) return { ok: false, error: "draft_not_found" };
  if (draft.status === "sent") {
    return { ok: true, idempotent: true, resend_id: draft.resend_id };
  }
  if (draft.status !== "approved") return { ok: false, error: "approval_required" };

  const payload = {
    from: draft.from,
    to: [draft.to],
    subject: draft.subject,
  };
  if (draft.text) payload.text = draft.text;
  if (draft.html) payload.html = draft.html;
  if (draft.reply_to) payload.reply_to = draft.reply_to;
  return { ok: true, payload, draft: clone(draft) };
}

function recordSendResult(lead, draftId, result, options = {}) {
  const updatedLead = clone(lead);
  updatedLead.outreach = ensureOutreach(updatedLead);
  const draft = updatedLead.outreach.drafts.find((item) => item.draft_id === draftId);
  if (!draft) return { ok: false, error: "draft_not_found" };
  if (draft.status === "sent") {
    return { ok: true, idempotent: true, lead: updatedLead, draft: clone(draft), resend_id: draft.resend_id };
  }

  const timestamp = nowIso(options);
  const providerStatus = Number(result?.status) || null;
  draft.provider_status = providerStatus;
  if (!result?.ok) {
    const providerMessage = result?.data?.message || result?.data?.error || `http_${providerStatus || "unknown"}`;
    draft.status = "send_failed";
    draft.last_error = String(providerMessage).slice(0, 300);
    updatedLead.updated_at = timestamp;
    return { ok: false, error: "send_failed", lead: updatedLead, draft: clone(draft) };
  }

  const resendId = result?.data?.id || null;
  draft.status = "sent";
  draft.sent_at = timestamp;
  draft.resend_id = resendId;
  draft.last_error = null;
  const conversation = Array.isArray(updatedLead.conversation) ? updatedLead.conversation : [];
  conversation.push({
    ts: timestamp,
    channel: "email_out",
    direction: "out",
    subject: draft.subject,
    text: (draft.text || draft.html || "").slice(0, 2000),
    alias: draft.created_by,
    session_id: null,
    draft_id: draft.draft_id,
    resend_id: resendId,
  });
  updatedLead.conversation = conversation;
  const touches = Array.isArray(updatedLead.touch_sequence) ? updatedLead.touch_sequence : [];
  touches.push({
    type: "approved_outreach",
    sent_at: timestamp,
    resend_id: resendId,
    subject: draft.subject,
    draft_id: draft.draft_id,
  });
  updatedLead.touch_sequence = touches;
  updatedLead.last_contact_at = timestamp;
  updatedLead.last_contact_channel = "email_out";
  updatedLead.updated_at = timestamp;
  return { ok: true, lead: updatedLead, draft: clone(draft), resend_id: resendId };
}

// ─── Exports ──────────────────────────────────────────────────────
//
// Public state-machine surface for the TheoForge outreach pipeline.
// Every function is pure: it clones the caller's lead, never mutates it,
// and makes no network, filesystem, or LLM calls. The HTTP layer in
// server.mjs adapts request payloads, calls one of these, and atomically
// persists the returned lead clone.
//
//   createDraftRecord(lead, input, options)   → pending approval-gated draft
//   approveDraftRecord(lead, input, options)  → explicit human approval
//   rejectDraftRecord(lead, input, options)   → explicit human rejection
//   prepareSend(lead, draftId)                → approved-only send payload
//   recordSendResult(lead, draftId, result)   → provider outcome, idempotent
export {
  OUTREACH_VERSION,
  approveDraftRecord,
  createDraftRecord,
  findDraft,
  isSuppressed,
  prepareSend,
  recordSendResult,
  rejectDraftRecord,
};
