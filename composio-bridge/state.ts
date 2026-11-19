/**
 * state.ts — on-disk state for the Composio bridge.
 *
 * Holds the stable Composio user id and the reusable Tool Router Session id,
 * keyed by a SHA-256 fingerprint of the project key so that changing keys
 * starts clean. The project key itself is NEVER written here — it stays in the
 * environment (COMPOSIO_API_KEY).
 *
 * File is created mode 0600 in a mode 0700 directory.
 */

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export interface ProjectEntry {
  userId: string;
  sessionId: string;
}

export interface BridgeState {
  version: 1;
  projects: Record<string, ProjectEntry>;
}

const STATE_PATH =
  process.env.COMPOSIO_STATE_FILE ||
  join(homedir(), ".hermes", "state", "composio-bridge.json");

let cached: BridgeState | undefined;

/** Stable, non-reversible per-project bucket key. */
export function keyFingerprint(apiKey: string): string {
  return createHash("sha256")
    .update("composio-bridge\0")
    .update(apiKey.trim())
    .digest("hex");
}

function freshState(): BridgeState {
  return { version: 1, projects: {} };
}

function loadState(): BridgeState {
  if (cached) return cached;
  try {
    const parsed = JSON.parse(readFileSync(STATE_PATH, "utf8")) as BridgeState;
    cached =
      parsed && typeof parsed === "object" && parsed.projects
        ? parsed
        : freshState();
  } catch (error) {
    // Missing or corrupt state file is normal on first run. Never fatal.
    if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") {
      console.warn(`[composio-bridge] could not read state (${String(error)}); starting fresh`);
    }
    cached = freshState();
  }
  return cached;
}

function persist(state: BridgeState): void {
  mkdirSync(dirname(STATE_PATH), { recursive: true, mode: 0o700 });
  const tmp = `${STATE_PATH}.tmp`;
  writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  renameSync(tmp, STATE_PATH);
  cached = state;
}

export function getProjectEntry(apiKey: string): ProjectEntry | undefined {
  return loadState().projects[keyFingerprint(apiKey)];
}

export function setProjectEntry(apiKey: string, entry: ProjectEntry): void {
  const state = loadState();
  state.projects[keyFingerprint(apiKey)] = entry;
  persist(state);
}

export function clearProjectEntry(apiKey: string): void {
  const state = loadState();
  delete state.projects[keyFingerprint(apiKey)];
  persist(state);
}

export function stateFilePath(): string {
  return STATE_PATH;
}
