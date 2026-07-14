---
name: tailscale-link-convention
description: "Use whenever you need to give Konan a link to a local web service, dashboard, or UI. Converts localhost/127.0.0.1 references to Tailscale Serve URLs. Also load when you are about to start a web service — this skill tells you how to expose it via Tailscale instead of binding to 0.0.0.0."
version: 1.0.0
tags: [tailscale, networking, links, convention, pantheon-wide, accessibility]
---

# Tailscale Link Convention — `localhost` → Tailscale Serve

> **The rule:** Never give `http://localhost:PORT` or `http://127.0.0.1:PORT` links. Use `tailscale serve` and give a `https://pantheon-laptop.tail164759.ts.net/[...]` URL instead.

## When to load this skill

Load this skill whenever:

- You are about to start a web service, dashboard, or UI
- You need to give Konan a URL to access something running on this machine
- You see another god giving `localhost` links in the shared context
- Konan asks you to "bind to 0.0.0.0" — load this and do the Tailscale approach instead
- You're responding to a build report, research report, or deployment where a web interface is mentioned

**Don't load this skill for:** External URLs, URLs the user already has, or terminal-only services.

## The procedure

### Step 1: Tailscale Serve — Quick Reference

Your Tailscale identity:

| Property | Value |
|---|---|
| Hostname | `pantheon-laptop.tail164759.ts.net` |
| Tailnet | `tail164759.ts.net` |
| Tailscale version | 1.98.8 |

```bash
# Expose an HTTP service (background, root mount)
tailscale serve --bg 3000
# → https://pantheon-laptop.tail164759.ts.net/

# Expose at a subpath
tailscale serve --bg --set-path /grafana 3000
# → https://pantheon-laptop.tail164759.ts.net/grafana

# Expose a self-signed HTTPS backend
tailscale serve --bg https+insecure://localhost:8443
# See current mounts
tailscale serve status

# Remove a specific mount
tailscale serve reset
```

### Step 2: Check existing mounts first

Before adding a new path, run `tailscale serve status` to see what's already mounted. Avoid path conflicts.

### Step 3: Give the Tailscale URL, NOT localhost

**Always** format the link as:

```
https://pantheon-laptop.tail164759.ts.net/<path>
```

### Step 4: If the port is dynamic or unknown

If you need to find what port a recently-started service is on:

```bash
ss -tlnp | grep <process-name>
```

Or check the output of the command that started the service.

## Pitfalls

- **Do NOT bind to `0.0.0.0`** — the whole point is that the service stays on localhost. Tailscale Serve proxies to `127.0.0.1`, so the service must listen on localhost.
- **Check `tailscale serve status` before adding** — duplicate paths cause the last one to win silently.
- **`tailscale serve --tcp`** is available for raw TCP (SSH, databases) on a different port.
- **For sensitive services**, default serve is tailnet-only (not public). Use `tailscale funnel` only if you explicitly mean to expose to the internet.
- **After a reboot**, tailscale serve config persists — it's stored in Tailscale's state, not in-memory.
- **If a service crashes and restarts**, the Tailscale route stays up and reconnects when the service comes back.

## Verification

After following this skill, confirm:

- [ ] The URL starts with `https://pantheon-laptop.tail164759.ts.net`
- [ ] The command used was `tailscale serve --bg` (not a raw localhost link)
- [ ] You checked `tailscale serve status` first for conflicts
- [ ] The service is bound to `127.0.0.1` or `localhost`, not `0.0.0.0`

## See also

- `Codex-Pantheon/standards/tailscale-serve-link-convention.md` — the canonical convention document
- `tailscale serve --help` — the CLI reference
