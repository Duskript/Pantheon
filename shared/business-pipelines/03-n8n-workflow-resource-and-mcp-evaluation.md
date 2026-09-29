# n8n / Workflow Resource Evaluation — Newsletter Pipeline

Generated: 2026-08-09T17:47:49Z
Owner: Hermes

## Questions from Konan

1. Is `emretasss/AI-Workflow-Hub-2000-` useful for the business newsletter/resource strategy?
2. Is there an n8n MCP that makes it easy for Hermes to manage n8n workflows?
3. What is the state of the n8n instance linked from this system?

## Live local/CachyOS findings

Hermes current MCP registry:

- `hermes mcp list` shows only `code-review-graph` enabled.
- No n8n MCP is currently configured in the active Hermes profile.

Configured remote service metadata exists in `~/.hermes/config.yaml`:

- CachyOS ODS host: `cachyos-konan.tail164759.ts.net`
- n8n URL: `https://cachyos-konan.tail164759.ts.net:5678/`
- n8n health URL: `https://cachyos-konan.tail164759.ts.net:5678/healthz`

CachyOS host proof over Tailscale SSH:

- Remote hostname: `cachyos-Konan`
- OS: CachyOS
- n8n is running via Docker container `ods-n8n` using image `n8nio/n8n:2.6.4`
- n8n listens on `100.114.60.103:5678`, `127.0.0.1:5678`, and Tailscale IPv6.

HTTPS probes:

- `/` => 200 HTML
- `/healthz` => 200 `{ "status": "ok" }`
- `/healthz/readiness` => 200 `{ "status": "ok" }`
- `/api/v1/workflows` => 401 with `'X-N8N-API-KEY' header required`

Conclusion: n8n is live and reachable, but Hermes does not currently have an n8n API key exposed in its environment, so workflow CRUD via API/MCP is blocked until an n8n API key is created/provided.

## AI-Workflow-Hub-2000- evaluation

Repo: `emretasss/AI-Workflow-Hub-2000-`

Observed from GitHub API:

- Total files: 2056
- Workflow files: 2055
- JSON workflows: 2055
- GitHub page reports 289 stars / 67 forks at time of extraction.
- README describes 2000+ free n8n AI automation workflows.

Sample workflow names include:

- `0001_Telegram_Schedule_Automation_Scheduled.json`
- `0003_Bitwarden_Automate.json`
- `0008_Slack_Stripe_Create_Triggered.json`
- `0015_HTTP_Cron_Update_Webhook.json`
- `0018_Manual_Chargebee_Create_Triggered.json`

Usefulness verdict:

- Useful as a raw inspiration/template corpus.
- Not trustworthy as a polished business-resource hub without curation.
- Best role: source material for a curated `Best GitHub Tools / Workflows for Business Automation` resource.
- Avoid bulk-importing random workflows into production n8n; import only after JSON/schema/security review.

Suggested resource angle:

> Best GitHub Tools for Business Automation — curated workflows, MCP servers, open-source automation tools, and operator-ready templates ranked by use case and production readiness.

Initial categories:

1. Lead capture + enrichment
2. Email/newsletter ops
3. CRM + follow-up
4. Content repurposing
5. Reporting/BI
6. Finance/invoicing/admin
7. AI-agent/MCP infrastructure
8. Self-hosted workflow engines

## n8n MCP options

### Recommended primary: `czlonkowski/n8n-mcp`

Evidence:

- GitHub repo: `czlonkowski/n8n-mcp`
- NPM package: `n8n-mcp`
- NPM version observed: `2.69.0`
- License: MIT
- GitHub page reports ~22.6k stars / 3.6k forks at time of extraction.
- Described as an MCP for Claude Desktop / Claude Code / Windsurf / Cursor to build n8n workflows.

Useful capabilities found in README/search results:

- Workflow creation/update/delete/list/get
- Partial workflow updates
- Workflow validation/autofix
- Template deployment
- Execution listing/testing
- Credential/data-table/folder management
- Health check
- Read-only deployment mode via disabled tools

Why it fits:

- Most mature/active-looking option found.
- Has both n8n knowledge/documentation and management tools.
- Supports disabling destructive/sensitive tools, which matters for a production-ish n8n instance.

Recommended initial posture:

- Configure read-only or mostly read-only first.
- Allow list/get/validate/audit/template exploration.
- Disable create/update/delete/test/credential/data-table tools until Konan explicitly approves write access.

Candidate Hermes config shape once an API key exists:

```yaml
mcp_servers:
  n8n:
    command: npx
    args:
      - -y
      - n8n-mcp
    env:
      N8N_API_URL: ${N8N_API_URL}
      N8N_API_KEY: ${N8N_API_KEY}
      DISABLED_TOOLS: n8n_create_workflow,n8n_update_full_workflow,n8n_update_partial_workflow,n8n_delete_workflow,n8n_autofix_workflow,n8n_deploy_template,n8n_test_workflow,n8n_manage_credentials,n8n_manage_datatable
    timeout: 180
    connect_timeout: 90
```

Need to verify exact env var names against the package docs before final install.

### Deprecated/not recommended: `czlonkowski/n8n-manager-for-ai-agents`

- README explicitly says it is no longer actively developed and points to `czlonkowski/n8n-mcp`.
- Do not use unless we need a very small historical reference.

### Alternative: `salacoste/mcp-n8n-workflow-builder`

- NPM package: `@kernel.salacoste/n8n-workflow-builder`
- Version observed: `0.9.3`
- License: MIT
- Multi-instance workflow-builder orientation.
- Less mature than `n8n-mcp` by stars/activity signals, but potentially useful if multi-environment routing becomes important.

## Recommended next move

1. Use Iris to build the newsletter landing-page concept first.
2. Build a local curated resource repo/directory from the workflow hub and other GitHub projects — do not attach the raw 2055-workflow dump directly.
3. Ask Konan to create/provide a scoped n8n API key, then wire `n8n-mcp` in read-only mode.
4. After read-only verification passes, selectively enable write tools only for sandbox workflows.

## Hard guardrails

- Do not bulk import AI-Workflow-Hub workflows into live n8n.
- Do not expose n8n credentials or workflow secrets in newsletter/public resources.
- Do not use n8n as the strategic replacement for TheoForge/Conductor; use it as a practical bridge/template/testing substrate only.
