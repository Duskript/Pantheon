# 2026-07-20 — Content Ops React Mobile UI Pivot

**Decision:** Content Operations Dashboard UI delivery is pivoted from the Appsmith `Pantheon Ops Hub` experiment to a custom React/Vite mobile app served by the existing Flask backend. The canonical UI source is `~/projects/content-dashboard/mobile-app/`; Flask serves its built `dist/` at `/` while preserving the existing `/api/*` routes.

**Rationale:** The Appsmith implementation rendered as an internal-tool table/dashboard and did not match Kairos's handoff: the source spec calls for a card-based approval queue, inline draft review, weekly calendar, TheoForge dark/parchment/gold styling, and a phone-form operator experience. Konan explicitly rejected the Appsmith result as "nothing like what Kairos described" and required the surface to be React-driven and mobile-form-factor.

**Alternatives considered:**
- Keep Appsmith and keep tuning widgets: rejected because the operator rejected the product direction, not just a rendering bug.
- Keep the legacy Flask/Jinja/Tailwind frontend: rejected because the operator explicitly asked for React-driven UI.
- Build a separate React service on another port: rejected for this pass because Flask can serve the built React app at the existing product URL while keeping API routes same-origin.

**Evidence:**
- Operator directive on 2026-07-20: "I need this to be react driven and should be in a mobile form factor. Also this is nothing like what Kairos described in his handoff."
- Source spec: `~/pantheon/plans/features/content-operations-dashboard/SPEC.md` sections 3, 8, 9, and 13.
- Implementation: `~/projects/content-dashboard/mobile-app/src/main.tsx`, `~/projects/content-dashboard/mobile-app/src/styles.css`, and Flask `app.py` serving `mobile-app/dist/`.
- Verification: `npm run typecheck`, `npm run build`, `python3 -m py_compile app.py models.py`, `curl http://127.0.0.1:5000/`, `curl http://127.0.0.1:5000/api/stats`, and browser verification of Approve/Drafts/Calendar/Add mobile views.

**Reversibility:** easy — Appsmith remains on disk as a superseded experiment, and Flask can serve a different frontend by changing `REACT_DIST`/root routing.

**Decided by:** Konan on 2026-07-20; implemented by Hephaestus on 2026-07-20

**Operator sign-off:** konan

**Affected:**
- `~/pantheon/plans/features/content-operations-dashboard/SPEC.md`
- `~/pantheon/plans/features/content-operations-dashboard/BUILD_GRAPH.md`
- `~/projects/content-dashboard/app.py`
- `~/projects/content-dashboard/mobile-app/`
- Appsmith `Pantheon Ops Hub` is superseded as the source-of-truth UI
