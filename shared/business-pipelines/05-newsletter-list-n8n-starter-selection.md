# Newsletter List n8n Starter Workflow Selection

Generated: 2026-08-09
Owner: Hermes
Source corpus: `emretasss/AI-Workflow-Hub-2000-`

## Correction / intent

Konan clarified that the AI Workflow Hub repo should be used as **starter workflow material for the email newsletter list backend**, not merely as a public reader resource.

## Best starter candidate

### Primary base: `0795_Schedule_Mailchimp_Create_Scheduled.json`

Local copy:

`/home/konan/pantheon/shared/business-pipelines/n8n-starter-workflows/raw-candidates/0795_Schedule_Mailchimp_Create_Scheduled.json`

Source path:

`workflows/0795_Schedule_Mailchimp_Create_Scheduled.json`

Why this is the best base:

- It is already newsletter-list shaped.
- It reads newsletter submissions from Google Sheets.
- It loops over each item.
- It adds each subscriber to Mailchimp.
- Only 6 nodes, so it is understandable and easy to adapt.

Original flow:

`Manual/Schedule Trigger → Google Sheets “Squarespace newsletter submissions” → Split in Batches → Mailchimp “Add new member”`

Recommended adaptation:

`Webhook: newsletter-signup → Normalize/Validate fields → Google Sheets append row → Mailchimp/Listmonk/Buttondown add/update subscriber → Send notification → Return success response`

## Secondary candidates

### `1860_GoogleSheets_Gmail_Automation_Webhook.json`

Local copy:

`/home/konan/pantheon/shared/business-pipelines/n8n-starter-workflows/raw-candidates/1860_GoogleSheets_Gmail_Automation_Webhook.json`

Use for:

- webhook intake pattern
- mapping form fields into clean fields
- saving rows to Google Sheets
- optional AI classification later

Do not use whole workflow initially — it has 24 nodes, Gemini, Gmail drafts, multiple classifiers, and more complexity than we need for first signup capture.

### `0243_HubSpot_Mailchimp_Create_Scheduled.json`

Good reference if we use HubSpot as the source of truth later. Not first pick because it assumes HubSpot and scheduled sync rather than a landing-page signup.

### `0345_Mailchimp_Cron_Create_Scheduled.json`

Good Airtable → Mailchimp reference if we choose Airtable as the lightweight list database. Not first pick unless Airtable becomes the list source.

## Recommended first workflow shape

Minimum viable newsletter-list workflow:

1. **Webhook Trigger**
   - Path: `newsletter-signup`
   - Method: `POST`
   - Expected payload:
     ```json
     {
       "email": "reader@example.com",
       "name": "Optional Name",
       "interest": "AI agents",
       "source": "newsletter_landing_page",
       "consent": true
     }
     ```

2. **Validate / Normalize**
   - Lowercase + trim email.
   - Reject missing/invalid email.
   - Require `consent=true`.
   - Add timestamps and source.

3. **Store raw subscriber row**
   - First choice: Google Sheets, because candidate 0795 already uses Sheets and it is easy to audit.
   - Later: migrate to Listmonk/Postgres if we self-host list management.

4. **Add/update subscriber in ESP**
   - If Mailchimp exists: adapt candidate 0795 directly.
   - If Buttondown/Kit/Listmonk chosen: replace Mailchimp node with HTTP Request/API node.

5. **Notify operator**
   - Discord/Telegram notification with email/name/source.

6. **Respond to landing page**
   - Success: `{ "ok": true, "message": "You're on the list." }`
   - Failure: clear 4xx JSON with reason.

## Raw candidates saved

Directory:

`/home/konan/pantheon/shared/business-pipelines/n8n-starter-workflows/raw-candidates/`

Files saved and JSON-validated:

- `0795_Schedule_Mailchimp_Create_Scheduled.json`
- `1860_GoogleSheets_Gmail_Automation_Webhook.json`

Other candidates inspected but not saved because they are lower-fit references rather than starter bases:

- `0243_HubSpot_Mailchimp_Create_Scheduled.json`
- `0244_HubSpot_Mailchimp_Create_Scheduled.json`
- `0345_Mailchimp_Cron_Create_Scheduled.json`

## Blockers to import/build live

- n8n is live on CachyOS, but `/api/v1/workflows` requires `X-N8N-API-KEY`.
- Hermes currently has `N8N_URL` but no `N8N_API_KEY` in its environment.
- Need a scoped n8n API key before Hermes can import/adapt workflows through API or MCP.

## Recommendation

Use candidate **0795** as the starter workflow, with **1860** as the webhook/form-field reference.

Do not import it untouched. Adapt it into the minimal landing-page capture flow above.
