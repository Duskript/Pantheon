/**
 * Composio Bridge — Node.js sidecar for Composio connections.
 *
 * Serves REST endpoints that the Python webui backend proxies to under
 * /api/composio/*. Runs on PORT (default 8789).
 *
 * Backed by a Composio *project* API key (ak_…) — see ./composio.ts. The bridge
 * NEVER exits because a key is missing or invalid: it always serves /health with
 * a machine-readable status so the onboarding wizard can show a "connect"
 * prompt instead of a dead service.
 */

import cors from "cors";
import dotenv from "dotenv";
import express, { Request, Response } from "express";

import {
  apiBase,
  canonicalToolkitSlug,
  deleteConnectedAccount,
  ensureSession,
  linkAccount,
  listConnectedAccounts,
  listProjectAuthConfigs,
  sessionToolkits,
  validateProjectKey,
} from "./composio";
import { stateFilePath } from "./state";

// composio-bridge/.env is the authoritative source for COMPOSIO_* in this
// component: it is gitignored and holds the project key. override:true makes the
// component's own file win over anything inherited from the service environment,
// while env vars absent from the file are left untouched.
dotenv.config({ override: true });

const PORT = parseInt(process.env.COMPOSIO_BRIDGE_PORT || "8789", 10);

/** The project key, from the first non-empty of these names. */
function projectKey(): string {
  return (
    process.env.COMPOSIO_API_KEY ||
    process.env.COMPOSIO_PROJECT_KEY ||
    process.env.COMPOSIO_CONSUMER_KEY || // legacy name; only valid if it is ak_…
    ""
  ).trim();
}

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

function fail(res: Response, status: number, error: string): void {
  res.status(status).json({ error });
}

// ─── Health ──────────────────────────────────────────────────────────────────

app.get("/health", async (_req: Request, res: Response) => {
  const key = projectKey();
  if (!key) {
    return res.json({
      status: "ok",
      composio: false,
      configured: false,
      key_valid: false,
      connections: 0,
      error: "No Composio project key configured. Set COMPOSIO_API_KEY (an ak_… project key).",
    });
  }
  const check = await validateProjectKey(key);
  if (!check.ok) {
    return res.json({
      status: "ok",
      composio: false,
      configured: true,
      key_valid: false,
      connections: 0,
      error: check.message,
    });
  }
  try {
    const session = await ensureSession(key);
    const accounts = await listConnectedAccounts(key, session.config?.user_id ?? null);
    return res.json({
      status: "ok",
      composio: true,
      configured: true,
      key_valid: true,
      connections: accounts.length,
      session_id: session.session_id,
    });
  } catch (error) {
    return res.json({
      status: "ok",
      composio: false,
      configured: true,
      key_valid: true,
      connections: 0,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

// ─── Config (no secrets) ─────────────────────────────────────────────────────

app.get("/config", async (_req: Request, res: Response) => {
  const key = projectKey();
  if (!key) {
    return res.json({ configured: false, base_url: apiBase(), state_file: stateFilePath() });
  }
  const check = await validateProjectKey(key);
  let userId: string | undefined;
  let sessionId: string | undefined;
  if (check.ok) {
    try {
      const session = await ensureSession(key);
      userId = session.config?.user_id;
      sessionId = session.session_id;
    } catch (error) {
      check.message = error instanceof Error ? error.message : String(error);
    }
  }
  return res.json({
    configured: true,
    key_valid: check.ok,
    key_prefix: key.slice(0, 3),
    key_issue: check.ok ? undefined : check.message,
    base_url: apiBase(),
    user_id: userId,
    session_id: sessionId,
    state_file: stateFilePath(),
  });
});

// ─── List all connections ─────────────────────────────────────────────────────

app.get("/connections", async (_req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  const check = await validateProjectKey(key);
  if (!check.ok) return fail(res, 502, check.message);
  try {
    const session = await ensureSession(key);
    const accounts = await listConnectedAccounts(key, session.config?.user_id ?? null);
    const items = accounts.map((a) => ({
      id: a.id,
      provider: a.toolkit?.slug,
      alias: a.alias ?? null,
      status: a.status,
      createdAt: a.created_at,
      updatedAt: a.updated_at,
    }));
    res.json({ items });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── Get single connection ────────────────────────────────────────────────────

app.get("/connections/:id", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  try {
    const session = await ensureSession(key);
    const accounts = await listConnectedAccounts(key, session.config?.user_id ?? null);
    const account = accounts.find((a) => a.id === String(req.params.id));
    if (!account) return fail(res, 404, "Connection not found");
    res.json(account);
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── List available providers (project auth configs) ─────────────────────────

app.get("/providers", async (_req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  const check = await validateProjectKey(key);
  if (!check.ok) return fail(res, 502, check.message);
  try {
    const project = await listProjectAuthConfigs(key);
    const items = Object.entries(project.choices).map(([slug, choice]) => ({
      id: choice.id,
      slug,
      name: slug,
      authScheme: choice.type,
      isManaged: false,
      status: choice.toolRouter ? "ENABLED" : "DISABLED",
    }));
    res.json({ items });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── Initiate an authorization flow ──────────────────────────────────────────

app.post("/connections/connect", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  const provider = String(req.body?.provider || "").trim();
  const alias = req.body?.alias ? String(req.body.alias) : undefined;
  if (!provider) return fail(res, 400, "provider is required");
  const check = await validateProjectKey(key);
  if (!check.ok) return fail(res, 502, check.message);
  try {
    const link = await linkAccount(key, provider, alias);
    res.json({
      id: link.id,
      url: link.url,
      provider: canonicalToolkitSlug(provider),
    });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── Poll a connection's status ──────────────────────────────────────────────

app.get("/connections/:id/status", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  try {
    const session = await ensureSession(key);
    const accounts = await listConnectedAccounts(key, session.config?.user_id ?? null);
    const account = accounts.find((a) => a.id === String(req.params.id));
    if (!account) return fail(res, 404, "Connection not found");
    res.json({
      id: account.id,
      provider: account.toolkit?.slug,
      status: account.status,
      createdAt: account.created_at,
      updatedAt: account.updated_at,
    });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── Delete a connection (revokes upstream, then deletes) ────────────────────

app.delete("/connections/:id", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  try {
    await deleteConnectedAccount(key, String(req.params.id));
    res.json({ ok: true });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

// ─── Renderer-neutral connected-services inventory ───────────────────────────
// One request returns every service and its accounts. Shape matches the
// OpenMausBot contract so any client (wizard, dashboard, bot) can consume it.

app.get("/connectors/connected", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) {
    return res.json({ configured: false, services: {} });
  }
  const check = await validateProjectKey(key);
  if (!check.ok) {
    return res.json({ configured: true, key_valid: false, error: check.message, services: {} });
  }
  try {
    const session = await ensureSession(key);
    const userId = session.config?.user_id ?? null;
    const requested = String(req.query.services || "")
      .split(",")
      .map((s) => canonicalToolkitSlug(s))
      .filter(Boolean);

    const [accounts, toolkits] = await Promise.all([
      listConnectedAccounts(key, userId, requested).catch(() => []),
      sessionToolkits(key, session.session_id, requested).catch(() => []),
    ]);

    const services: Record<string, { connected: boolean; pending: boolean; status?: string; accounts: unknown[] }> = {};
    for (const account of accounts) {
      const slug = account.toolkit?.slug ? canonicalToolkitSlug(account.toolkit.slug) : "";
      if (!slug) continue;
      const entry = services[slug] ?? { connected: false, pending: false, accounts: [] };
      entry.accounts.push({ id: account.id, alias: account.alias ?? null, status: account.status });
      if (/^active$/i.test(account.status ?? "")) {
        entry.connected = true;
        entry.status = account.status;
      } else if (/^(initiated|initializing|pending)$/i.test(account.status ?? "")) {
        entry.pending = true;
      }
      services[slug] = entry;
    }
    for (const toolkit of toolkits) {
      const slug = toolkit.slug ? canonicalToolkitSlug(toolkit.slug) : "";
      if (!slug) continue;
      const entry = services[slug] ?? { connected: false, pending: false, accounts: [] };
      if (toolkit.is_no_auth) entry.connected = true;
      services[slug] = entry;
    }
    res.json({ configured: true, key_valid: true, services });
  } catch (error) {
    res.json({
      configured: true,
      key_valid: true,
      error: error instanceof Error ? error.message : String(error),
      services: {},
    });
  }
});

// ─── Execute a Composio tool ─────────────────────────────────────────────────
// Runs a tool through the Session's MCP endpoint (JSON-RPC tools/call), so the
// call carries the Session's account selection and multi-account routing.

app.post("/execute", async (req: Request, res: Response) => {
  const key = projectKey();
  if (!key) return fail(res, 503, "No Composio project key configured");
  const tool = String(req.body?.tool || "").trim();
  if (!tool) return fail(res, 400, "tool is required");
  const args = req.body?.arguments ?? req.body?.params ?? {};
  try {
    const session = await ensureSession(key);
    const rpc = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: tool, arguments: args },
    };
    const upstream = await fetch(session.mcp.url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        "x-api-key": key,
      },
      body: JSON.stringify(rpc),
      signal: AbortSignal.timeout(60_000),
    });
    const text = await upstream.text();
    if (!upstream.ok) {
      return fail(res, 502, `Composio execute: HTTP ${upstream.status} ${text.slice(0, 300)}`);
    }
    // MCP over HTTP may answer as SSE (`data: {...}`) or plain JSON.
    const jsonLine = text.split("\n").find((l) => l.trim().startsWith("{"));
    const data = jsonLine ? JSON.parse(jsonLine) : text;
    res.json({ data });
  } catch (error) {
    fail(res, 500, error instanceof Error ? error.message : String(error));
  }
});

app.listen(PORT, () => {
  const key = projectKey();
  console.log(`🔌 Composio Bridge running on http://127.0.0.1:${PORT}`);
  console.log(`   key: ${key ? `${key.slice(0, 3)}… (${key.length} chars)` : "NOT SET"}`);
  console.log(`   api: ${apiBase()}`);
});
