"""
Pantheon Health Dashboard — standalone FastAPI microservice.

Self-contained health checker that polls every Pantheon subsystem
and exposes a JSON API + HTML dashboard on port 9120.

Endpoints:
  GET /                 → Full HTML dashboard
  GET /api/health       → JSON: complete system snapshot
  GET /api/health/gods  → JSON: per-god gateway status
  GET /api/health/sys   → JSON: disk, memory, CPU
  GET /api/health/cron  → JSON: cron job freshness
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

# ── Paths ────────────────────────────────────────────────────────────
PANTHEON_DIR = Path(os.environ.get("PANTHEON_DIR", str(Path.home() / "pantheon")))
HERMES_HOME  = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
ATHENAEUM_DIR = Path(os.environ.get("ATHENAEUM_DIR", str(Path.home() / "athenaeum")))
ICHOR_DB     = HERMES_HOME / "ichor.db"
CONDUCTOR_DIR = PANTHEON_DIR / "conductor"
WORKFLOWS_DIR = CONDUCTOR_DIR / "workflows"

GOD_PROFILES = ["hermes", "hephaestus", "iris", "marvin", "thoth"]

# Known gateway service names (systemd unit suffixes)
GOD_SERVICE_MAP = {
    "hermes":     "hermes-gateway",
    "hephaestus": "hermes-gateway-hephaestus",
    "iris":       "hermes-gateway-iris",
    "marvin":     "hermes-gateway-marvin",
    "thoth":      "thoth-gateway",
}

# Checks to probe at /api/health/gods detail
SERVICE_CHECKS = {
    "nats-server":       ("nats-server", 4222),
    "conductor":         ("conductor", 8088),
    "pantheon-mcp":      ("pantheon-mcp", 8010),
    "api-server":        ("api_server", 9119),
}

app = FastAPI(title="Pantheon Health Dashboard", version="0.1.0")


# ── Helpers ──────────────────────────────────────────────────────────

def _sh(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run a shell command, return (exit_code, stdout+stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return -1, "command not found"
    except subprocess.TimeoutExpired:
        return -2, "timeout"


def _port_open(host: str, port: int, timeout: float = 3) -> bool:
    """TCP connect check."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, timeout: float = 5) -> tuple[int, str]:
    """Simple HTTP GET via curl (avoid deps)."""
    rc, out = _sh(["curl", "-sS", "-m", str(int(timeout)), "-o", "/dev/null", "-w", "%{http_code}", url], timeout=int(timeout) + 2)
    try:
        code = int(out.strip())
    except ValueError:
        code = 0
    return rc, code


# ── Collectors ───────────────────────────────────────────────────────

def check_gods() -> dict[str, Any]:
    """Per-god gateway health via systemctl."""
    results: dict[str, Any] = {}
    for god in GOD_PROFILES:
        svc = GOD_SERVICE_MAP.get(god, f"hermes-gateway-{god}")
        rc, out = _sh(["systemctl", "--user", "is-active", svc])
        active = out.strip() == "active"
        results[god] = {
            "service": svc,
            "status": "active" if active else out.strip() or "unknown",
            "pid": None,
        }
        if active:
            # Grab PID
            pid_out = subprocess.run(["pgrep", "-f", f"profile {god}.*gateway"], capture_output=True, timeout=5).stdout.decode().strip()
            results[god]["pid"] = pid_out.strip() if pid_out else None
    return results


def check_services() -> dict[str, Any]:
    """Core infrastructure services."""
    results: dict[str, Any] = {}
    for name, (proc, port) in SERVICE_CHECKS.items():
        rc_pid, pid_out = _sh(["pgrep", "-f", proc], timeout=5)
        port_open = _port_open("127.0.0.1", port)
        results[name] = {
            "pid": pid_out.strip() if pid_out and rc_pid == 0 else None,
            "port": port,
            "port_open": port_open,
            "running": rc_pid == 0,
        }
    return results


def check_ichor() -> dict[str, Any]:
    """Read ichor health from DB directly."""
    result: dict[str, Any] = {
        "db_exists": ICHOR_DB.exists(),
        "fts5_count": None,
        "graph_entities": None,
        "graph_relationships": None,
        "events_count": None,
        "provisional_entities": None,
        "error": None,
    }
    if not ICHOR_DB.exists():
        result["error"] = "ichor.db not found"
        return result

    try:
        conn = sqlite3.connect(str(ICHOR_DB))
        cur = conn.cursor()
        # Check which tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}

        if "memory_store" in tables:
            cur.execute("SELECT COUNT(*) FROM memory_store WHERE backend='fts5'")
            result["fts5_count"] = cur.fetchone()[0]

        if "entities" in tables:
            cur.execute("SELECT COUNT(*) FROM entities")
            result["graph_entities"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM entities WHERE provisional=1")
            result["provisional_entities"] = cur.fetchone()[0]
        if "relationships" in tables:
            cur.execute("SELECT COUNT(*) FROM relationships")
            result["graph_relationships"] = cur.fetchone()[0]

        if "ichor_events" in tables:
            cur.execute("SELECT COUNT(*) FROM ichor_events")
            result["events_count"] = cur.fetchone()[0]

        conn.close()
    except Exception as e:
        result["error"] = str(e)

    return result


def check_hades() -> dict[str, Any]:
    """Check Hades report freshness."""
    reports_dir = ATHENAEUM_DIR / "Codex-Pantheon" / "reports"
    result: dict[str, Any] = {
        "latest_report": None,
        "age_hours": None,
        "fresh": False,
        "error": None,
    }
    if not reports_dir.exists():
        result["error"] = "reports dir not found"
        return result

    reports = sorted(reports_dir.glob("hades-2*-*.md"), reverse=True)
    if not reports:
        result["error"] = "no hades reports found"
        return result

    latest = reports[0]
    mtime = latest.stat().st_mtime
    age_hours = (time.time() - mtime) / 3600
    result["latest_report"] = latest.name
    result["age_hours"] = round(age_hours, 1)
    result["fresh"] = age_hours < 27  # Should run nightly, allow some lag
    return result


def check_athenaeum() -> dict[str, Any]:
    """Athenaeum codex overview."""
    result: dict[str, Any] = {
        "codex_count": 0,
        "total_files": 0,
        "walkable": False,
        "error": None,
    }
    if not ATHENAEUM_DIR.exists():
        result["error"] = "athenaeum dir not found"
        return result

    # Count codex directories (subdirs of Codex-*)
    codexes = [d for d in ATHENAEUM_DIR.iterdir() if d.is_dir() and d.name.startswith("Codex-")]
    result["codex_count"] = len(codexes)

    # Count files recursively (quick estimate - depth 2)
    total = 0
    for c in codexes:
        for f in c.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".py", ".ts", ".yaml", ".json", ".txt"):
                total += 1
    result["total_files"] = total
    result["walkable"] = (ATHENAEUM_DIR / "INDEX.md").exists()
    return result


def check_cron_freshness() -> dict[str, Any]:
    """Check if key cron jobs have run recently."""
    cron_dir = HERMES_HOME / "cron" / "output"
    result: dict[str, Any] = {
        "jobs": {},
        "error": None,
    }
    if not cron_dir.exists():
        result["error"] = "cron output dir not found"
        return result

    # Check specific critical cron jobs
    critical_jobs = {
        "morning-briefing":     "331070b7515c",
        "dawn-patrol-raw":      "bc48fc05574b",
        "dawn-patrol-thoth":    "6cca0b6cc16e",
        "hades-nightly":        "cfb065b056ac",
        "hermes-dojo":          "094c10e20512",
        "ichor-maint":          "ichor-daily-maint",
    }
    for label, job_id in critical_jobs.items():
        job_dir = cron_dir / job_id
        if not job_dir.exists():
            result["jobs"][label] = {"last_run": None, "age_hours": None, "fresh": False}
            continue
        files = sorted(job_dir.glob("*.md"), reverse=True)
        if not files:
            result["jobs"][label] = {"last_run": None, "age_hours": None, "fresh": False}
            continue
        mtime = files[0].stat().st_mtime
        age_hours = (time.time() - mtime) / 3600
        result["jobs"][label] = {
            "last_run": files[0].stem,
            "age_hours": round(age_hours, 1),
            "fresh": age_hours < 27,
        }
    return result


def check_conductor_quarantine() -> dict[str, Any]:
    """Check conductor quarantine backlog."""
    script = CONDUCTOR_DIR / "scripts" / "quarantine_status.py"
    result: dict[str, Any] = {
        "count": None,
        "oldest_age_seconds": None,
        "error": None,
    }
    if not script.exists():
        result["error"] = "quarantine_status.py not found"
        return result

    rc, out = _sh(["python3", str(script)], timeout=10)
    if rc != 0:
        result["error"] = f"script exited {rc}: {out[:200]}"
        return result

    try:
        data = json.loads(out)
        result["count"] = data.get("count", 0)
        result["oldest_age_seconds"] = data.get("oldest_age_seconds")
    except json.JSONDecodeError:
        result["error"] = f"unparseable output: {out[:200]}"
    return result


def check_system() -> dict[str, Any]:
    """Disk, memory, CPU."""
    try:
        disk = psutil.disk_usage("/")
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=1)
        load_avg = psutil.getloadavg()
        return {
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "used_gb": round(disk.used / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
                "percent": disk.percent,
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 1),
                "available_gb": round(mem.available / (1024**3), 1),
                "percent": mem.percent,
            },
            "cpu": {
                "percent": cpu_pct,
                "load_1m": round(load_avg[0], 2),
                "load_5m": round(load_avg[1], 2),
                "load_15m": round(load_avg[2], 2),
            },
        }
    except Exception as e:
        return {"error": str(e)}


def check_api_pool() -> dict[str, Any]:
    """Probe credential pool health by checking auth.json."""
    auth_path = HERMES_HOME / "auth.json"
    result: dict[str, Any] = {
        "providers": {},
        "error": None,
    }
    if not auth_path.exists():
        result["error"] = "auth.json not found"
        return result

    try:
        with open(auth_path) as f:
            data = json.load(f)
        pool = data.get("credential_pool", {})
        for provider, entries in pool.items():
            total = len(entries)
            ok_count = sum(1 for e in entries if e.get("last_status") in (None, "ok"))
            exhausted = sum(1 for e in entries if e.get("last_status") == "exhausted")
            result["providers"][provider] = {
                "total_keys": total,
                "ok": ok_count,
                "exhausted": exhausted,
                "healthy": exhausted < total if total > 0 else False,
            }
    except Exception as e:
        result["error"] = str(e)

    return result


# ── API Routes ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health_full() -> dict[str, Any]:
    """Full system health snapshot — runs ALL checks in parallel."""
    gods, services, ichor, hades, athenaeum, cron_q, quarantine, sys_info, pool = await asyncio.gather(
        asyncio.to_thread(check_gods),
        asyncio.to_thread(check_services),
        asyncio.to_thread(check_ichor),
        asyncio.to_thread(check_hades),
        asyncio.to_thread(check_athenaeum),
        asyncio.to_thread(check_cron_freshness),
        asyncio.to_thread(check_conductor_quarantine),
        asyncio.to_thread(check_system),
        asyncio.to_thread(check_api_pool),
    )

    # Compute overall status
    all_gods_up = all(g.get("status") == "active" for g in gods.values())
    all_services_up = all(s.get("port_open") or s.get("running") for s in services.values())
    ichor_healthy = ichor.get("fts5_count") is not None or ichor.get("graph_entities") is not None
    hades_fresh = hades.get("fresh", False)
    pool_healthy = all(p.get("healthy", False) for p in pool.get("providers", {}).values())

    issues = []
    if not all_gods_up:
        down = [g for g, v in gods.items() if v.get("status") != "active"]
        issues.append(f"gods down: {', '.join(down)}")
    if not all_services_up:
        down_svc = [n for n, v in services.items() if not (v.get("port_open") or v.get("running"))]
        if down_svc:
            issues.append(f"services down: {', '.join(down_svc)}")
    if not ichor_healthy:
        issues.append("ichor db unhealthy")
    if not hades_fresh:
        issues.append(f"hades stale ({hades.get('age_hours', '?')}h)")
    if not pool_healthy:
        bad_pool = [p for p, v in pool.get("providers", {}).items() if not v.get("healthy", False)]
        if bad_pool:
            issues.append(f"pool issues: {', '.join(bad_pool)}")
    quarantine_count = quarantine.get("count", 0)
    if quarantine_count and quarantine_count > 0:
        issues.append(f"conductor quarantine: {quarantine_count} files")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": "healthy" if len(issues) == 0 else "degraded" if len(issues) <= 2 else "unhealthy",
        "issues": issues,
        "gods": gods,
        "services": services,
        "ichor": ichor,
        "hades": hades,
        "athenaeum": athenaeum,
        "cron": cron_q,
        "quarantine": quarantine,
        "system": sys_info,
        "api_pool": pool,
    }


@app.get("/api/health/gods")
async def health_gods() -> dict[str, Any]:
    gods = await asyncio.to_thread(check_gods)
    services = await asyncio.to_thread(check_services)
    pool = await asyncio.to_thread(check_api_pool)
    return {"gods": gods, "services": services, "api_pool": pool}


@app.get("/api/health/sys")
async def health_sys() -> dict[str, Any]:
    return await asyncio.to_thread(check_system)


@app.get("/api/health/cron")
async def health_cron() -> dict[str, Any]:
    return await asyncio.to_thread(check_cron_freshness)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Live HTML dashboard — fetches /api/health via JS and renders cards."""
    return HTMLResponse(HTML_DASHBOARD)


# ── Static HTML Dashboard ────────────────────────────────────────────

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pantheon Health Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --card: #1a1d29; --border: #2a2d3a;
    --green: #34d399; --yellow: #fbbf24; --red: #ef4444; --gray: #6b7280;
    --text: #e2e8f0; --muted: #94a3b8;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); padding: 20px;
  }
  .header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 24px; gap: 12px; flex-wrap: wrap;
  }
  .header h1 { font-size: 1.5rem; font-weight: 700; }
  .header-right { display: flex; align-items: center; gap: 16px; font-size: 0.85rem; color: var(--muted); }
  .overall-badge {
    padding: 4px 14px; border-radius: 20px; font-weight: 600; font-size: 0.8rem;
  }
  .healthy { background: rgba(52,211,153,.15); color: var(--green); }
  .degraded { background: rgba(251,191,36,.15); color: var(--yellow); }
  .unhealthy { background: rgba(239,68,68,.15); color: var(--red); }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }

  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px; display: flex; flex-direction: column; gap: 10px;
  }
  .card-header { display: flex; justify-content: space-between; align-items: center; }
  .card-title { font-size: 0.9rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  .card .status-dot {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  }
  .dot-ok { background: var(--green); }
  .dot-warn { background: var(--yellow); }
  .dot-err { background: var(--red); }
  .dot-none { background: var(--gray); }

  .row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; }
  .row-label { color: var(--muted); }
  .row-value { font-weight: 500; }
  .badge { padding: 1px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; }
  .badge-active, .badge-ok { background: rgba(52,211,153,.15); color: var(--green); }
  .badge-inactive, .badge-stale, .badge-exhausted { background: rgba(239,68,68,.15); color: var(--red); }
  .badge-warning { background: rgba(251,191,36,.15); color: var(--yellow); }
  .badge-unknown { background: rgba(107,114,128,.15); color: var(--gray); }

  .issues-list { list-style: none; padding: 0; }
  .issues-list li { padding: 4px 0; font-size: 0.85rem; color: var(--red); }
  .issues-list li::before { content: '⚠ '; }

  .progress-bar {
    width: 100%; height: 4px; background: var(--border); border-radius: 4px; overflow: hidden;
  }
  .progress-fill { height: 100%; border-radius: 4px; transition: width 0.5s; }
  .fill-green { background: var(--green); }
  .fill-yellow { background: var(--yellow); }
  .fill-red { background: var(--red); }

  .refresh-btn {
    background: var(--card); border: 1px solid var(--border); color: var(--text);
    padding: 6px 16px; border-radius: 8px; cursor: pointer; font-size: 0.8rem;
  }
  .refresh-btn:hover { background: var(--border); }

  @media (max-width: 700px) {
    .grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="header">
  <h1>🩺 Pantheon Health</h1>
  <div class="header-right">
    <span id="timestamp">loading…</span>
    <span id="overall-badge" class="overall-badge healthy">checking</span>
    <button class="refresh-btn" onclick="fetchHealth()">⟳ refresh</button>
  </div>
</div>
<div id="issues-container"></div>
<div id="grid" class="grid"></div>

<script>
async function fetchHealth() {
  document.querySelector('.refresh-btn').textContent = '⟳ loading…';
  try {
    const res = await fetch('/api/health');
    const d = await res.json();
    render(d);
  } catch(e) {
    document.getElementById('grid').innerHTML = `<div class="card"><div class="card-header"><span class="card-title">Connection Error</span></div><div class="row"><span class="row-label">${e}</span></div></div>`;
  }
  document.querySelector('.refresh-btn').textContent = '⟳ refresh';
}

function statusDot(status) {
  if (status === 'active' || status === true || status === 'ok') return 'dot-ok';
  if (status === 'degraded' || status === 'warning') return 'dot-warn';
  if (status === 'inactive' || status === false || status === 'exhausted' || status === 'error') return 'dot-err';
  return 'dot-none';
}

function badge(s, label) {
  if (!label) label = String(s);
  const cls = s === true || s === 'active' || s === 'ok' || s === 0 || s === '0' ? 'badge-active' :
             s === false || s === 'inactive' || s === 'exhausted' ? 'badge-inactive' :
             s === 'warning' ? 'badge-warning' : 'badge-unknown';
  return `<span class="badge ${cls}">${label}</span>`;
}

function progressBar(pct, cls = 'fill-yellow') {
  if (pct > 80) cls = 'fill-red';
  else if (pct > 60) cls = 'fill-yellow';
  else cls = 'fill-green';
  return `<div class="progress-bar"><div class="progress-fill ${cls}" style="width:${pct}%"></div></div>`;
}

function render(d) {
  document.getElementById('timestamp').textContent = new Date(d.timestamp).toLocaleString();

  const badge = document.getElementById('overall-badge');
  badge.textContent = d.overall;
  badge.className = `overall-badge ${d.overall}`;

  // Issues
  const ic = document.getElementById('issues-container');
  if (d.issues && d.issues.length) {
    ic.innerHTML = `<div class="card" style="border-color:rgba(239,68,68,.3)"><ul class="issues-list">${d.issues.map(i => `<li>${i}</li>`).join('')}</ul></div>`;
  } else {
    ic.innerHTML = '';
  }

  const grid = document.getElementById('grid');

  let cards = '';

  // ── Gods card ──
  cards += `<div class="card"><div class="card-header"><span class="card-title">God Gateways</span><span class="status-dot ${statusDot(Object.values(d.gods).every(g=>g.status==='active'))}"></span></div>`;
  for (const [name, g] of Object.entries(d.gods)) {
    cards += `<div class="row"><span class="row-label">${name}</span>${badge(g.status)}</div>`;
  }
  cards += `</div>`;

  // ── Services card ──
  cards += `<div class="card"><div class="card-header"><span class="card-title">Infrastructure</span><span class="status-dot ${statusDot(Object.values(d.services).every(s=>s.port_open||s.running))}"></span></div>`;
  for (const [name, s] of Object.entries(d.services)) {
    const ok = s.port_open || s.running;
    cards += `<div class="row"><span class="row-label">${name}</span>${ok ? badge(true) : badge(false)}${s.pid ? ` <span style="color:var(--muted);font-size:0.75rem">PID ${s.pid}</span>` : ''}</div>`;
  }
  cards += `</div>`;

  // ── Ichor card ──
  const ichor = d.ichor;
  cards += `<div class="card"><div class="card-header"><span class="card-title">Ichor Memory</span><span class="status-dot ${ichor.error ? 'dot-err' : 'dot-ok'}"></span></div>`;
  if (ichor.error) { cards += `<div class="row"><span class="row-label">error</span><span style="color:var(--red)">${ichor.error}</span></div>`; }
  cards += `<div class="row"><span class="row-label">FTS5 entries</span><span class="row-value">${ichor.fts5_count ?? '?'}</span></div>`;
  cards += `<div class="row"><span class="row-label">Graph entities</span><span class="row-value">${ichor.graph_entities ?? '?'}</span></div>`;
  cards += `<div class="row"><span class="row-label">Relationships</span><span class="row-value">${ichor.graph_relationships ?? '?'}</span></div>`;
  cards += `<div class="row"><span class="row-label">Events</span><span class="row-value">${ichor.events_count ?? '?'}</span></div>`;
  if (ichor.provisional_entities !== null) {
    cards += `<div class="row"><span class="row-label">Provisional entities</span><span class="row-value">${ichor.provisional_entities}</span></div>`;
  }
  cards += `</div>`;

  // ── Hades card ──
  const hades = d.hades;
  cards += `<div class="card"><div class="card-header"><span class="card-title">Hades</span><span class="status-dot ${hades.fresh ? 'dot-ok' : 'dot-err'}"></span></div>`;
  cards += `<div class="row"><span class="row-label">Latest report</span><span class="row-value">${hades.latest_report ?? 'none'}</span></div>`;
  cards += `<div class="row"><span class="row-label">Age</span><span class="row-value">${hades.age_hours !== null ? hades.age_hours + 'h' : '?'}</span></div>`;
  cards += `<div class="row"><span class="row-label">Fresh</span>${badge(hades.fresh, hades.fresh ? 'yes' : 'no')}</div>`;
  cards += `</div>`;

  // ── Athenaeum card ──
  const ath = d.athenaeum;
  cards += `<div class="card"><div class="card-header"><span class="card-title">Athenaeum</span><span class="status-dot ${ath.error ? 'dot-err' : 'dot-ok'}"></span></div>`;
  if (ath.error) { cards += `<div class="row"><span class="row-label">error</span><span style="color:var(--red)">${ath.error}</span></div>`; }
  cards += `<div class="row"><span class="row-label">Codexes</span><span class="row-value">${ath.codex_count}</span></div>`;
  cards += `<div class="row"><span class="row-label">Files</span><span class="row-value">${ath.total_files}</span></div>`;
  cards += `<div class="row"><span class="row-label">Walkable</span>${badge(ath.walkable)}</div>`;
  cards += `</div>`;

  // ── Cron card ──
  cards += `<div class="card"><div class="card-header"><span class="card-title">Cron Jobs</span></div>`;
  for (const [name, j] of Object.entries(d.cron.jobs)) {
    cards += `<div class="row"><span class="row-label">${name}</span>${badge(j.fresh, j.fresh ? j.age_hours + 'h' : (j.age_hours ? j.age_hours + 'h stale' : 'never'))}</div>`;
  }
  cards += `</div>`;

  // ── API Pool card ──
  const pool = d.api_pool;
  cards += `<div class="card"><div class="card-header"><span class="card-title">API Key Pool</span><span class="status-dot ${pool.error ? 'dot-err' : 'dot-ok'}"></span></div>`;
  if (pool.error) { cards += `<div class="row"><span class="row-label">error</span><span style="color:var(--red)">${pool.error}</span></div>`; }
  for (const [prov, p] of Object.entries(pool.providers)) {
    const healthy = p.ok > 0 && p.exhausted < p.total_keys;
    cards += `<div class="row"><span class="row-label">${prov}</span>${badge(healthy, p.ok + '/' + p.total_keys)}`;
    if (p.exhausted > 0) cards += ` <span style="color:var(--red);font-size:0.75rem">${p.exhausted} exhausted</span>`;
    cards += `</div>`;
  }
  cards += `</div>`;

  // ── Quarantine card ──
  const q = d.quarantine;
  cards += `<div class="card"><div class="card-header"><span class="card-title">Conductor Quarantine</span><span class="status-dot ${(q.count || 0) > 0 ? 'dot-warn' : 'dot-ok'}"></span></div>`;
  cards += `<div class="row"><span class="row-label">Pending files</span><span class="row-value">${q.count ?? '?'}</span></div>`;
  if (q.oldest_age_seconds) cards += `<div class="row"><span class="row-label">Oldest</span><span class="row-value">${Math.round(q.oldest_age_seconds/3600)}h</span></div>`;
  if (q.error) cards += `<div class="row"><span class="row-label">error</span><span style="color:var(--red)">${q.error}</span></div>`;
  cards += `</div>`;

  // ── System card ──
  const sys = d.system;
  if (!sys.error) {
    cards += `<div class="card"><div class="card-header"><span class="card-title">System</span></div>`;
    cards += `<div class="row"><span class="row-label">Disk</span><span class="row-value">${sys.disk.free_gb}GB free / ${sys.disk.total_gb}GB</span></div>`;
    cards += `<div class="row" style="flex-direction:column;gap:4px"><span class="row-label">Disk usage ${sys.disk.percent}%</span>${progressBar(sys.disk.percent)}</div>`;
    cards += `<div class="row"><span class="row-label">Memory</span><span class="row-value">${sys.memory.available_gb}GB free / ${sys.memory.total_gb}GB</span></div>`;
    cards += `<div class="row" style="flex-direction:column;gap:4px"><span class="row-label">Memory ${sys.memory.percent}%</span>${progressBar(sys.memory.percent)}</div>`;
    cards += `<div class="row"><span class="row-label">CPU</span><span class="row-value">${sys.cpu.percent}% (load: ${sys.cpu.load_1m})</span></div>`;
    cards += `</div>`;
  }

  grid.innerHTML = cards;
}

fetchHealth();
// Auto-refresh every 60 seconds
setInterval(fetchHealth, 60000);
</script>
</body>
</html>
"""


# ── Entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9120, log_level="info")
