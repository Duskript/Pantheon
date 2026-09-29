# Iris Follow-up — Newsletter Landing Page Backend Clarification

Hermes correction after Konan clarified intent.

## Correction

The n8n AI Workflow Hub repo is not just a public resource hook for readers. Konan's immediate thought is also: use one of those n8n AI workflows as a starter backend workflow for the newsletter list.

## Landing page implication

Please design the newsletter landing page so the signup form can post cleanly to an n8n webhook endpoint later.

Recommended form fields:

- email — required
- name — optional
- interest — optional enum/text, e.g. `AI agents`, `business automation`, `MCP/tools`, `revenue experiments`
- source — hidden value like `newsletter_landing_page`
- consent checkbox/copy — simple explicit opt-in

## UX notes

- Keep the CTA: `Join the field report`.
- The GitHub/resource hook can still exist, but the backend automation is the priority.
- Include success/error states in the mockup:
  - Success: `You're on the list — first field report is coming soon.`
  - Error: `Something glitched. Try again or email me directly.`

## Backend placeholder

Use a placeholder endpoint in the mockup, not a live endpoint yet:

`POST /webhook/newsletter-signup`

No deployment yet unless Konan approves.
