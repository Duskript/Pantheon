"""Recall ladder contract tests (Phase 9)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor_recall_ladder import recall_with_ladder  # noqa: E402


def test_require_exact_returns_lcm_hint_without_calling_lcm(tmp_path) -> None:
    db_path = str(tmp_path / "ichor.db")
    IchorDB(db_path=db_path).connect().close()
    result = recall_with_ladder(
        "exact transcript please",
        tags=["user:konan"],
        tags_match="any_strict",
        require_exact=True,
        db_path=db_path,
    )
    data = result.to_dict()
    assert any(h["kind"] == "lcm_expand_hint" for h in data["source_expansion_hints"])
    assert any(step["name"] == "lcm_expand" for step in data["steps"])
    assert "lcm_expand_hint" in data["source_expansion_hints"][0]["kind"]


def _seed_pages(db_path: str) -> None:
    """Three pages that ALL match the probe query, so the old early-stop fires."""
    from lib.ichor_knowledge_pages import KnowledgePageStore

    store = KnowledgePageStore(db_path=db_path)
    for i in range(3):
        store.upsert_page(
            key=f"category:probe-{i}",
            question="what is the current blocker status?",
            scope_tags=[],
            content_md="# what is the current blocker status?\n\n- blocker status note",
            source_observation_ids=[i + 1],
        )


def test_pages_do_not_short_circuit_the_ladder(tmp_path) -> None:
    """A projection is derived from observations, so it must never displace them.

    `page_step.enough = len(pages) >= 3` was latent while the knowledge-page
    table was empty (zero rows can never satisfy `>= 3`). Wiring a real writer
    made it live: three weak token-overlap page hits returned three snippets and
    skipped the observations, events and graph steps entirely. The steps after
    `knowledge_pages` must still run.
    """
    db_path = str(tmp_path / "ichor.db")
    IchorDB(db_path=db_path).connect().close()
    _seed_pages(db_path)

    result = recall_with_ladder(
        "what is the current blocker status?", db_path=db_path
    )
    data = result.to_dict()
    steps = {step["name"]: step for step in data["steps"]}
    assert steps["knowledge_pages"]["attempted"] is True
    assert steps["knowledge_pages"]["result_count"] >= 3, "premise: pages matched"
    assert steps["knowledge_pages"]["enough"] is False
    assert steps["observations"]["attempted"] is True, (
        "the ladder stopped at the page projection and never looked for evidence"
    )
    assert "early_stop" not in steps["knowledge_pages"].get("reasons", [])
