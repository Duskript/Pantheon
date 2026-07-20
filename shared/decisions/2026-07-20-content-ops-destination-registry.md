# 2026-07-20 — Content Ops Destination Registry

**Decision:** Content Operations targets are modeled as data-driven destinations, not as a fixed `surface` enum. `content_items.surface` remains as the back-compat primary destination slug, but the authoritative targeting model is the `destinations` registry plus `content_item_destinations` join table so one content item can target Konan LinkedIn, Konan Facebook, TheoForge Solutions LinkedIn, TheoForge Solutions Facebook, TheoForgeSolutions Blog, or future destinations such as Bluesky/X without another schema rewrite.

**Rationale:** The dashboard needs to route the same Kairos output to personal and TheoForge accounts across multiple platforms. A hard-coded four-value enum would force code/schema changes for every new channel and could not accurately represent cross-post items. A registry keeps posting metadata (`platform`, `account`, `posting_method`, `phone_package`, `api_enabled`, `active`, `sort_order`) next to the destination and lets the React UI render available targets dynamically.

**Alternatives considered:**
- Keep `surface` as a fixed SQLite CHECK enum: rejected because adding Konan Facebook, Bluesky, X/Twitter, or more blog/account targets would require table rebuilds and code changes.
- Store cross-post targets as comma-separated text on `content_items`: rejected because it is harder to query, validate, and attach phone/API posting metadata.
- Create separate duplicate `content_items` rows per target: rejected because approvals, rewrites, scheduling, and source provenance would drift across duplicates.

**Evidence:**
- Canonical spec updated: `~/pantheon/plans/features/content-operations-dashboard/SPEC.md` fields/API/storage/phone package sections.
- Implementation: `~/projects/content-dashboard/schema.sql`, `~/projects/content-dashboard/models.py`, `~/projects/content-dashboard/app.py`, `~/projects/content-dashboard/mobile-app/src/main.tsx`, `~/projects/content-dashboard/mobile-app/src/styles.css`.
- Verification on 2026-07-20: Python compile passed, SQLite migration seeded `['konan-linkedin', 'konan-facebook', 'theoforge-linkedin', 'theoforge-facebook', 'blog']`, `GET /api/destinations` returned the five destinations, cross-post API smoke returned primary+crosspost destination arrays, `npm run build` passed, browser verified multi-destination badges and dynamic Add-tab destination checkboxes.

**Reversibility:** easy — the old `surface` field remains for compatibility, so callers that only need a single target can keep using it while richer clients read/write `destinations`.

**Decided by:** Konan correction + Hephaestus implementation on 2026-07-20

**Operator sign-off:** konan
