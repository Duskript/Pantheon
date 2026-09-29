# Self-Hosted Mailing List Options for the Newsletter Landing Page

Generated: 2026-08-09
Owner: Hermes
Context: Iris landing page mockup posts signup payloads to `POST /webhook/newsletter-signup`; CachyOS already runs n8n, so the mailing list app should be easy for n8n to call.

## Short answer

Use **listmonk** for v1. It is the cleanest match for this project: self-hosted, newsletter/list focused, Docker/simple-binary deployable, PostgreSQL-backed, and lightweight.[1][2]

It is also API-friendly for n8n because listmonk documents REST-like JSON APIs and subscriber creation endpoints.[11][12]

The runner-up is **Keila** if we want a prettier newsletter-editor/form-builder experience and privacy-first defaults, but it has a smaller community and a heavier Elixir/Phoenix-style operational footprint than listmonk.[3][4]

Use **Mautic** only if we decide this newsletter is actually a full marketing automation/lead-scoring machine. It is powerful, has first-class n8n support, but it is overkill for “capture signup → send field report → track engagement.”[5][6][13]

## Decision criteria

For this newsletter pipeline, the mailing-list app needs to:

1. accept signups from the landing page or n8n;
2. support lists/segments/tags/custom fields;
3. support double opt-in or at least clean consent tracking;
4. support broadcast newsletters and basic analytics;
5. use an external sender cleanly: SES, Postmark, Mailgun, SendGrid, SMTP, etc.;
6. run safely behind Tailscale/reverse proxy;
7. avoid becoming a giant marketing-automation project before we validate demand.

## Ranked options

### 1. listmonk — recommended v1 pick

**Fit:** best.

listmonk describes itself as a self-hosted newsletter and mailing-list manager, free/open source, with Docker and single-binary install paths.[1] Its GitHub README says it is standalone, self-hosted, fast, feature-rich, and uses PostgreSQL.[2]

Why it fits this pipeline:

- Built exactly for newsletters/mailing lists, not a whole CRM.
- Docker path is simple: `listmonk/listmonk:latest` plus Postgres.[1]
- Official docs say all dashboard features are exposed through REST-like JSON APIs, with API users/tokens created in the admin UI.[11]
- Subscriber API supports `POST /api/subscribers`, public subscription endpoints, updating subscribers, and list membership changes.[12]
- Handles segmentation with SQL expressions, analytics, templates, multi-SMTP queues, rate limits, transactional messages, and messenger webhooks.[1]
- Lightweight enough to run on CachyOS beside n8n without turning the box into a PHP hydra.[1]

How we would hook it up:

```text
Landing page form
  → n8n webhook /webhook/newsletter-signup
  → validate email + consent
  → Listmonk HTTP Request: POST /api/subscribers
  → add subscriber to “Operator Field Report” list
  → optional: send opt-in confirmation / welcome email
  → Discord/Telegram notification
```

Main tradeoffs:

- Less “marketing automation canvas” than Mautic.
- Editor/forms are good enough, not Mailchimp-polished.
- We still need a real SMTP/ESP for deliverability; self-hosting the list app does not magically make inbox placement safe.

**Verdict:** choose this unless we explicitly need multi-step automation/lead scoring on day one.

---

### 2. Keila — best nicer-newsletter UX alternative

**Fit:** good.

Keila is a 100% open-source newsletter tool, made in Germany/hosted in the EU, with visual editor, Markdown, MJML, form builder, custom fields, captcha/double opt-in, analytics, segmentation, Liquid templates, API, CSV import/export, and bring-your-own email via SMTP/SES/Mailgun/Postmark/SendGrid.[3]

Its GitHub README says Keila is an open-source Mailchimp/Sendinblue alternative, supports sign-up forms, can send via own inbox for small newsletters, and supports AWS SES, SendGrid, Mailgun, Postmark, and SMTP; it also has an official Docker image and sample Docker Compose.[4] The self-hosting docs say Keila is available as Docker image `pentacent/keila` and needs PostgreSQL.[3]

Why it might beat listmonk:

- Cleaner newsletter-authoring UX.
- Built-in form builder and bot protection/double opt-in story.
- Strong privacy posture and easy tracking-off option.
- Good if Iris cares about the editor/admin experience.

Main tradeoffs:

- Smaller community than listmonk: ~2.2k GitHub stars vs listmonk’s ~22.6k at retrieval time.[2][4]
- Less battle-tested at huge scale.
- Elixir/Phoenix app means slightly more operational weirdness than a Go binary if something breaks.

**Verdict:** evaluate second if listmonk feels too utilitarian or if native signup-form/double-opt-in UX matters more than lowest ops burden.

---

### 3. Mautic — strongest automation, wrong-sized for v1

**Fit:** powerful but too much for the first validation loop.

Mautic positions itself as the world’s largest open-source marketing automation product, with campaign builder, email/page builder, privacy/GDPR features, REST API, lead nurturing/scoring, and plugin extensibility.[5] Its GitHub repo has a large, mature codebase and community footprint.[6]

Why it is attractive:

- Native marketing automation, scoring, segments, campaigns, landing pages.
- n8n has a Mautic integration surface, and Mautic’s own blog says n8n can create/update contacts, add tags, add/remove contacts from segments/campaigns, edit Do Not Contact, send campaign-type emails, and adjust points.[13]
- Better future fit if this becomes a serious lead-nurture engine for TheoForge/business services.

Why not v1:

- More moving parts: PHP app, cron workers, queue/database maintenance, marketing-automation configuration.
- Easy to burn setup time before we know whether the newsletter attracts subscribers/replies.
- We already have n8n for workflow logic; using Mautic’s full automation canvas now duplicates complexity.

**Verdict:** keep as phase-2/phase-3 if the list validates and we need lead scoring/nurture campaigns.

---

### 4. SendPortal — Laravel-friendly middle ground

**Fit:** possible, but not first choice here.

SendPortal is open-source self-hosted email marketing software with newsletter management, subscriber/list management, campaign management, message tracking, reports, multiple workspaces, and a REST API.[7] Its GitHub README says it integrates with Amazon SES, Postmark, SendGrid, Mailgun, and Mailjet, and requires PHP 8.2+, Laravel 10+, and MySQL or PostgreSQL.[10]

Why it might fit:

- Polished enough, newsletter-centric, REST API.
- Good if we want Laravel-stack familiarity.

Why not first:

- More framework ops than listmonk.
- Smaller/lower-activity footprint than listmonk.
- No obvious advantage for our n8n-first signup flow.

**Verdict:** fine tool, but listmonk/Keila are better matches.

---

### 5. Mailtrain — legacy/stable, but operationally chunky

**Fit:** avoid unless we inherit an existing Mailtrain setup.

Mailtrain v2 is a self-hosted newsletter app built on Node.js and MySQL/MariaDB, with subscriber list management, segmentation, custom fields, MJML templates, reports, automation, permissions, namespaces, and builtin Zone-MTA.[8]

Why it is not first:

- Recommended minimum hardware in the README is 2 vCPU and 4096 MB RAM.[8]
- It uses three endpoints — trusted, sandbox, public — for security/XSS isolation, which means more reverse proxy/DNS ceremony than we need.[8]
- The workflow is heavier than listmonk for a first newsletter capture lane.

**Verdict:** not worth the ceremony for this use case.

---

### 6. phpList — mature but dated

**Fit:** avoid for this project.

phpList is open-source newsletter/email marketing software and has a long-running community; the site reports broad country usage and current release activity.[9]

Why not first:

- Older UX/admin model.
- Less aligned with n8n/API-first operator workflow.
- Reasonable for nonprofits/legacy LAMP comfort, but not for a fast operator-grade landing page/list pipeline.

**Verdict:** skip unless there is a very specific phpList reason.

## SMTP / deliverability reality check

Self-hosting the app is not the same as self-hosting deliverability. For a public newsletter, use a reputable sender/relay and set up SPF, DKIM, DMARC, bounce handling, unsubscribe, and double opt-in. listmonk, Keila, SendPortal, Mautic, and Mailtrain can manage lists/campaigns, but the actual outbound sender should probably be one of:

- Amazon SES — cheapest at scale, more setup friction.
- Postmark — excellent deliverability, pricier, strong for transactional; can still handle broadcasts depending policy/use.
- Mailgun — flexible, okay with bulk if configured properly.
- SendGrid — broad support, mixed reputation depending account quality.
- Brevo/SMTP2GO/etc. — possible if cost/deliverability works.

For v1, I would not run our own SMTP/MTA. That is a deliverability swamp, boss. Let the app be self-hosted; let email delivery use a real relay.

## Recommended v1 architecture

```text
Iris static landing page
  form action: POST /webhook/newsletter-signup
      ↓
CachyOS n8n workflow
  validate email + consent
  normalize fields
  write audit row to Google Sheet/Postgres
  POST subscriber to listmonk API
  send double opt-in/welcome if configured
  notify Hermes/Konan
      ↓
listmonk
  Operator Field Report list
  segments: AI agents, business automation, MCP/tools, revenue experiments
  campaigns: first issue + weekly field reports
      ↓
SMTP relay
  SES/Postmark/Mailgun/etc.
```

## My recommendation

Start with **listmonk + external SMTP relay**, wired through n8n. It gives us the fewest moving pieces and the cleanest bridge from the existing landing page contract.

If we hit UX friction in authoring newsletters, test **Keila** before reaching for Mautic.

If the newsletter starts driving real leads and needs behavior-triggered nurture, then graduate to **Mautic** or integrate listmonk events into a separate CRM/automation layer.

## Immediate next steps

1. Deploy listmonk locally/tailnet-only on CachyOS or the Pantheon host.
2. Create list: `Operator Field Report`.
3. Create fields/attributes: `name`, `interest`, `source`, `consent_at`.
4. Create least-privilege API user/token for subscriber create/update only.
5. Adapt the n8n starter workflow:
   - landing page webhook;
   - validation/consent;
   - `POST /api/subscribers` to listmonk;
   - notification;
   - success/error JSON response.
6. Add SMTP relay after list capture works.
7. Send a single test signup through the real landing-page form and verify it appears in listmonk.

## Sources

[1] https://listmonk.app — listmonk — self-hosted newsletter and mailing list manager
[2] https://github.com/knadh/listmonk — knadh/listmonk GitHub repository
[3] https://www.keila.io — Keila — Open Source Email Newsletters
[4] https://github.com/pentacent/keila — pentacent/keila GitHub repository
[5] https://www.mautic.org — Mautic — Open Source Marketing Automation
[6] https://github.com/mautic/mautic — mautic/mautic GitHub repository
[7] https://sendportal.io — SendPortal — Open Source Email Marketing Software
[8] https://github.com/Mailtrain-org/mailtrain — Mailtrain v2 GitHub repository
[9] https://www.phplist.org — phpList.org
[10] https://github.com/mettle/sendportal — mettle/sendportal GitHub repository
[11] https://listmonk.app/docs/apis/apis — listmonk API introduction
[12] https://listmonk.app/docs/apis/subscribers — listmonk subscribers API
[13] https://n8n.io/integrations/mautic — n8n Mautic integration actions
