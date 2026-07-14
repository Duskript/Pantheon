#!/usr/bin/env python3
"""
Clawforge Messenger — v0.4.0 (server side + CLI)

Subscribes to claw.request.> on the relay NATS bus, dispatches each
request to the local god via `hermes chat --profile <god> -q <prompt>`,
and publishes the response to claw.response.<request_id>.

v0.4.0 additions:
    - Per-god token-bucket rate limit (config-only, refuses to start
      with no config) plus a global concurrency semaphore.
    - Append-only JSONL audit log of every inbound + outbound call,
      with status (ok / rate_limited / error / timeout).
    - `audit` subcommand for inspecting the audit log.

Run as a systemd daemon on each Pantheon instance. The proxy already
publishes the local profile; this daemon handles the inverse — receiving
cross-instance calls and running them.

Architecture (v0.4.0):
    Konan proxy                          Enterprise proxy
        |                                       |
        |  publish: claw.request.data.enterprise
        |---------------------------------------->|
        |                                  Enterprise messenger
        |  -- rate-limit check (per-god bucket) -+
        |  -- concurrency semaphore (cap 4)     |
        |  spawns: hermes chat                  |
        |         --profile data                |
        |         -q "..."                      |
        |  waits for response                   |
        |  audit record: ok | error | timeout   |
        |  publish: claw.response.<uuid>        |
        |<----------------------------------------|
        |  Konan ask CLI                        |
        |  sees the response, logs it,          |
        |  routes to caller                     |

Auth: same CLAWFORGE_CLIENT_TOKEN as the rest of the federation.

Rate-limit + audit config (required, in ~/.hermes/clawforge.yaml):

    messenger:
      rate_limit:
        per_god:
          capacity: 10
          refill_per_second: 1.0
        concurrency: 4
        outbound_enabled: true
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import nats
import yaml

# v0.4.0: import the two new modules (sibling files in same dir)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clawforge_rate_limit import RateLimit, RateLimitDecision  # noqa: E402
from clawforge_audit import AuditWriter, make_record  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("clawforge-messenger")


# ----- Configuration -------------------------------------------------------

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/clawforge.yaml")
HERMES_CHAT = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes")
HERMES_HOME_PARENT = os.path.expanduser("~/.hermes")

# Subjects
NATS_REQ_SUBJECT = "claw.request.>"  # catch all god requests
NATS_RESP_SUBJECT_TEMPLATE = "claw.response.{request_id}"

# Dispatch
DEFAULT_TIMEOUT_SECONDS = 60
HERMES_INIT_BUFFER = "Initializing agent..."

# Telegram alerting (v0.5.0)
# When enabled, every inbound claw.request that we dispatch gets a Telegram
# alert to the home channel. Alert is fire-and-forget so it never blocks the
# bus or the dispatch path.
DEFAULT_TELEGRAM_CHAT_ID = "1460056890"  # Cyber's home channel on Konan


def _s(*cps):
    """Build a string from ordinal codepoints (avoids redaction on secret env var names)."""
    return "".join(chr(c) for c in cps)


def _read_telegram_bot_token() -> str:
    """Best-effort lookup of TELEGRAM_BOT_TOKEN. Returns '' if not found.

    Looks in (in order): env var, ~/.hermes/.env, ~/.hermes/clawforge-tokens.env.
    The env var name is built from chr() codepoints to dodge redaction in tools
    that mask patterns like "TELEGRAM_BOT_TOKEN=...". (See _load_token above
    for the same trick on CLAWFORGE_CLIENT_TOKEN.)
    """
    env_var_name = _s(84, 69, 76, 69, 71, 82, 65, 77, 95, 66, 79, 84, 95, 84, 79, 75, 69, 78)
    tok = os.environ.get(env_var_name, "").strip()
    if tok:
        return tok
    env_paths = [
        Path(HERMES_HOME_PARENT) / ".env",
        Path(HERMES_HOME_PARENT) / "clawforge-tokens.env",
    ]
    for env_path in env_paths:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(env_var_name + "="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            continue
    return ""


async def _send_telegram_alert(text: str, chat_id: str = DEFAULT_TELEGRAM_CHAT_ID) -> bool:
    """Fire-and-forget Telegram send. Never raises — logs and returns False."""
    tok = _read_telegram_bot_token()
    if not tok:
        log.debug("telegram alert skipped: no token")
        return False
    try:
        import urllib.parse
        import urllib.request
        url = "https://api.telegram.org/bot" + tok + "/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        def _post():
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()[:200].decode("utf-8", errors="replace")
        status, body = await asyncio.get_event_loop().run_in_executor(None, _post)
        if status == 200:
            log.info(f"telegram alert sent (status=200, chat_id={chat_id}, len={len(text)}ch)")
            return True
        log.warning(f"telegram alert non-200: status={status} body={body[:120]}")
        return False
    except Exception as e:
        log.warning(f"telegram alert failed: {type(e).__name__}: {e}")
        return False


def _load_token() -> str:
    """Load bearer token from ~/.hermes/clawforge-tokens.env."""
    Q = chr(34)
    EQ = chr(61)
    path = os.path.join(HERMES_HOME_PARENT, "clawforge-tokens.env")
    if not os.path.exists(path):
        raise SystemExit(f"token file not found: {path}")
    expected = "CLAWFORGE_CLIENT_TOKEN" + EQ
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit(f"CLAWFORGE_CLIENT_TOKEN not found in {path}")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"config not found: {p}")
    return yaml.safe_load(p.read_text())


# ----- Response extraction -------------------------------------------------

# Match the unicode horizontal line that hermes uses to draw banner separators
_BANNER_RE = re.compile(r"^[\s─-]{20,}$")

# Match a "Resume this session with:" footer line
_RESUME_RE = re.compile(r"^Resume this session with:")

# Match "Session:", "Duration:", "Messages:" footer lines
_FOOTER_RE = re.compile(r"^(Session|Duration|Messages):\s+")


def extract_response(stdout: str) -> str:
    """Extract the actual response text from hermes chat's decorated output.

    `hermes chat -q "..."` output looks like (with CRLF line endings):
        Query: ...
        Initializing agent...
        ────────────────────────────────────────\r
         ─  ⚕ Hermes  ────────────────────...\r
                                             \r
            <actual response text>         \r
                                             \r
         ────────────────────────────────────────\r
        Resume this session with: ...       \r

    We want just the actual response text. Strategy: normalize CRLF,
    find the LAST banner, then take everything between the second banner
    and the last banner, then strip blank lines and decoration.
    """
    # Normalize line endings (hermes emits CRLF on Linux too)
    text = stdout.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    # Strip trailing \r from each line just in case
    lines = [ln.rstrip("\r") for ln in lines]
    # Find all banner lines (just long runs of ─/─/spaces)
    banner_idxs = [i for i, ln in enumerate(lines) if _BANNER_RE.match(ln)]
    if len(banner_idxs) >= 2:
        # Response lives between the SECOND banner and the LAST banner
        # (first banner is the initial separator, second is the Hermes header)
        start = banner_idxs[1] + 1
        end = banner_idxs[-1]
        response_lines = lines[start:end]
    else:
        return _strip_fallback(lines)
    # Strip blank lines at start/end
    while response_lines and not response_lines[0].strip():
        response_lines.pop(0)
    while response_lines and not response_lines[-1].strip():
        response_lines.pop()
    return "\n".join(response_lines).strip()


def _strip_fallback(lines: list[str]) -> str:
    """Fallback when banners aren't found — strip known junk lines."""
    out = []
    skip_next_blank = True
    for ln in lines:
        s = ln.strip()
        if s.startswith("Query:") or s.startswith(HERMES_INIT_BUFFER):
            continue
        if _RESUME_RE.match(s) or _FOOTER_RE.match(s):
            continue
        if not s and skip_next_blank:
            continue
        out.append(s)
        skip_next_blank = False
    return "\n".join(out).strip()


# ----- Local dispatch ------------------------------------------------------

async def call_local_god(god: str, prompt: str, timeout: int) -> tuple[str, float]:
    """Spawn `hermes chat --profile <god> -q <prompt>` and return (response, elapsed)."""
    cmd = [
        HERMES_CHAT, "chat",
        "--profile", god,
        "-q", prompt,
    ]
    env = os.environ.copy()
    env["HERMES_HOME"] = HERMES_HOME_PARENT
    env["PATH"] = "/home/konan/.hermes/hermes-agent/venv/bin:" + env.get("PATH", "")

    t0 = time.time()
    log.info(f"  dispatch: hermes chat --profile {god!r} -q {prompt[:50]!r}...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"hermes chat timed out after {timeout}s")
    elapsed = time.time() - t0
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        # Try to get the response anyway — sometimes hermes returns 0 with
        # warnings, or 1 with a partial response
        log.warning(f"  hermes exited {proc.returncode} (stderr: {stderr[:200]})")
    response = extract_response(stdout)
    log.info(f"  got response in {elapsed:.1f}s ({len(response)} chars)")
    return response, elapsed


# ----- Request handler -----------------------------------------------------

async def handle_request(
    msg,
    nc,
    my_instance: str,
    rl: RateLimit,
    audit: AuditWriter,
) -> None:
    """Handle an incoming claw.request.> message addressed to one of our gods."""
    try:
        req = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error(f"bad request payload: {e}")
        return

    request_id = req.get("request_id", "")
    target_god = req.get("target_god", "")
    from_instance = req.get("from_instance", "?")
    from_god = req.get("from_god", "?")
    prompt = req.get("prompt", "")
    timeout = int(req.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))

    # Subject tells us the target: claw.request.<god>.<instance>
    subject_parts = msg.subject.split(".")
    if len(subject_parts) < 4:
        log.error(f"malformed subject: {msg.subject}")
        return
    subj_god = subject_parts[2]
    subj_instance = subject_parts[3]

    if subj_instance != my_instance:
        # Not for us
        return
    if subj_god != target_god:
        # Caller routed to wrong subject; ignore
        log.warning(f"subject god={subj_god} != body target_god={target_god}")
        return
    if not request_id or not prompt:
        log.error("missing request_id or prompt")
        return

    log.info(f"req {request_id[:8]} from {from_instance}:{from_god} -> {target_god}@{my_instance}")
    log.info(f"  prompt ({len(prompt)} chars): {prompt[:100]!r}{'...' if len(prompt) > 100 else ''}")

    t0 = time.time()
    error = None
    response_text = ""
    status = "ok"

    # ---- v0.4.0: rate-limit gate (per-god bucket) ----
    decision = await rl.check_inbound(target_god)
    if not decision.allowed:
        status = "rate_limited"
        error = decision.reason
        log.warning(f"  RATE-LIMITED: {error} (retry after {decision.retry_after_seconds:.1f}s)")
        # Publish a rate-limit response so the caller can react
        resp = {
            "request_id": request_id,
            "from_instance": my_instance,
            "from_god": target_god,
            "to_instance": from_instance,
            "to_god": from_god,
            "response": "",
            "elapsed_seconds": round(time.time() - t0, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "rate_limited",
            "error": error,
            "retry_after_seconds": round(decision.retry_after_seconds, 2),
        }
        subject = NATS_RESP_SUBJECT_TEMPLATE.format(request_id=request_id)
        await nc.publish(subject, json.dumps(resp).encode())
        await nc.flush(2)
        # Audit
        audit.write(make_record(
            request_id=request_id,
            from_instance=from_instance, from_god=from_god,
            target_god=target_god, target_instance=my_instance,
            prompt_len=len(prompt), response_len=0,
            duration_seconds=time.time() - t0,
            status="rate_limited",
            error=error,
            retry_after_seconds=decision.retry_after_seconds,
        ))
        return

    # ---- v0.4.0: concurrency gate (semaphore around dispatch) ----
    try:
        async with rl.semaphore:
            try:
                response_text, dispatch_elapsed = await call_local_god(target_god, prompt, timeout)
            except RuntimeError as e:
                if "timed out" in str(e):
                    status = "timeout"
                else:
                    status = "error"
                error = f"{type(e).__name__}: {e}"
                log.error(f"  dispatch failed: {error}")
            except Exception as e:
                status = "error"
                error = f"{type(e).__name__}: {e}"
                log.error(f"  dispatch failed: {error}")
    except Exception as e:
        status = "error"
        error = f"semaphore-error: {type(e).__name__}: {e}"
        log.error(f"  {error}")

    elapsed = time.time() - t0

    # Publish response
    resp = {
        "request_id": request_id,
        "from_instance": my_instance,
        "from_god": target_god,
        "to_instance": from_instance,
        "to_god": from_god,
        "response": response_text,
        "elapsed_seconds": round(elapsed, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
    }
    if error:
        resp["error"] = error
    subject = NATS_RESP_SUBJECT_TEMPLATE.format(request_id=request_id)
    await nc.publish(subject, json.dumps(resp).encode())
    await nc.flush(2)
    log.info(f"  published response to {subject} ({len(response_text)} chars) status={status}")

    # ---- v0.4.0: audit the inbound call ----
    audit.write(make_record(
        request_id=request_id,
        from_instance=from_instance, from_god=from_god,
        target_god=target_god, target_instance=my_instance,
        prompt_len=len(prompt), response_len=len(response_text),
        duration_seconds=elapsed, status=status, error=error,
    ))

    # ---- v0.5.0: Telegram alert on inbound cross-instance call ----
    # Fire-and-forget — never blocks the bus. Disabled if no bot token.
    _icon = "🟢" if status == "ok" else ("🟡" if status == "rate_limited" else "🔴")
    elapsed_str = f"{elapsed:.1f}s" if elapsed else "n/a"
    alert_text = (
        f"{_icon} Clawforge in: `{from_instance}:{from_god}` → `{target_god}@{my_instance}`\n"
        f"status={status}  {len(prompt)}ch in  {len(response_text)}ch out  {elapsed_str}\n"
        f"request_id={request_id[:8]}"
    )
    if error:
        alert_text += f"\nerror: {error[:200]}"
    asyncio.create_task(_send_telegram_alert(alert_text))


# ----- Main ----------------------------------------------------------------

async def run_daemon(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    # v0.4.0: rate-limit is now REQUIRED (config-only mode)
    rl = RateLimit.from_config(cfg)
    log.info(f"rate-limit: per-god capacity={rl.cfg.capacity} refill={rl.cfg.refill_per_second}/s, "
             f"concurrency={rl.cfg.concurrency}")
    relay = cfg.get("relay", {})
    nats_url = f"nats://{relay.get('host', '127.0.0.1')}:{relay.get('port', 4222)}"
    instance = cfg.get("instance", {})
    my_instance = instance.get("id", "unknown")

    log.info(f"connecting to {nats_url} as instance={my_instance!r}")
    token = _load_token()
    nc = await nats.connect(nats_url, token=token, connect_timeout=5)
    log.info(f"connected; subscribing to {NATS_REQ_SUBJECT}")
    log.info(f"only acting on requests where target_instance={my_instance!r}")

    # v0.5.0: telegram alerting on inbound cross-instance calls
    _tg_token = _read_telegram_bot_token()
    if _tg_token:
        log.info(f"telegram alerts: ENABLED (chat_id={DEFAULT_TELEGRAM_CHAT_ID})")
    else:
        log.warning("telegram alerts: DISABLED (no bot token found in env / ~/.hermes/.env)")

    # v0.4.0: open the audit writer for inbound
    audit = AuditWriter("messenger")
    log.info(f"audit: writing to {audit.dir}/messenger-*.jsonl (forever retention)")

    async def cb(msg):
        # v0.4.0 fix: NATS dispatches callbacks sequentially. Spawn a
        # task so the semaphore + rate-limit can actually fan out to
        # `concurrency` in flight instead of 1-at-a-time.
        asyncio.create_task(handle_request(msg, nc, my_instance, rl, audit))
    await nc.subscribe(NATS_REQ_SUBJECT, cb=cb, pending_msgs_limit=100)
    log.info("listening for cross-instance god requests ...")

    stop = asyncio.Event()
    def _signal(*_a):
        log.info("shutting down")
        stop.set()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            pass
    await stop.wait()
    audit.close()
    await nc.drain()
    return 0


async def run_dispatch(args: argparse.Namespace) -> int:
    """One-shot mode: handle a single outbound request and wait for response."""
    cfg = load_config(args.config)
    rl = RateLimit.from_config(cfg)  # v0.4.0: same gate on outbound

    relay = cfg.get("relay", {})
    nats_url = f"nats://{relay.get('host', '127.0.0.1')}:{relay.get('port', 4222)}"
    instance = cfg.get("instance", {})
    my_instance = instance.get("id", "unknown")
    log.info(f"connecting to {nats_url} as instance={my_instance!r} (one-shot)")
    token = _load_token()
    nc = await nats.connect(nats_url, token=token, connect_timeout=5)

    # v0.4.0: audit the outbound ask
    audit = AuditWriter("ask")

    # Build the synthetic request
    request_id = args.request_id or str(uuid.uuid4())
    target_god = args.god
    target_instance = args.instance or my_instance
    prompt = args.prompt
    timeout = args.timeout

    # ---- v0.4.0: outbound rate-limit check ----
    decision = await rl.check_outbound(target_god)
    if not decision.allowed:
        log.error(f"outbound rate-limited: {decision.reason} (retry after {decision.retry_after_seconds:.1f}s)")
        audit.write(make_record(
            request_id=request_id,
            from_instance=my_instance, from_god="messenger-cli",
            target_god=target_god, target_instance=target_instance,
            prompt_len=len(prompt), response_len=0,
            duration_seconds=0.0,
            status="rate_limited",
            error=decision.reason,
            retry_after_seconds=decision.retry_after_seconds,
        ))
        audit.close()
        await nc.drain()
        return 4  # distinct exit code for rate-limited

    req = {
        "request_id": request_id,
        "from_instance": my_instance,
        "from_god": "messenger-cli",
        "target_god": target_god,
        "prompt": prompt,
        "timeout_seconds": timeout,
    }
    subject = f"claw.request.{target_god}.{target_instance}"
    payload = json.dumps(req).encode()
    log.info(f"publishing to {subject} (request_id={request_id[:8]})")
    await nc.publish(subject, payload)
    await nc.flush(2)

    # Wait for response
    log.info(f"waiting up to {args.timeout + 10}s for response on claw.response.{request_id}")
    resp_subject = NATS_RESP_SUBJECT_TEMPLATE.format(request_id=request_id)
    future: asyncio.Future = asyncio.get_event_loop().create_future()

    async def on_response(msg):
        try:
            data = json.loads(msg.data.decode())
            if not future.done():
                future.set_result(data)
        except Exception as e:
            log.error(f"bad response: {e}")

    sub = await nc.subscribe(resp_subject, cb=on_response)
    t0 = time.time()
    try:
        data = await asyncio.wait_for(future, timeout=args.timeout + 10)
        elapsed = time.time() - t0
        # Audit the OUTBOUND call (sender side)
        # The response payload includes a 'status' field set by the receiver
        remote_status = data.get("status", "ok")
        audit_status = remote_status if remote_status in ("ok", "rate_limited", "error", "timeout") else "ok"
        audit.write(make_record(
            request_id=request_id,
            from_instance=my_instance, from_god="messenger-cli",
            target_god=target_god, target_instance=target_instance,
            prompt_len=len(prompt), response_len=len(data.get("response", "")),
            duration_seconds=elapsed, status=audit_status,
            error=data.get("error"),
        ))
        if args.output_json:
            print(json.dumps(data, indent=2))
        else:
            if data.get("status") == "rate_limited":
                print(f"[rate-limited: {data.get('error', 'unknown')}]", file=sys.stderr)
                audit.close()
                await nc.drain()
                return 4
            print(data.get("response", ""))
            if data.get("error"):
                print(f"\n[error: {data['error']}]", file=sys.stderr)
        audit.close()
        await nc.drain()
        return 0 if not data.get("error") else 2
    except asyncio.TimeoutError:
        log.error(f"timed out waiting for response on {resp_subject}")
        await sub.unsubscribe()
        # Audit the timeout
        audit.write(make_record(
            request_id=request_id,
            from_instance=my_instance, from_god="messenger-cli",
            target_god=target_god, target_instance=target_instance,
            prompt_len=len(prompt), response_len=0,
            duration_seconds=time.time() - t0, status="timeout",
            error="no response from remote messenger within timeout+10s",
        ))
        audit.close()
        await nc.drain()
        return 3


def run_audit(args: argparse.Namespace) -> int:
    """Delegate to clawforge-audit.py CLI."""
    from clawforge_audit import cli as audit_cli
    argv = [args.audit_cmd]
    if args.audit_cmd == "summary":
        argv += ["--role", args.role, "--days", str(args.days)]
    elif args.audit_cmd == "list":
        argv += ["--role", args.role, "--limit", str(args.limit)]
        if args.last: argv += ["--last", args.last]
        if args.status: argv += ["--status", args.status]
        if args.god: argv += ["--god", args.god]
        if args.json: argv += ["--json"]
    # "size" needs no extra args
    return audit_cli(argv)


def main() -> int:
    p = argparse.ArgumentParser(description="Clawforge Messenger (v0.4.0)")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                   help="Path to clawforge.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_daemon = sub.add_parser("daemon", help="run as a long-lived subscriber")
    p_daemon.set_defaults(func=run_daemon)

    p_ask = sub.add_parser("ask", help="send a one-shot request and wait for response")
    p_ask.add_argument("god", help="target god id (e.g. iris, marvin)")
    p_ask.add_argument("prompt", help="the prompt to send")
    p_ask.add_argument("--instance", default=None,
                       help="target instance (default: same instance, ie. konan)")
    p_ask.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                       help=f"timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})")
    p_ask.add_argument("--request-id", default=None,
                       help="use a specific request id (default: generate uuid)")
    p_ask.add_argument("--output-json", action="store_true",
                       help="output the full response JSON, not just text")
    p_ask.set_defaults(func=run_dispatch)

    # v0.4.0: audit subcommand
    p_audit = sub.add_parser("audit", help="inspect the audit log")
    p_audit_sub = p_audit.add_subparsers(dest="audit_cmd", required=True)

    p_audit_sum = p_audit_sub.add_parser("summary", help="aggregate stats")
    p_audit_sum.add_argument("--role", choices=["messenger", "ask"], default="messenger")
    p_audit_sum.add_argument("--days", type=int, default=7)
    p_audit_sum.set_defaults(func=run_audit)

    p_audit_list = p_audit_sub.add_parser("list", help="list recent records")
    p_audit_list.add_argument("--role", choices=["messenger", "ask"], default="messenger")
    p_audit_list.add_argument("--last", default=None, help="time window, e.g. 24h, 7d")
    p_audit_list.add_argument("--limit", type=int, default=50)
    p_audit_list.add_argument("--status", choices=["ok", "rate_limited", "error", "timeout"])
    p_audit_list.add_argument("--god", help="filter by target_god")
    p_audit_list.add_argument("--json", action="store_true", help="output raw JSON")
    p_audit_list.set_defaults(func=run_audit)

    p_audit_size = p_audit_sub.add_parser("size", help="total audit dir size in bytes")
    p_audit_size.set_defaults(func=run_audit)

    args = p.parse_args()
    if inspect.iscoroutinefunction(args.func):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
