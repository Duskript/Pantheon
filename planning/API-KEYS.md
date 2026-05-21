# Pantheon — Required API Keys & External Services

> **This is a living document.** Update it whenever a new integration, provider, or
> external service is added to Pantheon. The purpose is not to store secrets
> (those go in `.env` / `~/.hermes/.env`) but to document **what** is needed,
> **why**, and **how to get it**.

---

## 1. Inference Provider (Required)

| Field | Value |
|---|---|
| **What** | LLM inference API for all agent/god chat completions |
| **Default** | OpenCode Go (`https://opencode.ai/zen/go/v1`) |
| **Env var** | `OPENCODE_GO_API_KEY` |
| **Where to get** | [opencode.ai](https://opencode.ai) — sign up, get API key |
| **Alternatives** | OpenRouter, Anthropic, OpenAI, any OpenAI-compatible endpoint |
| **Config file** | `~/.hermes/config.yaml` — provider/model settings |
| **Fallback** | Configured in `fallback` section of config.yaml |

**Impact if missing:** Pantheon cannot function. All god conversations require this.

---

## 2. Composio API Key (Required for App Integrations)

| Field | Value |
|---|---|
| **What** | 500+ app integrations (Gmail, Slack, GitHub, Notion, Google Drive, etc.) |
| **Env var** | `COMPOSIO_API_KEY` (set in `~/.hermes/.env` or config) |
| **Where to get** | [composio.dev](https://composio.dev) — sign up, create API key |
| **MCP config** | Already wired in `~/.hermes/config.yaml` under `mcp_servers.composio` |
| **Auth flow** | Per-app OAuth via Composio's connection manager |

**Impact if missing:** The Composio MCP server won't connect. Apps like Gmail, Google Drive,
Slack, GitHub, Notion, etc. will be unavailable through the composio toolset.
**Alternative:** Manual API calls via curl/terminal for each service.

---

## 3. Tailscale (Required for Remote Access)

| Field | Value |
|---|---|
| **What** | Secure mesh VPN for accessing Pantheon from any device |
| **How to install** | `curl -fsSL https://tailscale.com/install.sh | sh` |
| **Auth** | Tailscale account (Google/GitHub/Email) |
| **Config** | `sudo tailscale up` — authenticates to your tailnet |
| **Serve config** | `sudo tailscale serve --https=443 8787` to expose WebUI |

**Impact if missing:** Pantheon is only accessible from localhost on the server.
No phone/tablet/laptop access without Tailscale or similar VPN.

---

## 4. OpenRouter API Key (Optional — Embeddings + Model Fallback)

| Field | Value |
|---|---|
| **What** | Free embedding API + paid model access as a fallback provider |
| **Env var** | `OPENROUTER_API_KEY` |
| **Where to get** | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **Used for** | ChromaDB embeddings (semantic search), optional model routing |
| **Cost** | Embeddings via `nvidia/llama-nemotron-embed-vl-1b-v2:free` — **free tier** |

**Impact if missing:** Semantic search (ChromaDB) degrades gracefully — FTS5 + Graph still
provide keyword and relationship search. The system works without it.

---

## 5. GitHub Token (Optional — Repo Operations)

| Field | Value |
|---|---|
| **What** | GitHub API access for PRs, issues, code operations |
| **Env var** | `GITHUB_TOKEN` or `GH_TOKEN` |
| **Where to get** | [github.com/settings/tokens](https://github.com/settings/tokens) |
| **Scopes needed** | `repo`, `workflow` for most operations |
| **MCP config** | Already wired in `~/.hermes/config.yaml` under `mcp_servers.github` |

**Impact if missing:** GitHub MCP server won't connect. PRs, issues, and code search
through the god interface won't work. Can still use `gh` CLI directly.

---

## 6. OpenCode Go Account (Default Inference)

| Field | Value |
|---|---|
| **What** | Inference API for the default model (`deepseek-v4-flash`) |
| **URL** | `https://opencode.ai/zen/go/v1` |
| **Env var** | `OPENCODE_GO_API_KEY` |
| **Where to get** | [opencode.ai](https://opencode.ai) — sign up for API access |
| **Used by** | All gods by default, Soul Forge |

**Impact if missing:** Primary inference won't work. Must configure an alternative provider.

---

## 7. (Optional) OpenAI / Anthropic / Other Providers

Any OpenAI-compatible provider can be configured in `~/.hermes/config.yaml` under
`custom_providers` or the `providers` section. The WebUI supports provider switching
per-conversation.

---

## Setup Order (for onboarding / fresh install)

```
1. OpenCode Go API key        ← REQUIRED, Pantheon won't run without inference
2. Composio API key           ← REQUIRED for app integrations
3. Tailscale                  ← REQUIRED for remote access
4. OpenRouter API key         ← OPTIONAL, adds semantic search
5. GitHub token               ← OPTIONAL, adds repo operations
```

## Where Keys Live

| File | Contents |
|---|---|
| `~/.hermes/.env` | Runtime secrets loaded by Hermes Agent |
| `~/pantheon/.env` | Pantheon WebUI env vars |
| `.env.example` | Template with blank placeholders (in repo) |
| `~/.hermes/config.yaml` | MCP server headers/tokens (masked in UI) |

**Never commit actual keys to git.** The `.env` files and `secrets/` directory are
in `.gitignore`. Use `.env.example` as a template.
