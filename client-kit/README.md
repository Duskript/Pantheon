# Pantheon Client Kit

Ship six gods to a client: **hermes** (the conductor), **rheta**, **iris**, **thoth**,
**kairos**, **caduceus**. The kit renders them from the same interview spec the
onboarding wizard asks questions from, places them, and then removes every trace of
the operator's runtime from them.

Roster locked 2026-11-15: option B minus `{apollo, marvin, mercer, hephaestus}`.

## What's in the box

| File | Job |
|---|---|
| `manifest.yaml` | **The pack's source of truth.** Per-god identity, routing, normalised domains, the known limits, and the placement layout. A maintainer edits this file, not the code. |
| `roster_install.py` | The installer: render → place → scrub. Also the pack's self-audit (`--check`) and the live-profile repair tool (`--sanitize`). |
| `interview_engine.py` *(Phase 4)* | Will be copied in here so the pack is self-contained; today the installer reads it from `webui/api/` plus `plans/pantheon-client-kit/{interview,roster}.yaml`. |

## Usage

```bash
# Audit the pack before it touches anything (exits 1 on any defect)
python3 client-kit/roster_install.py --check

# Rehearse — prints what it would do, writes nothing
python3 client-kit/roster_install.py --root /home/client --dry-run

# Install, with the client's interview answers if you have them
python3 client-kit/roster_install.py --root /home/client --answers answers.json

# As part of the whole install
bash install/install-pantheon.sh --client --client-root /home/client
bash install/install-pantheon.sh --client --client-dry-run --phase 8b   # rehearsal
```

`--root` defaults to `$HOME`; the installer refuses to write outside it (every path
is resolved and checked with `relative_to`, and the guard is unit-tested).

## The scrub is the point

A client kit that ships the operator's memory is a data leak, not an onboarding.
For every profile it creates, the installer deletes `state.db*`, `response_store.db*`,
`verification_evidence.db*`, `lcm.db*`, `*.bak*`, and the `sessions/`, `cron/`,
`ichor/`, `memories/`, `webui_state/` trees — and **blanks** `MEMORY.md` and `USER.md`
rather than deleting them, because the runtime expects the files to exist. The
fleet-level `~/.hermes/memories/MEMORY.md` and `USER.md` are blanked too.

## Known limits (shipped as documentation, not discovered by the client)

- **No builder.** Hephaestus and Marvin are unshipped, so nothing in this install
  writes code or builds tooling. Phase 8 skips the Hephaestus assets and Phase 9
  skips his skill manifest for the same reason.
- **No sales god.** Mercer is unshipped; lead qualification has no owner.
- **No fleet cron.** Phase 11 is skipped in client mode — those jobs (dawn patrol,
  digests, tech-debt scans) are the operator's. A client's schedule comes from the
  interview: T4 sets the timezone, G9 sets recurring work.
- **Discord bots are created in a browser.** Applications cannot be created through
  the Discord API; the kit drives the Developer Portal from one logged-in profile.

## The roster defects this kit exists to stop

Found by reading the real profile files — none of it is visible from a roster list.
`--sanitize` repairs them in place, on a live tree, without losing artwork:

| God | Defect | Repair |
|---|---|---|
| rheta | `icon` was a **447,678-char** inline base64 data-url (and mislabeled: a PNG data-url carrying JPEG bytes) | bytes extracted to `icon.png` (sha256-identical), field became `/api/gods/rheta/icon` |
| iris | `icon` was a **2,691,894-char** inline data-url — the single largest bloat item | extracted to `icon.png`, served path written |
| kairos | **no `god.json` at all** — no display name, icon or colour anywhere in the UI | created from `manifest.yaml`; avatar still to be supplied |
| thoth, caduceus, rheta, iris | domains rendered four different ways (`God of Knowledge`, `Medical assistant`, `Copywriting rhetoric And persuasion`) | normalised to `Thing · Thing · Thing` |

Measured on the live fleet, 2026-11-18: **3,194,532 bytes of `god.json` → 796 bytes**,
with the artwork hash-identical and the live `/api/gods/<n>/icon` route still serving it
(200, `image/jpeg` for rheta, `image/png` for iris).

> Two traps worth remembering, because both look fine until they don't:
> a rename in `manifest.yaml` must propagate to SOUL.md, persona.md, MEMORY.md **and the
> Codex directory name**, or one install renders one identity two ways; and the serving
> route reads **exactly `icon.png`** and sniffs the Content-Type itself, so the extracted
> filename must not follow the payload's real format.

## Verification

```bash
python3 -m pytest tests/test_client_kit_roster.py tests/test_interview_engine.py -q   # 48 tests
```

The suite drives synthetic reproductions of every live defect (JPEG-behind-a-PNG-label,
a missing `god.json`, a dirty profile full of history) plus the traversal guard, the
secret gate, dry-run purity, and idempotency.

---

# Conductor onboarding (Phase 3)

`conductor_onboard.py` takes the client from *"I made one bot by hand"* to *"all six
gods are live, each in its own lane, verified"*. The conductor is **hermes** — the one
bot the client creates manually; this module does everything after that.

```bash
python3 client-kit/conductor_onboard.py --check                     # permissions + manifest
python3 client-kit/conductor_onboard.py --platform discord \
        --guild-id <id>                                            # the ordered call list
python3 client-kit/conductor_onboard.py --platform telegram --verify # what must be observed
```

As part of the install: `install-pantheon.sh --client --phase 8c
--conductor-platform discord --conductor-guild <id>`. It prints the live-verification
signals **first**, then the plan, and calls nothing. `--conductor-apply` needs
`--conductor-token-file` — a token on argv leaks into shell history and the process
listing.

## The permission split is a hard gate, not a note

| Role | Permission integer | Bits |
|---|---|---|
| Worker god | `379968` | reactions, view/send, embed, attach, history, external emoji |
| **Conductor** | `51808422992` | workers **+** `MANAGE_CHANNELS`, `MANAGE_ROLES`, `MANAGE_THREADS`, `CREATE_PUBLIC_THREADS` |

Handing a worker invite to the conductor fails *live*, at "create the category". The kit
refuses it up front and names the missing bits.

## What is scripted, and what stays manual

Everything after a token exists: the invite URL (built from the token's own
base64-decoded `client_id` — **the token itself is never printed or embedded**), the
container (category + one channel per god, reuse-then-create), per-god identity, the lane
config, `PHONEBOOK.json`, and the live checklist.

The two exceptions are honest and measured:

- **Discord applications cannot be created through the API.** `portal_intake.py` drives
  the Developer Portal over CDP instead — health-checking its selectors **before any
  click** (a redesign stops the run rather than guessing at new markup) and reading the
  token from the token-reset **response body**, never the DOM. It needs an external
  Chromium carrying the client's login; with no `browser.cdp_url` it prints the manual
  checklist (~30–45 s per god).
- **Telegram's hands-free path needs `telethon`**, which is not installed here. The module
  refuses with `pip install telethon` and still returns the plan.

## Verification signals (nothing is "done" until it is observed)

Discord: adapter connected → own-lane post answered without an @mention → the same post in
*another* god's channel ignored → nothing routes to `#general`.

Telegram: adapter connected → an unmentioned group message reaches a god at all (privacy
mode off) → the log line `Ignoring messages in chat <chat_id> topic 1: not in
allowed_topics [...]` → own-topic post answered without an @mention. That log line was
read out of a real gateway on 2026-11-15, and it proves privacy mode *and* the topic lock
in one line.

