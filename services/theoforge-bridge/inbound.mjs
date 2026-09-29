// services/theoforge-bridge/inbound.mjs
// Pure inbound email reply state machine for the TheoForge bridge.
// Phase A: deterministic classification + lead mutation + approval-gated reply draft.
//
// This module is deliberately dependency-free on network, Resend, filesystem,
// and LLM access. It mutates an in-memory lead clone according to the Spec
// Contract at plans/theoforge-outreach-fusion-contract.md and lets the caller
// persist the result.
//
// Fail-closed guarantees:
//   - unsubscribe replies never create an outbound draft
//   - reply drafts are status:"draft" and are never approved or sent here
//   - unknown leads are rejected (lead_required) without creating anything

import { createHash } from "node:crypto";
import { createDraftRecord } from "./outreach.mjs";

const INBOUND_VERSION = 1;

// Length bounds for preserved inbound fields (applied after trimming).
export const INBOUND_BOUNDS = Object.freeze({
  subject: 500,
  text: 2000,
  message_id: 500,
  in_reply_to: 500,
  references: 2000,
});

export const REPLY_DRAFT_BODY =
  "Thanks for getting back to us. A member of the TheoForge team is " +
  "reviewing your message and will follow up with you shortly. " +
  "If you'd rather book time directly in the meantime, just let us know.";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Unsubscribe intent phrases, matched case-insensitively against subject + body.
// Classified BEFORE positive/negative/question/neutral.
const UNSUBSCRIBE_PATTERNS = [
  /\bunsubscribe\b/i,
  /\bremove me\b/i,
  /\bstop emailing\b/i,
  /\bstop sending\b/i,
  /\bdo not contact\b/i,
  /\bdon'?t contact\b/i,
  /\btake me off\b/i,
  /\btake my (name|email) off\b/i,
];

// Question signals: a question mark, a leading question word, or common
// question phrasings. Checked before positive/negative because the literal
// intent expressed by the lead is a question either way. The leading-word
// pattern uses the multiline flag so a question opening the body (after the
// subject line in the haystack) is still detected.
const QUESTION_PATTERNS = [
  /\?/,
  /^(what|when|where|which|who|whom|whose|why|how|can|could|would|will|are|is|do|does|did|may|might|should)\b/im,
  /\b(can|could|would|will) you\b/i,
  /\b(how about|what about)\b/i,
];

// Strong positive-intent signals (subject + body).
const POSITIVE_PATTERNS = [
  /\byes\b/i,
  /\binterested\b/i,
  /\bsounds good\b/i,
  /\blet'?s do it\b/i,
  /\blet'?s talk\b/i,
  /\blet'?s chat\b/i,
  /\bschedule\b/i,
  /\bbook (a |the )?(call|time|meeting|demo)\b/i,
  /\bworks for me\b/i,
  /\bperfect\b/i,
  /\bawesome\b/i,
  /\bcount me in\b/i,
  /\bgreat\b/i,
  /\bgood to go\b/i,
  /\bsign me up\b/i,
  /\bplease call\b/i,
  /\bcall me\b/i,
];

// Strong negative-intent signals (subject + body).
const NEGATIVE_PATTERNS = [
  /\bno thanks\b/i,
  /\bno thank you\b/i,
  /\bnot interested\b/i,
  /\bno interest\b/i,
  /\bnot a fit\b/i,
  /\bnot for me\b/i,
  /\bleave me alone\b/i,
  /\bgo away\b/i,
  /\bstop contacting\b/i,
  /\bplease stop\b/i,
  /\bwaste of (my )?time\b/i,
  /\bscam\b/i,
  /\bspam\b/i,
  /\bdon'?t email (me|us) again\b/i,
  /\bdo not email (me|us) again\b/i,
];

function clone(value) {
  return structuredClone(value);
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function boundString(value, max) {
  if (value === undefined || value === null) return "";
  return String(value).trim().slice(0, max);
}

function haystack(normalized) {
  return `${normalized.subject}\n${normalized.text}`;
}

function detectUnsubscribe(normalized) {
  return UNSUBSCRIBE_PATTERNS.some((re) => re.test(haystack(normalized)));
}

function detectQuestion(normalized) {
  return QUESTION_PATTERNS.some((re) => re.test(haystack(normalized)));
}

function detectPositive(normalized) {
  return POSITIVE_PATTERNS.some((re) => re.test(haystack(normalized)));
}

function detectNegative(normalized) {
  return NEGATIVE_PATTERNS.some((re) => re.test(haystack(normalized)));
}

function isSuppressedLead(lead) {
  return lead?.re_engagement_allowed === false
    || lead?.suppressed === true
    || lead?.outreach?.suppressed === true;
}

function replyDraftSubject(normalized) {
  const subject = normalized.subject || "";
  if (/^re\s*:/i.test(subject)) return subject.slice(0, 200);
  return `Re: ${subject}`.slice(0, 200);
}

function findReplyDraft(lead, eventKey) {
  const drafts = lead?.outreach?.drafts;
  if (!Array.isArray(drafts)) return null;
  const existing = drafts.find(
    (draft) => draft && draft.idempotency_key === `inbound:reply:${eventKey}`,
  );
  return existing ? clone(existing) : null;
}

/**
 * classifyInboundReply({ from, to, subject, text, message_id, in_reply_to, references })
 * -> { ok, classification, normalized, is_unsubscribe, is_actionable, event_key }
 *
 * classification: "unsubscribe" | "positive" | "negative" | "question" | "neutral"
 * is_actionable:  true for positive and question, false otherwise
 * event_key:      provider message_id when present, otherwise a deterministic
 *                 sha256 digest over normalized sender + subject + text.
 *                 Never random, so deduplication is stable across retries.
 */
export function classifyInboundReply(input = {}) {
  const from = normalizeEmail(input?.from);
  const text = String(input?.text ?? "").trim();
  const fields = {};

  if (!from) fields.from = "required";
  else if (!EMAIL_RE.test(from)) fields.from = "invalid";

  if (!text) fields.text = "required";

  if (Object.keys(fields).length > 0) {
    return {
      ok: false,
      error: "validation_failed",
      fields,
      classification: null,
      normalized: null,
      is_unsubscribe: false,
      is_actionable: false,
      event_key: null,
    };
  }

  const normalized = {
    from,
    to: input?.to ? normalizeEmail(input.to) : null,
    subject: boundString(input?.subject, INBOUND_BOUNDS.subject),
    text: text.slice(0, INBOUND_BOUNDS.text),
    message_id: boundString(input?.message_id, INBOUND_BOUNDS.message_id) || null,
    in_reply_to: boundString(input?.in_reply_to, INBOUND_BOUNDS.in_reply_to) || null,
    references: boundString(input?.references, INBOUND_BOUNDS.references) || null,
  };

  const event_key = normalized.message_id
    ? normalized.message_id
    : `inb-${createHash("sha256")
        .update(`${normalized.from}\u0000${normalized.subject}\u0000${normalized.text}`)
        .digest("hex")}`;

  // ── Deterministic classification cascade ──
  // 1. unsubscribe (detected before everything else, fail-closed)
  // 2. question  (structural signal: "?" or question phrasing)
  // 3. negative  (a negated positive like "not interested" is negative intent;
  //               when both positive and negative fire, negative wins)
  // 4. positive
  // 5. neutral
  const is_unsubscribe = detectUnsubscribe(normalized);
  const hasPositive = detectPositive(normalized);
  const hasNegative = detectNegative(normalized);

  let classification;
  if (is_unsubscribe) {
    classification = "unsubscribe";
  } else if (detectQuestion(normalized)) {
    classification = "question";
  } else if (hasPositive && hasNegative) {
    classification = "negative";
  } else if (hasPositive) {
    classification = "positive";
  } else if (hasNegative) {
    classification = "negative";
  } else {
    classification = "neutral";
  }

  const is_actionable = classification === "positive" || classification === "question";

  return { ok: true, classification, normalized, is_unsubscribe, is_actionable, event_key };
}

/**
 * applyInboundReply(lead, inbound, options = {})
 * -> { ok, lead, classification, suppressed, draft, idempotent, error? }
 *
 * Never mutates the caller's lead. Appends exactly one "email_in" conversation
 * entry, updates contact timestamps, suppresses on unsubscribe, and creates
 * exactly one pending approval-gated reply draft for positive/question replies.
 * Re-applying the same inbound event_key is a deterministic no-op.
 */
export function applyInboundReply(lead, inbound, options = {}) {
  if (!lead || typeof lead !== "object") {
    return {
      ok: false,
      error: "lead_required",
      classification: null,
      suppressed: false,
      draft: null,
      idempotent: false,
    };
  }

  const classified = classifyInboundReply(inbound);
  if (!classified.ok) {
    return {
      ok: false,
      error: classified.error,
      fields: classified.fields,
      classification: null,
      suppressed: false,
      draft: null,
      idempotent: false,
    };
  }

  const { classification, normalized, is_unsubscribe, event_key } = classified;
  const timestamp = options.now ? options.now() : new Date().toISOString();

  // Deterministic deduplication: the same inbound event never lands twice.
  const conversation0 = Array.isArray(lead.conversation) ? lead.conversation : [];
  if (conversation0.some((entry) => entry && entry.event_key === event_key)) {
    return {
      ok: true,
      lead: clone(lead),
      classification,
      suppressed: isSuppressedLead(lead),
      draft: findReplyDraft(lead, event_key),
      idempotent: true,
    };
  }

  const updatedLead = clone(lead);
  const conversation = Array.isArray(updatedLead.conversation) ? updatedLead.conversation : [];
  conversation.push({
    ts: timestamp,
    channel: "email_in",
    direction: "in",
    sender: normalized.from,
    subject: normalized.subject,
    text: normalized.text,
    message_id: normalized.message_id,
    in_reply_to: normalized.in_reply_to,
    references: normalized.references,
    event_key,
  });
  updatedLead.conversation = conversation;
  updatedLead.last_contact_at = timestamp;
  updatedLead.last_contact_channel = "email_in";
  updatedLead.updated_at = timestamp;

  // Suppression state that pre-existed this reply (unsubscribe flips it true).
  let suppressed = isSuppressedLead(lead);

  if (is_unsubscribe) {
    updatedLead.suppressed = true;
    updatedLead.re_engagement_allowed = false;
    const outreach = updatedLead.outreach && typeof updatedLead.outreach === "object"
      ? clone(updatedLead.outreach)
      : {};
    outreach.suppressed = true;
    updatedLead.outreach = outreach;
    suppressed = true;
    return { ok: true, lead: updatedLead, classification, suppressed, draft: null, idempotent: false };
  }

  if (classification === "negative" || classification === "neutral") {
    return { ok: true, lead: updatedLead, classification, suppressed, draft: null, idempotent: false };
  }

  // Actionable (positive | question): exactly one pending approval-gated draft.
  const draftResult = createDraftRecord(updatedLead, {
    to: updatedLead.lead_email,
    from: normalized.to || "",
    subject: replyDraftSubject(normalized),
    text: REPLY_DRAFT_BODY,
    created_by: "system:inbound-reply",
    idempotency_key: `inbound:reply:${event_key}`,
  }, { now: options.now, idFactory: options.idFactory });

  if (!draftResult.ok) {
    return {
      ok: false,
      error: "draft_creation_failed",
      cause: draftResult.error,
      fields: draftResult.fields,
      classification,
      suppressed,
      draft: null,
      idempotent: false,
    };
  }

  return {
    ok: true,
    lead: draftResult.lead,
    classification,
    suppressed,
    draft: draftResult.draft,
    idempotent: false,
  };
}

export { INBOUND_VERSION };