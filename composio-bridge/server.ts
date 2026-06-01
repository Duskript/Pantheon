/**
 * Composio Bridge — Node.js sidecar for Composio OAuth connections.
 *
 * Serves REST endpoints that the Python webui backend proxies to.
 * Runs on port 8789.
 */

import express, { Request, Response } from "express";
import cors from "cors";
import { Composio } from "@composio/core";
import dotenv from "dotenv";

dotenv.config();

const API_KEY = process.env.COMPOSIO_API_KEY || "";

if (!API_KEY) {
  console.error("❌ COMPOSIO_API_KEY not set in environment or .env");
  process.exit(1);
}

let composio: Composio;
let client: any; // Use any for the client — SDK types lag behind the API

try {
  composio = new Composio({ apiKey: API_KEY });
  client = composio.getClient();
  console.log("✅ Composio client initialized");
} catch (e) {
  console.error("❌ Failed to initialize Composio client:", e);
  process.exit(1);
}

const app = express();
const PORT = parseInt(process.env.COMPOSIO_BRIDGE_PORT || "8789", 10);

app.use(cors());
app.use(express.json());

// ─── Health ───────────────────────────────────────────────────

app.get("/health", async (_req: Request, res: Response) => {
  try {
    const accounts = await client.connectedAccounts.list();
    res.json({
      status: "ok",
      composio: true,
      connections: accounts?.items?.length || 0,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.json({ status: "ok", composio: false, error: msg });
  }
});

// ─── List all connections ─────────────────────────────────────

app.get("/connections", async (_req: Request, res: Response) => {
  try {
    const accounts = await client.connectedAccounts.list();
    const items = (accounts?.items || []).map((a: any) => ({
      id: a.id,
      provider: a.toolkit?.slug,
      status: a.status,
      createdAt: a.created_at,
      updatedAt: a.updated_at,
    }));
    res.json({ items });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(500).json({ error: msg });
  }
});

// ─── Get single connection ────────────────────────────────────

app.get("/connections/:id", async (req: Request, res: Response) => {
  try {
    const id = String(req.params.id);
    const account = await client.connectedAccounts.retrieve(id);
    res.json(account);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(404).json({ error: msg });
  }
});

// ─── List available providers (auth configs) ──────────────────

app.get("/providers", async (_req: Request, res: Response) => {
  try {
    const configs = await client.authConfigs.list();
    const items = (configs?.items || []).map((a: any) => ({
      id: a.id,
      slug: a.toolkit?.slug,
      name: a.name || a.toolkit?.slug || a.id,
      authScheme: a.auth_scheme,
      isManaged: a.is_composio_managed,
      status: a.status,
    }));
    res.json({ items });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(500).json({ error: msg });
  }
});

// ─── Initiate OAuth connection ────────────────────────────────

app.post("/connections/connect", async (req: Request, res: Response) => {
  try {
    const { provider, userId } = req.body;
    if (!provider) {
      return res.status(400).json({ error: "provider is required" });
    }

    // Find the auth config for this provider
    const configs = await client.authConfigs.list();
    const authConfig = (configs?.items || []).find(
      (a: any) => a.toolkit?.slug === provider
    );

    if (!authConfig) {
      return res.status(404).json({ error: `No auth config found for ${provider}` });
    }

    // Use the link endpoint for composio-managed OAuth
    const result: any = await client.post("/api/v3/connected_accounts/link", {
      body: {
        auth_config_id: authConfig.id,
        user_id: userId || "konan",
      },
    });

    res.json({
      id: result.connected_account_id,
      url: result.redirect_url,
      linkToken: result.link_token,
      expiresAt: result.expires_at,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(500).json({ error: msg });
  }
});

// ─── Poll connection status ───────────────────────────────────

app.get("/connections/:id/status", async (req: Request, res: Response) => {
  try {
    const id = String(req.params.id);
    const account = await client.connectedAccounts.retrieve(id);
    res.json({
      id: account.id,
      provider: account.toolkit?.slug,
      status: account.status,
      createdAt: account.created_at,
      updatedAt: account.updated_at,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(404).json({ error: msg });
  }
});

// ─── Delete connection ────────────────────────────────────────

app.delete("/connections/:id", async (req: Request, res: Response) => {
  try {
    await client.connectedAccounts.delete(String(req.params.id));
    res.json({ ok: true });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(500).json({ error: msg });
  }
});

// ─── Execute a Composio tool ──────────────────────────────────

app.post("/execute", async (req: Request, res: Response) => {
  try {
    const { tool, params, connectedAccountId } = req.body;
    if (!tool) {
      return res.status(400).json({ error: "tool is required" });
    }

    const result = await client.tools.execute({
      tool,
      params: params || {},
      connectedAccountId,
    });

    res.json({ data: result });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    res.status(500).json({ error: msg });
  }
});

// ─── Start server ─────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`🔌 Composio Bridge running on http://127.0.0.1:${PORT}`);
});
