#!/usr/bin/env python3
"""Cache-hit + metered-cost instrument for Hermes session usage.

Reads the Hermes session ledger (state.db, read-only) and reports, per route:

  * prompt tokens split into cache-read (hit) vs cache-miss
  * cache hit rate
  * metered cost, priced retroactively through agent.usage_pricing so the whole
    stored history is valued, not just rows written after the fix

and, for OpenCode Go (a $10/mo subscription whose usage is capped in DOLLARS),
cap burn against the published $12/5h, $30/wk, $60/mo limits.

Two deliberate honesty rules:

  1. Cost is priced at OFF-PEAK published rates (matching the convention already
     used by the bundled DeepSeek rows in agent/usage_pricing.py). Real spend is
     higher for traffic in DeepSeek's peak windows (01:00-04:00 and 06:00-10:00
     UTC, Mon-Fri), where every rate doubles.
  2. Cap-window burn is attributed by a row's last_seen timestamp, because the
     ledger aggregates per (session, model, provider) and keeps no per-call
     table. Treat 5h/7d figures as approximate; the credential-pool block is
     exact and comes from the provider's own rate-limit responses.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
SOURCE_TREE = HERMES_HOME / "hermes-agent"
STATE_DB = HERMES_HOME / "state.db"
AUTH_JSON = HERMES_HOME / "auth.json"

# OpenCode Go published dollar-value caps, in seconds.
GO_WINDOWS = (("5h", 5 * 3600, 12.0), ("7d", 7 * 86400, 30.0), ("30d", 30 * 86400, 60.0))

# Routes whose marginal cost is genuinely zero, so "unknown pricing" would be a
# misleading label: local inference and free-tier model ids.
_LOCAL_PROVIDERS = {"custom", "local", "bonsai", "ollama", "ollama-cloud", "cachyos-ods",
                    "cachyos-llama", "ornith", "local-litellm", "ods", "cachyos"}


def _load_pricing():
    """Import agent.usage_pricing from the live Hermes source tree."""
    if str(SOURCE_TREE) not in sys.path:
        sys.path.insert(0, str(SOURCE_TREE))
    from agent.usage_pricing import (  # noqa: PLC0415
        CanonicalUsage,
        estimate_usage_cost,
    )

    return CanonicalUsage, estimate_usage_cost


def _rows(days: float):
    """Yield ledger rows as dicts, oldest last_seen first."""
    if not STATE_DB.exists():
        raise SystemExit(f"no session ledger at {STATE_DB}")
    cutoff = time.time() - days * 86400
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            """
            SELECT session_id, model, billing_provider, billing_base_url,
                   SUM(input_tokens)       AS miss_in,
                   SUM(cache_read_tokens)  AS cache_read,
                   SUM(cache_write_tokens) AS cache_write,
                   SUM(output_tokens)      AS output,
                   SUM(api_call_count)     AS calls,
                   MAX(last_seen)          AS last_seen
              FROM session_model_usage
             WHERE last_seen >= ?
             GROUP BY session_id, model, billing_provider, billing_base_url
            """,
            (cutoff,),
        )
        for row in cur.fetchall():
            yield dict(row)
    finally:
        con.close()


def _is_free_route(model: str, provider: str) -> bool:
    return (provider or "").strip().lower() in _LOCAL_PROVIDERS or model.endswith(":free") or "-free" in model


def collect(days: float):
    """Aggregate priced and unpriced usage per route."""
    CanonicalUsage, estimate_usage_cost = _load_pricing()
    routes: dict[tuple[str, str], dict] = {}
    unpriced: dict[tuple[str, str], int] = {}
    go_events: list[tuple[float, float]] = []
    now = time.time()

    for row in _rows(days):
        model = row["model"] or "<unknown>"
        provider = (row["billing_provider"] or "").strip()
        key = (model, provider or "<unrecorded>")
        usage = CanonicalUsage(
            input_tokens=row["miss_in"] or 0,
            output_tokens=row["output"] or 0,
            cache_read_tokens=row["cache_read"] or 0,
            cache_write_tokens=row["cache_write"] or 0,
        )
        result = estimate_usage_cost(
            model, usage, provider=provider, base_url=row["billing_base_url"]
        )
        bucket = routes.setdefault(
            key,
            {"model": model, "provider": provider or "<unrecorded>", "miss_in": 0,
             "cache_read": 0, "output": 0, "calls": 0, "cost": 0.0, "priced": False},
        )
        for field, value in (("miss_in", row["miss_in"]), ("cache_read", row["cache_read"]),
                             ("output", row["output"]), ("calls", row["calls"])):
            bucket[field] += value or 0

        tokens = (row["miss_in"] or 0) + (row["cache_read"] or 0) + (row["output"] or 0)
        if result.status in ("estimated", "included"):
            bucket["priced"] = True
            bucket["cost"] += float(result.amount_usd or 0.0)
            if provider.lower() == "opencode-go":
                go_events.append((row["last_seen"] or 0.0, float(result.amount_usd or 0.0)))
        else:
            unpriced[key] = unpriced.get(key, 0) + tokens

    go_caps = []
    for label, span, limit in GO_WINDOWS:
        burned = sum(cost for ts, cost in go_events if ts >= now - span)
        go_caps.append({"window": label, "limit_usd": limit, "burned_usd": burned,
                        "pct": (burned / limit * 100.0) if limit else 0.0})
    return routes, unpriced, go_caps


def pool_status() -> list[dict]:
    """Exact per-key OpenCode Go state from the live credential pool."""
    if not AUTH_JSON.exists():
        return []
    try:
        auth = json.loads(AUTH_JSON.read_text())
        pool = (auth.get("credential_pool") or {}).get("opencode-go") or []
    except (OSError, ValueError):
        return []
    out = []
    for entry in pool:
        reset = entry.get("last_error_reset_at")
        out.append({
            "label": entry.get("label") or entry.get("id") or "?",
            "status": entry.get("last_status") or "?",
            "reason": entry.get("last_error_reason") or "",
            "reset_at": reset,
            "reset_in_h": ((reset - time.time()) / 3600.0) if reset else None,
            "requests": entry.get("request_count") or 0,
        })
    return out


def _hit_rate(miss_in: int, cache_read: int) -> float:
    total = miss_in + cache_read
    return (cache_read / total * 100.0) if total else 0.0


def render(routes, unpriced, go_caps, days: float) -> str:
    out: list[str] = []
    ordered = sorted(routes.values(),
                     key=lambda r: r["miss_in"] + r["cache_read"] + r["output"], reverse=True)
    total_tokens = sum(r["miss_in"] + r["cache_read"] + r["output"] for r in ordered)
    total_cost = sum(r["cost"] for r in ordered)
    total_read = sum(r["cache_read"] for r in ordered)
    total_miss = sum(r["miss_in"] for r in ordered)

    out.append(f"Cache + metered cost — last {days:g} days")
    out.append("=" * 78)
    out.append(f"prompt tokens {total_miss + total_read:,}   "
               f"cache hit {_hit_rate(total_miss, total_read):.1f}%   "
               f"metered ${total_cost:,.2f}")
    out.append("")
    out.append(f"{'model':30} {'provider':14} {'miss_in':>13} {'cache_read':>14} {'hit%':>6} {'cost':>9}")
    out.append("-" * 78)
    for r in ordered[:18]:
        if r["miss_in"] + r["cache_read"] + r["output"] == 0:
            continue
        cost = f"${r['cost']:.2f}" if r["priced"] else ("free" if _is_free_route(r["model"], r["provider"]) else "n/a")
        out.append(f"{r['model'][:30]:30} {r['provider'][:14]:14} {r['miss_in']:13,} "
                   f"{r['cache_read']:14,} {_hit_rate(r['miss_in'], r['cache_read']):5.1f}% {cost:>9}")

    out.append("")
    out.append("OpenCode Go cap burn ($12/5h · $30/wk · $60/mo of usage value)")
    out.append("-" * 78)
    out.append("  Short windows can read low: a blocked or idle route records no usage")
    out.append("  rows at all (a 429 produces none), so trust the pool block below for")
    out.append("  the current window and these figures for the trailing trend.")
    for cap in go_caps:
        bar = "#" * int(min(cap["pct"], 100.0) / 5.0)
        out.append(f"  {cap['window']:>4}  ${cap['burned_usd']:6.2f} / ${cap['limit_usd']:5.2f}"
                   f"  {cap['pct']:5.1f}%  {bar}")

    pool = pool_status()
    if pool:
        out.append("")
        out.append("Credential pool (exact, from the provider's own rate-limit responses)")
        out.append("-" * 78)
        for entry in pool:
            tail = f"reset in {entry['reset_in_h']:.1f}h" if entry["reset_in_h"] else ""
            out.append(f"  {entry['label'][:32]:32} {entry['status']:10} "
                       f"{(entry['reason'] or '-')[:20]:20} {tail}")

    if unpriced:
        free = sum(t for (m, p), t in unpriced.items() if _is_free_route(m, p))
        real = [(k, t) for k, t in unpriced.items() if not _is_free_route(k[0], k[1])]
        out.append("")
        out.append("Unpriced usage")
        out.append("-" * 78)
        out.append(f"  {free:,} tokens on local/free routes (genuinely $0, not a gap)")
        for (model, provider), tokens in sorted(real, key=lambda kv: -kv[1])[:8]:
            out.append(f"  {tokens:>13,}  {model[:34]:34} {provider[:20]}")
        if not real:
            out.append("  no metered route is missing a rate")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cache-hit + metered-cost instrument for Hermes session usage"
    )
    parser.add_argument("--days", type=float, default=30.0, help="trailing window (default 30)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    routes, unpriced, go_caps = collect(args.days)
    if args.json:
        print(json.dumps({
            "days": args.days,
            "routes": sorted(routes.values(), key=lambda r: -(r["miss_in"] + r["cache_read"])),
            "unpriced": [{"model": m, "provider": p, "tokens": t} for (m, p), t in unpriced.items()],
            "opencode_go_caps": go_caps,
            "credential_pool": pool_status(),
        }, indent=2, default=str))
    else:
        print(render(routes, unpriced, go_caps, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
