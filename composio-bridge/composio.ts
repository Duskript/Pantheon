/**
 * composio.ts — Composio v3.1 REST client + Tool Router Session manager.
 *
 * Pattern ported into Pantheon from OpenMausBot (Apache-2.0) — see NOTICE.
 * The approach: talk to the Composio REST API directly with a *project* API
 * key (ak_…) in the `x-api-key` header, and let ONE reusable Tool Router
 * Session per stable user id own all connection state, authorization links and
 * the MCP endpoint. No SDK, no vendor types lagging behind the API.
 *
 * API contract (Composio v3.1):
 *   base    https://backend.composio.dev/api/v3.1
 *   header  x-api-key: ak_…
 *   POST    /tool_router/session                  create a session
 *   GET     /tool_router/session/{id}             read a session
 *   PATCH   /tool_router/session/{id}             { auth_configs }
 *   POST    /tool_router/session/{id}/link        { toolkit, alias? } → redirect_url
 *   GET     /tool_router/session/{id}/toolkits    ?limit&toolkits
 *   GET     /auth_configs                         ?is_composio_managed=false
 *   PATCH   /auth_configs/{id}                    { type, is_enabled_for_tool_router }
 *   GET     /connected_accounts                   ?limit&user_ids&toolkit_slugs&cursor
 *   DELETE  /connected_accounts/{id}?revoke_on_delete=true
 */

import { randomUUID } from "node:crypto";

import { getProjectEntry, setProjectEntry } from "./state";

export const DEFAULT_BASE = "https://backend.composio.dev/api/v3.1";

/** Maximum usable accounts per toolkit (multi-account mode). */
export const MULTI_ACCOUNT_CONFIG = {
  enable: true,
  max_accounts_per_toolkit: 5,
  require_explicit_selection: true,
} as const;

export function apiBase(): string {
  return (process.env.COMPOSIO_API_BASE || DEFAULT_BASE).replace(/\/+$/, "");
}

export function projectHeaders(apiKey: string, json = false): Record<string, string> {
  const headers: Record<string, string> = { "x-api-key": apiKey.trim() };
  if (json) headers["content-type"] = "application/json";
  return headers;
}

/** Composio's slug is `twitter`; older cards and model calls may still say `x`. */
export function canonicalToolkitSlug(slug: string): string {
  const normalized = (slug || "").trim().toLowerCase();
  return normalized === "x" ? "twitter" : normalized;
}

export async function responseError(res: Response, fallback: string): Promise<string> {
  const raw = await res.text().catch(() => "");
  try {
    const body = JSON.parse(raw) as Record<string, any>;
    const msg = body?.error?.message ?? body?.message ?? body?.error;
    if (typeof msg === "string" && msg.trim()) return msg;
    if (msg) return JSON.stringify(msg);
    return fallback;
  } catch {
    return raw.trim().slice(0, 300) || fallback;
  }
}

// ─── Project key validation ──────────────────────────────────────────────────

export interface KeyCheck {
  ok: boolean;
  status: number;
  message: string;
}

/**
 * Validate that a key looks like a Composio *project* key and is accepted by the
 * API. The `ck_` key shown on the personal "Sessions & API Key" page is a
 * different credential and will not work here — say so plainly rather than
 * letting the caller discover it as a 401.
 */
export async function validateProjectKey(apiKey: string): Promise<KeyCheck> {
  const key = (apiKey || "").trim();
  if (!key) {
    return { ok: false, status: 0, message: "No Composio project key configured" };
  }
  if (!key.startsWith("ak_")) {
    return {
      ok: false,
      status: 0,
      message:
        "Composio project API keys start with ak_. The ck_ key on the personal Sessions & API Key page will not work — copy the key from your project's Settings → API Keys page.",
    };
  }
  try {
    const res = await fetch(`${apiBase()}/auth_configs?limit=1`, {
      headers: projectHeaders(key),
      signal: AbortSignal.timeout(15_000),
    });
    if (res.ok) return { ok: true, status: res.status, message: "ok" };
    return {
      ok: false,
      status: res.status,
      message: await responseError(res, `Composio rejected the key (HTTP ${res.status})`),
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

// ─── Project auth configs ────────────────────────────────────────────────────

export interface AuthConfigChoice {
  id: string;
  type: string;
  toolRouter: boolean;
}

export interface ProjectAuthConfigs {
  /** toolkit slug → the config to use for it */
  choices: Record<string, AuthConfigChoice>;
  /** toolkit slug → config id, only for configs already enabled for Tool Router */
  configs: Record<string, string>;
  readError?: string;
}

interface RawAuthConfig {
  id?: string;
  type?: string | null;
  status?: string | null;
  is_composio_managed?: boolean;
  is_enabled_for_tool_router?: boolean | null;
  created_at?: string | null;
  last_updated_at?: string | null;
  toolkit?: { slug?: string };
}

function usableConfig(item: RawAuthConfig): boolean {
  return item.is_composio_managed !== true && (!item.status || /^enabled$/i.test(item.status));
}

const MAX_AUTH_CONFIG_PAGES = 20;

/**
 * Read the project's own (non-Composio-managed) auth configs, newest first per
 * toolkit. A read failure is reported, never fatal — Sessions keep the last
 * list or none.
 */
export async function listProjectAuthConfigs(
  apiKey: string,
  options: { fresh?: boolean } = {},
): Promise<ProjectAuthConfigs> {
  const byToolkit = new Map<string, AuthConfigChoice[]>();
  const created = new Map<string, string>();
  let cursor: string | undefined;
  try {
    for (let page = 0; page < MAX_AUTH_CONFIG_PAGES; page += 1) {
      const params = new URLSearchParams({ is_composio_managed: "false", limit: "100" });
      if (cursor) params.set("cursor", cursor);
      const res = await fetch(`${apiBase()}/auth_configs?${params}`, {
        headers: projectHeaders(apiKey),
        signal: AbortSignal.timeout(15_000),
      });
      if (!res.ok) throw new Error(await responseError(res, `HTTP ${res.status}`));
      const body = (await res.json()) as { items?: RawAuthConfig[]; next_cursor?: string | null };
      for (const item of body.items ?? []) {
        const slug = item.toolkit?.slug ? canonicalToolkitSlug(item.toolkit.slug) : "";
        if (!slug || !item.id || !usableConfig(item)) continue;
        const existing = byToolkit.get(slug) ?? [];
        existing.push({
          id: item.id,
          type: item.type || "custom",
          toolRouter: item.is_enabled_for_tool_router === true,
        });
        byToolkit.set(slug, existing);
        created.set(item.id, item.created_at || item.last_updated_at || "");
      }
      const next = body.next_cursor ?? undefined;
      if (!next || next === cursor) break;
      cursor = next;
    }
  } catch (error) {
    const readError = error instanceof Error ? error.message : String(error);
    console.warn(`[composio-bridge] could not read project auth configs (${readError})`);
    return { choices: {}, configs: {}, readError };
  }

  const choices: Record<string, AuthConfigChoice> = {};
  for (const [slug, configs] of byToolkit) {
    configs.sort(
      (a, b) =>
        (created.get(b.id) ?? "").localeCompare(created.get(a.id) ?? "") ||
        a.id.localeCompare(b.id),
    );
    const chosen = configs[0];
    if (chosen) choices[slug] = chosen;
  }
  return {
    choices,
    configs: Object.fromEntries(
      Object.entries(choices).flatMap(([slug, choice]) => (choice.toolRouter ? [[slug, choice.id]] : [])),
    ),
  };
}

/**
 * Turn on Tool Router for one of the project's own auth configs — Composio only
 * uses a custom config when the flag is set, and a person's own config can have
 * it off by default.
 */
export async function turnOnToolRouter(apiKey: string, choice: AuthConfigChoice): Promise<void> {
  const res = await fetch(`${apiBase()}/auth_configs/${encodeURIComponent(choice.id)}`, {
    method: "PATCH",
    headers: projectHeaders(apiKey, true),
    body: JSON.stringify({ type: choice.type, is_enabled_for_tool_router: true }),
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) {
    throw new Error(
      `Could not enable Tool Router for auth config ${choice.id} (${await responseError(res, `HTTP ${res.status}`)}). ` +
        "Check that your Composio project key may edit auth configs.",
    );
  }
}

// ─── Tool Router Sessions ────────────────────────────────────────────────────

export interface SessionResponse {
  session_id: string;
  mcp: { type: "http" | "sse"; url: string };
  config?: {
    user_id?: string;
    multi_account?: {
      enable?: boolean;
      max_accounts_per_toolkit?: number;
      require_explicit_selection?: boolean;
    };
    auth_configs?: Record<string, string>;
  };
}

function parseSession(raw: unknown): SessionResponse {
  const session = raw as SessionResponse;
  if (!session?.session_id || !session?.mcp?.url) {
    throw new Error("Composio returned a malformed Session");
  }
  return session;
}

export async function getSession(apiKey: string, sessionId: string): Promise<SessionResponse | null> {
  const res = await fetch(`${apiBase()}/tool_router/session/${encodeURIComponent(sessionId)}`, {
    headers: projectHeaders(apiKey),
    signal: AbortSignal.timeout(15_000),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await responseError(res, `Composio session: HTTP ${res.status}`));
  return parseSession(await res.json());
}

const REFUSED_SESSION_STATUSES = new Set([400, 404, 409, 422]);

/**
 * Create a Session, retrying without any auth config Composio refuses so a
 * single bad config can never block the rest.
 */
async function createSession(
  apiKey: string,
  userId: string,
  authConfigs: Record<string, string>,
): Promise<SessionResponse> {
  const post = (configs: Record<string, string>) => {
    const body: Record<string, unknown> = {
      user_id: userId,
      manage_connections: {
        enable: true,
        enable_wait_for_connections: true,
        enable_connection_removal: true,
      },
      multi_account: MULTI_ACCOUNT_CONFIG,
    };
    if (Object.keys(configs).length) body.auth_configs = configs;
    return fetch(`${apiBase()}/tool_router/session`, {
      method: "POST",
      headers: projectHeaders(apiKey, true),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
  };

  let named = authConfigs;
  let res = await post(named);
  while (!res.ok && Object.keys(named).length && REFUSED_SESSION_STATUSES.has(res.status)) {
    const said = await responseError(res, `HTTP ${res.status}`);
    const kept = Object.fromEntries(Object.entries(named).filter(([, id]) => !said.includes(id)));
    named = Object.keys(kept).length < Object.keys(named).length ? kept : {};
    console.warn(`[composio-bridge] Composio refused a Session naming auth configs (${said}); retrying without them`);
    res = await post(named);
  }
  if (!res.ok) {
    throw new Error(await responseError(res, `Composio rejected the project key (HTTP ${res.status})`));
  }
  return parseSession(await res.json());
}

function supportsMultiAccount(session: SessionResponse): boolean {
  return session.config?.multi_account?.enable === true;
}

function sessionCoversAuthConfigs(session: SessionResponse, wanted: Record<string, string>): boolean {
  const have = session.config?.auth_configs ?? {};
  const haveLower = Object.fromEntries(
    Object.entries(have).map(([slug, id]) => [canonicalToolkitSlug(slug), id]),
  );
  return Object.entries(wanted).every(([slug, id]) => haveLower[slug] === id);
}

async function nameAuthConfigsInPlace(
  apiKey: string,
  session: SessionResponse,
  configs: Record<string, string>,
): Promise<SessionResponse | null> {
  const res = await fetch(`${apiBase()}/tool_router/session/${encodeURIComponent(session.session_id)}`, {
    method: "PATCH",
    headers: projectHeaders(apiKey, true),
    body: JSON.stringify({ auth_configs: configs }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    console.warn(
      `[composio-bridge] Composio would not change the Session's auth configs (${await responseError(res, `HTTP ${res.status}`)}); creating a new Session`,
    );
    return null;
  }
  return getSession(apiKey, session.session_id);
}

/**
 * The Session for this project key: reuse the stored one while it is healthy,
 * otherwise create and persist a fresh one. Connections belong to the Composio
 * user (not the Session), so recreating with the same user id keeps every grant.
 */
export async function ensureSession(apiKey: string): Promise<SessionResponse> {
  const project = await listProjectAuthConfigs(apiKey);
  const entry = getProjectEntry(apiKey);

  if (entry?.sessionId) {
    const existing = await getSession(apiKey, entry.sessionId).catch(() => null);
    if (existing && supportsMultiAccount(existing) && sessionCoversAuthConfigs(existing, project.configs)) {
      return existing;
    }
    if (existing) {
      const named = await nameAuthConfigsInPlace(apiKey, existing, project.configs);
      if (named) {
        setProjectEntry(apiKey, { userId: named.config?.user_id ?? entry.userId, sessionId: named.session_id });
        return named;
      }
    }
  }

  const userId = entry?.userId ?? `pantheon_${randomUUID()}`;
  const session = await createSession(apiKey, userId, project.configs);
  setProjectEntry(apiKey, { userId: session.config?.user_id ?? userId, sessionId: session.session_id });
  return session;
}

// ─── Connected accounts ──────────────────────────────────────────────────────

export interface ConnectedAccount {
  id?: string;
  user_id?: string;
  alias?: string | null;
  status?: string;
  updated_at?: string;
  created_at?: string;
  toolkit?: { slug?: string };
}

export const MAX_CONNECTED_ACCOUNT_PAGES = 100;

export async function listConnectedAccounts(
  apiKey: string,
  userId: string | null,
  slugs: string[] = [],
): Promise<ConnectedAccount[]> {
  const accounts: ConnectedAccount[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;

  for (let page = 0; page < MAX_CONNECTED_ACCOUNT_PAGES; page += 1) {
    const params = new URLSearchParams({ limit: "50", order_by: "updated_at", order_direction: "desc" });
    if (userId) params.set("user_ids", userId);
    if (slugs.length) params.set("toolkit_slugs", slugs.map(canonicalToolkitSlug).join(","));
    if (cursor) params.set("cursor", cursor);
    const res = await fetch(`${apiBase()}/connected_accounts?${params}`, {
      headers: projectHeaders(apiKey),
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(await responseError(res, `Composio accounts: HTTP ${res.status}`));
    const body = (await res.json()) as { items?: ConnectedAccount[]; next_cursor?: string | null };
    accounts.push(...(body.items ?? []));
    const next = body.next_cursor || undefined;
    if (!next) return accounts;
    if (seen.has(next)) throw new Error("Composio account inventory contains a pagination cursor cycle");
    seen.add(next);
    cursor = next;
  }
  throw new Error("Composio account inventory exceeded the pagination safety limit");
}

/** Revoke the upstream provider grant, then delete the account. */
export async function deleteConnectedAccount(apiKey: string, id: string): Promise<void> {
  const res = await fetch(
    `${apiBase()}/connected_accounts/${encodeURIComponent(id)}?revoke_on_delete=true`,
    { method: "DELETE", headers: projectHeaders(apiKey), signal: AbortSignal.timeout(30_000) },
  );
  if (!res.ok) throw new Error(await responseError(res, `Composio disconnect: HTTP ${res.status}`));
}

// ─── Link (connect) ──────────────────────────────────────────────────────────

export interface LinkResult {
  id?: string;
  url: string;
}

/** Start an authorization flow for `toolkit`; returns the URL the user opens. */
export async function linkAccount(
  apiKey: string,
  toolkit: string,
  alias?: string,
): Promise<LinkResult> {
  const session = await ensureSession(apiKey);
  const body: Record<string, string> = { toolkit: canonicalToolkitSlug(toolkit) };
  if (alias) body.alias = alias;
  const res = await fetch(
    `${apiBase()}/tool_router/session/${encodeURIComponent(session.session_id)}/link`,
    {
      method: "POST",
      headers: projectHeaders(apiKey, true),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    },
  );
  if (!res.ok) throw new Error(await responseError(res, `Composio link: HTTP ${res.status}`));
  const payload = (await res.json()) as { redirect_url?: string; connected_account_id?: string; id?: string };
  const url = payload.redirect_url;
  if (!url) throw new Error("Composio returned no authorization link");
  return { id: payload.connected_account_id ?? payload.id, url };
}

// ─── Session toolkits / inventory ────────────────────────────────────────────

export interface ToolkitState {
  slug?: string;
  is_no_auth?: boolean;
  connected_account?: { id?: string; status?: string };
}

/** The Session's own view of which toolkits have a usable account. */
export async function sessionToolkits(
  apiKey: string,
  sessionId: string,
  slugs: string[] = [],
): Promise<ToolkitState[]> {
  const params = new URLSearchParams({ limit: "50" });
  if (slugs.length) params.set("toolkits", slugs.map(canonicalToolkitSlug).join(","));
  const res = await fetch(
    `${apiBase()}/tool_router/session/${encodeURIComponent(sessionId)}/toolkits?${params}`,
    { headers: projectHeaders(apiKey), signal: AbortSignal.timeout(15_000) },
  );
  if (!res.ok) throw new Error(await responseError(res, `Composio toolkits: HTTP ${res.status}`));
  const body = (await res.json()) as { items?: ToolkitState[] };
  return body.items ?? [];
}
