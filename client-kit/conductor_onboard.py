"""Pantheon Client Kit — conductor onboarding (SPEC-CONTRACT Phase 3).

Takes a client from *"I made one bot by hand"* to *"all six gods are live, each in
its own lane, verified"*. The conductor is **hermes**: it is the single bot the
client creates manually, and this module does everything after that.

The automation boundary is real and was measured, not assumed (SPEC §3):

| Platform | Can the conductor create the other bots? | What stays manual |
|---|---|---|
| **Telegram** | Yes — BotFather is reachable from a *user* account, so an MTProto userbot can script `/newbot`, capture each token, then set name + avatar. | One interactive userbot login (api_id/api_hash + phone + code). |
| **Discord** | No — applications cannot be created through the API. The kit drives the Developer Portal in a browser over CDP and captures the token from the token-reset XHR response. | The client's one-time Discord login in the automation browser profile. |

Everything after tokens exist *is* scriptable, and that is the bulk of this module:
build the invite URL from the token's own client_id, invite, create the container
(category + one channel per god), set per-god identity, write the per-god lane
config and `PHONEBOOK.json`, start the per-god gateway units, then verify live.

Safety rules enforced here as checks:

* **A token is never printed, logged, or embedded in a URL or report.** The invite
  URL carries only the numeric client_id, derived by base64-decoding the token's
  first segment.
* **The conductor needs a different invite than the workers.** Workers are
  least-privilege (`379968`); the conductor needs `MANAGE_CHANNELS`,
  `MANAGE_ROLES`, `CREATE_PUBLIC_THREADS` and `MANAGE_THREADS` on top
  (`51808422992`). Handing a worker invite to the conductor fails at "create the
  category", so it is a hard gate, not a note.
* **Nothing destructive, ever.** The executor refuses any DELETE; a mis-targeted
  call against a client's live guild is unrecoverable.
* **Dry-run is the default.** A plan is a first-class output: the exact ordered
  call list, printable to the client.
* **A missing dependency is a refusal with the fix**, not a silent skip — the
  Telegram path says `pip install telethon` and still returns the plan.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import importlib.util
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

import yaml

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "manifest.yaml"
ROSTER_INSTALL = HERE / "roster_install.py"

DISCORD_API = "https://discord.com/api/v10"

#: Least-privilege invite for a *worker* god: talk, and nothing else.
WORKER_PERMISSIONS = 379968
#: The conductor's invite: workers + MANAGE_CHANNELS|MANAGE_ROLES|
#: CREATE_PUBLIC_THREADS|MANAGE_THREADS = 379968 | 16 | 268435456 | 34359738368 | 17179869184
CONDUCTOR_PERMISSIONS = 51808422992

PERMISSION_BITS: dict[str, int] = {
    "ADD_REACTIONS": 1 << 6,
    "MANAGE_CHANNELS": 1 << 4,
    "VIEW_CHANNEL": 1 << 10,
    "SEND_MESSAGES": 1 << 11,
    "EMBED_LINKS": 1 << 14,
    "ATTACH_FILES": 1 << 15,
    "READ_MESSAGE_HISTORY": 1 << 16,
    "USE_EXTERNAL_EMOJIS": 1 << 18,
    "MANAGE_ROLES": 1 << 28,
    "MANAGE_THREADS": 1 << 34,
    "CREATE_PUBLIC_THREADS": 1 << 35,
}
CONDUCTOR_ONLY_BITS = ("MANAGE_CHANNELS", "MANAGE_ROLES", "MANAGE_THREADS", "CREATE_PUBLIC_THREADS")

LANE_FREE = "own_lane_free_response"
LANE_MENTION = "own_lane_mention_only"

#: The Telegram userbot dependency. Measured absent on the operator's box, so the
#: path refuses with the fix rather than pretending the capability exists.
TELEGRAM_DEP = "telethon"

#: Verified live-verification signals. The Telegram one was read out of a real
#: gateway log on 2026-11-15 — it proves privacy mode AND the topic lock at once.
VERIFY_SIGNALS: dict[str, list[dict]] = {
    "discord": [
        {"id": "adapter", "expected": "gateway adapter reports connected for every shipped god"},
        {"id": "lane", "expected": "a post in the god's own channel is answered without an @mention"},
        {"id": "containment", "expected": "the same post in another god's channel is ignored"},
        {"id": "phase", "expected": "no message routes to #general"},
    ],
    "telegram": [
        {"id": "adapter", "expected": "gateway adapter reports connected for every shipped god"},
        {"id": "privacy", "expected":
            "an unmentioned group message reaches a god's adapter at all "
            "(privacy mode is off), proven by the topic-gate log line"},
        {"id": "lock", "expected":
            "log shows: Ignoring messages in chat <chat_id> topic 1: not in allowed_topics [...]"},
        {"id": "lane", "expected": "a post in the god's own topic is answered without an @mention"},
    ],
}


class ConductorError(RuntimeError):
    """The conductor cannot proceed, or a safety gate refused."""


def _roster_install():
    """Import the sibling roster installer (the pack is flat on purpose)."""
    spec = importlib.util.spec_from_file_location("client_kit_roster_install", ROSTER_INSTALL)
    if spec is None or spec.loader is None:
        raise ConductorError(f"cannot import {ROSTER_INSTALL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["client_kit_roster_install"] = module
    spec.loader.exec_module(module)
    return module


def load_manifest(path: pathlib.Path | None = None) -> dict:
    return _roster_install().load_manifest(pathlib.Path(path) if path else DEFAULT_MANIFEST)


# ── tokens, permissions, invites ───────────────────────────────────────────

def client_id_from_token(token: str) -> str:
    """Decode the numeric application id from a Discord bot token.

    A bot token is ``base64(client_id).base64(rest)``. Only the numeric id is
    shareable — the token itself never leaves this function.
    """
    if not token or token.count(".") < 2:
        raise ConductorError("not a Discord bot token (expected three '.'-separated segments)")
    segment = token.split(".", 1)[0]
    try:
        decoded = base64.b64decode(segment + "=" * (-len(segment) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ConductorError("could not base64-decode the token's first segment") from exc
    if not re.fullmatch(r"\d{5,25}", decoded.strip()):
        raise ConductorError("the token's first segment did not decode to a numeric client id")
    return decoded.strip()


def permission_names(value: int) -> list[str]:
    """Human-readable names for a permission integer — for auditing the invite."""
    return [name for name, bit in PERMISSION_BITS.items() if value & bit]


def missing_conductor_permissions(value: int) -> list[str]:
    """Which conductor-only bits an integer is missing (a worker invite fails this)."""
    return [name for name in CONDUCTOR_ONLY_BITS if not value & PERMISSION_BITS[name]]


def check_conductor_permissions(value: int) -> None:
    """Refuse a worker invite for the conductor before it burns a live guild call."""
    missing = missing_conductor_permissions(value)
    if missing:
        raise ConductorError(
            f"that invite lacks {', '.join(missing)}. The conductor must create the "
            f"category and per-god channels, so it needs {CONDUCTOR_PERMISSIONS}, not the "
            f"worker invite {WORKER_PERMISSIONS}."
        )


def invite_url(client_id: str, permissions: int = WORKER_PERMISSIONS,
               scopes: tuple[str, ...] = ("bot", "applications.commands")) -> str:
    """The OAuth URL that puts a bot in the guild. Contains no secret."""
    if not re.fullmatch(r"\d{5,25}", str(client_id)):
        raise ConductorError(f"'{client_id}' is not a numeric client id")
    return (f"https://discord.com/oauth2/authorize?client_id={client_id}"
            f"&permissions={permissions}&scope={'%20'.join(scopes)}")


def invite_plan(manifest: dict, tokens: dict[str, str] | None = None) -> list[dict]:
    """Per-god invite rows. Missing tokens become an explicit gap, never a guess."""
    tokens = tokens or {}
    rows: list[dict] = []
    for god, meta in manifest["gods"].items():
        conductor = god == manifest.get("conductor")
        permissions = CONDUCTOR_PERMISSIONS if conductor else WORKER_PERMISSIONS
        token = tokens.get(god, "")
        row: dict[str, Any] = {
            "god": god,
            "role": "conductor" if conductor else "worker",
            "permissions": permissions,
            "permission_names": permission_names(permissions),
            "client_id": None,
            "invite_url": None,
            "status": "❓ open — token not supplied yet",
        }
        if token:
            client_id = client_id_from_token(token)
            if conductor:
                check_conductor_permissions(permissions)
            row.update({
                "client_id": client_id,
                "invite_url": invite_url(client_id, permissions),
                "status": "ready",
            })
        rows.append(row)
    return rows


# ── the mesh plan ──────────────────────────────────────────────────────────

@dataclass
class MeshAction:
    """One ordered API call. `destructive` ops are refused outright."""

    op: str
    target: str
    payload: dict = field(default_factory=dict)
    destructive: bool = False
    note: str = ""

    def public(self) -> dict:
        return {"op": self.op, "target": self.target, "payload": self.payload,
                "destructive": self.destructive, "note": self.note}


def _channel_name(display_name: str) -> str:
    name = re.sub(r"[^a-z0-9\- ]", "", display_name.lower()).strip().replace(" ", "-")
    return (name or "god")[:100]


def plan_discord_mesh(manifest: dict, guild_id: str, tokens: dict[str, str] | None = None,
                      category_name: str = "Pantheon Gods") -> dict:
    """The ordered call list that turns one invited conductor into six lanes.

    Reuse-then-create: if the category already exists it is reused, so re-running
    against an existing install repairs it instead of duplicating the container.
    """
    tokens = tokens or {}
    invited = {row["god"] for row in invite_plan(manifest, tokens) if row["status"] == "ready"}
    channels = [
        {
            "god": god,
            "name": _channel_name(meta["display_name"]),
            "topic": meta["role"],
            "lane": LANE_FREE,
            "display_name": meta["display_name"],
        }
        for god, meta in manifest["gods"].items()
    ]
    actions = [
        MeshAction("GET", f"/guilds/{guild_id}", note="confirm the conductor can see the guild"),
        MeshAction("GET", f"/guilds/{guild_id}/channels", note="look for an existing category"),
        MeshAction("POST", f"/guilds/{guild_id}/channels",
                   {"name": category_name, "type": 4},
                   note="create the category only if it is absent"),
    ]
    for channel in channels:
        actions.append(MeshAction(
            "POST", f"/guilds/{guild_id}/channels",
            {"name": channel["name"], "type": 0, "parent_id": "<category>",
             "topic": channel["topic"]},
            note=f"one lane for {channel['display_name']}",
        ))
    actions.append(MeshAction("PATCH", "/users/@me", {"username": "<conductor name>"},
                              note="conductor identity (Discord rate-limits username changes)"))
    return {
        "platform": "discord",
        "guild_id": str(guild_id),
        "category": {"name": category_name, "policy": "reuse-or-create"},
        "channels": channels,
        "invites": invite_plan(manifest, tokens),
        "invited": sorted(invited),
        "actions": [a.public() for a in actions],
    }


def plan_telegram_mesh(manifest: dict, chat_id: str = "<supergroup id>") -> dict:
    """The Telegram plan. Bot creation is userbot-driven; lanes are topics."""
    channels = [
        {"god": god, "topic": _channel_name(meta["display_name"]), "role": meta["role"],
         "lane": LANE_FREE}
        for god, meta in manifest["gods"].items()
    ]
    actions = [
        MeshAction("USERBOT", "BotFather:/newbot", {"count": len(channels)},
                   note=f"requires {TELEGRAM_DEP} — one interactive login, then every bot "
                        f"is created, named and given its avatar"),
        MeshAction("USERBOT", "BotFather:/setuserpic", {"per_god": True},
                   note="avatar set from the client's upload"),
        MeshAction("BOTAPI", f"chat:{chat_id}/topics", {"count": len(channels)},
                   note="one topic per god inside a private supergroup"),
        MeshAction("CONFIG", "telegram.allowed_topics", {"per_god": True},
                   note="hard inbound gate: a topic not in the list is dropped"),
        MeshAction("CONFIG", "telegram.extra.ignored_threads", {"value": [1]},
                   note="General stays dead even if the allowlist is widened later"),
    ]
    return {
        "platform": "telegram",
        "chat_id": str(chat_id),
        "channels": channels,
        "availability": telegram_availability(),
        "actions": [a.public() for a in actions],
    }


def telegram_availability() -> dict:
    """Is the hands-free Telegram path actually usable here? Say so plainly."""
    try:
        import telethon  # noqa: F401
    except ImportError:
        return {
            "available": False,
            "reason": f"'{TELEGRAM_DEP}' is not installed — the userbot cannot create bots",
            "fix": f"{sys.executable} -m pip install {TELEGRAM_DEP}",
            "what_still_works": "the plan, the lane config and the PHONEBOOK wiring",
        }
    return {"available": True, "reason": "", "fix": "", "what_still_works": ""}


# ── per-god lanes + phonebook ──────────────────────────────────────────────

def lane_env(god: str, meta: dict, *, platform: str, channel_id: str, lane: str,
             allowed_users: list[str] | None = None) -> dict[str, str]:
    """The env lines that make one god answer in one lane and nowhere else."""
    free = lane == LANE_FREE
    env = {
        "DISCORD_HOME_CHANNEL": channel_id,
        "DISCORD_HOME_CHANNEL_NAME": meta["display_name"],
        "DISCORD_ALLOWED_CHANNELS": channel_id,
        "DISCORD_FREE_RESPONSE_CHANNELS": channel_id if free else "",
        "DISCORD_REQUIRE_MENTION": "false" if free else "true",
        "DISCORD_AUTO_THREAD": "true",
        "DISCORD_ALLOW_BOTS": "all",
        "DISCORD_IGNORE_NO_MENTION": "false" if free else "true",
        "DISCORD_ALLOWED_USERS": ",".join(allowed_users or []),
    }
    if platform == "telegram":
        env.update({
            "TELEGRAM_HOME_CHANNEL": channel_id,
            "TELEGRAM_ALLOWED_USERS": ",".join(allowed_users or []),
            "TELEGRAM_GROUP_ALLOWED_CHATS": channel_id,
            "TELEGRAM_GROUP_ALLOWED_USERS": ",".join(allowed_users or []),
        })
    return env


def telegram_topic_config(god: str, meta: dict, topic_id: str, lane: str = LANE_FREE) -> dict:
    """Config values for a god's Telegram lane — the hard inbound gate."""
    free = lane == LANE_FREE
    return {
        "telegram.allowed_topics": [str(topic_id)],
        "telegram.free_response_topics": [f"<chat_id>:{topic_id}"] if free else [],
        "telegram.extra.ignored_threads": [1],
    }


def phonebook(manifest: dict, channels: dict[str, str] | None = None) -> str:
    """PHONEBOOK.json in the shape the live fleet actually uses.

    `channels` maps god -> home channel id; a god with no id gets null rather than
    a fabricated one, because a wrong channel id silently routes handoffs nowhere.
    """
    channels = channels or {}
    payload = {
        "schema_version": "1.0",
        "description": (
            "Pantheon messenger phonebook — directory of gods, their home channels, roles "
            "and the shared free-response channels. Any god may read this file to route a "
            "handoff reply back to the sender's channel."
        ),
        "conductor": manifest.get("conductor"),
        "gods": {
            god: {
                "role": meta["role"],
                "home_channel": channels.get(god),
                "discord_bot": True,
                "domain": meta["domain"],
                "routes_to": {k: v for k, v in (meta.get("routes_to") or {}).items()
                              if v in manifest["gods"]},
            }
            for god, meta in manifest["gods"].items()
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def verify_checklist(platform: str) -> list[dict]:
    """What to check, live, before calling the install done."""
    signals = VERIFY_SIGNALS.get(platform)
    if signals is None:
        raise ConductorError(f"no verification signals defined for platform '{platform}'")
    return [dict(signal, done=False) for signal in signals]


# ── execution ──────────────────────────────────────────────────────────────

class DiscordTransport:
    """Minimal HTTP transport, injectable so tests never touch the network."""

    def __init__(self, token: str, api: str = DISCORD_API, timeout: int = 20):
        if not token:
            raise ConductorError("a conductor token is required to talk to Discord")
        self.token = token
        self.api = api.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, Any]:
        import urllib.error
        import urllib.request

        url = f"{self.api}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=body, method=method.upper())
        req.add_header("Authorization", f"Bot {self.token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "PantheonClientKit/1.0")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            return exc.code, {"error": raw[:400]}
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a failure row
            return 0, {"error": str(exc)}


class MeshExecutor:
    """Applies a plan. Refuses destructive ops and defaults to dry-run."""

    REDACTED = "***"

    def __init__(self, transport: DiscordTransport | None, dry_run: bool = True):
        self.transport = transport
        self.dry_run = dry_run
        self.log: list[dict] = []

    def apply(self, actions: list[MeshAction | dict]) -> list[dict]:
        for action in actions:
            row = action if isinstance(action, MeshAction) else MeshAction(**action)
            if row.destructive or row.op.upper() == "DELETE":
                raise ConductorError(
                    f"refusing a destructive op ({row.op} {row.target}) — a mis-targeted "
                    f"call against a client's live guild is unrecoverable"
                )
            if row.op.upper() in ("USERBOT", "CONFIG", "BOTAPI"):
                self.log.append({"op": row.op, "target": row.target, "result": "planned",
                                 "detail": row.note})
                continue
            if self.dry_run:
                self.log.append({"op": row.op, "target": row.target, "result": "dry-run",
                                 "payload": row.payload, "detail": row.note})
                continue
            if self.transport is None:
                raise ConductorError(f"{row.op} {row.target} needs a conductor token")
            status, body = self.transport.request(row.op, row.target, row.payload)
            self.log.append({"op": row.op, "target": row.target, "result": status,
                             "ok": 200 <= int(status) < 300})
        return self.log


def assert_no_token_leak(text: str, tokens: Iterable[str] = ()) -> None:
    """Fail loudly if any supplied token appears in output meant to be shared.

    Invite URLs carry only the decoded numeric client_id, so a token reaching
    printable output is always a bug — and this output gets pasted into chat.
    """
    for token in tokens:
        if token and token in text:
            raise ConductorError("a bot token leaked into shareable output")


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="conductor_onboard",
        description="Onboard the conductor: invites, channel mesh, lanes, phonebook, verify.",
    )
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--platform", choices=("discord", "telegram"), default="discord")
    parser.add_argument("--guild-id", default="<guild id>")
    parser.add_argument("--chat-id", default="<supergroup id>")
    parser.add_argument("--conductor-token-file", default=None,
                        help="file containing the conductor's bot token (never passed on argv)")
    parser.add_argument("--check", action="store_true", help="validate the manifest + permissions")
    parser.add_argument("--plan", action="store_true", help="print the plan only")
    parser.add_argument("--verify", action="store_true", help="print the live-verification checklist")
    parser.add_argument("--dry-run", action="store_true", help="print the call list (default)")
    parser.add_argument("--apply", action="store_true", help="actually call the platform API")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    manifest = load_manifest(pathlib.Path(args.manifest) if args.manifest else None)
    tokens: dict[str, str] = {}
    if args.conductor_token_file:
        tokens[manifest["conductor"]] = pathlib.Path(
            args.conductor_token_file).expanduser().read_text(encoding="utf-8").strip()

    if args.check:
        problems = _roster_install().check_pack(manifest)
        try:
            check_conductor_permissions(CONDUCTOR_PERMISSIONS)
        except ConductorError as exc:
            problems.append(str(exc))
        print(json.dumps({"ok": not problems, "problems": problems}, indent=2)
              if args.json else
              ("conductor check OK — permission split verified "
               f"(workers {WORKER_PERMISSIONS}, conductor {CONDUCTOR_PERMISSIONS}); "
               f"{len(manifest['gods'])} gods; telegram userbot available="
               f"{telegram_availability()['available']}"
               if not problems else "conductor check FAILED:\n  - " + "\n  - ".join(problems)))
        return 1 if problems else 0

    if args.verify:
        checklist = verify_checklist(args.platform)
        if args.json:
            print(json.dumps(checklist, indent=2))
        else:
            print(f"Live verification — {args.platform} (nothing is 'done' until it is observed):")
            for row in checklist:
                print(f"  [ ] {row['id']}: {row['expected']}")
        return 0

    plan = (plan_discord_mesh(manifest, args.guild_id, tokens)
            if args.platform == "discord" else plan_telegram_mesh(manifest, args.chat_id))
    assert_no_token_leak(json.dumps(plan, ensure_ascii=False), tokens.values())

    if args.plan:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0

    try:
        executor = MeshExecutor(
            DiscordTransport(tokens.get(manifest["conductor"], "")) if args.apply else None,
            dry_run=not args.apply,
        )
        # A dry run deliberately needs no credentials. --apply without one is a
        # clean refusal, not an unauthenticated call and not a stack trace at the
        # operator — and the token is read from a file, never from argv, because
        # argv leaks into shell history and the process listing.
        log = executor.apply(plan["actions"])
    except ConductorError as exc:
        print(f"conductor error: {exc}", file=sys.stderr)
        if args.apply:
            print("  pass --conductor-token-file <path> — a token on the command line "
                  "leaks into shell history and process listings", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"plan": plan, "log": log}, indent=2, ensure_ascii=False))
    else:
        mode = "APPLY" if args.apply else "DRY RUN (nothing was called)"
        print(f"{mode} — {args.platform}, {len(plan['channels'])} lanes")
        for row in log:
            detail = row.get("detail") or row.get("result")
            print(f"  {row['op']:8} {row['target']:44} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
