# Iris Newsletter Landing Mockup

Generated: 2026-08-09T18:02:24Z
Owner: Iris
Status: first-pass static mockup only; not deployed.

## Artifacts

- `index.html` — self-contained static HTML/CSS landing page mockup.
- `preview-desktop.png` — Chrome headless render at 1440×1600.
- `preview-mobile.png` — Chrome headless render at 390×1200.

## Design direction

Business/operator tone: dark, credible, technical, and conversion-focused without drifting into neon AI spectacle. The page frames the offer as a field report for operators turning tools into margin, with a visible signup card and a companion resource hook.

Primary CTA copy is exactly:

`Join the field report`

Companion resource hook:

`Best GitHub Tools for Business Automation`

## Backend placeholder contract

The form is designed to later post cleanly to n8n:

- Method: `POST`
- Action: `/webhook/newsletter-signup`
- Fields:
  - `email` — required email input
  - `name` — optional text input
  - `interest` — optional select with `AI agents`, `business automation`, `MCP/tools`, `revenue experiments`
  - `source` — hidden value `newsletter_landing_page`
  - `consent` — required explicit opt-in checkbox, value `true`

Static states included in the mockup:

- Success: `You're on the list — first field report is coming soon.`
- Error: `Something glitched. Try again or email me directly.`

## Verification performed

- HTML artifact written and hash-verified by Hermes write tool.
- Python structural check confirmed:
  - form endpoint/method present and correct
  - all required field names present
  - CTA copy present
  - success/error states present
  - resource hook present
  - forbidden public-surface terms absent: phone automation, consignment, flipping, health, Konan, Rudolph
- Contrast spot checks passed WCAG AA threshold:
  - body text on background: 17.32:1
  - muted text on dark panel: 8.70:1
  - button text on gold: 9.15:1
  - gold accent on background: 14.02:1
- Chrome headless rendered desktop and mobile screenshots successfully.

## Gaps / next moves

- This is not wired to a live backend; the form action is intentionally a placeholder.
- No deployment performed.
- Final ESP/list choice still belongs to the backend workflow decision: Mailchimp/Listmonk/Buttondown/etc.
- If approved, next move is Marvin/n8n backend wireup using the starter workflow shape from `05-newsletter-list-n8n-starter-selection.md`, then Iris verifies the page against the live response contract.
