"""Pantheon God Runtime — gateway process lifecycle management.

Scans system processes to determine which god gateways are running,
and provides invoke/sleep actions to start/stop per-profile gateway processes.

Heartbeat files: Each god runtime can write ~/.hermes/gods/{name}/heartbeat.json
on each loop iteration. The health panel reads these to determine 5-state status.
"""
import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Heartbeat directory ─────────────────────────────────────────────────────
HEARTBEAT_DIR = Path.home() / ".hermes" / "gods"

# ── Heartbeat helpers ───────────────────────────────────────────────────────


def _ensure_heartbeat_dir() -> Path:
    """Create the heartbeat directory if it doesn't exist."""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    return HEARTBEAT_DIR


def _write_god_heartbeat(god_name: str, status: str = "active", session_id: str = None) -> dict:
    """Write a heartbeat file for a god runtime.

    Called by the god's main loop (or periodically) to signal liveness.
    Returns the heartbeat dict that was written.
    """
    god_dir = _ensure_heartbeat_dir() / god_name
    god_dir.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "timestamp": time.time(),
        "iso_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "session_id": session_id or None,
        "pid": os.getpid(),
    }
    hb_file = god_dir / "heartbeat.json"
    try:
        hb_file.write_text(json.dumps(heartbeat))
    except OSError as e:
        logger.warning("Failed to write heartbeat for '%s': %s", god_name, e)
    return heartbeat


def _read_god_heartbeat(god_name: str) -> dict | None:
    """Read a god's heartbeat file. Returns None if file doesn't exist."""
    hb_file = HEARTBEAT_DIR / god_name / "heartbeat.json"
    if not hb_file.exists():
        return None
    try:
        return json.loads(hb_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _check_god_process(name: str) -> dict | None:
    """Check if a god process exists using /proc/{pid}/status.

    Returns {'pid': int, 'state': str} or None if not found.
    """
    # First use the cached ps scan result
    state = _get_god_state(name)
    if state.get("state") != "awake":
        return None
    pid = state.get("pid")
    if not pid:
        return None
    # Verify process is still alive using /proc
    try:
        proc_status = Path(f"/proc/{pid}/status")
        if proc_status.exists():
            data = proc_status.read_text()
            for line in data.splitlines():
                if line.startswith("State:"):
                    proc_state = line.split(":")[1].strip().split()[0]
                    return {"pid": pid, "state": proc_state, "proc_state": proc_state}
    except (OSError, FileNotFoundError):
        pass
    # Fallback: try kill -0
    try:
        os.kill(pid, 0)
        return {"pid": pid, "state": "alive", "proc_state": "S"}
    except OSError:
        return None


# ── Process scanning ──────────────────────────────────────────────────────

_GOD_STATE_CACHE = {}       # god_name -> {'state': str, 'pid': int, 'since': float}
_GOD_STATE_CACHE_TS = 0     # last cache refresh
_CACHE_TTL = 5.0            # seconds before re-scanning ps aux


def _scan_gateway_processes() -> dict[str, dict]:
    """Scan ps aux for hermes gateway processes keyed by profile name.

    Returns {profile_name: {'pid': int, 'state': 'awake', 'since': float}}
    """
    god_processes = {}
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            # Match: hermes --profile <name> gateway run
            if '--profile' in line and 'gateway' in line and 'run' in line:
                parts = line.split()
                name = None
                for i, p in enumerate(parts):
                    if p == '--profile' and i + 1 < len(parts):
                        name = parts[i + 1].strip()
                        break
                if name:
                    pid = _extract_pid(line)
                    god_processes[name] = {
                        'pid': pid,
                        'state': 'awake',
                        'since': time.time(),
                    }
            # Match: the default profile gateway (no --profile flag)
            # Only match the main hermes gateway run, not child bash wrappers
            elif 'gateway' in line and 'run' in line and '--profile' not in line:
                pid = _extract_pid(line)
                if pid and pid != 1:
                    god_processes['default'] = {
                        'pid': pid,
                        'state': 'awake',
                        'since': time.time(),
                    }
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Failed to scan gateway processes: %s", e)

    return god_processes


def _extract_pid(line: str) -> int | None:
    """Extract PID from a ps aux line."""
    parts = line.split()
    if len(parts) > 1:
        try:
            return int(parts[1])
        except (ValueError, IndexError):
            pass
    return None


def _get_god_state(name: str) -> dict:
    """Get the current runtime state for a god/profile by scanning processes.

    Returns {'state': 'awake'|'sleeping', 'pid': int|None, 'since': float|None}
    """
    global _GOD_STATE_CACHE, _GOD_STATE_CACHE_TS
    now = time.time()
    if now - _GOD_STATE_CACHE_TS > _CACHE_TTL:
        _GOD_STATE_CACHE = _scan_gateway_processes()
        _GOD_STATE_CACHE_TS = now

    entry = _GOD_STATE_CACHE.get(name, {})
    return {
        'state': entry.get('state', 'sleeping'),
        'pid': entry.get('pid'),
        'since': entry.get('since'),
    }


def refresh_god_statuses() -> dict[str, dict]:
    """Force-refresh the process cache and return all gods' runtime states."""
    global _GOD_STATE_CACHE, _GOD_STATE_CACHE_TS
    _GOD_STATE_CACHE = _scan_gateway_processes()
    _GOD_STATE_CACHE_TS = time.time()
    return dict(_GOD_STATE_CACHE)


# ── Invoke / Sleep ────────────────────────────────────────────────────────

_hermes_cli = None  # lazy-resolve


def _resolve_hermes_cli() -> str:
    """Find the 'hermes' CLI binary path."""
    global _hermes_cli
    if _hermes_cli:
        return _hermes_cli

    # Try PATH first
    for path in os.environ.get('PATH', '').split(':'):
        candidate = Path(path) / 'hermes'
        if candidate.exists() and os.access(candidate, os.X_OK):
            _hermes_cli = str(candidate)
            return _hermes_cli

    # Fallback: look in the hermes-agent venv
    venv_paths = [
        Path.home() / '.hermes' / 'hermes-agent' / 'venv' / 'bin' / 'hermes',
        Path.home() / '.local' / 'bin' / 'hermes',
    ]
    for vp in venv_paths:
        if vp.exists() and os.access(vp, os.X_OK):
            _hermes_cli = str(vp)
            return vp

    _hermes_cli = 'hermes'  # fallback — let subprocess figure it out
    return _hermes_cli


def invoke_god(name: str) -> dict:
    """Invoke (start) a god's gateway process.

    Starts `hermes --profile <name> gateway run --replace` in the background.
    Returns {'ok': True, 'state': 'starting'} on success.
    """
    if name == 'default':
        # Default Hermes is always-on via systemd; just confirm it's running
        state = _get_god_state('default')
        if state['state'] == 'awake':
            return {'ok': True, 'state': 'awake', 'message': 'Hermes is already awake'}
        # If the default gateway somehow isn't running, try starting it
        cli = _resolve_hermes_cli()
        subprocess.Popen(
            [cli, 'gateway', 'run', '--replace'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _invalidate_cache()
        return {'ok': True, 'state': 'starting', 'message': 'Invoking Hermes...'}

    cli = _resolve_hermes_cli()
    try:
        proc = subprocess.Popen(
            [cli, '--profile', name, 'gateway', 'run', '--replace'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _invalidate_cache()
        return {
            'ok': True,
            'state': 'starting',
            'pid': proc.pid,
            'message': f'{name.capitalize()} invoked',
        }
    except FileNotFoundError:
        return {'ok': False, 'state': 'error', 'error': 'Hermes CLI not found'}
    except Exception as e:
        logger.error("Failed to invoke god '%s': %s", name, e)
        return {'ok': False, 'state': 'error', 'error': str(e)}


def sleep_god(name: str) -> dict:
    """Put a god to sleep by killing its gateway process.

    Returns {'ok': True, 'state': 'sleeping'} on success.
    """
    if name == 'default':
        return {
            'ok': False,
            'state': 'error',
            'error': 'Cannot sleep the default Hermes — she is always-on',
        }

    state = _get_god_state(name)
    if state['state'] != 'awake':
        return {'ok': True, 'state': 'sleeping', 'message': f'{name.capitalize()} is already sleeping'}

    pid = state.get('pid')
    if not pid:
        return {'ok': False, 'state': 'error', 'error': 'Could not find gateway process'}

    try:
        os.kill(pid, 15)  # SIGTERM
        # Give it a moment, then SIGKILL if still alive
        time.sleep(0.5)
        try:
            os.kill(pid, 0)  # Check if alive
            os.kill(pid, 9)  # SIGKILL
        except OSError:
            pass  # Process already dead — good
        _invalidate_cache()
        return {'ok': True, 'state': 'sleeping', 'message': f'{name.capitalize()} put to sleep'}
    except ProcessLookupError:
        _invalidate_cache()
        return {'ok': True, 'state': 'sleeping', 'message': f'{name.capitalize()} was already asleep'}
    except Exception as e:
        logger.error("Failed to sleep god '%s': %s", name, e)
        return {'ok': False, 'state': 'error', 'error': str(e)}


def _invalidate_cache() -> None:
    """Force the next status check to re-scan processes."""
    global _GOD_STATE_CACHE_TS
    _GOD_STATE_CACHE_TS = 0
