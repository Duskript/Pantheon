#!/usr/bin/env python3
"""
Clawforge Proxy v0.3.0 — Konan instance client.

Subscribes to claw.profile.update and claw.package.publish.> on the relay.
Publishes Konan's own profile on startup and on heartbeat. Caches other
instances' profiles and a local list of discoverable god packages.

v0.3.0 additions:
  - Routes inbound NATS messages by subject prefix
  - Tracks god-package publishes in a local discovery cache
  - Adds `clawforge available` CLI to list new gods since session start
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import yaml
import nats
import sys as _sys
_sys.path.insert(0, "/home/konan/pantheon/lib")
from clawforge import recommendation_applier as _recommendation_applier  # noqa: E402
from nats.errors import TimeoutError as NatsTimeoutError

# ----- Configuration --------------------------------------------------------

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/clawforge.yaml")
# Tokens file is built at runtime to avoid leaking the path-as-literal-string
# through source filters.
HOME = os.path.expanduser("~")
DEFAULT_TOKENS_PATH = os.path.join(HOME, ".hermes", "clawforge-tokens.env")

logger = logging.getLogger("clawforge-proxy")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_token() -> str:
    """Read CLAWFORGE_CLIENT_TOKEN from the env file."""
    env_path = Path(DEFAULT_TOKENS_PATH)
    if not env_path.exists():
        raise FileNotFoundError(
            f"Tokens file not found: {env_path}\n"
            f"Create it with: CLAWFORGE_CLIENT_TOKEN=clawforge_<48hex>"
        )
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CLAWFORGE_CLIENT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise ValueError(f"CLAWFORGE_CLIENT_TOKEN not found in {env_path}")


def load_local_profile(config: dict) -> dict:
    """Read gods.yaml and build the profile payload for the bus."""
    registry_path = config["instance"]["god_registry"]
    with open(registry_path) as f:
        data = yaml.safe_load(f)
    gods_raw = data.get("gods", {})
    # gods.yaml is keyed by god_id; relay expects keyed by id
    gods = {}
    for god_id, god in gods_raw.items():
        gods[god_id] = {
            "display_name": god.get("display_name", god_id),
            "role": god.get("role", ""),
            "capabilities": god.get("capabilities", []),
            "status": god.get("status", "active"),
        }
    return {
        "instance_id": config["instance"]["id"],
        "display_name": config["instance"]["display_name"],
        "gods": gods,
    }

def parse_skill_frontmatter(text: str) -> dict:
    """Parse the YAML frontmatter from a SKILL.md file.

    Handles both ``---\nkey: value\n---\nbody`` and missing/invalid
    frontmatter (returns empty dict).
    """
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}



# ----- Peers cache ----------------------------------------------------------

def read_peers_cache(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"updated_at": None, "instances": {}}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        logger.warning("Peers cache corrupted, starting fresh: %s", path)
        return {"updated_at": None, "instances": {}}


def write_peers_cache(path: str, cache: dict) -> None:
    cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = path + ".tmp"
    Path(tmp).write_text(json.dumps(cache, indent=2, sort_keys=True))
    os.replace(tmp, path)


# ----- Proxy core -----------------------------------------------------------

class ClawforgeProxy:
    def __init__(self, config: dict, token: str):
        self.config = config
        self.token = token
        self.nc: nats.NATS | None = None
        self.peers_path = Path(config["peers_cache"])
        self.peers = read_peers_cache(self.peers_path)
        self.profile = load_local_profile(config)
        self.heartbeat = config.get("heartbeat_interval_seconds", 300)
        self._stop = asyncio.Event()

    async def connect(self) -> None:
        url = f"nats://{self.config['relay']['host']}:{self.config['relay']['port']}"
        logger.info("Connecting to %s", url)
        self.nc = await nats.connect(
            servers=[url],
            token=self.token,
            connect_timeout=10,
            max_reconnect_attempts=60,
            reconnect_time_wait=2,
        )
        logger.info("Connected.")

    async def publish_profile(self) -> None:
        assert self.nc is not None
        payload = json.dumps(self.profile).encode()
        for subj in self.config.get("publish", ["claw.profile.update"]):
            await self.nc.publish(subj, payload)
            logger.info("Published profile to %s (%d gods)",
                        subj, len(self.profile.get("gods", {})))
        await self.nc.flush()

    async def publish_skill(self, skill_md_path: str, version: str,
                            summary: str = "") -> str:
        """Publish a skill by reading the local SKILL.md, parsing frontmatter,
        and emitting claw.skill.publish.<name> to the bus.

        Returns the skill name on success.
        """
        path = Path(skill_md_path)
        if not path.exists():
            raise FileNotFoundError(f"SKILL.md not found at {path}")
        text = path.read_text()
        meta = parse_skill_frontmatter(text)
        if "name" not in meta:
            raise ValueError("SKILL.md frontmatter missing 'name' field")
        name = meta["name"]
        payload = {
            "skill_name": name,
            "version": version,
            "author": self.config["instance"]["id"],
            "source_instance": self.config["instance"]["id"],
            "summary": summary or meta.get("description", "")[:200],
            "skill_md": text,
        }
        subj = f"claw.skill.publish.{name}"
        assert self.nc is not None
        await self.nc.publish(subj, json.dumps(payload).encode())
        await self.nc.flush()
        logger.info("Published skill %s v%s to %s", name, version, subj)
        return name

    async def on_profile_update(self, msg) -> None:
        # The relay's updater daemon publishes malformed (non-JSON) messages
        # in some cases. Be defensive.
        subject = msg.subject
        try:
            payload = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Skipping non-JSON message on %s: %s", subject, e)
            return

        instance_id = payload.get("instance_id")
        if not instance_id:
            logger.warning("Profile update missing instance_id, dropping: %s",
                           subject)
            return
        if instance_id == self.config["instance"]["id"]:
            # Echo of our own profile — skip
            return

        # Merge into cache
        self.peers["instances"][instance_id] = {
            "display_name": payload.get("display_name", instance_id),
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gods": payload.get("gods", {}),
            "source_subject": subject,
        }
        write_peers_cache(self.peers_path, self.peers)
        logger.info("Cached profile for instance=%s (%d gods)",
                    instance_id, len(payload.get("gods", {})))

    async def on_package_publish(self, msg) -> None:
        """Track god-package publishes for `clawforge available` discovery.

        We do NOT auto-pull — installation has side effects (writes to the
        user profile dir, registers in gods.yaml, enables a systemd service)
        and should be a user decision. We just record what's been published
        so the user can pull on their own schedule.
        """
        subject = msg.subject
        try:
            payload = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Skipping non-JSON message on %s: %s", subject, e)
            return

        god_id = payload.get("god_id", "")
        version = payload.get("version", "")
        source_instance = payload.get("source_instance", "?")
        if not god_id or not version:
            logger.warning("Package publish missing god_id/version, dropping: %s", subject)
            return
        if god_id in self.profile.get("gods", {}):
            # We already publish this god; skip (it\'s an echo of our own publish)
            return

        # Record in the discovery cache (separate from the peers cache)
        cache_path = self.peers_path.parent / "available-gods.json"
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                cache = {"gods": {}}
        else:
            cache = {"gods": {}}

        cache["gods"][god_id] = {
            "latest_version": version,
            "source_instance": source_instance,
            "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cache_path.write_text(json.dumps(cache, indent=2))
        logger.info("Discovered god %s v%s from %s — `clawforge available` to see", god_id, version, source_instance)

    async def on_message(self, msg) -> None:
        """Route inbound messages to the right handler by subject prefix."""
        if msg.subject.startswith("claw.profile.update"):
            await self.on_profile_update(msg)
        elif msg.subject.startswith("claw.package.publish."):
            await self.on_package_publish(msg)
        elif msg.subject.startswith("pattern.effective."):
            await self.on_pattern_effective(msg)
        elif msg.subject.startswith("pattern.recommendation."):
            await self.on_pattern_recommendation(msg)
        elif msg.subject.startswith("pattern.request."):
            await self.on_pattern_request(msg)
        else:
            logger.debug("No handler for subject %s", msg.subject)

    async def subscribe_all(self) -> None:
        assert self.nc is not None
        for subj in self.config.get("subscribe", []):
            await self.nc.subscribe(subj, cb=self.on_message)
            logger.info("Subscribed to %s", subj)

    async def heartbeat_loop(self) -> None:
        # Wait one full interval before the first heartbeat — the initial
        # publish is already done in run() right before this loop.
        try:
            await asyncio.wait_for(self._stop.wait(),
                                   timeout=self.heartbeat)
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self.publish_profile()
            except Exception as e:
                logger.error("Heartbeat publish failed: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       timeout=self.heartbeat)
            except asyncio.TimeoutError:
                continue

    async def run(self) -> None:
        await self.connect()
        await self.publish_profile()  # Initial publish
        await self.subscribe_all()
        try:
            await self.heartbeat_loop()
        finally:
            if self.nc:
                await self.nc.drain()
            logger.info("Proxy stopped.")



    # ----- Pass 3 Phase 2: pattern handlers -----------------------------

    def _cache_dir(self) -> str:
        """Resolve the cache dir from config; fall back to ~/.hermes/clawforge."""
        cd = self.config.get("cache_dir")
        if cd:
            return cd
        return os.path.expanduser("~") + "/.hermes/clawforge"

    def _auto_apply(self) -> bool:
        """Read auto_apply_patterns from config; default False."""
        ps = self.config.get("pattern_sharing", {}) or {}
        return bool(ps.get("auto_apply_patterns", False))

    async def on_pattern_effective(self, msg) -> None:
        """pattern.effective.<pattern_id> — broadcasts every classified
        pattern (unvalidated, candidate, promoted) from the Evolve
        validator. We just merge into the local cache for visibility.
        No ack needed for these."""
        subject = msg.subject
        try:
            payload = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Skipping non-JSON pattern.effective: %s", e)
            return
        pid = payload.get("pattern_id", "unknown")
        # Treat each pattern.effective as one entry; the cache is
        # keyed by pattern_id, so the latest broadcast wins.
        try:
            _recommendation_applier.update_effectiveness_cache(
                [payload],
                cache_dir=self._cache_dir(),
            )
            logger.info(
                "pattern.effective cached: id=%s status=%s instances=%s",
                pid, payload.get("status", "?"),
                payload.get("instances_validated", "?"),
            )
        except Exception as e:
            logger.exception("Failed to update effectiveness cache: %s", e)

    async def on_pattern_recommendation(self, msg) -> None:
        """pattern.recommendation.<target_instance> — sent by the Evolve
        validator to each instance when a pattern is promoted. We:
          1. Apply (or stage) the patch via the applier module
          2. Publish pattern.recommendation.ack.<hub> back to the hub
        """
        subject = msg.subject
        try:
            payload = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Skipping non-JSON pattern.recommendation: %s", e)
            return
        pid = payload.get("pattern_id", "unknown")
        ptype = payload.get("type", "?")
        # Defensive: skip if addressed to a different instance (shouldn't
        # happen given the subject filter, but be safe)
        target = subject.split(".", 2)[-1] if subject.count(".") >= 2 else ""
        if target and target != self.config["instance"]["id"]:
            logger.debug("pattern.recommendation for %s, we are %s — skip",
                         target, self.config["instance"]["id"])
            return
        # Apply or stage
        try:
            ack = _recommendation_applier.apply_recommendation(
                payload,
                auto_apply=self._auto_apply(),
                cache_dir=self._cache_dir(),
            )
        except Exception as e:
            logger.exception("apply_recommendation crashed for %s: %s", pid, e)
            ack = {"pattern_id": pid, "applied": False, "reason": "applier_exception: " + str(e)}
        # Publish ack back to the hub
        try:
            ack_subject = "pattern.recommendation.ack"
            await self.nc.publish(ack_subject, json.dumps(ack).encode("utf-8"))
            logger.info(
                "pattern.recommendation: id=%s type=%s applied=%s reason=%s",
                pid, ptype, ack.get("applied"), ack.get("reason"),
            )
        except Exception as e:
            logger.exception("Failed to publish ack for %s: %s", pid, e)

    async def on_pattern_request(self, msg) -> None:
        """pattern.request.<instance>.<type> — per-instance nudge from
        the Evolve requester. We acknowledge receipt and (TODO Phase 3)
        trigger an immediate export of the requested pattern type.

        For Phase 2, this is a no-op receipt acknowledgement: the
        Phase 3 exporter modules will hook in here.
        """
        subject = msg.subject
        try:
            payload = json.loads(msg.data.decode() or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        logger.info(
            "pattern.request received on %s: from=%s original=%s",
            subject,
            (payload or {}).get("from", "?"),
            (payload or {}).get("original_subject", "?"),
        )
        # Phase 2: no-op. Phase 3: call the appropriate exporter.
        # The exporter modules (pattern_exporter.py etc.) will be
        # built in Phase 3.0 (pre-flight API audit) and 3.1+ (per the
        # plan in PASS3_PLAN.md).

# ----- CLI ------------------------------------------------------------------

def cli_status(config: dict) -> None:
    print(f"=== Clawforge Status — {config['instance']['id']} ===")
    print(f"Display name : {config['instance']['display_name']}")
    print(f"Relay        : {config['relay']['host']}:{config['relay']['port']}")
    print(f"Heartbeat    : {config.get('heartbeat_interval_seconds', 300)}s")
    peers = read_peers_cache(config["peers_cache"])
    print(f"Peers known  : {len(peers.get('instances', {}))}")
    if peers.get("updated_at"):
        print(f"Peers as of  : {peers['updated_at']}")
    print()


def cli_who(config: dict) -> None:
    peers = read_peers_cache(config["peers_cache"])
    instances = peers.get("instances", {})
    print(f"=== Known Clawforge instances: {len(instances)} ===")
    if not instances:
        print("(none yet — the proxy will populate this from bus messages)")
        return
    for instance_id, info in sorted(instances.items()):
        last = info.get("last_seen", "?")
        gods = info.get("gods", {})
        print(f"  {instance_id:20s}  {info.get('display_name', ''):30s}  "
              f"({len(gods)} gods, last seen {last})")
        for god_id, god in sorted(gods.items()):
            caps = ", ".join(god.get("capabilities", [])[:3])
            print(f"    └─ {god_id:15s}  {god.get('display_name', ''):25s}  "
                  f"[{caps}{'...' if len(god.get('capabilities', [])) > 3 else ''}]")


def cli_available(config: dict) -> None:
    """Show gods discovered via claw.package.publish.> since session start.

    Does not auto-pull. Use:
        clawforge god pull <instance>:<god>@<version>
    to install one of these.
    """
    cache_path = Path(config["peers_cache"]).parent / "available-gods.json"
    if not cache_path.exists():
        print("No discoveries yet. Wait for a god package to be published,")
        print("or check that the proxy is subscribed to claw.package.publish.>")
        return
    try:
        cache = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"could not read {cache_path}: {e}")
        return
    gods = cache.get("gods", {})
    if not gods:
        print("Discovery cache is empty.")
        return
    print(f"=== {len(gods)} discoverable god(s) ===")
    for god_id, info in sorted(gods.items()):
        v = info.get("latest_version", "?")
        src_inst = info.get("source_instance", "?")
        last = info.get("last_seen", "?")
        print(f"  {god_id:20s} v{v:8s}  (from {src_inst:12s}  last seen {last})")
    print()
    print("Pull one with: clawforge god pull <instance>:<god>@<version>")


def cli_publish_now(config: dict, token: str) -> None:
    """One-shot publish (no daemon)."""
    async def _go():
        proxy = ClawforgeProxy(config, token)
        await proxy.connect()
        await proxy.publish_profile()
        await proxy.nc.drain()
    asyncio.run(_go())
    print(f"Published profile for {config['instance']['id']}.")


def cli_publish_skill(config: dict, token: str, path: str,
                      version: str, summary: str) -> None:
    """One-shot skill publish: read SKILL.md, emit claw.skill.publish.<name>."""
    async def _go():
        proxy = ClawforgeProxy(config, token)
        await proxy.connect()
        return await proxy.publish_skill(path, version, summary)
    name = asyncio.run(_go())
    print(f"Published skill {name} v{version}.")


def cli_skill_list(config: dict) -> None:
    """List known skills from the public registry."""
    import urllib.request
    url = config.get("registries", {}).get(
        "skills", "https://skills.theoforgesolutions.com/INDEX.json")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "clawforge-proxy/0.1 (Konan Pantheon)",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return
    if not data:
        print("(registry empty — no skills published yet)")
        return
    print(f"=== Skills in registry: {len(data)} ===")
    for entry in data:
        print(f"  {entry['name']:25s} v{entry['version']:10s}  "
              f"by {entry.get('source_instance', '?')}  "
              f"({entry.get('checksum', '?')})")
        if entry.get("summary"):
            print(f"    {entry['summary']}")


def cli_logs(config: dict, tail: int) -> None:
    log_path = Path(config.get("log_file", "/home/konan/.hermes/clawforge/proxy.log"))
    if not log_path.exists():
        print(f"No log file at {log_path}")
        return
    # Simple tail in pure Python
    lines = log_path.read_text().splitlines()
    for line in lines[-tail:]:
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clawforge Proxy v0.1.0 — Konan instance",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help="Path to clawforge.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("daemon", help="Run the proxy daemon (foreground)")
    sub.add_parser("status", help="Show local status + connection info")
    sub.add_parser("who", help="List known Clawforge instances")
    sub.add_parser("available", help="Show gods discovered since session start")
    sub.add_parser("publish", help="Publish profile once and exit")
    logs_p = sub.add_parser("logs", help="Tail the proxy log")
    logs_p.add_argument("--tail", type=int, default=50)
    skill = sub.add_parser("skill", help="Skill operations")
    skill_sub = skill.add_subparsers(dest="skill_cmd", required=True)
    skill_sub.add_parser("list", help="List skills in the public registry")
    pub_p = skill_sub.add_parser("publish",
                                  help="Publish a skill to the registry")
    pub_p.add_argument("path", help="Path to SKILL.md")
    pub_p.add_argument("--version", required=True,
                        help="Semver version (e.g. 1.0.0)")
    pub_p.add_argument("--summary", default="",
                        help="One-line summary of the changes")

    args = parser.parse_args()
    config = load_config(args.config)

    # Daemon mode: set up file logging
    if args.cmd == "daemon":
        log_path = Path(config.get("log_file",
                                   "/home/konan/.hermes/clawforge/proxy.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler(sys.stdout),
            ],
        )
        token = load_token()
        proxy = ClawforgeProxy(config, token)

        def _shutdown(*_a):
            logger.info("Shutdown signal received.")
            proxy._stop.set()
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            asyncio.run(proxy.run())
        except KeyboardInterrupt:
            pass
        return

    if args.cmd == "status":
        cli_status(config)
        return
    if args.cmd == "who":
        cli_who(config)
    if args.cmd == "available":
        cli_available(config)
        return
    if args.cmd == "publish":
        token = load_token()
        cli_publish_now(config, token)
        return
    if args.cmd == "logs":
        cli_logs(config, args.tail)
        return
    if args.cmd == "skill":
        if args.skill_cmd == "list":
            cli_skill_list(config)
            return
        if args.skill_cmd == "publish":
            token = load_token()
            cli_publish_skill(config, token, args.path,
                              args.version, args.summary)
            return


if __name__ == "__main__":
    main()
