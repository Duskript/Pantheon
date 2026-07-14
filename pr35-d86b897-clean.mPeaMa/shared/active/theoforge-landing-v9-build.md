# theoforge-landing-v9 — MONOLITH BUILD (SHIPPED)

**Status:** Phase 1 (visual) + Phase 2 (lead capture) SHIPPED. Phase 3 (chat/LLM) stubbed.
**Canonical reference:** Iris's v9 monolith at `/home/konan/workspace/theoforge-v3/index-v9.html` (SHA-256 `17b50887...`, 62,192 bytes, 1,805 lines).
**Live:** `http://pantheon.tail164759.ts.net:4321/`

---

## What this is

A custom Node server that serves Iris's v9 monolith as the static foundation and adds two API routes (`/api/leads`, `/api/chat`) for the lead-capture and chat-pipeline wiring.

**Architecture:**

```
~/workspace/theoforge-landing-v9-monolith/
├── server.mjs          (150-line http server, ~7.7KB)
├── lib/
│   ├── lead.mjs        (Phase 2: validation, honeypot, JSONL persist)
│   └── chat.mjs        (Phase 1 stub: scripted replies, ready for Mercer swap)
├── public/
│   └── index.html      (Iris's v9 monolith, 63.4KB — 1.2KB added for form wiring)
└── data/leads/         (empty — leads persist to ~/.theoforge/leads/ instead)
```

## Build approach (per Konan's direction, 2026-06-06)

Konan said: "Take Iris's index-v9.html and use that as the foundation for this landing page. Everything else should be built on top of this. The layout of everything is perfect, so take all of her mockup stuff and use that as canon."

This replaces the earlier Astro 6 build (which is still at `~/workspace/theoforge-landing-v9/` and backed up at `~/workspace/theoforge-landing-v9-ASTRO-BACKUP/`). The Astro build had two CSS-in-body leak bugs that required Vite/Astro-specific workarounds; using the monolith as the foundation eliminates the entire CSS-pipeline risk surface.

## What was changed in the monolith

Only 3 surgical edits, all in the email-form region:

1. **Form fields injected** — Iris's monolith had the form structure (`.email-form`, `.field-row`, `<button>`, `.small`) but the input fields were empty `<div>` placeholders. I injected:
   ```html
   <input type="text"  name="name"      placeholder="Full name"          required />
   <input type="email" name="email"     placeholder="Email address"     required />
   <textarea           name="challenge" placeholder="What's eating your hours (optional)" />
   <input type="text"  name="website"   class="hp" tabindex="-1" autocomplete="off" />  <!-- honeypot -->
   <button type="submit">→ <span>Send me a free ops audit</span></button>
   ```

2. **`handleEmailSubmit()` replaced** — was a UI-only mock (set .small text, disable inputs). Replaced with a real `fetch("/api/leads", { method: "POST", body: JSON.stringify({...}) })` call with success/validation/error states, plus a honeypot check.

3. **Submit event listener added** — `document.querySelectorAll("form.email-form").forEach(f => f.addEventListener("submit", ...))` to wire the form to the new handler.

**Everything else is byte-identical to Iris's monolith.** Layout, fonts, tokens, ornaments, ledger, pull quote, mid-section, colophon, footer, the 3-act chat reveal (5.5s FAB / 7s teaser / 10s auto-pop) — all untouched.

## API routes

### POST /api/leads
- Body: `{ name, email, challenge?, website?, submittedAt? }`
- Validation: name ≥ 2 chars, email regex, challenge ≤ 1000 chars
- Honeypot: if `website` is non-empty, return `{ok: true, leadId: "honeypot"}` silently, do NOT persist
- On success: append to `~/.theoforge/leads/YYYY-MM-DD.jsonl` (mode 0o600), return `{ok: true, leadId}`
- On validation fail: return 400 + `{fields: {name?, email?, challenge?}}`

### POST /api/chat
- Body: `{ message, agentId? }`
- Phase 1: returns scripted reply (rotates through 3 prepared messages)
- Phase 3: will call Mercer LLM, streaming response

### GET /healthz
- Returns server status, uptime, pid, monolith-present, phase info

## What this unblocks

- **Phase 2 (lead capture)**: ✅ SHIPPED, tested legit/validation/honeypot/GET/Tailscale
- **Phase 3 (Mercer LLM)**: `/api/chat` is stubbed, ready to swap handler to a real LLM call. The monolith's `sendMessage()` function still uses local scripted responses; the swap is to replace the local `agentResponses[...]` lookup with `fetch("/api/chat", ...)`.
- **Phase 4 (Cal.com)**: monolith has booking pills, just need a real Cal.com lookup
- **Phase 5 (15 agent avatars)**: monolith has the `agents` array with persona names; add `<img>` to monogram area
- **Phase 6 (observability)**: structured log lines already in the server (`[leads]`, `[chat]`)

## Earlier attempts (context)

The first v9 build (Astro 6 + Preact + TypeScript) is at `~/workspace/theoforge-landing-v9/` and `~/workspace/theoforge-landing-v9-ASTRO-BACKUP/`. That build:
- Created 21 components from Iris's spec doc, not from her monolith
- Fought two CSS-in-body-leak bugs in Astro 6 + Vite SSR
- Final visual approximated the monolith but had measurable diffs in font sizes, spacing, drop cap, FILED stamp
- Form was wired, chat was a Preact island

The monolith build replaces all of that with Iris's literal HTML+CSS+JS, plus a 150-line server. **This is the canonical v9 going forward.**

## What I need from you

- Iris visual QA on the live Tailscale link (the page should now match the monolith byte-for-byte plus the form inputs)
- Stamp color decision (oxblood vs gold) — if it needs to change, it's a one-line CSS edit in the monolith
- v6 supersession: this monolith build effectively makes the v6 Astro build obsolete. Want me to mark v6 as SUPERSEDED in the shared INDEX, or keep both for now?


---

## Phase 3 (Mercer LLM chat) — SHIPPED 2026-06-06

**Per Thoth's handoff (`~/pantheon/shared/mercer-to-landing-handoff.md`):** replaced the canned 7-step `flowStep` machine in the monolith with a real Mercer connection. The widget's `sendMessage()` now POSTs to `/api/mercer/message`; the server spawns a `hermes chat -p mercer -Q` subprocess, parses the reply, and returns `{ reply: "..." }`.

### Architecture

```
widget sendMessage()
  ↓ POST { session_id, alias, message }
POST /api/mercer/message
  ↓
lib/mercer.mjs
  ├─ Session map (in-memory, Map<landingSid, {hermesSid, alias, ...}>)
  │   - cold turn: spawn `hermes chat -q ...` (no --resume)
  │   - warm turn: spawn `hermes chat -q ... --resume <hermesSid>`
  │   - lazy TTL eviction at 24h
  │   - hard cap 50 concurrent sessions
  ├─ Identity wrapper: prepends "[Landing page chat widget — voice: ${alias}]"
  │   to the first turn; subsequent turns get a shorter "The prospect said:" prefix
  ├─ Quiet-mode parsing: session_id is on STDERR, reply is on STDOUT
  └─ Subprocess timeout: 60s (Mercer typically 12-15s on deepseek-v4-flash)
```

### Endpoints (added)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/mercer/message` | `{session_id, alias, message}` | `{ok, reply, session_id, elapsed_ms}` |
| POST | `/api/mercer/reset` | `{session_id}` | `{ok, cleared}` |
| GET | `/api/mercer/health` | — | `{ok, sessions, max, uptime_s}` |

### Front-end changes (in `public/index.html`)

- Dropped `let flowStep = 0;` and `let context = {};`
- Replaced `sendMessage()` (was ~90 lines of `if (flowStep === N)`) with a 40-line caller
- Replaced `runIntroSequence()` greeting to match Thoth's handoff copy
- Deleted `offerBooking()` and `bookSlot()` (Phase 4+ will re-introduce Cal.com-backed booking)
- Added `getMercerSessionId()` helper — UUID stored in `sessionStorage["mercer_session"]`
- Kept `addMessage`, `showTyping`, `randTyping`, `getAgent`, `AGENTS`, FAB timing
- Email form (`handleEmailSubmit`, `/api/leads`) untouched — separate path

### Performance

| Turn | Path | Latency |
|---|---|---|
| 1 (cold) | `hermes chat -q` (no --resume) | 22.5s (subprocess startup + first roundtrip) |
| 2+ (warm) | `hermes chat -q --resume <sid>` | 11.8-11.9s (Hermes session already in SQLite) |
| Widget masks with | `randTyping()` | 1.8-4.0s randomized before reply appears |

The widget's `randTyping()` animation sits in front of the subprocess wait, so leads see a 2-4s typing-dots pause before the reply renders — perceptually human-feel.

### End-to-end test (curl, 2026-06-06 10:47)

```
TURN 1 (cold):   22.5s — "What's on your mind? What made you reach out?"
TURN 2 (resume): 11.8s — "Four days is brutal for month-end... how many people on your team?"
TURN 3 (resume): 11.9s — "Those two things are the classic time sinks..."
```

All three turns used the same Hermes session_id `20260606_104734_c2d911`. Mercer's voice is **Challenger + specific + audit-style** (per persona.md) — no brochure-speak, no "we're excited to announce," no AI-leak. Tool calls stripped (none in current flow — Mercer doesn't use tools yet).

### Edge cases verified

- `POST /api/mercer/message` empty message → `{ok:false, error:"empty_message"}`
- Missing `session_id` → `{ok:false, error:"missing_session_id"}`
- Wrong method → 405
- Bad JSON → 400 + `{error:"bad_json"}`
- `/api/mercer/reset` → clears the map entry, next turn starts cold
- `/api/mercer/health` → reports `sessions` count, `max=50`, `uptime_s`
- `/api/leads` still works (Phase 2 untouched)

### Files in build (post-Phase 3)

```
~/workspace/theoforge-landing-v9-monolith/
├── server.mjs           (10.8KB — 3 new routes added)
├── lib/
│   ├── lead.mjs         (Phase 2 — unchanged)
│   ├── chat.mjs         (Phase 1 stub — kept for legacy /api/chat)
│   └── mercer.mjs       (Phase 3 — NEW, 9KB, session map + subprocess pool)
├── public/
│   └── index.html       (59.6KB — down from 63.9KB after canned chat removal)
└── package.json
```

### Decisions logged (Phase 3)

1. **CLI subprocess over Python SDK or proxy** — Mercer's persona/SOUL rules only load through the CLI's `hermes chat -p mercer` path. Proxy mode is Nous/xAI-only and strips profile context. SDK embedding would reimplement the persona loader. Subprocess cost (12-15s/turn) is acceptable behind `randTyping()`.

2. **Session map: in-memory only** — no disk persistence. Server restart = new sessions. Acceptable for landing-page traffic (24h TTL covers any single lead's chat lifetime).

3. **STDERR for session_id** — Hermes treats `session_id:` as diagnostic metadata (stderr), not chat output (stdout). Parser scans both streams.

4. **Identity injection via message prefix, not system prompt** — preserves Mercer's full persona/Challenger rules. The widget gives him the voice name and the line; his brain applies unchanged.

5. **`/api/chat` kept as legacy stub** — in case any external tooling (or a stale browser tab) still calls it. The widget points to `/api/mercer/message`.

6. **`randTyping()` mask** — accepts the 12-15s subprocess cost because the widget already had 1.8-4.0s of typing-dots animation. Removing it would make Mercer feel instant/unhuman.

### Pitfalls (from Thoth's handoff) — all addressed

- ✅ **Tool call leakage** — `-Q` mode + defensive `stripToolArtifacts()` regex sweep
- ✅ **Session persistence** — warm turns use `--resume <hermesSid>`, cold turns capture and stash
- ✅ **Typing animation preserved** — `randTyping()` (1800-4000ms) still wraps every reply
- ✅ **Email form unchanged** — `/api/leads` is a separate path, never touched
- ✅ **Name pool untouched** — `AGENTS` array + `getAgent()` + `sessionStorage` persistence all preserved

### What's still TODO (Phase 4-6)

- **Phase 4 (Cal.com):** real booking instead of the deleted `bookSlot()` pills. Mercer will tell prospects to grab a slot via a Cal.com link in his replies.
- **Phase 5 (avatars):** the 14-name pool currently has no avatar images — just initials. Add real ` ` per name.
- **Phase 6 (observability):** structured per-session logs in `~/.theoforge/sessions/<sid>.jsonl` so we can replay a lead's conversation if they ghost and come back.


---

## Phase 1.13 (Brand assets) — SHIPPED 2026-06-06

**Per Iris's handoff (`msg_20260606_175742_marvin`):** swap the 2 inline-SVG brand elements in the monolith for the JPEG brand assets from `~/athenaeum/Codex-God-Iris/theoforge-brand/logo/`. Update 3 CSS rules. Remove 1 JS line.

### What changed (5 patches, all in `public/index.html`)

| # | Location | Change |
|---|---|---|
| 1 | CSS line 191 | `.monogram svg { ... }` → `.monogram { display: block; }` |
| 2 | CSS lines 890-903 | `.chat-fab .avatar { ... color: var(--gold); font... }` (text-styled) → `.chat-fab .avatar-img { ... object-fit: cover; }` (img-styled) |
| 3 | Markup line 1248 | Glass nav `<div class="monogram"><svg>...</svg></div>` → `<img class="monogram" src="/assets/brand/theoforge-monogram-light.jpg" width="32" height="32">` |
| 4 | Markup line 1507 | FAB `<span class="avatar" id="fabAvatar">S</span>` → `<img class="avatar-img" id="fabAvatar" src="/assets/brand/theoforge-monogram-dark.jpg" width="50" height="50">` |
| 5 | JS line 1571 | Removed `document.getElementById("fabAvatar").textContent = agent.initial;` (avatar is no longer a text node) |

**Header avatar preserved (correctly):** `<span class="avatar" id="headerAvatar">S</span>` in the chat-window header stays as a text node. Per Iris: "The agent name appears in the chat window header... so the per-agent identity is still conveyed there."

### Brand assets added

```
~/workspace/theoforge-landing-v9-monolith/public/assets/brand/
├── theoforge-monogram-light.jpg  (167,854 bytes, from codex)
└── theoforge-monogram-dark.jpg   (164,005 bytes, from codex)
```

Two assets copied (only the two we needed). The other 6 (wordmarks, logos, lockups) in the codex are not yet referenced by the page.

### Visual verification (chromium headless screenshot, 2026-06-06 12:06)

- **Top-left (glass nav, 32×32):** Real `TF` monogram visible in gold hairline frame ✅
- **Bottom-right (chat FAB, 50×50):** Real `TF` monogram in gold on dark round button ✅
- **No broken image icons** anywhere on the page
- **No console errors** from missing assets

### Decision: used JPEGs, not SVGs

Iris's message says `.svg` filenames, but the assets in the codex are JPEGs (the MANIFEST notes "production build needs SVG export" as future work). I used `.jpg` filenames so the page renders correctly NOW, with a comment in the markup saying "swap to .svg when SVG export lands." When Iris runs the Gemini wordmark prompt and produces the SVGs, the swap is a 2-line find-replace (light + dark monogram).

### Nit: glass nav color mode

Iris's literal message: "Use `theoforge-monogram-light.svg` (dark TF on transparent) — the dark ink will be invisible against the dark nav." Then in the rationale: "My recommendation: use the dark monogram (gold on transparent) since the glass nav is dark." I followed the literal message (light variant); her rationale is correct that dark would be more visible. **The hairline gold frame is visible on both, but the dark monogram (gold TF) would render more contrast.** Worth a 1-line follow-up: swap `/assets/brand/theoforge-monogram-light.jpg` → `/assets/brand/theoforge-monogram-dark.jpg` in the glass nav `<img>`.

### What's NOT yet done (deferred to Iris / Konan)

1. **SVG export** — needs Gemini prompt run. Konan has the prompt per MANIFEST.
2. **6 more brand assets** (wordmarks, logos, lockups) — copied when needed for social cards, OG image, colophon.
3. **Favicon variants** — 16/32/180/192/512 from the dark monogram, plus the special "solid gold square" favicon Iris designed.
4. **OG image** — 1200×630 dark with title overlay (title TBD by Iris).
5. **Glass nav color mode** — swap light → dark monogram (above nit).

### Lines of code / bytes

- `public/index.html`: 59,200 → 59,358 bytes (net +158 — inline SVG was bigger than the JPEG `<img>` tag, but the new UTF-8 comments in the patches added bytes)
- 2 new files in `public/assets/brand/`
- 0 changes to any other file (server.mjs, lib/*, package.json untouched)
## Phase 3.5 (Conversational flow + prospect handoff) — SHIPPED 2026-06-06

**Konan's corrections (2026-06-06, multiple turns):**

1. **Agent intro timing:** agent introduces themselves ONCE, on the second turn (not the first). Turn 1 = name-ask. Turn 2 = self-intro. Never again.
2. **No Konan mention:** the agent never references Konan, the founder, "the team", or "Konan asked me to reach out" in the conversation. The reveal is Konan's job on the sales call.
3. **No greeting word:** no "Hi", "Hey", "Hello", "Good morning". Drop straight in.
4. **Scheduling is conversational:** no pop-up, no calendar widget, no clickable UI. Mercer offers 2-3 specific times in chat; lead picks one; Mercer confirms. No Cal.com tool call yet (Phase 4 will wire it).
5. **After scheduling confirmation, Mercer surfaces 4 things in order:**
   - "I'll get it on Konan's calendar now"
   - What Konan will cover on the call
   - The report / write-up being sent right now
   - The day-before follow-up touch
6. **Prospect record / CRM:** Mercer compiles a structured prospect record during the conversation (name, business, role, situation, challenge, budget_signal, timeline, decision_making, scheduling_window). On booking intent, the front-end POSTs the record to `/api/prospects` and a followup reminder to `/api/prospects/followup`.

**Implementation:**

- `lib/mercer.mjs` rewritten with `buildWrappedTurn({ turn, alias, message, isFirstEver })` — turn-aware system prefix. Turn 1: name-ask only, no self-intro, no Konan. Turn 2: self-intro ONCE, then pivot to the actual question. Turn 3+: gather, no self-intro repeat. Scheduling turn: confirm + report + followup.
- `turnCount` tracked in the session map. Bumped on each call. Reset on recovered-session path.
- `lib/prospect.mjs` (NEW) — chat-side prospect capture. Validates name + alias + session_id + turn_count; optional fields are soft-capped. Honeypot on `website`. Persists to `~/.theoforge/prospects/{YYYY-MM-DD}.jsonl` (mode 0o600).
- `lib/prospect.mjs` (NEW `handleFollowup`) — day-before reminder queue. POST `/api/prospects/followup { prospectId, alias, scheduled_for, note }` writes a followup record to `~/.theoforge/followups/{YYYY-MM-DD}.jsonl`. fire_at is `appt - 24h` clamped to `[now+1h, ...]`. A future cron-driven daemon will pick these up and fire the reminder.
- `public/index.html`:
  - `runIntroSequence()` no longer hardcodes a greeting. It calls `/api/mercer/message` with a synthetic prompt so Mercer produces the turn-1 opener (varies per lead).
  - `extractProspectName()` walks the chat history, finds the most recent name-ask assistant line, and pulls the next user line's first 1-2 capitalized words. Best-effort — Konan can correct from the transcript.
  - `extractScheduledTime()` regexes day-of-week (Monday-Sunday, today, tomorrow) + time-of-day (10am, 2pm, morning, afternoon) into an ISO 8601 string. Falls back to "next occurrence of that day at the named hour" — if today is Wednesday and lead says "Friday 2pm", result is this Friday 2pm. If today is Friday and they say "Friday 2pm", result is *next* Friday 2pm.
  - `looksLikeBookingIntent(text)` triggers the prospect POST when the lead's message contains "yes", "sure", "sounds good", "book it", "schedule", a day name, "tomorrow", "this week", or `\d{1,2}\s*(am|pm|:\d{2})`.
  - `postProspectHandoff(turnCount, prospectText)` is gated on `extractProspectName()` returning non-null. If we don't have a name yet, we defer (don't fake it). Once posted, a `_prospectPostedThisSession` flag prevents duplicates. On success, also POSTs `/api/prospects/followup` if we could extract a time.
  - `transcriptExcerpt(maxChars)` returns the last `maxChars` of the chat (default 1200), formatted as `AgentName: ...\nProspect: ...\n...`, with a leading `"..."` if truncated.
- `server.mjs` — added 2 routes (`/api/prospects`, `/api/prospects/followup`), updated startup banner.

**Verified live (4-turn E2E, 2026-06-06 19:55 UTC):**

- Turn 1: Mercer reply = `"What do I call you?"` (12.2s, name-ask only, no intro, no Konan, no greeting)
- Turn 2 (lead: "Sarah"): Mercer reply = `"I'm James, one of the ops leads here. What brought you in today — anything specific going on?"` (10.3s, self-intro once, then pivot)
- Turn 3 (lead: 12-person roofing, 3 weeks behind on invoicing): Mercer reply gathers naturally (`"Three weeks is a long gap in this business — what's causing the bottleneck?..."`)
- Turn 4 (lead: "Yeah... Friday 2pm works."): Mercer reply is the full scheduling handoff — confirms the time, sets call expectations, mentions the write-up, mentions the day-before ping
- All in one Mercer session (hermes_sid `20260606_135615_8d4490`), no reset between turns.
- `/api/prospects` smoke: returns `{ok:true, prospectId:"1780775864-sarah-chen-7e2eda"}`, file written with 0o600.
- `/api/prospects/followup` smoke: returns `{ok:true, followupId:"fu-1780775864-68e1f6", fire_at:"2026-06-11T18:00:00.000Z"}`, file written with 0o600.

**Backlog:**

- Phase 4: Cal.com tool wiring (Mercer actually books the calendar), Resend tool wiring (the write-up goes out as a real email, not just a JSONL record). The current scheduling handoff is conversational commitment only.
- Phase 4 followup daemon: cron reads `~/.theoforge/followups/{date}.jsonl` and fires reminders when `fire_at` <= now.
- Phase 4: lead capture form (`/api/leads`) and chat prospect capture (`/api/prospects`) currently write to separate jsonl files. Phase 4 unifies them into a single CRM-shaped schema.


## Phase 4 (Unified lead schema + email pipeline) — SHIPPED 2026-06-06

**Goal:** one lead file per person, joined by email across all channels (chat, form, email-in, email-out). n8n workflows + chat widget + form all write to the same place. Konan's morning read = one folder, one schema.

**Schema spec:** `~/pantheon/shared/lead-schema.md` (canonical, 16KB). Pipeline states: `prospect → appointment → close → customer` (linear), with `departed` as a sibling terminal state reachable from any. Soft-departure for customers via `departed_at` + `departure_history` (preserves the cycle, allows re-engagement).

**Storage path:** `~/athenaeum/Codex-God-Mercer/leads/{slug}.json` (one file per lead, slug from email local-part, mode 0o600, atomic write via tmp+mv).

**Why this path (vs the old `~/.theoforge/prospects/{date}.jsonl`):**
- The Codex path is the canonical home for "codex knowledge" per the Pantheon memory model
- The future CRM will read from this folder — viewers on the same data, not parallel sources
- Konan's morning read = `ls ~/athenaeum/Codex-God-Mercer/leads/` + `cat` the new ones

**What changed in the back-end (`lib/prospect.mjs` rewrite, 20.6KB):**
- `validateProspect` requires `lead_email` (PRIMARY KEY), `lead_name`, `alias`. For chat-channel, `session_id` is required.
- `mergeProspect` does upsert-by-email. Reads existing file, mutates in memory, atomic-write.
- `audit` is a 7-center map (`lead_capture, scheduling, client_intake, communications, task_ops, billing, retention`), each with `{status, quote, asked_at}`, status ∈ `{untouched, partial, covered}`. Status only advances, never retreats.
- `pipeline_stage` only advances forward (prospect → appointment → close → customer), or transitions to `departed` (any → departed). `departed → prospect` is a re-engagement that preserves `departure_history`.
- `mercer_sessions` is a list (not a single value). Most leads have one. Re-engagements add a new one.
- `conversation` is append-only, never rewritten in place. Every entry has `ts, channel, direction, subject, text, session_id?, alias?, mercer_audit_snapshot?`.
- `touch_sequence` tracks outreach separately from the conversation.
- `tags` is a merged set (union of incoming tags + existing).
- New exports: `listLeads({stage, departed_only})` for Konan's morning read, `markDeparted({lead_email, reason})` for soft-depart.

**What changed in the form handler (`lib/lead.mjs` rewrite, 3.9KB):**
- Was writing to `~/.theoforge/leads/{date}.jsonl` (deprecated)
- Now translates the form payload to the unified schema and calls `handleProspect` directly
- `alias: "TheoForge Web"` (a stable sentinel so form-captures can be filtered)
- `tags: ["form-capture"]` (same — filterable)
- `channel: "form"`
- The form's `/api/leads` endpoint is now a thin shim over `/api/prospects`; both write to the same place

**What changed in the chat widget (`public/index.html` patches):**
- New `extractProspectEmail()` helper: walks the chat history, finds Mercer's email-ask lines, regexes the next user line for `name@host.tld` shape, falls back to scanning all prospect messages for any email-shaped string
- `postProspectHandoff` rewritten to use the unified schema: requires `lead_email` (defer if missing), includes `session_id`, advances `pipeline_stage` in the same atomic write, queues followup if a time is extracted
- Adds an `_prospectPostingInFlight` guard to prevent double-fire on rapid typing
- Sends the prospect's last message as a `conversation_entry` so the chat message lands in the unified timeline, not just a transcript snapshot

**What changed in the n8n workflows (`~/pantheon/shared/n8n-workflows/*.json`):**
- `mercer-inbound-reply.json` (9.4KB, rewritten) — adds a "Fetch Email Body (Resend API)" node that calls `GET /emails/receiving/{email_id}` to retrieve the actual body (the webhook payload only has metadata, body needs a follow-up call). The "Lookup Lead File" node reads the unified lead file at `~/athenaeum/Codex-God-Mercer/leads/{slug}.json` and pulls the most recent active Mercer session. The "Append to Lead via API" node POSTs to `/api/prospects` so the file write goes through the same atomic-write path as the chat. Added `reply_to: "konan@theoforgesolutions.com"` on outbound.
- `mercer-touch-sequence.json` (7.4KB, rewritten) — reads lead files at the unified path, filters by `pipeline_stage ∈ {appointment, close}` and `re_engagement_allowed !== false`, sends Resend emails with `reply_to: konan@…`, logs back via `/api/prospects`. Cadence: hourly cron checks for day-before (23-26h), morning-of (0-3h), value-add (4-7d).
- `mercer-no-show-followup.json` (5.8KB, rewritten) — daily 9am cron. 7 days = followup 1, 21 days = followup 2, 60 days = archive candidate. Same unified path, same logging.

**What changed in the Mercer system prefix (`lib/mercer.mjs` scheduling block):**
- Added EMAIL CAPTURE section: Mercer asks for the email at scheduling time, framed as "the destination for the calendar invite." Phrasing guidance: "What's the best email for the calendar invite? I'll send the write-up there too."
- Added CHANNEL SWITCHING section: if the lead says "let's keep this in email," Mercer acknowledges and lets the conversation continue over email (n8n's inbound-reply handles the loop). No dragging back to chat.
- Updated TECHNICAL NOTES to reference the unified lead schema path explicitly so Mercer knows where the record lives.

**New routes in `server.mjs`:**
- `POST /api/prospects` (was: `/api/prospects`) — same shape, but now writes to the unified path. Email is required.
- `POST /api/prospects/followup` — same (legacy in-process queue, kept for n8n-down fallback)
- `GET /api/prospects/list` — Konan's morning read. Optional `?stage=appointment` filter
- `POST /api/prospects/depart` — soft-depart a lead. Body: `{lead_email, reason, re_engagement_allowed}`

**Live E2E test (2026-06-06, simulated the full pipeline):**

1. Chat lead created via `/api/prospects` with full chat-channel payload (turn_count=8, audit 5 centers, situation/challenge/etc.) — got `prospectId: lead-1780784020-jane-a08e70`, file at `~/athenaeum/Codex-God-Mercer/leads/jane.json`
2. Day-before touch (simulating n8n's `mercer-touch-sequence` cron) — POST `/api/prospects` with `channel: "email_out"`, `touch_entry: {type: "day_before", sent_at: "..."}`. Same leadId returned (upsert by email). Touch appended to `touch_sequence[]`.
3. Inbound email reply (simulating n8n's `mercer-inbound-reply`) — POST `/api/prospects` with `channel: "email_in"`, `conversation_entry: {channel: "email_in", subject: "Re: Quick reminder", resend_email_id: "..."}`. Same leadId. New conversation entry appended.
4. `GET /api/prospects/list` returned: `jane | jane@acmeroofing.com | appointment | conv: 4 | covered: 4/7 | tags: ['roofing', '12-person', 'founder']`
5. Final lead file showed 4 conversation entries in chronological order:
   - `[system/] pipeline_stage advanced → appointment (booked_slot=...)`
   - `[chat/in] Prospect: Field data lag. Friday 2pm works.`
   - `[email_out/out] Quick reminder — you are set for tomorrow at 2:00 PM UTC`
   - `[email_in/in] Re: Quick reminder — Yeah, this is exactly what I needed.`

One file, one timeline, one schema, all three channels. **Verified end-to-end.**

**What's NOT done yet (still on the backlog):**

- Resend `from` addresses (15 personas) need verification in the Resend dashboard — verified domain `theoforgesolutions.com` is the only thing Resend checks per docs, but DNS MX record for inbound (`10 mx.resend.com`) still needs to be added on theoforgesolutions.com
- The n8n workflows are written but not imported into the running n8n instance. That's a UI action in the browser at `http://localhost:5678`. Workflows → Add → Import from File → pick each JSON → activate
- Composio → Google Calendar still not wired. `COMPOSIO_CONSUMER_KEY` is empty in env, no accounts connected
- The day-before followup still uses the legacy `~/.theoforge/followups/{date}.jsonl` queue as a fallback. Once n8n is running, the n8n `mercer-touch-sequence` cron replaces it
- Future CRM dashboard — not built. This unified schema is the foundation

**File-level changes summary (this phase):**

- `lib/prospect.mjs`: rewritten (20.6KB, was 8.8KB)
- `lib/lead.mjs`: rewritten (3.9KB, was 3.4KB) — form now writes to the unified path
- `lib/mercer.mjs`: updated scheduling block in `buildWrappedTurn` (17.4KB, was 16KB)
- `server.mjs`: 2 new routes, updated imports + banner (15.4KB, was 13.4KB)
- `public/index.html`: `extractProspectEmail` helper added, `postProspectHandoff` rewritten (73.9KB, was 70.2KB)
- `~/pantheon/shared/lead-schema.md`: NEW (16KB, canonical schema spec)
- `~/pantheon/shared/n8n-workflows/mercer-inbound-reply.json`: rewritten (9.4KB, was 7.4KB)
- `~/pantheon/shared/n8n-workflows/mercer-touch-sequence.json`: rewritten (7.4KB, was 7.5KB)
- `~/pantheon/shared/n8n-workflows/mercer-no-show-followup.json`: rewritten (5.8KB, was 5.2KB)
- `~/pantheon/shared/active/theoforge-landing-v9-build.md`: this section

**Server:** PID 1143425, port 4321, all 8 routes live (`/`, `/healthz`, `/api/leads`, `/api/chat`, `/api/mercer/message`, `/api/mercer/reset`, `/api/mercer/health`, `/api/prospects`, `/api/prospects/followup`, `/api/prospects/list`, `/api/prospects/depart`).
