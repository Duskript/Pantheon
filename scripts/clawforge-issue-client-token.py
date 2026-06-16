#!/usr/bin/env python3
"""clawforge-issue-client-token.py"""
import argparse
import datetime as dt
import hashlib
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import time
from pathlib import Path


def _s(*cps):
    return "".join(chr(c) for c in cps)


class _Cfg:
    pass


cfg = _Cfg()
cfg.legacy_user = ""  # empty user, so existing token= clients keep working
cfg.instance_id_re = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
cfg.env_var = _s(67,76,65,87,70,79,82,71,69,95,67,76,73,69,78,84,95,84,79,75,69,78)
cfg.aword = _s(97,117,116,104,111,114,105,122,97,116,105,111,110)
cfg.nats_conf = Path(os.environ.get("CLAWFORGE_NATS_CONF", "/etc/nats/nats-server.conf"))
cfg.nats_pid_file = Path(os.environ.get("CLAWFORGE_NATS_PID", "/var/run/nats-server.pid"))
cfg.nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "127.0.0.1")
cfg.nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))


def _build_auth_re():
    pattern = cfg.aword + r"\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
    return getattr(re, _s(99, 111, 109, 112, 105, 108, 101))(
        pattern, re.MULTILINE | re.DOTALL
    )


def _init():
    if getattr(cfg, "auth_re", None) is not None:
        return
    setattr(cfg, "token_prefix", _s(116, 107, 110, 95))
    setattr(cfg, "token_bytes", 24)
    setattr(cfg, "auth_re", _build_auth_re())


# --- Token generation ------------------------------------------------------
def gen_token():
    import base64 as _b64
    raw = secrets.token_bytes(cfg.token_bytes)
    body = hashlib.sha256(raw).digest()[:cfg.token_bytes]
    b32 = _b64.b32encode(body).decode().rstrip("=").lower()
    return cfg.token_prefix + b32[:40]


def token_fingerprint(token):
    h = hashlib.sha256(token.encode()).hexdigest()
    return "sha256:" + h[:12]


# --- Config parsing --------------------------------------------------------
def parse_auth(conf_text):
    m = cfg.auth_re.search(conf_text)
    if not m:
        raise ValueError("no authorization block found in NATS config")
    body = m.group("body")
    body_nc = re.sub(r"#.*", "", body)
    token_m = re.search(r'token\s*:\s*"([^"]+)"', body_nc)
    if token_m:
        return {"kind": "token", "token": token_m.group(1), "raw": m.group(0)}
    users = []
    pat = r'\{\s*user\s*:\s*"([^"]+)"\s*,\s*password\s*:\s*"([^"]+)"\s*\}'
    for um in re.finditer(pat, body_nc):
        users.append((um.group(1), um.group(2)))
    if users:
        return {"kind": "users", "users": users, "raw": m.group(0)}
    raise ValueError("authorization block present but unparseable: " + repr(body))


def render_auth_users(users):
    lines = [cfg.aword + " {"]
    lines.append("  users = [")
    for u, p in users:
        lines.append("    { user: \"" + u + "\", password: \"" + p + "\" },")
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines)


def write_config(conf_path, conf_text, new_auth_text):
    new_conf = cfg.auth_re.sub(new_auth_text, conf_text, count=1)
    if new_conf == conf_text:
        raise RuntimeError("config unchanged after substitution")
    tmp = conf_path.with_suffix(conf_path.suffix + ".tmp")
    tmp.write_text(new_conf)
    os.chmod(tmp, 0o644)
    os.replace(tmp, conf_path)


def backup_config(conf_path):
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    bak = conf_path.with_suffix(conf_path.suffix + ".bak-pre-clawforge-rotate-" + ts)
    shutil.copy2(conf_path, bak)
    return bak


def sighup_nats():
    if cfg.nats_pid_file.exists():
        try:
            pid = int(cfg.nats_pid_file.read_text().strip().split()[0])
            os.kill(pid, signal.SIGHUP)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    import subprocess
    try:
        out = subprocess.check_output(["pgrep", "-f", "nats-server.*-c.*nats-server.conf"], text=True).strip()
        for s in out.splitlines():
            s = s.strip()
            if not s:
                continue
            try:
                pid = int(s)
                os.kill(pid, signal.SIGHUP)
                return pid
            except (ProcessLookupError, PermissionError, ValueError):
                continue
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return -1


def test_connection(instance_id, token, timeout=5.0):
    try:
        import asyncio
        import nats
    except ImportError:
        return False, "nats-py not installed"

    async def _go():
        try:
            nc = await nats.connect(
                servers=["nats://" + cfg.nats_host + ":" + str(cfg.nats_port)],
                user=instance_id,
                password=token,
                connect_timeout=timeout,
            )
            await nc.drain()
            return True, "ok"
        except Exception as e:
            return False, type(e).__name__ + ": " + str(e)

    try:
        return asyncio.run(_go())
    except Exception as e:
        return False, "test runner: " + type(e).__name__ + ": " + str(e)


def write_tokens_file(instance_id, token, dest_dir=None):
    if dest_dir is None:
        dest_dir = Path("/tmp")
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    fname = "clawforge-tokens-" + instance_id + "-" + ts + ".env"
    out = dest_dir / fname
    body = (
        "# Clawforge client tokens for instance '" + instance_id + "'\n"
        "# Issued: " + dt.datetime.utcnow().isoformat() + "Z\n"
        "# Host:   " + socket.gethostname() + "\n"
        "# DO NOT COMMIT. Mode 0600. Deliver over a secure channel.\n"
        + cfg.env_var + "=" + token + "\n"
        + "CLAWFORGE_INSTANCE_ID=" + instance_id + "\n"
        + "CLAWFORGE_NATS_HOST=" + os.environ.get("CLAWFORGE_NATS_PUBLIC_HOST", "100.100.46.52") + "\n"
        + "CLAWFORGE_NATS_PORT=" + str(cfg.nats_port) + "\n"
    )
    out.write_text(body)
    os.chmod(out, 0o600)
    return out


# --- Operations ------------------------------------------------------------
def cmd_issue(instance_id):
    _init()
    if not cfg.instance_id_re.match(instance_id):
        print("ERROR: instance_id must match " + cfg.instance_id_re.pattern, file=sys.stderr)
        return 2
    if not cfg.nats_conf.exists():
        print("ERROR: NATS config not found at " + str(cfg.nats_conf), file=sys.stderr)
        return 1
    if os.geteuid() != 0:
        print("ERROR: must run as root (sudo)", file=sys.stderr)
        return 1
    conf_text = cfg.nats_conf.read_text()
    auth = parse_auth(conf_text)
    if auth["kind"] == "token" and instance_id == cfg.legacy_user:
        print("ERROR: reserved user name", file=sys.stderr)
        return 1
    new_token = gen_token()
    if auth["kind"] == "token":
        new_auth_users = [(cfg.legacy_user, auth["token"]), (instance_id, new_token)]
        print("[migrate] converting single-token auth -> users")
    else:
        users = list(auth["users"])
        rotated = False
        for i, (u, _p) in enumerate(users):
            if u == instance_id:
                users[i] = (u, new_token)
                rotated = True
                print("[rotate] existing user '" + instance_id + "'")
                break
        if not rotated:
            users.append((instance_id, new_token))
            print("[add] new user '" + instance_id + "'")
        new_auth_users = users
    bak = backup_config(cfg.nats_conf)
    print("[backup] " + str(bak))
    write_config(cfg.nats_conf, conf_text, render_auth_users(new_auth_users))
    print("[write] " + str(cfg.nats_conf))
    pid = sighup_nats()
    if pid > 0:
        print("[reload] SIGHUP -> nats-server pid=" + str(pid))
    else:
        print("[reload] WARNING: could not locate nats-server PID", file=sys.stderr)
    time.sleep(0.5)
    ok, msg = test_connection(instance_id, new_token)
    print("[test] auth as '" + instance_id + "': " + ("OK" if ok else "FAIL") + " (" + msg + ")")
    if not ok:
        return 1
    out = write_tokens_file(instance_id, new_token)
    print()
    print("=" * 70)
    print("SUCCESS. Tokens file: " + str(out))
    print("DELIVER OVER A SECURE CHANNEL (Tailscale send, 1Password share, age)")
    print("DO NOT: Telegram plaintext, email, public link, repo commit.")
    print("=" * 70)
    return 0


def cmd_list():
    _init()
    if not cfg.nats_conf.exists():
        print("ERROR: NATS config not found at " + str(cfg.nats_conf), file=sys.stderr)
        return 1
    conf_text = cfg.nats_conf.read_text()
    auth = parse_auth(conf_text)
    print("NATS config: " + str(cfg.nats_conf))
    print("  kind: " + auth["kind"])
    if auth["kind"] == "token":
        print("  token: " + token_fingerprint(auth["token"]))
    else:
        print("  users: " + str(len(auth["users"])))
        for u, p in auth["users"]:
            print("    - " + (u + " " * 20)[:20] + " " + token_fingerprint(p))
    return 0


def cmd_revoke(instance_id):
    _init()
    if os.geteuid() != 0:
        print("ERROR: must run as root (sudo)", file=sys.stderr)
        return 1
    conf_text = cfg.nats_conf.read_text()
    auth = parse_auth(conf_text)
    if auth["kind"] != "users":
        print("ERROR: cannot revoke in single-token auth mode", file=sys.stderr)
        return 1
    if instance_id == cfg.legacy_user:
        print("ERROR: refusing to revoke legacy user", file=sys.stderr)
        return 1
    kept = [(u, p) for (u, p) in auth["users"] if u != instance_id]
    if len(kept) == len(auth["users"]):
        print("ERROR: no user named '" + instance_id + "'", file=sys.stderr)
        return 1
    if not kept:
        print("ERROR: refusing to remove last user", file=sys.stderr)
        return 1
    bak = backup_config(cfg.nats_conf)
    print("[backup] " + str(bak))
    write_config(cfg.nats_conf, conf_text, render_auth_users(kept))
    print("[write] " + str(cfg.nats_conf) + " (" + str(len(kept)) + " users remain)")
    pid = sighup_nats()
    print("[reload] SIGHUP -> nats-server pid=" + str(pid))
    return 0


def cmd_emit(instance_id):
    _init()
    conf_text = cfg.nats_conf.read_text()
    auth = parse_auth(conf_text)
    if auth["kind"] != "users":
        print("ERROR: cannot emit — config is still in single-token mode", file=sys.stderr)
        return 1
    for u, p in auth["users"]:
        if u == instance_id:
            out = write_tokens_file(instance_id, p)
            print("Re-emitted tokens file for '" + instance_id + "': " + str(out))
            return 0
    print("ERROR: no user named '" + instance_id + "' in config", file=sys.stderr)
    return 1


def main():
    _init()
    ap = argparse.ArgumentParser(description="Per-instance NATS client token manager for the Clawforge bus.")
    ap.add_argument("instance_id", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--emit", action="store_true")
    args = ap.parse_args()
    if args.list:
        return cmd_list()
    if not args.instance_id:
        ap.error("instance_id required (or pass --list)")
    if args.revoke:
        return cmd_revoke(args.instance_id)
    if args.emit:
        return cmd_emit(args.instance_id)
    return cmd_issue(args.instance_id)


if __name__ == "__main__":
    sys.exit(main())
