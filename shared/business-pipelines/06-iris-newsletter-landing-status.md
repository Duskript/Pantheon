# Iris Status — Newsletter Landing Page Mockup

Generated: 2026-08-09T18:02:24Z

## Decision shipped

Iris created a first-pass static landing page for the business-centric newsletter as a dark, operator-grade field report page: clear promise, signup-first conversion path, and a companion `Best GitHub Tools for Business Automation` resource hook.

## Artifacts

Directory: `/home/konan/pantheon/shared/business-pipelines/iris-newsletter-landing/`

- `index.html`
- `README.md`
- `preview-desktop.png`
- `preview-mobile.png`

## Verification

- Required signup fields present: email, name, interest, source, consent.
- Form action/method: `POST /webhook/newsletter-signup`.
- Static success and error states included.
- Prohibited topics absent from page text.
- WCAG AA contrast spot checks passed.
- Chrome headless rendered desktop and mobile screenshots.

## Not done

- No deploy.
- No backend wiring.
