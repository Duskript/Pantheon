"""ACL-gated Person Roots retrieval backend for Ichor.

Person Roots live as perspective-bound markdown files under the user's
Athenaeum relationship tree. This backend makes them available through
``ichor_retrieve`` without flattening private relationship context into the
generic memory pool:

1. Resolve a target person from an explicit target or query aliases.
2. Evaluate the Person Roots ACL before reading any profile file.
3. Return only allowed file snippets, or a redacted ACL decision.

The relationship file tree remains the source of truth. Ichor is the retrieval
surface and privacy gate.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.person_roots.hooks import build_context_decision
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository

_BACKEND_NAME = "person_roots"
_MAX_SNIPPET_CHARS = 1800
_ALIAS_BOUNDARY = r"(?<![\w-]){alias}(?![\w-])"


def _enabled() -> bool:
    return os.environ.get("ICHOR_PERSON_ROOTS_ENABLED", "true").strip().lower() != "false"


def _root_from_env(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    return Path(os.environ.get("ICHOR_PERSON_ROOTS_ROOT", str(DEFAULT_ROOT))).expanduser()


class PersonRootsBackend:
    """Read-only, ACL-gated backend over Person Roots markdown files."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = _root_from_env(root)
        self._repo = PersonRootsRepository(self.root)

    def health(self) -> bool:
        """Health probe: root exists and at least one person can be listed."""
        if not _enabled():
            return False
        try:
            return self.root.exists() and bool(self._repo.list_people())
        except Exception:
            return False

    def search(
        self,
        query: str,
        limit: int = 10,
        requesting_person_id: str | None = None,
        target_person: str | None = None,
        context_domain: str = "profile",
        fact_type: str = "private",
        purpose: str = "general_retrieval",
        source_platform: str | None = None,
        channel_id: str | None = None,
        actor_god: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Search person roots after resolving a target and enforcing ACL.

        ``fact_type`` deliberately defaults to ``private``. A caller that omits
        requester identity will receive a redacted denial instead of private
        relationship profile content.
        """
        if not _enabled():
            return []
        targets = self._resolve_targets(query, target_person)
        if not targets:
            return []

        results: List[Dict[str, Any]] = []
        for person_id in targets[: max(1, int(limit))]:
            decision = build_context_decision(
                requesting_person_id=requesting_person_id,
                target_name=person_id,
                requested_context_domain=context_domain,
                requested_fact_type=fact_type,
                purpose=purpose,
                source_platform=source_platform,
                channel_id=channel_id,
                actor_god=actor_god,
                root=self.root,
            )
            results.append(
                self._decision_to_result(
                    decision=decision,
                    query=query,
                    context_domain=context_domain,
                    fact_type=fact_type,
                    purpose=purpose,
                    actor_god=actor_god,
                )
            )
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return results[: max(1, int(limit))]

    def _resolve_targets(self, query: str, target_person: str | None) -> List[str]:
        if target_person:
            resolved = self._repo.resolve_name(target_person) or target_person
            try:
                self._repo.load_person(resolved)
                return [resolved]
            except Exception:
                # Unknown explicit targets become a redacted ACL result by
                # letting build_context_decision resolve the original string.
                return [target_person]

        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []

        matches: List[tuple[float, str]] = []
        seen: set[str] = set()
        for person_id in self._repo.list_people():
            try:
                person = self._repo.load_person(person_id)
            except Exception:
                continue
            aliases = [person.person_id, person.display_name, *person.aliases]
            best = 0.0
            for alias in aliases:
                score = _alias_score(alias, normalized_query)
                if score > best:
                    best = score
            if best > 0 and person_id not in seen:
                matches.append((best, person_id))
                seen.add(person_id)

        matches.sort(key=lambda item: item[0], reverse=True)
        return [person_id for _, person_id in matches]

    def _decision_to_result(
        self,
        decision: Dict[str, Any],
        query: str,
        context_domain: str,
        fact_type: str,
        purpose: str,
        actor_god: str | None,
    ) -> Dict[str, Any]:
        person_id = decision.get("target_person_id")
        display_name = decision.get("target_display_name") or person_id or "Unknown person"
        access = str(decision.get("decision") or "deny")
        allowed_files = tuple(str(p) for p in decision.get("allowed_files") or ())

        if access == "allow":
            snippet, source_ids = self._snippet_from_files(allowed_files)
            score = _score_allowed(query, display_name, context_domain)
            result_type = "person_root"
            title = f"{display_name} — {context_domain}"
        else:
            snippet = f"Person Roots ACL decision: {access}. {decision.get('reason', '')}"
            source_ids = [f"person:{person_id}"] if person_id else []
            score = 0.12 if access == "needs_owner_approval" else 0.05
            result_type = "person_root_acl"
            title = f"{display_name} — access {access}"

        return {
            "id": f"person_root:{person_id or 'unknown'}:{context_domain}:{access}",
            "score": round(score, 3),
            "backend": _BACKEND_NAME,
            "type": result_type,
            "title": title,
            "snippet": snippet[:_MAX_SNIPPET_CHARS],
            "source": "person_roots",
            "source_ids": source_ids,
            "person_id": person_id,
            "display_name": display_name,
            "access_decision": access,
            "access_reason": decision.get("reason", ""),
            "redacted_domains": tuple(decision.get("redacted_domains") or ()),
            "allowed_files": allowed_files if access == "allow" else (),
            "log_required": bool(decision.get("log_required")),
            "context_domain": context_domain,
            "fact_type": fact_type,
            "purpose": purpose,
            "actor_god": actor_god,
            "rank_reasons": [
                "person_roots_alias_match",
                f"acl:{access}",
                f"domain:{context_domain}",
            ],
        }

    def _snippet_from_files(self, file_paths: tuple[str, ...]) -> tuple[str, List[str]]:
        chunks: List[str] = []
        source_ids: List[str] = []
        used = 0
        for raw_path in file_paths:
            path = Path(raw_path)
            try:
                text = _strip_frontmatter(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rel = _safe_relative(path, self.root)
            source_ids.append(f"person_file:{rel}")
            chunk = f"## {path.name}\n{text.strip()}".strip()
            if not chunk:
                continue
            remaining = _MAX_SNIPPET_CHARS - used
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                chunk = chunk[: max(0, remaining - 20)].rstrip() + "…"
            chunks.append(chunk)
            used += len(chunk)
        return "\n\n".join(chunks), source_ids


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _alias_score(alias: str, normalized_query: str) -> float:
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return 0.0
    pattern = _ALIAS_BOUNDARY.format(alias=re.escape(normalized_alias))
    if re.search(pattern, normalized_query):
        # Prefer specific aliases over short/common fragments.
        return min(1.0, 0.65 + (len(normalized_alias) / 60.0))
    return 0.0


def _score_allowed(query: str, display_name: str, context_domain: str) -> float:
    score = 0.72
    normalized = _normalize_text(query)
    if _normalize_text(display_name) and _normalize_text(display_name) in normalized:
        score += 0.12
    domain_tokens = {p for p in re.split(r"[_\W]+", context_domain.casefold()) if p}
    query_tokens = set(re.findall(r"[a-z0-9_]+", normalized))
    if domain_tokens & query_tokens:
        score += 0.08
    return min(0.98, score)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return text


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return path.name
