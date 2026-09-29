"""Ichor Person Roots backend integration tests.

The Person Roots tree is private/perspective-bound. These tests verify that
Ichor can retrieve it only through the ACL-gated backend and that the public MCP
surface passes the required requester/target/purpose context instead of doing
unscoped file reads.
"""
from __future__ import annotations

import importlib.machinery
import json
import tempfile
import unittest
from pathlib import Path

from lib.ichor.person_roots_backend import PersonRootsBackend
from lib.ichor_hybrid import MemoryTrait

REPO_ROOT = Path("/home/konan/pantheon")
RELATIONSHIPS_ROOT = Path("/home/konan/athenaeum/Codex-User/relationships")
MCP_PATH = REPO_ROOT / "lib" / "ichor_mcp.py"


class TestIchorPersonRootsBackend(unittest.TestCase):
    def test_direct_user_can_retrieve_allowed_xander_code_roast_context(self) -> None:
        backend = PersonRootsBackend(RELATIONSHIPS_ROOT)
        results = backend.search(
            "Xander code roast learning setup",
            limit=3,
            requesting_person_id="xander",
            target_person="Alexander",
            context_domain="code_submitted_by_xander",
            fact_type="private",
            purpose="code_roast_and_learning",
            actor_god="marvin",
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["backend"], "person_roots")
        self.assertEqual(result["person_id"], "xander")
        self.assertEqual(result["access_decision"], "allow")
        self.assertIn("Marvin Code Roast", result["snippet"])
        self.assertIn("PROJECTS/code-roast.md", " ".join(result["source_ids"]))

    def test_unknown_requester_gets_redacted_denial_not_private_snippet(self) -> None:
        backend = PersonRootsBackend(RELATIONSHIPS_ROOT)
        results = backend.search(
            "Xander profile",
            limit=3,
            target_person="xander",
            context_domain="profile",
            fact_type="private",
            purpose="general_retrieval",
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["access_decision"], "deny")
        self.assertEqual(result["allowed_files"], ())
        self.assertIn("Unknown requester", result["snippet"])
        self.assertNotIn("Konan's son", result["snippet"])

    def test_public_brand_sensitive_context_requires_approval(self) -> None:
        backend = PersonRootsBackend(RELATIONSHIPS_ROOT)
        results = backend.search(
            "Finn family context for public post",
            limit=3,
            requesting_person_id="kairos",
            target_person="Finn",
            context_domain="family_sensitive_fact",
            fact_type="sensitive",
            purpose="public_brand_post",
            actor_god="kairos",
        )

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["access_decision"], "needs_konan_approval")
        self.assertTrue(result["log_required"])
        self.assertEqual(result["allowed_files"], ())

    def test_memory_trait_default_retrieve_does_not_auto_read_person_roots(self) -> None:
        result = MemoryTrait().retrieve("Xander code roast", limit=5)

        self.assertNotIn("person_roots", result["backends_used"])
        self.assertFalse(
            any(item.get("backend") == "person_roots" for item in result["results"])
        )

    def test_memory_trait_auto_joins_person_roots_when_context_is_supplied(self) -> None:
        result = MemoryTrait().retrieve(
            "Xander code roast",
            limit=5,
            requesting_person_id="xander",
            target_person="xander",
            person_context_domain="code_submitted_by_xander",
            person_fact_type="private",
            person_purpose="code_roast_and_learning",
            active_god="marvin",
        )

        self.assertIn("person_roots", result["backends_used"])
        roots = [item for item in result["results"] if item.get("backend") == "person_roots"]
        self.assertTrue(roots)
        self.assertEqual(roots[0]["access_decision"], "allow")

    def test_mcp_retrieve_passes_person_roots_acl_context(self) -> None:
        with tempfile.TemporaryDirectory(dir="/home/konan") as home_dir:
            loader = importlib.machinery.SourceFileLoader(
                f"ichor_mcp_person_roots_{Path(home_dir).name}",
                str(MCP_PATH),
            )
            mod = loader.load_module()  # type: ignore[deprecated-call]
            response = json.loads(mod.ichor_retrieve(
                "Xander code roast",
                limit=5,
                backends="person_roots",
                active_god="marvin",
                requesting_person_id="xander",
                target_person="xander",
                person_context_domain="code_submitted_by_xander",
                person_fact_type="private",
                person_purpose="code_roast_and_learning",
            ))
            mod._drain_recall_log_writes()

        self.assertNotIn("error", response)
        roots = [item for item in response["results"] if item.get("backend") == "person_roots"]
        self.assertTrue(roots)
        self.assertEqual(roots[0]["access_decision"], "allow")


if __name__ == "__main__":
    unittest.main()
