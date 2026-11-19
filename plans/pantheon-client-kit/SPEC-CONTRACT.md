# Pantheon Client Kit — Spec Contract

**Date:** 2026-11-15 · **Author:** Hermes · **Status:** decisions locked by Konan; **Phases 1–2 built 2026-11-18**
**Origin thread:** answers to the 4 forks from *Package Pantheon install with fresh memory* (2026-11-13).

## Build status (2026-11-18)

| Phase | Deliverable | State |
|-------|-------------|-------|
| **1 — Identity engine** | `webui/api/interview_engine.py` (spec-driven, 2 layers, skip logic, unknowns-as-open), CLI runner, WebUI endpoints at `/api/client-kit/interview{,/answer,/reset,/render}`, `tests/test_interview_engine.py` (27 tests) | ✅ **built** |
| **2 — Roster installer** | `client-kit/manifest.yaml`, `client-kit/roster_install.py` (render → place → scrub), `--client` mode in `install/install-pantheon.sh` (+ phase 8b), `tests/test_client_kit_roster.py` (21 tests), `client-kit/README.md` | ✅ **built** |
| **3 — Conductor onboarding** | `client-kit/conductor_onboard.py` (invites from the token's own client_id, permission split, ordered mesh plan, per-god lanes, PHONEBOOK, verification checklist) + `client-kit/portal_intake.py` (CDP portal intake, health-checked, fork A) + phase 8c in the installer, `tests/test_conductor_onboarding.py` (29) + `tests/test_portal_intake.py` (14) | ✅ **built** — plan-first; **live apply needs a real tenant** |
| **4 — Packager** | `pantheon-client-kit.tar.gz` with the interview engine/`interview.yaml` copied in (the pack is not yet self-contained), plus the interactive interview runner | ⬜ not started |
| **5 — (parked)** | TheoForge PWA on the Hermes Web UI | ⬜ parked by Konan |

### Phase 3 boundaries — what is automatable, and what is not

Restated with the *measured* evidence, because the difference decides the client experience:

- **Discord:** applications cannot be created through the API, so Phase 3 commits to fork A — driving
  the Developer Portal over CDP. `portal_intake.py` health-checks its selector set **before any click**
  and captures the token from the token-reset **response body**, not the DOM. It needs an *external*
  Chromium carrying the client's logged-in session: Lightpanda keeps only logs and has **no cookie
  jar** (measured 2026-11-15), and `browser.cdp_url` is empty by default. No endpoint ⇒ the manual
  checklist (~30–45 s per god) is printed.
- **Telegram:** the hands-free path is real but **dependency-gated** — `telethon` is not installed on
  this box, so the module refuses with `pip install telethon` and still returns the plan.
- **After tokens exist, everything is scripted:** invite URL from the token's own `client_id`
  (base64-decoded first segment; the token itself is never printed), container creation,
  per-god lane config, `PHONEBOOK.json`, gateway unit start, then the live checklist.
- **The permission split is a hard gate.** Workers are least-privilege `379968`; the conductor needs
  `MANAGE_CHANNELS|MANAGE_ROLES|CREATE_PUBLIC_THREADS|MANAGE_THREADS` → `51808422992`. Handing a
  worker invite to the conductor would fail live at "create the category", so the kit refuses it and
  says which bits are missing.
- **Nothing destructive, ever.** The executor refuses any `DELETE`; a mis-targeted call against a
  client's live guild is unrecoverable.
- **A plan is a first-class output.** Every phase is plan-first: `install-pantheon.sh --phase 8c`
  prints the live-verification signals and the ordered call list, and refuses to call a platform
  without `--conductor-token-file` (read from a file, never argv — argv leaks into shell history).

### §7.2 roster defects — fixed, not inherited (2026-11-18)

Repaired in place on the live fleet by `roster_install.py --sanitize`, with the artwork
proved hash-identical and the live `/api/gods/<n>/icon` route re-verified:

- **rheta** — 447,678-char inline data-url extracted to `icon.png` (the payload was JPEG
  behind a PNG label; the serving route sniffs magic bytes, so the bytes go in `icon.png`
  and the field became `/api/gods/rheta/icon`).
- **iris** — 2,691,894-char inline data-url extracted likewise.
- **kairos** — had **no `god.json` at all**; created from `manifest.yaml` (avatar still to
  be supplied by the client).
- **thoth / caduceus / rheta / iris** — domains normalised to `Thing · Thing · Thing`.
- **Measured:** 3,194,532 bytes of fleet `god.json` → **796 bytes**.

Two implementation traps found while building this (both silent):
a rename in `manifest.yaml` must propagate to SOUL.md / persona.md / MEMORY.md **and the
Codex directory name**, and the icon route reads **exactly `icon.png`** — the extracted
filename must not follow the payload's true format.

Every claim below is marked verified / unverified, with its evidence.

---

## 1. Locked decisions (Konan, 2026-11-15)

| # | Fork | Choice | What it means concretely |
|---|------|--------|--------------------------|
| 1 | Which gods ship | **B − {apollo, marvin, mercer, hephaestus}** | Client roster = **Hermes, Rheta, Iris, Thoth, Kairos, Caduceus** (6 gods). |
| 2 | Package form | **C** | Both: `--client` mode in `install-pantheon.sh` + in-repo `god-pack/`, **and** a standalone `pantheon-client-kit.tar.gz` for delivery. |
| 3 | Where the interview lives | **C**, primaries = **name, personality, responsibilities** | Extend the `webui/api/soul_forge.py` engine; expose via **both** CLI and WebUI wizard. The identity trio is the primary content — specialized workflows are secondary. |
| 4 | What "fresh memory" means | **C** | Zero runtime memory (no `state.db` history, no `ichor` history, blank MEMORY/USER), **but** the interview seeds a starter memory. The seed question set is the gating deliverable → `seed-interview.md`. |

### Roster verification (why exactly those 6)

`gods/gods.yaml` on disk holds **13** entries: hermes, hephaestus, hephaestus-qa, rheta, iris, mercer, theoforge-ve, thoth, marvin, kairos, apollo, caduceus, mercury.

- Option **B** was the 10 "marketable domain gods": hermes, hephaestus, rheta, iris, mercer, thoth, marvin, kairos, apollo, caduceus.
- Minus apollo, marvin, mercer, hephaestus → **hermes, rheta, iris, thoth, kairos, caduceus**.
- `hephaestus-qa`, `theoforge-ve`, `mercury` were never in B — they are infra/support (a verification instance, a workflow editor, an attached memory node), not product gods. They stay off the client roster.

Hermes ships as the **conductor**: it is the one bot the client sets up by hand, and it then builds the rest (§4).

---

## 2. Scope added 2026-11-15 (channel onboarding)

1. Each god gets its **own channel or topic** and answers freely there (no @mention required).
2. Gods can **send handoffs into another god's channel/topic** — work moves god→god without the human relaying it.
3. Automation target: **one bot set up manually**, which creates all the others and assigns their tokens.
4. During setup, **ask the client whether they want an image assigned to each bot**.
5. *(Parked, future)* — repoint the Hermes Web UI as the primary interaction surface, shipped as a natively-wrapped **PWA for phones branded as a TheoForge app**.

Items 1–2 are already solved on the Pantheon side and are documented; the work is packaging them for a client, not inventing them:

- **Discord:** per-god `allowed_channels` + `free_response_channels`; the real loop-guard is `bots_require_inline_mention: true` on every profile. Cross-lane handoffs ride the Conductor handoff `routing.reply_to_channel` + `~/pantheon/shared/PHONEBOOK.json`.
- **Telegram:** one private supergroup with Topics; per-god `telegram.allowed_topics` is a hard inbound gate; `free_response_topics` gives the no-@mention feel; `ignored_threads: [1]` keeps General dead.

---

## 3. The automation boundary — what is *actually* automatable (verified)

This is the load-bearing constraint. The dream is "one bot creates the rest." The truth differs per platform:

| Platform | Can the conductor create the bots? | Evidence | What stays manual |
|----------|-----------------------------------|----------|-------------------|
| **Telegram** | **YES** — fully | BotFather is reachable only from a **user account**, never the Bot API. A MTProto userbot session (Telethon/Pyrogram) can script `/newbot` for N gods, capture each token, then `/setnewbotname`, `/setuserpic`, `/setdescription`. | **One** interactive userbot login per tenant (api_id/api_hash + phone + code), once. Everything after is hands-free, avatars included. |
| **Discord** | **NO** | Applications/bots **cannot be created via API** — Developer Portal only. Confirmed by Discord's own quick-start ("create an app in the developer portal") and a 2026-08-27 writeup on exactly this gap. | **~30–45 s per god** in the portal (Create App → Bot tab → Reset Token → enable *Message Content* + *Server Members* intents). Everything after the token exists is scripted. |
| **Discord — browser-driven portal (COMMITTED, fork A)** | Fragile but chosen | Drive the Developer Portal with an authenticated browser session over CDP. Capture the generated token from the **token-reset XHR response**, not by scraping the DOM. | The client's **one-time Discord login** in the automation browser profile. ToS-gray; breaks on portal redesigns → needs a health check in the kit. |

**Consequence:** the automation story differs by platform, and fork A makes Discord *hands-free at the cost of fragility*:

- **Telegram** — one userbot login, then N bots + names + avatars, zero further clicks. Robust (BotFather's interface is stable and MTProto is a supported API).
- **Discord** — one browser login, then N bots created by driving a **single-page app that redesigns without notice**. Same zero-clicks outcome, materially higher maintenance risk. Build a portal-selector health check into the kit, and keep the manual-portal path documented as the fallback when it rots.

> Unverified-vs-verified note: `telethon` is **not installed** on this box (verified — ImportError in both system python and the hermes venv). The Telegram path is a dependency to add, not a capability assumed to exist. The browser path's feasibility against the live portal is being probed, not assumed — see §8.

---

## 4. What the conductor does once tokens exist (all of this IS scriptable)

1. **Build the invite URL** from the token's client_id (base64-decode the first token segment — verified recipe, currently in `pantheon-discord-god-routing/references/discord-invite-link.md`).
2. **Invite** the bot, then **create the container**: category + one channel (or topic) per god.
3. **Set per-god identity**: bot display name + avatar.
4. **Write per-god `.env`** (token, `allowed_channels`, `free_response_channels`, allowlists, home channel) and **`config.yaml`**.
5. **Write `PHONEBOOK.json`** — god → home channel, free-response set, reply protocol (this is what makes cross-god handoffs land in the right lane).
6. **Enable + start the per-god gateway units.**
7. **Verify live**: adapter reports connected, the channel whitelist is honored, and a real round-trip post succeeds.

### Permission finding (live, 2026-11-15) — the conductor needs a *different* invite than the workers

Current per-god invite permission integer is **`379968`**:

```
ADD_REACTIONS (64) · VIEW_CHANNEL (1024) · SEND_MESSAGES (2048) · EMBED_LINKS (16384)
ATTACH_FILES (32768) · READ_MESSAGE_HISTORY (65536) · USE_EXTERNAL_EMOJIS (262144)
```

That set has **no** `MANAGE_CHANNELS` (1<<4), **no** `MANAGE_ROLES` (1<<28), **no** `CREATE_PUBLIC_THREADS` (1<<35), **no** `MANAGE_THREADS` (1<<34). So:

- **Worker gods stay least-privilege at `379968`** — they only ever need to talk.
- **The conductor bot needs an elevated invite:** `379968 | 16 | 268435456 | 34359738368 | 17179869184` = **`51808422992`**.

Reference (verified live on the Pantheon guild `1499851384814702783`, 14 members, 23 channels): categories **"Pantheon Gods"** and **"Text Channels"** already exist, and every god channel lives under them — so the conductor's job on an existing install is to *reuse* the container, and on a fresh install to create it. `MANAGE_ROLES` matters because locking a client-visible category requires denying `@everyone`, which `MANAGE_CHANNELS` alone cannot do.

---

## 5. Build phases

| Phase | Deliverable | Depends on |
|-------|-------------|-----------|
| **1 — Identity engine** | `soul_forge.py` refactored into a god-agnostic interview engine that emits name/personality/responsibilities (SOUL.md + persona.md + god.json) for any of the 6; CLI + WebUI surfaces. | approval of `seed-interview.md` |
| **2 — Roster installer** | `--client` mode in `install-pantheon.sh`: 6-god manifest, memory scrub (blank MEMORY/USER, no state.db/ichor history), `config.yaml` templating (creds stripped), Codex scaffolding, **and the roster defects in §7.2 fixed on the way through**. Pack lives at `~/pantheon/client-kit/` (§7.4). | Phase 1 |
| **3 — Conductor onboarding** | Platform choice → token acquisition (Telegram userbot / Discord portal intake) → channel mesh creation → allowlist + PHONEBOOK wiring → gateway start → live verification. | Phase 2 |
| **4 — Packager** | `pantheon-client-kit.tar.gz` + the interactive interview runner shipped inside it. | Phase 3 |
| **5 — (parked)** | TheoForge PWA on the Hermes Web UI. | Konan's go |

---

## 6. Decisions (Konan, 2026-11-15 — second pass)

| # | Fork | Decision | Implemented as |
|---|------|----------|----------------|
| **A** | Discord bot creation | **Browser-driven** — no manual portal clicking for the client | The kit drives the Developer Portal over CDP from a persistent automation browser profile. The client logs into Discord **once** in that profile. Token is captured from the token-reset XHR response (structured data, survives cosmetic DOM churn); selectors are health-checked. Manual portal path stays documented as the fallback. |
| **B** | Client's default platform | **Ask the client — and explain the trade** | The interview (T8) must not just ask "Telegram or Discord?" — it explains both, so the client chooses knowingly. Decision aid below. |
| **C** | Per-bot images | **Client uploads.** Generation is not assumed available. | Avatar intake = file upload per god. Opt-in: browser-drive Gemini to generate avatars — **future option, explicitly parked**, not in this build. |
| **D** | God names | **Personalisation is highly recommended; defaults allowed** | Interview leads with name/personality/responsibilities and *recommends* personalising, but accepts "keep the defaults" as a first-class answer (one click), which then skips the rest of the identity trio. |

### B — the platform decision aid the interview must present

| | **Telegram** | **Discord** |
|---|---|---|
| Per-god lane | One topic inside a private supergroup | One channel (or thread) per god |
| Setup automation | One userbot login → all bots created, named, avatar set, zero clicks | One browser login → all bots created via portal automation (fragile path) |
| Robustness of the automation | High — MTProto is a supported API, BotFather's UI is stable | Medium — driving a SPA that redesigns without notice |
| Human/thread model | Topics; simpler, fewer controls | Categories, roles, per-channel permissions, threads — richer containment |
| Access model | `TELEGRAM_ALLOWED_USERS` / group-scoped allowlists | `DISCORD_ALLOWED_USERS` + per-god `allowed_channels` |
| Best when | You want it working in an afternoon and never think about it | You want a real server structure and strict per-lane containment |

### C — parked, explicitly out of scope
Browser-driving Gemini (or any image tool) to generate per-god avatars. Revisit after the kit ships; the intake is a file upload until then, with a clear "upload an image" prompt and a default totem if they decline.

---

## 7. Phase-0 findings (measured 2026-11-15, read-only)

These were found *after* the spec was first written, while grounding the build. Each changed a design decision.

### 7.1 Fork A is viable — the portal renders, CDP is available

| Probe | Result |
|-------|--------|
| Load `discord.com/developers/applications` in the browser engine | **Renders.** Title `My Applications \| Discord Developer Portal`; real DOM (React root `app-mount`); pre-login buttons present including **`New Application`** and `Log In`. |
| `cdp('Network.enable')` / `cdp('Page.enable')` | **OK** — so the token can be captured from the token-reset **response body**, not scraped from the DOM. |
| Persistent login storage | Lightpanda's cache holds **only logs — no cookie jar**. So the client's Discord session cannot live there. |
| `browser.cdp_url` in config | **Present and empty** — the kit can point the driver at an **external Chromium carrying the client's logged-in profile** instead. |

**Design consequence:** the Discord path is *"external Chromium over CDP, driven by the kit"*, not *"Lightpanda"*. Lightpanda proved the SPA renders and the elements exist; the authenticated session has to come from a real browser profile. This is a Phase-3 build item, and the selector set needs the health check promised in §3.

### 7.2 Roster audit — three real defects the kit must fix, not inherit

Full detail in `roster.yaml`. Summary:

1. **`kairos` has no `god.json` at all.** No display name, icon, or colour. A client install would ship a god with no visual identity. → the interview must collect it (G1) or the kit must generate it.
2. **3.1 MB of inline base64 icons**: `rheta` 447,678 chars, `iris` 2,691,894 chars. Both bake Konan's own artwork into a file the client receives, and inflate the kit. → strip to files or drop in favour of the client's upload (fork C).
3. **Domain strings are inconsistent and one is mis-cased** (`Copywriting rhetoric And persuasion`, `God of UI/UX Design`, `Medical assistant`, `Messenger · Gateway · Operations`). → normalise to one `Thing · Thing · Thing` style before shipping.

### 7.3 The roster cut breaks Kairos's routing map

`kairos`'s live routing sends implementation/scheduling to **Hephaestus** and pulls customer language from **Mercer**. **Neither god ships.** Left alone, Kairos hands work to gods that don't exist in the client install.

Remapped in `roster.yaml` to `{research: thoth, copy: rheta, visuals: iris}`, with implementation/scheduling falling back to the conductor or the client's own tooling.

**Two further consequences of the cut, documented rather than papered over:** the kit ships **no builder** (Hephaestus + Marvin are out, so nothing can write code or tooling for the client) and **no sales god** (Mercer is out, so lead qualification has no owner). Both are stated limits in the client README, not silent gaps.

### 7.4 Directory name

The in-repo pack lives at **`~/pantheon/client-kit/`** — *not* `god-pack/` as §5 first said, because `~/pantheon/god-packages/` already exists (shared-skills + fleet-skills) and two near-identical names is how the wrong directory gets edited. §5 corrected above.

---

## 8. Provenance

Every command in this spec was read-only, run 2026-11-15 between 13:55 and 14:05 MST. No file was written outside `~/pantheon/plans/pantheon-client-kit/`, no service restarted, no config edited, no token printed (client ids derived by base64-decoding the first token segment only).
