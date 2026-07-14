# TheoForge demo lead capture

Updated: 2026-06-14
Owner: Marvin

## Current state
- Public demo-page form endpoint: `https://theoforgesolutions.com/webhook/theoforge-leads`
- relay-7 Caddy proxies `/webhook/*` to Pantheon n8n over Tailscale: `http://100.68.106.59:5678`
- n8n workflow: `TheoForge Demo Lead Capture` (`CBtxlowywXCODDXT`), active
- Form JS: `/home/konan/workspace/ledger-product-page/modal.js` and `/home/konan/workspace/pantheon-platform-page/modal.js`; deployed to `/var/www/theoforge/demos-site/modal.js` on relay-7
- Storage target: TheoForge Bridge `POST /ingest/prospect`, writing JSON lead files under `/home/konan/athenaeum/Codex-God-Mercer/leads`

## Routing rules
- Ledger early-access form has `data-form-type="early-access"`; JS sends `category: "prospect"`, `notify: false`
- Pantheon contact/team form has `data-form-type="contact"`; JS sends `category: "team_request"`, `notify: true`
- n8n stores every submission through the Bridge
- n8n Telegram notification branch runs only for `notify: true`

## Verification evidence
- Public POST to `https://theoforgesolutions.com/webhook/theoforge-leads` returned `{"message":"Workflow was started"}`
- Prospect test wrote `/home/konan/athenaeum/Codex-God-Mercer/leads/public-prospect-1781402439.json`
- Team-request test wrote `/home/konan/athenaeum/Codex-God-Mercer/leads/public-team-1781402439.json`
- n8n execution list showed team-request execution ran the `Telegram Notify` node
- Live JS contains `/webhook/theoforge-leads`; no placeholder n8n endpoint remains

## Notes
- A Bridge-side notify patch exists in `/home/konan/pantheon/services/theoforge-bridge/server.mjs`, but system service restart was blocked by local sudo. n8n handles Telegram notification independently, so production form flow is working without relying on that bridge restart.
