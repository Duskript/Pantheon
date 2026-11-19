"""Pantheon Client Kit — the god-agnostic seed-interview engine.

Phase 1 of ``plans/pantheon-client-kit/SPEC-CONTRACT.md``: turn the free-form
Hephaestus forge interview into a **spec-driven** engine that any of the shipped
gods can be forged through, and that renders every artifact the interview
promises — tenant facts, person roots, and per-god SOUL.md / persona.md /
god.json / MEMORY.md / Codex index / .env / config.yaml.

Design rules this module enforces (they are checks, not conventions):

* The question set is **data** (``interview.yaml``), never prose in this file, so
  the CLI runner and the WebUI wizard cannot drift apart.
* A question with no ``writes_to`` does not ship.  ``check_spec()`` fails on one.
* ``writes_to`` paths are **dotted** (``god.SOUL.md``).  A colon inside a YAML
  flow sequence parses as a mapping and silently corrupts the document, so
  ``check_spec()`` rejects it.
* Nothing is invented.  An unanswered question becomes an explicit ``open``
  unknown with an owner — never a plausible-looking guess.
* Client kits never ship operator artwork: ``god.json.icon`` is a reference or
  the client's own upload, never an inline ``data:`` URL.

The module is pure stdlib + PyYAML: no network, no LLM, no Hermes import.  That
is what lets the CLI, the WebUI and the shipped tarball all run the same engine.

Public surface
--------------
``load_spec`` / ``load_roster`` / ``check_spec``      — the data
``InterviewEngine``                                   — the state machine
``render_artifacts`` / ``verify_render`` / ``write_artifacts``  — the outputs
``session()``                                         — the WebUI's store
``main()``                                            — the CLI runner
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]  # webui/api/ -> webui/ -> repo
KIT_DIR = REPO_ROOT / "plans" / "pantheon-client-kit"
DEFAULT_SPEC = KIT_DIR / "interview.yaml"
DEFAULT_ROSTER = KIT_DIR / "roster.yaml"

TENANT = "tenant"
GOD = "god"

#: Answers that mean "keep the default identity" and therefore skip the rest of
#: the identity trio (interview.yaml G1 ``on_keep``).
KEEP_WORDS = {
    "keep", "keeps", "keep default", "keep defaults", "keep the defaults",
    "keep the default", "default", "defaults", "as-is", "as is", "asis", "same",
}

#: Deterministic domain normalisation for the shipped roster.  The live profiles
#: carry four different styles (see roster.yaml ``needs_fix``); a client kit must
#: render exactly one.  Keyed by god, so it stays auditable rather than clever.
DOMAIN_OVERRIDES: dict[str, str] = {
    "hermes": "Messenger · Gateway · Operations",
    "rheta": "Copywriting · Rhetoric · Persuasion",
    "iris": "UI/UX Design",
    "thoth": "Research · Synthesis · Intel",
    "kairos": "Social Media · Marketing",
    "caduceus": "Medicine · Health · Clinical Research",
}
DOMAIN_SEP = " · "

INLINE_IMAGE_PREFIXES = ("data:image", "data:application", "data:text")

#: Icon values that mean "the client declined / kept our default totem".
DEFAULT_ICON_WORDS = {"", "default", "defaults", "totem", "default totem", "none", "no"}

#: Roster-cut capabilities that must be stated as limits, not left as silent gaps.
ROSTER_LIMITS = [
    ("No builder", "Hephaestus and Marvin are not shipped, so no god in this install "
                   "writes code or builds tooling. Engineering asks have no owner."),
    ("No sales god", "Mercer is not shipped, so lead qualification and pipeline work have "
                     "no owner. Re-add per client if that scope is bought."),
]

#: Every artifact ``seed_write`` promises, and how a rendered path proves it.
SEED_ARTIFACT_MATCHERS: dict[str, str] = {
    "tenant.json": "tenant.json",
    "person_roots": "person_roots/",
    "SOUL.md": "/SOUL.md",
    "persona.md": "/persona.md",
    "god.json": "/god.json",
    "MEMORY.md": "/MEMORY.md",
    "Codex-INDEX.md": "Codex-God-",
    ".env": "/.env",
    "config.yaml": "/config.yaml",
}


class SpecError(ValueError):
    """The interview spec or a supplied answer is not usable."""


# ── small helpers ──────────────────────────────────────────────────────────

def _today() -> str:
    import datetime as _dt

    return _dt.date.today().isoformat()


def _slug(text: Any) -> str:
    text = re.sub(r"[^\w\s-]", "", str(text or "").strip().lower())
    return re.sub(r"[\s_]+", "-", text).strip("-") or "unknown"


def _title(text: Any) -> str:
    return " ".join(
        w if (w.isupper() and len(w) > 2) else w.capitalize()
        for w in str(text or "").strip().split()
    )


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _bullets(items: Any, indent: str = "- ") -> str:
    rows = [str(i).strip() for i in _as_list(items) if str(i).strip()]
    return "\n".join(f"{indent}{r}" for r in rows) if rows else f"{indent}❓ open"


def normalize_domain(god: str, raw: Any) -> str:
    """Normalise a roster ``domain`` to one house style: ``Thing · Thing · Thing``."""
    if god in DOMAIN_OVERRIDES:
        return DOMAIN_OVERRIDES[god]
    parts = re.split(r"\s*(?:·|\||/|,|&|\band\b)\s*", str(raw or "").strip())
    cleaned = []
    for part in parts:
        part = re.sub(r"^(god of|god|the)\s+", "", part.strip(), flags=re.I).strip()
        if part:
            cleaned.append(_title(part))
    return DOMAIN_SEP.join(cleaned) if cleaned else _title(god)


def assert_no_inline_image(where: str, value: Any) -> None:
    """Client kits must never embed operator artwork (SPEC §7.2 defect 2)."""
    if isinstance(value, str) and value.strip().lower().startswith(INLINE_IMAGE_PREFIXES):
        raise SpecError(
            f"{where}: inline image data-url is not allowed in a client kit "
            f"({len(value)} chars). Use a served path or the client's own upload."
        )


def is_keep(value: Any) -> bool:
    return str(value or "").strip().lower() in KEEP_WORDS


def wants_default_icon(value: Any) -> bool:
    return str(value or "").strip().lower() in DEFAULT_ICON_WORDS


# ── spec model ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Question:
    """One interview question, straight out of ``interview.yaml``."""

    id: str
    layer: str
    ask: str
    type: str = "text"
    group: str = ""
    required: bool = False
    optional: bool = False
    writes_to: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    default: Any = None
    maximum: int | None = None
    note: str = ""
    on_keep: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def skippable(self) -> bool:
        return self.optional or not self.required

    @property
    def artifact(self) -> str:
        return self.writes_to[0] if self.writes_to else ""

    def public(self) -> dict:
        """The shape the WebUI hands the browser (no internal prose bloat)."""
        out: dict[str, Any] = {
            "id": self.id,
            "layer": self.layer,
            "ask": self.ask,
            "type": self.type,
        }
        for key in ("group", "note"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.choices:
            out["choices"] = list(self.choices)
        if self.fields:
            out["fields"] = list(self.fields)
        if self.maximum:
            out["max"] = self.maximum
        if self.default is not None:
            out["default"] = self.default
        out["required"] = bool(self.required and not self.optional)
        out["writes_to"] = list(self.writes_to)
        return out


class KitSpec:
    """The parsed, validated interview spec."""

    def __init__(self, data: dict, source: Path | None = None):
        self.data = data or {}
        self.source = source
        self.version = self.data.get("version", "0")
        self.defaults = self.data.get("defaults") or {}
        self.seed_write = self.data.get("seed_write") or {}
        self.not_asked = self.data.get("not_asked") or []
        self._layers: dict[str, list[Question]] = {}
        layers = self.data.get("layers") or {}
        if not layers:
            raise SpecError(f"{source}: no 'layers' block")
        for layer, body in layers.items():
            questions = [self._question(layer, raw) for raw in (body or {}).get("questions") or []]
            if not questions:
                raise SpecError(f"{source}: layer '{layer}' has no questions")
            self._layers[layer] = questions

    @staticmethod
    def _question(layer: str, raw: dict) -> Question:
        if not raw.get("id"):
            raise SpecError(f"a {layer} question is missing 'id'")
        return Question(
            id=raw["id"],
            layer=layer,
            ask=raw.get("ask", ""),
            type=raw.get("type", "text"),
            group=raw.get("group", ""),
            required=bool(raw.get("required")),
            optional=bool(raw.get("optional")),
            writes_to=tuple(raw.get("writes_to") or ()),
            choices=tuple(raw.get("choices") or ()),
            fields=tuple(raw.get("fields") or ()),
            default=raw.get("default"),
            maximum=raw.get("max"),
            note=raw.get("note", ""),
            on_keep=raw.get("on_keep", ""),
            raw=raw,
        )

    def questions(self, layer: str) -> list[Question]:
        return list(self._layers.get(layer, []))

    @property
    def layers(self) -> list[str]:
        return list(self._layers)

    def per_god_layer(self) -> str:
        """Which layer repeats per shipped god (``foreach: shipped_roster``)."""
        for layer, body in (self.data.get("layers") or {}).items():
            if (body or {}).get("foreach"):
                return layer
        return GOD

    def question(self, layer: str, qid: str) -> Question:
        for q in self.questions(layer):
            if q.id == qid:
                return q
        raise SpecError(f"no {layer} question '{qid}' in the spec")

    def artifacts(self) -> list[str]:
        out: list[str] = []
        for group in ("per_install", "per_god"):
            out.extend(_as_list(self.seed_write.get(group)))
        return out


def load_spec(path: str | Path | None = None) -> KitSpec:
    p = Path(path) if path else DEFAULT_SPEC
    if not p.exists():
        raise SpecError(f"interview spec not found: {p}")
    with p.open(encoding="utf-8") as fh:
        return KitSpec(yaml.safe_load(fh), p)


def check_spec(spec: KitSpec) -> list[str]:
    """Structural problems that must be fixed before the set ships.

    Returns a list of human-readable problems; empty means clean.
    """
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for layer in spec.layers:
        for q in spec.questions(layer):
            if (layer, q.id) in seen:
                problems.append(f"{layer}: duplicate question id {q.id}")
            seen.add((layer, q.id))
            if not q.writes_to:
                problems.append(f"{layer}:{q.id} has no writes_to — cut it")
            if not q.ask:
                problems.append(f"{layer}:{q.id} has no 'ask' text")
            for target in q.writes_to:
                if ":" in target:
                    problems.append(
                        f"{layer}:{q.id} writes_to '{target}' uses a colon — use dotted "
                        f"form (god.SOUL.md); a colon in a YAML flow sequence parses "
                        f"as a mapping and silently corrupts the document"
                    )
    if not spec.questions(TENANT):
        problems.append("no tenant layer — the interview has no per-install half")
    if not spec.artifacts():
        problems.append("seed_write declares no artifacts")
    return problems


# ── roster ─────────────────────────────────────────────────────────────────

@dataclass
class GodEntry:
    name: str
    role: str = ""
    display_name: str = ""
    color: str | None = None
    icon: str | None = None
    domain: str = ""
    responsibilities: tuple[str, ...] = ()
    routes_to: dict = field(default_factory=dict)
    notes: str = ""
    safety: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "display_name": self.display_name,
            "color": self.color,
            "domain": self.domain,
            "responsibilities": list(self.responsibilities),
            "routes_to": dict(self.routes_to),
        }


class Roster:
    def __init__(self, data: dict, source: Path | None = None):
        self.data = data or {}
        self.source = source
        self.version = self.data.get("version", "0")
        self.conductor = self.data.get("conductor") or ""
        self.limits = self.data.get("roster_cut_consequences") or []
        self.hygiene = self.data.get("artifact_hygiene") or {}
        self._gods: dict[str, GodEntry] = {}
        for name, body in (self.data.get("gods") or {}).items():
            body = body or {}
            if not body.get("ships", False):
                continue
            self._gods[name] = GodEntry(
                name=name,
                role=body.get("role", ""),
                display_name=body.get("default_display_name") or name.capitalize(),
                color=body.get("default_color"),
                icon=body.get("default_icon"),
                domain=normalize_domain(name, body.get("default_domain")),
                responsibilities=tuple(body.get("core_responsibilities") or ()),
                routes_to=dict(body.get("routes_to") or ()),
                notes=body.get("notes", ""),
                safety=dict(body.get("safety") or {}),
            )

    @property
    def gods(self) -> list[GodEntry]:
        return list(self._gods.values())

    def names(self) -> list[str]:
        return list(self._gods)

    def get(self, name: str) -> GodEntry:
        if name not in self._gods:
            raise SpecError(f"'{name}' is not a shipped god in the roster")
        return self._gods[name]


def load_roster(path: str | Path | None = None) -> Roster:
    p = Path(path) if path else DEFAULT_ROSTER
    if not p.exists():
        raise SpecError(f"roster not found: {p}")
    with p.open(encoding="utf-8") as fh:
        return Roster(yaml.safe_load(fh), p)


# ── the engine ─────────────────────────────────────────────────────────────

@dataclass
class OpenQuestion:
    """An unanswered question recorded as an unknown — never invented."""

    key: str
    layer: str
    question_id: str
    god: str = ""
    owner: str = "client"

    def public(self) -> dict:
        return {
            "key": self.key,
            "layer": self.layer,
            "question_id": self.question_id,
            "god": self.god,
            "status": "open",
            "owner": self.owner,
        }


class InterviewEngine:
    """Runs the two-layer interview and knows what was skipped and why.

    Answer keys are ``"T1"`` for the tenant layer and ``"<god>/<G1>"`` for the
    per-god layer, so one flat dict carries a whole install.
    """

    def __init__(self, spec: KitSpec, roster: Roster):
        self.spec = spec
        self.roster = roster
        self.answers: dict[str, Any] = {}
        self.skipped: dict[str, str] = {}
        self._order: list[tuple[str, str, Question]] | None = None
        self._defaults_cache: dict[str, Any] | None = None

    # -- ordering & skip logic --------------------------------------------
    def order(self) -> list[tuple[str, str, Question]]:
        """The full run: tenant first, then per-god, identity-first."""
        if self._order is None:
            rows: list[tuple[str, str, Question]] = []
            for q in self.spec.questions(TENANT):
                rows.append((TENANT, "", q))
            layer = self.spec.per_god_layer()
            for god in self.roster.names():
                for q in self.spec.questions(layer):
                    rows.append((god, god, q))
            self._order = rows
        return self._order

    @staticmethod
    def key_for(god: str, q: Question) -> str:
        return q.id if not god else f"{god}/{q.id}"

    def _is_skipped(self, god: str, q: Question) -> str:
        """Return the skip reason, or '' when the question runs."""
        # The flag lives on G1 ("on_keep: skip to G4 ..."), so it must be read
        # from G1 — reading it off the question being skipped silently disables
        # the whole rule and every god gets asked its identity trio anyway.
        if god and q.id in ("G2", "G3"):
            g1_question = self.spec.question(self.spec.per_god_layer(), "G1")
            if g1_question.on_keep and is_keep(self.answers.get(f"{god}/G1")):
                return (
                    "G1 answered 'keep' — the rest of the identity trio is skipped, "
                    "roster defaults kept"
                )
        gate = q.raw.get("skip_if") or {}
        if gate and gate.get("question"):
            src = gate["question"]
            src_key = src if not god else f"{god}/{src}"
            if gate.get("in") and str(self.answers.get(src_key)) in [str(v) for v in gate["in"]]:
                return f"skip_if {src} in {gate['in']}"
            if gate.get("equals") is not None and str(self.answers.get(src_key)) == str(gate["equals"]):
                return f"skip_if {src} == {gate['equals']}"
        return ""

    def refresh_skips(self) -> dict[str, str]:
        for _layer, god, q in self.order():
            reason = self._is_skipped(god, q)
            if reason:
                self.skipped.setdefault(self.key_for(god, q), reason)
        return dict(self.skipped)

    def run_keys(self) -> list[str]:
        self.refresh_skips()
        return [
            self.key_for(g, q)
            for _layer, g, q in self.order()
            if self.key_for(g, q) not in self.skipped
        ]

    def next_question(self) -> dict | None:
        """The next unanswered question, or None when the run is complete."""
        self.refresh_skips()
        for _layer, god, q in self.order():
            key = self.key_for(god, q)
            if key in self.skipped or key in self.answers:
                continue
            payload = q.public()
            payload["key"] = key
            if god:
                payload["god"] = god
                payload["god_default"] = self.roster.get(god).public()
            if q.raw.get("present_tradeoff"):
                payload["tradeoff"] = PLATFORM_TRADEOFF
            if q.raw.get("options_from"):
                payload["options"] = [
                    self.roster.get(n).public() for n in self.roster.names()
                ]
            return payload
        return None

    def answer(self, key: str, value: Any) -> dict:
        """Record one answer (by key) and return the state after it."""
        if "/" in key:
            god, qid = key.split("/", 1)
            q = self.spec.question(self.spec.per_god_layer(), qid)
        else:
            god, qid = "", key
            q = self.spec.question(TENANT, qid)
        if q.type == "multiselect":
            value = _as_list(value)
        if q.required and not q.optional and value in (None, "", [], {}):
            raise SpecError(f"{key} is required and cannot be answered empty")
        if q.maximum and isinstance(value, list) and len(value) > q.maximum:
            value = value[: q.maximum]
        self.answers[key] = value
        self._defaults_cache = None
        return self.state()

    def progress(self) -> dict:
        keys = self.run_keys()
        answered = [k for k in keys if k in self.answers]
        return {
            "total": len(keys),
            "answered": len(answered),
            "remaining": len(keys) - len(answered),
            "skipped": len(self.skipped),
            "complete": len(keys) - len(answered) == 0,
        }

    def is_complete(self) -> bool:
        return bool(self.progress()["complete"])

    def unknowns(self) -> list[OpenQuestion]:
        """Unanswered *skippable* questions — the only thing that may stay blank.

        An unanswered required question is an interviewer bug, not an unknown, so
        ``missing_required()`` reports it separately.
        """
        out: list[OpenQuestion] = []
        self.refresh_skips()
        for _layer, god, q in self.order():
            key = self.key_for(god, q)
            if key in self.answers or key in self.skipped:
                continue
            if q.skippable:
                out.append(OpenQuestion(key=key, layer=q.layer, question_id=q.id, god=god))
        return out

    def missing_required(self) -> list[str]:
        out: list[str] = []
        self.refresh_skips()
        for _layer, god, q in self.order():
            key = self.key_for(god, q)
            if key in self.answers or key in self.skipped:
                continue
            if q.required and not q.optional:
                out.append(key)
        return out

    def defaults_applied(self) -> dict[str, Any]:
        """Required questions answered by their spec default, not by the client."""
        if self._defaults_cache is None:
            self.refresh_skips()
            out: dict[str, Any] = {}
            for _layer, god, q in self.order():
                key = self.key_for(god, q)
                if key in self.answers or key in self.skipped:
                    continue
                if q.default is not None:
                    out[key] = q.default
            self._defaults_cache = out
        return dict(self._defaults_cache)

    def value(self, key: str, default: Any = None) -> Any:
        if key in self.answers:
            return self.answers[key]
        if key in self.defaults_applied():
            return self.defaults_applied()[key]
        return default

    def state(self) -> dict:
        return {
            "progress": self.progress(),
            "next": self.next_question(),
            "skipped": dict(self.skipped),
            "unknowns": [u.public() for u in self.unknowns()],
            "missing_required": self.missing_required(),
            "defaults_applied": self.defaults_applied(),
        }

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict:
        return {"answers": self.answers, "skipped": self.skipped}

    @classmethod
    def from_dict(cls, spec: KitSpec, roster: Roster, payload: dict) -> "InterviewEngine":
        eng = cls(spec, roster)
        eng.answers = dict((payload or {}).get("answers") or {})
        eng.refresh_skips()
        return eng


PLATFORM_TRADEOFF: dict[str, Any] = {
    "telegram": [
        "One topic per god inside a private supergroup",
        "One userbot login creates every bot, sets names and avatars — zero further clicks",
    ],
    "discord": [
        "One channel (or thread) per god, with real categories and per-channel permissions",
        "Bots are created by driving the Developer Portal in a browser — one login, but a fragile path",
    ],
    "note": "Ask, then explain. A bare 'Telegram or Discord?' buys a coin flip.",
}


# ── renderers ──────────────────────────────────────────────────────────────

#: Colours for gods whose roster entry carries none (kairos: "NO god.json EXISTS").
DEFAULT_COLORS: dict[str, str] = {"kairos": "#F59F00"}


def _is_placeholder(value: Any) -> bool:
    """roster.yaml records defects inline ('<inline image data-url, ...>').

    Those are notes to the kit, not assets — shipping one puts literal prose in
    the client's god.json. Treat any '<...>' value as absent.
    """
    text_value = str(value or "").strip()
    return text_value.startswith("<") and text_value.endswith(">")


def _resolved_display(god: str, entry: GodEntry, engine: InterviewEngine) -> str:
    """The name the client chose, or the roster default when they kept it.

    This is the single source for the display name: god.json, SOUL.md,
    persona.md, the Codex directory, and PHONEBOOK.json all read it, so a
    rename cannot take effect in one artifact and miss another.
    """
    chosen = engine.value(f"{god}/G1")
    if isinstance(chosen, str) and chosen.strip() and not is_keep(chosen):
        return chosen.strip()
    return entry.display_name


def _color_for(entry: GodEntry) -> str:
    return entry.color or DEFAULT_COLORS.get(entry.name, "#94A3B8")


def _god_icon(god: str, entry: GodEntry, g7: Any) -> str:
    """Icon for a client kit: the client's upload, a served path — never base64."""
    if not wants_default_icon(g7) and not _is_placeholder(g7):
        assert_no_inline_image(f"gods/{god}/god.json icon", g7)
        return str(g7).strip()
    icon = entry.icon if entry.icon and not _is_placeholder(entry.icon) else f"/api/gods/{god}/icon"
    assert_no_inline_image(f"gods/{god}/god.json icon", icon)
    return icon


def _business_name(raw: Any) -> str:
    """T1 reads 'Name — what it does'. The kit needs the name, not the paragraph."""
    text_value = str(raw or "").strip()
    for sep in (" — ", " – ", " - ", ".", ":", ","):
        head, found, _tail = text_value.partition(sep)
        if found and head.strip():
            return head.strip()
    return text_value


def _routes_for(god: str, entry: GodEntry, engine: InterviewEngine) -> dict:
    """G5 (or the roster default) as {kind: god}, filtered to shipped gods.

    A routing entry naming a god that is not installed is a dead handoff that
    only fails at runtime, so unknown destinations are dropped here.
    """
    chosen = engine.value(f"{god}/G5")
    if isinstance(chosen, dict) and chosen:
        return {k: v for k, v in chosen.items() if v in engine.roster.names()}
    if isinstance(chosen, str) and chosen.strip().lower() == "all":
        return {name: name for name in engine.roster.names() if name != god}
    return {k: v for k, v in entry.routes_to.items() if v in engine.roster.names()}


def _owns_for(god: str, entry: GodEntry, engine: InterviewEngine) -> list[str]:
    """G3 returns {'owns': [...], 'routes_elsewhere': {...}} or free text."""
    valued = engine.value(f"{god}/G3")
    if isinstance(valued, dict):
        owns = [str(x) for x in _as_list(valued.get("owns")) if str(x).strip()]
        return owns or list(entry.responsibilities)
    if valued:
        return [str(valued)]
    return list(entry.responsibilities)


def _people(eng: InterviewEngine) -> list[dict]:
    """T2 gives the humans; T3 gives their platform IDs. Never invented."""
    rows: list[dict] = []
    by_name: dict[str, dict] = {}
    for row in _as_list(eng.value("T3")):
        if isinstance(row, dict):
            name = str(row.get("person") or row.get("name") or "").strip().lower()
            if name:
                by_name[name] = row
    for row in _as_list(eng.value("T2")):
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            role = str(row.get("role") or "").strip()
            contact = str(row.get("contact") or "").strip()
        else:
            name, role, contact = str(row).strip(), "", ""
        link = by_name.get(name.lower(), {})
        rows.append({
            "name": name,
            "slug": _slug(name),
            "role": role or "❓ open",
            "contact": contact or "❓ open",
            "discord_id": str(link.get("discord_id") or ""),
            "telegram_id": str(link.get("telegram_id") or ""),
            "approver": bool(link.get("approver")),
        })
    return [r for r in rows if r["name"]]


def _approver(people: list[dict]) -> str:
    for person in people:
        if person["approver"]:
            return person["name"]
    return people[0]["name"] if people else "❓ open (no approver named — T2)"


def _frontmatter(doc: str, slug: str, extra: list[str] | None = None) -> str:
    """Person-root frontmatter. Closes AFTER the doc-specific fields.

    Ending the block before them silently drops display_name / direct_user /
    trust_tier out of the metadata and into the body, where every resolver
    ignores them.
    """
    lines = [
        "---",
        f"person_id: {slug}",
        f"document_type: {doc}",
        "schema_version: 0.1",
        "status: draft",
        f"created: {_today()}",
        f"updated: {_today()}",
        "source_authority: client",
        "sensitivity: private",
    ]
    lines.extend(extra or [])
    lines.append("---")
    return "\n".join(lines) + "\n"


def _person_root_files(person: dict, tenant: dict) -> dict[str, str]:
    slug, name = person["slug"], person["name"]
    quoted = json.dumps(name, ensure_ascii=False)
    business = tenant.get("business_name") or "this install"
    contacts = []
    if person["contact"] != "❓ open":
        contacts.append(f"- Contact: {person['contact']}")
    if person["discord_id"]:
        contacts.append(f"- Discord user ID: {person['discord_id']}")
    if person["telegram_id"]:
        contacts.append(f"- Telegram user ID: {person['telegram_id']}")
    if not contacts:
        contacts.append("- ❓ open — no contact details or platform IDs supplied (T2/T3)")
    account_links = (
        "```yaml\naccount_links:\n  discord:\n    user_ids: ["
        + (f'"{person["discord_id"]}"' if person["discord_id"] else "")
        + "]\n  telegram:\n    user_ids: ["
        + (f'"{person["telegram_id"]}"' if person["telegram_id"] else "")
        + "]\n```"
    )
    profile = _frontmatter("profile", slug, [
        f"display_name: {quoted}",
        f"full_name: {quoted}",
        "aliases:",
        f"  - {quoted}",
        "direct_user: true",
        "trust_tier: tier_1_recognized",
        "project_lanes: []",
    ]) + (
        f"\n# {name} — Profile\n\n## Summary\n\n"
        f"{person['role']} at {business}.\n\n"
        "## Known context\n\n"
        f"- Role: {person['role']}\n"
        f"- Approver for anything leaving the building: "
        f"{'yes' if person['approver'] else 'no'}\n\n"
        "## Contact\n\n" + "\n".join(contacts) + "\n\n"
        "## Source notes\n\n"
        "- Every fact above comes from the setup interview (T2/T3). Nothing was invented.\n"
    )
    permissions = _frontmatter("permissions", slug, ["trust_tier: tier_1_recognized"]) + (
        "\n# Permissions\n\n## Account links\n\n" + account_links + "\n\n"
        "## Allowed context\n\n- own_submitted_material\n"
        "- general_pantheon_help_within_this_installs_lanes\n\n"
        "## Denied context\n\n- secrets\n- other_people_private_profiles\n"
        "- anything outside this install's gods\n\n"
        "## Runtime rule\n\n"
        f"{name} is allowlisted as a direct user of this Pantheon. Access is limited "
        "to the gods shipped in this install.\n"
    )
    memory_policy = _frontmatter("memory_policy", slug) + (
        "\n# Memory Policy\n\n## Auto-capture allowed\n\n"
        "- self_stated_preferences\n- submitted_project_context\n\n"
        "## Auto-capture denied\n\n- secrets\n- private facts about third parties\n\n"
        "## Requires approval\n\n- trust_tier_changes\n- account_links\n"
    )
    notes = _frontmatter("notes", slug) + "\n# Notes\n\n❓ open — nothing recorded yet.\n"
    aliases = _frontmatter("aliases", slug, ["aliases:", f"  - {quoted}"]) + (
        f"\n# {name} — Aliases\n\n| Alias | Notes |\n|---|---|\n"
        f"| {slug} | Primary slug / common name |\n"
    )
    log = _frontmatter("interaction_log", slug) + (
        "\n# Interaction Log\n\n| Date | Source | Summary | Notes |\n|---|---|---|---|\n"
        "| (none) | — | No logged interactions yet. | — |\n"
    )
    docs = {
        "PROFILE.md": profile,
        "PERMISSIONS.md": permissions,
        "MEMORY_POLICY.md": memory_policy,
        "NOTES.md": notes,
        "ALIASES.md": aliases,
        "INTERACTION_LOG.md": log,
    }
    return {f"person_roots/{slug}/{name_}": body for name_, body in docs.items()}


def _index_rows(people: list[dict]) -> str:
    lines = [
        "# Person Roots — resolver rows (append to `Codex-User/relationships/INDEX.md`)",
        "",
        "| Person ID | Display Name | Aliases | Direct User | Trust Tier | Folder | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in people:
        lines.append(
            f"| {p['slug']} | {p['name']} | {p['name']} | yes | tier_1_recognized | "
            f"{p['slug']}/ | Onboarded by the client kit interview (T2/T3). |"
        )
    links = [p for p in people if p["discord_id"] or p["telegram_id"]]
    if links:
        lines += ["", "## Account links", "",
                  "| Platform | Account ID | Person ID | Status | Verified By | Notes |",
                  "|---|---|---|---|---|---|"]
        for p in links:
            for plat, key in (("discord", "discord_id"), ("telegram", "telegram_id")):
                if p[key]:
                    lines.append(
                        f"| {plat} | {p[key]} | {p['slug']} | unverified | — | "
                        f"Supplied by the client at setup; verify live before trusting. |"
                    )
    return "\n".join(lines) + "\n"


def _soul_md(god: str, entry: GodEntry, eng: InterviewEngine, tenant: dict,
             people: list[dict]) -> str:
    display = _resolved_display(god, entry, eng)
    owns_text = _bullets(_owns_for(god, entry, eng))
    routes = _routes_for(god, entry, eng)
    routing_lines = [f"- {k} → {v}" for k, v in routes.items()] or ["- ❓ open"]
    guardrails = [
        str(eng.value("T7") or "❓ open"),
        str(eng.value(f"{god}/G10") or "anything external — ask first"),
    ]
    lane = eng.value(f"{god}/G4", "own_lane_free_response")
    free = ("answers freely in its own lane" if lane == "own_lane_free_response"
            else "answers only when named")
    jobs = eng.value(f"{god}/G9") or eng.value("T6")
    return f"""# {display} — {entry.role or entry.domain}

## Identity

{display} is the {entry.role or entry.domain} in this Pantheon — one of
{len(eng.roster.names())} gods installed for {tenant.get('business_name') or 'this business'}.

## Domain

{owns_text}

## Persona

Voice and character live in `persona.md` beside this file. Read it before writing
in this god's name.

## How We Work Together

- Escalate to **{_approver(people)}** for anything the guardrails below gate.
- This god {free}.
- Platform: **{eng.value('T8', '❓ open')}**.

## Guardrails

{_bullets(guardrails)}

## Routing Map — who this god hands off to

{chr(10).join(routing_lines)}

> A destination that is not in this install is a dead handoff. Every name above is
> a shipped god; anything else is handled here or by the client's own tooling.

## Recurring Work

{_bullets(jobs, "- ")}

## Skills

Load `agile-conversation`, `auto-compact-topic-shift`, and `pantheon-bridge` at
session start, plus any domain skills listed in `config.yaml`.

## Ichor Integration — Tier A Extraction

Session close events are extracted automatically (zero-LLM). Use `ichor_retrieve`
for fused multi-signal recall instead of separate memory searches.

## Filesystem Access

### Allowed
- this install's root
### Off limits
- system paths, credentials, anything outside the install root

## Topic-Shift Detection Protocol

Watch for a change of subject, then announce it and offer to file the previous
thread before continuing.

## Notifications

Report task completion and errors to the client's approval channel.

## Shared Context

The business this install serves:

> {tenant.get('about') or '❓ open (T1)'}

Read `shared/` before asking the client to repeat themselves. Write to it only
when a decision, blocker, or finished artifact would matter to another god.

## Fallback Behavior

- Out of context: stop, write a handoff summary, and surface it.
- Unsure whether to proceed: stop and ask.
- Never guess on infrastructure or money decisions.
"""


def _persona_md(god: str, entry: GodEntry, eng: InterviewEngine) -> str:
    display = _resolved_display(god, entry, eng)
    described = eng.value(f"{god}/G2")
    if described and not is_keep(described):
        source = "Described by the client at setup (G2)."
        body = str(described).strip()
    else:
        source = "Derived from the roster default — the client kept the defaults (G1)."
        body = (
            f"{display} speaks as {entry.role or entry.domain}: direct, competent, and "
            f"specific to the work rather than chatty."
        )
    return f"""# Persona: {display}

**Role:** {entry.role or entry.domain}
**Source:** {source}

## Voice

{body}

## Signature Moves

- Names the outcome before the method.
- Says what it will not do, and who should do it instead.
- Asks one clarifying question rather than guessing twice.

## Boundaries

- Never claims work it did not do.
- Never sends anything externally without the client's approval gate.

## Default Question

"What is the outcome you want, and who should own it?"
"""


def _memory_md(god: str, entry: GodEntry, eng: InterviewEngine, tenant: dict) -> str:
    display = _resolved_display(god, entry, eng)
    open_gaps = [u.key for u in eng.unknowns() if u.god == god]
    return f"""# {display} — Seeded Memory

Written at setup. Facts the client stated, plus explicit gaps. Nothing invented.

## Business

{tenant.get('about') or '❓ open (T1)'}

## Day-one facts (G8)

{_bullets(eng.value(f"{god}/G8"))}

## Owns / hands off (G3)

{_bullets(_owns_for(god, entry, eng))}

## Handoff partners (G5)

{_bullets([f"{k} → {v}" for k, v in _routes_for(god, entry, eng).items()])}

## Recurring work (G9)

{_bullets(eng.value(f"{god}/G9"))}

## Open gaps

{_bullets(open_gaps, "- ❓ open: ")}
"""


def _codex_index(god: str, entry: GodEntry, eng: InterviewEngine, tenant: dict) -> str:
    display = _resolved_display(god, entry, eng)
    cats = _as_list(eng.value("T6")) + _as_list(eng.value("T9"))
    return f"""# Codex-{display} — INDEX

Hades-excluded index for {display}'s knowledge base.

## Categories to seed

{_bullets(cats)}

## Ingest queue

From T9 (paths the client handed over at setup):

{_bullets(eng.value("T9"))}

## Notes

- Seeded by the client kit interview for {tenant.get('business_name') or 'this business'}.
- Add pages as the god learns; keep this index the entry point.
"""


def _env_file(god: str, entry: GodEntry, eng: InterviewEngine, install_name: str) -> str:
    people = _people(eng)
    ids = [p["discord_id"] for p in people if p["discord_id"]]
    tg_ids = [p["telegram_id"] for p in people if p["telegram_id"]]
    lane = eng.value(f"{god}/G4", "own_lane_free_response")
    mention = "false" if lane == "own_lane_free_response" else "true"
    return f"""# {_resolved_display(god, entry, eng)} — platform credentials for this install.
# NOTHING here is a real secret: the kit never ships one. Fill these before start.

DISCORD_BOT_TOKEN=
DISCORD_HOME_CHANNEL=
DISCORD_HOME_CHANNEL_NAME=
DISCORD_ALLOWED_USERS={",".join(ids)}
DISCORD_ALLOWED_CHANNELS=
DISCORD_FREE_RESPONSE_CHANNELS=
DISCORD_REQUIRE_MENTION={mention}
DISCORD_AUTO_THREAD=true

TELEGRAM_BOT_TOKEN=
TELEGRAM_HOME_CHANNEL=
TELEGRAM_ALLOWED_USERS={",".join(tg_ids)}
TELEGRAM_GROUP_ALLOWED_CHATS=
TELEGRAM_GROUP_ALLOWED_USERS=

HERMES_HOME={install_name}/profiles/{god}
A2A_AGENT_NAME={god}
"""


def install_root(install_name: str = "pantheon-client") -> str:
    """Where a god's install lives on the client's box (informational only)."""
    return f"~/{install_name}"


def _config_yaml(god: str, entry: GodEntry, eng: InterviewEngine, install_name: str) -> str:
    display = _resolved_display(god, entry, eng)
    safety = entry.safety.get("hard_boundaries") or []
    safety_line = f"    hard_boundaries: [{', '.join(safety)}]" if safety else "    {}"
    return f"""# {display} — profile config for this install.
# model/provider are left unset on purpose: the onboarding wizard probes what this
# machine actually has (see the interview's `not_asked` list) and fills them.
model:
  default: null      # set by onboarding — do not copy another install's model
  provider: null
toolsets:
- hermes-cli
- web
- terminal
- session_search
- memory
- skills
agent:
  max_turns: 90
  quiet_mode: true
plugins:
  enabled:
  - pantheon-background-ops
skills:
  external_dirs:
  - {install_root(install_name)}/god-packages/shared-skills
god:
  name: {god}
  display_name: {display}
  domain: {entry.domain}
  safety:
{safety_line}
"""


def _phonebook(roster: Roster, eng: InterviewEngine) -> str:
    book: dict[str, Any] = {"conductor": roster.conductor, "gods": {}}
    for entry in roster.gods:
        lane = eng.value(f"{entry.name}/G4", "own_lane_free_response")
        book["gods"][entry.name] = {
            "display_name": _resolved_display(entry.name, entry, eng),
            "home_channel": "",
            "free_response": lane == "own_lane_free_response",
            "routes_to": _routes_for(entry.name, entry, eng),
        }
    return json.dumps(book, indent=2, ensure_ascii=False) + "\n"


def _tenant_json(eng: InterviewEngine, people: list[dict]) -> str:
    raw_t1 = eng.value("T1")
    t4 = eng.value("T4")
    payload = {
        "schema_version": "0.1",
        "generated": _today(),
        "business_name": _business_name(raw_t1),
        "about": raw_t1,
        "people": people,
        "timezone": t4.get("timezone") if isinstance(t4, dict) else t4,
        "working_hours": t4.get("hours") if isinstance(t4, dict) else None,
        "brand_voice": eng.value("T5"),
        "day_one_jobs": _as_list(eng.value("T6")),
        "never": eng.value("T7"),
        "platform": eng.value("T8"),
        "ingest_paths": _as_list(eng.value("T9")),
        "unknowns": [u.public() for u in eng.unknowns()],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _client_readme(roster: Roster, eng: InterviewEngine, tenant: dict) -> str:
    god_rows = "\n".join(
        f"| {_resolved_display(g.name, g, eng)} | {g.role or g.domain} | {g.domain} |"
        for g in roster.gods
    )
    limits = "\n\n".join(f"**{name}.** {detail}" for name, detail in ROSTER_LIMITS)
    return f"""# {tenant.get('business_name') or 'Your Pantheon'} — Client Kit

Generated by the seed interview. Every fact below came from the setup interview;
gaps are marked `❓ open` rather than guessed.

## Your gods

| God | Role | Domain |
|---|---|---|
{god_rows}

**Conductor:** {roster.conductor or 'hermes'} — the one bot you set up by hand; it
creates and wires the rest.

## What ships

- `tenant.json` — what you told us about the business
- `person_roots/` — one folder per person, plus resolver rows for the index
- `gods/<god>/` — SOUL.md, persona.md, god.json, MEMORY.md, .env, config.yaml
- `athenaeum/Codex-God-*/INDEX.md` — knowledge-base scaffold per god
- `PHONEBOOK.json` — who hands work to whom

## Known limits (by design)

{limits}

## Before you start

1. Fill each `gods/<god>/.env` (tokens are blank on purpose — the kit ships none).
2. Set model/provider via the onboarding wizard; it probes this machine.
3. Verify every platform ID before trusting it — a wrong ID fails silently.

## Open questions from the interview

{_bullets([u.key for u in eng.unknowns()], "- ❓ open: ")}
"""


def render_artifacts(engine: InterviewEngine, spec: KitSpec | None = None,
                     roster: Roster | None = None, install_name: str = "pantheon-client",
                     generated: str | None = None) -> dict[str, str]:
    """Render every artifact the interview promises. Returns path -> content."""
    spec = spec or engine.spec
    roster = roster or engine.roster
    people = _people(engine)
    tenant = {
        "business_name": _business_name(engine.value("T1")),
        "about": engine.value("T1"),
    }
    out: dict[str, str] = {"tenant.json": _tenant_json(engine, people)}
    out["person_roots/INDEX_ROWS.md"] = _index_rows(people)
    for person in people:
        out.update(_person_root_files(person, tenant))
    for entry in roster.gods:
        god = entry.name
        display = _resolved_display(god, entry, engine)
        icon = _god_icon(god, entry, engine.value(f"{god}/G7"))
        god_json = {
            "display_name": display,
            "icon": icon,
            "color": _color_for(entry),
            "domain": entry.domain,
        }
        out[f"gods/{god}/SOUL.md"] = _soul_md(god, entry, engine, tenant, people)
        out[f"gods/{god}/persona.md"] = _persona_md(god, entry, engine)
        out[f"gods/{god}/god.json"] = json.dumps(god_json, indent=2, ensure_ascii=False) + "\n"
        out[f"gods/{god}/MEMORY.md"] = _memory_md(god, entry, engine, tenant)
        out[f"gods/{god}/.env"] = _env_file(god, entry, engine, install_name)
        out[f"gods/{god}/config.yaml"] = _config_yaml(god, entry, engine, install_name)
        out[f"athenaeum/Codex-God-{display}/INDEX.md"] = _codex_index(
            god, entry, engine, tenant
        )
    out["PHONEBOOK.json"] = _phonebook(roster, engine)
    out["CLIENT-README.md"] = _client_readme(roster, engine, tenant)
    manifest = {
        "schema_version": "0.1",
        "generated": generated or _today(),
        "spec_version": spec.version,
        "roster_version": roster.version,
        "gods": roster.names(),
        "files": sorted(out),
        "unknowns": [u.public() for u in engine.unknowns()],
        "unanswered_required": engine.missing_required(),
        "skipped": dict(engine.skipped),
        "defaults_applied": engine.defaults_applied(),
    }
    out["MANIFEST.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    return out


def verify_render(artifacts: dict[str, str], spec: KitSpec) -> list[str]:
    """Confirm every artifact ``seed_write`` promises was actually rendered."""
    missing: list[str] = []
    for name in spec.artifacts():
        needle = SEED_ARTIFACT_MATCHERS.get(name)
        if needle is None:
            missing.append(f"{name}: no matcher registered in SEED_ARTIFACT_MATCHERS")
            continue
        if not any(needle in path for path in artifacts):
            missing.append(f"{name}: nothing rendered (looked for '{needle}')")
    return missing


def write_artifacts(out_dir: str | Path, artifacts: dict[str, str]) -> list[str]:
    """Write the rendered tree. Returns the written paths, relative to ``out_dir``."""
    root = Path(out_dir)
    written: list[str] = []
    for rel, content in sorted(artifacts.items()):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel)
    return written


def build(spec: KitSpec, roster: Roster, answers: dict | None = None) -> InterviewEngine:
    return InterviewEngine.from_dict(spec, roster, {"answers": answers or {}})


# ── WebUI session store ────────────────────────────────────────────────────

_SESSIONS: dict[str, InterviewEngine] = {}


def session(key: str = "default", reset: bool = False) -> InterviewEngine:
    """The WebUI's single in-flight interview, mirroring soul_forge's sessions."""
    if reset or key not in _SESSIONS:
        _SESSIONS[key] = InterviewEngine(load_spec(), load_roster())
    return _SESSIONS[key]


def reset_sessions() -> None:
    _SESSIONS.clear()


# ── CLI ────────────────────────────────────────────────────────────────────

def _load_answers(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("answers", data) if isinstance(data, dict) else {}


def _apply(engine: InterviewEngine, answers: dict) -> list[str]:
    unknown: list[str] = []
    for key, value in answers.items():
        try:
            engine.answer(key, value)
        except SpecError:
            unknown.append(key)
    return unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="interview_engine",
        description="Run the Pantheon client-kit seed interview; render the install tree.",
    )
    parser.add_argument("--spec", default=None, help="interview.yaml (default: the repo plan)")
    parser.add_argument("--roster", default=None, help="roster.yaml (default: the repo plan)")
    parser.add_argument("--answers", default=None, help="JSON file of answers (flat or {'answers': ...})")
    parser.add_argument("--out", default=None, help="directory to render the install tree into")
    parser.add_argument("--install-name", default="pantheon-client")
    parser.add_argument("--check", action="store_true", help="validate the spec, exit 1 on problems")
    parser.add_argument("--start", action="store_true", help="print the run order (the full question list)")
    parser.add_argument("--interactive", action="store_true", help="walk the interview on stdin")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        spec = load_spec(args.spec)
        roster = load_roster(args.roster)
    except SpecError as exc:
        print(f"spec error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        problems = check_spec(spec)
        if args.json:
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
        elif problems:
            print(f"spec check FAILED — {len(problems)} problem(s):")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(
                f"spec check OK — {sum(len(spec.questions(l)) for l in spec.layers)} questions "
                f"across {len(spec.layers)} layers; {len(spec.artifacts())} declared artifacts; "
                f"{len(roster.names())} shipped gods ({', '.join(roster.names())})"
            )
        return 1 if problems else 0

    engine = InterviewEngine(spec, roster)

    if args.start:
        order = engine.order()
        if args.json:
            print(json.dumps([{"layer": l, "god": g, "id": q.id, "writes_to": list(q.writes_to)}
                              for l, g, q in order], indent=2))
        else:
            for layer, god, q in order:
                print(f"{q.id:<4} [{'tenant' if not god else god}] -> {', '.join(q.writes_to)}")
            print(f"\n{len(order)} question-instances; {len(engine.run_keys())} to ask.")
        return 0

    if args.answers:
        strays = _apply(engine, _load_answers(args.answers))
        if strays:
            print(f"warning: ignored {len(strays)} unknown key(s): {', '.join(strays)}", file=sys.stderr)

    if args.interactive:
        while True:
            question = engine.next_question()
            if not question:
                break
            label = f"[{question.get('god')}] " if question.get("god") else ""
            print(f"\n{question['id']} {label}{question['ask']}")
            if question.get("choices"):
                print(f"   choices: {', '.join(question['choices'])}")
            if question.get("default") is not None:
                print(f"   default: {question['default']}")
            try:
                raw = input("> ").strip()
            except EOFError:
                break
            if not raw and question.get("default") is not None:
                raw = question["default"]
            if not raw and not question.get("required"):
                continue
            if question.get("type") in ("list", "multiselect"):
                raw = [p.strip() for p in raw.split("||") if p.strip()]
            engine.answer(question["key"], raw)

    state = engine.state()
    if not args.out:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    artifacts = render_artifacts(engine, spec, roster, install_name=args.install_name)
    missing = verify_render(artifacts, spec)
    written = write_artifacts(args.out, artifacts)
    summary = {
        "out": str(Path(args.out).resolve()),
        "files_written": len(written),
        "artifacts": sorted(artifacts),
        "missing_from_seed_write": missing,
        "progress": state["progress"],
        "unknowns": len(state["unknowns"]),
        "unanswered_required": state["missing_required"],
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Rendered {len(written)} files into {summary['out']}")
        print(f"  interview: {state['progress']['answered']}/{state['progress']['total']} answered, "
              f"{state['progress']['skipped']} skipped, {len(state['unknowns'])} open")
        if state["missing_required"]:
            print(f"  ⚠ unanswered required: {', '.join(state['missing_required'])}")
        if missing:
            print(f"  ⚠ seed_write artifacts not rendered: {', '.join(missing)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
