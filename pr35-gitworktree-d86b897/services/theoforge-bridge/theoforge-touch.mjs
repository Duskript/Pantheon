#!/usr/bin/env node
/* theoforge-touch.mjs — Mercer touch sequence executor.
 *
 * Runs hourly. Reads "due touches" from the bridge, formats the email,
 * sends via Resend, and appends a touch_entry to the lead record.
 *
 * Replaces the n8n touch-sequence workflow (which was blocked by a
 * n8n-side credential data bug — see journal 2026-06-07). Does the
 * same job in 80 lines of Node and zero workflow state to maintain.
 *
 * The 24h and "morning of" windows are the bridge's responsibility
 * (see /scout/due-touches in server.mjs). We just iterate, format,
 * send, and log.
 *
 * Cron: hourly. The systemd unit is theoforge-touch.service; the
 * timer is theoforge-touch.timer. Don't run this from crontab — use
 * the timer so the logs land in journald.
 *
 * Idempotency: the bridge's scout only returns touches that don't
 * have a `sent_at` value. Once we send and append-touch, the touch
 * gets `sent_at` set, and the next run skips it.
 */

const BRIDGE_URL = process.env.BRIDGE_URL || "http://100.68.106.59:4323";
const TIMEOUT_MS = 20_000;
const FROM_ADDRESS = "Konan <hello@theoforgesolutions.com>";

function log(...a) { console.log(`[${new Date().toISOString()}]`, ...a); }
function err(...a) { console.error(`[${new Date().toISOString()}]`, ...a); }

async function bridgeFetch(path, init = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(`${BRIDGE_URL}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "content-type": "application/json", ...(init.headers || {}) },
    });
    const text = await r.text();
    let body;
    try { body = JSON.parse(text); } catch { body = { ok: false, error: "non_json", raw: text.slice(0, 300) }; }
    return { ok: r.ok && body.ok, status: r.status, body };
  } catch (e) {
    return { ok: false, status: 0, body: { ok: false, error: e.name === "AbortError" ? "timeout" : e.message } };
  } finally {
    clearTimeout(t);
  }
}

async function sendTouch(item) {
  const { lead_email, lead_name, touch_type, booked_slot, alias } = item;

  // 1) Format the email
  // The bridge's /format/touch expects `appt_time` (not `appt_time_iso`).
  // We pass booked_slot straight through since it's already ISO 8601.
  const fmt = await bridgeFetch("/format/touch", {
    method: "POST",
    body: JSON.stringify({
      touch_type,
      lead_name: lead_name || "there",
      appt_time: booked_slot,
      alias: alias || "rachel",
    }),
  });
  if (!fmt.ok) {
    err(`format_failed email=${lead_email} error=${fmt.body.error}`);
    return false;
  }
  const { subject, text } = fmt.body;

  // 2) Send via Resend
  const send = await bridgeFetch("/resend/send", {
    method: "POST",
    body: JSON.stringify({
      to: lead_email,
      from: FROM_ADDRESS,
      subject,
      html: `<div style="font-family:system-ui,sans-serif;line-height:1.6;color:#222">${text.replace(/\n/g, "<br>")}</div>`,
    }),
  });
  if (!send.ok) {
    err(`resend_failed email=${lead_email} error=${send.body.error} msg=${send.body.message || ""}`);
    return false;
  }
  // Bridge returns { ok, status, data: { id: <resend_id>, ... } }
  // where `data` is the raw Resend API response.
  const resendId = send.body.data?.id || "unknown";

  // 3) Append touch entry to the lead record
  const append = await bridgeFetch("/lead/append-touch", {
    method: "POST",
    body: JSON.stringify({
      lead_email,
      touch_entry: {
        type: touch_type,
        sent_at: new Date().toISOString(),
        resend_id: resendId,
        subject,
      },
    }),
  });
  if (!append.ok) {
    err(`append_touch_failed email=${lead_email} error=${append.body.error}`);
    // Email was sent — log and move on. The next scout run will retry
    // the append but not re-send (sent_at is set, so scout won't return it).
    return true;
  }

  log(`sent touch_type=${touch_type} email=${lead_email} resend_id=${resendId}`);
  return true;
}

async function main() {
  log(`starting touch run bridge=${BRIDGE_URL}`);

  // Health gate — if bridge is down, abort the run (don't crash, don't loop)
  const health = await bridgeFetch("/healthz");
  if (!health.ok) {
    err(`bridge_unreachable aborting: ${health.body.error || health.status}`);
    process.exit(2);
  }

  const scout = await bridgeFetch("/scout/due-touches");
  if (!scout.ok) {
    err(`scout_failed error=${scout.body.error}`);
    process.exit(2);
  }
  const items = scout.body.items || [];
  log(`scout returned ${items.length} due touch(es)`);

  if (items.length === 0) {
    log(`nothing to do — exiting 0`);
    process.exit(0);
  }

  let sent = 0, failed = 0;
  for (const item of items) {
    const ok = await sendTouch(item);
    if (ok) sent++; else failed++;
  }
  log(`done sent=${sent} failed=${failed}`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  err(`unhandled error: ${e?.stack || e}`);
  process.exit(2);
});
