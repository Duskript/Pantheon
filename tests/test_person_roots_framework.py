"""Synthetic Person Roots framework tests.

Uses generated sample identities only. Never loads live relationship data.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lib.ichor.person_roots_backend import PersonRootsBackend
from lib.person_roots.accounts import resolve_account
from lib.person_roots.acl import evaluate_access
from lib.person_roots.apply import ingest_and_apply
from lib.person_roots.hooks import build_context_decision
from lib.person_roots.ingest import build_ingest_plan
from lib.person_roots.observer import observe_source_files
from lib.person_roots.resolver import PersonRootsRepository
from lib.person_roots.schema import ALLOW, DENY, NEEDS_OWNER_APPROVAL, AccessRequest


def write_doc(path: Path, *, person_id: str | None, document_type: str, sensitivity: str = "private", frontmatter: str = "", body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"document_type: {document_type}", f"sensitivity: {sensitivity}"]
    if person_id is not None:
        fm.append(f"person_id: {person_id}")
    if frontmatter:
        fm.extend(line for line in frontmatter.strip().splitlines() if line.strip())
    path.write_text("\n".join(fm) + "\n---\n\n" + body, encoding="utf-8")


def build_sample_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "INDEX.md").write_text(
        "---\ndocument_type: index\nsensitivity: private\n---\n\n"
        "# Person Roots Index\n\n## Resolver Table\n\n"
        "| Person ID | Display Name | Aliases | Direct User | Account Links | Notes |\n"
        "|---|---|---|---|---|---|\n"
        "| sample-owner | Sample Owner | Owner | true | local:owner-account:verified | Framework owner |\n"
        "| sample-dev | Sample Developer | Developer; Alex Example | true | discord:123456789012345678:verified | Code-review learner |\n"
        "| sample-contact | Sample Contact | Contact | false | — | Example contact |\n"
        "\n## Account Links\n\n"
        "| Platform | Account ID | Person ID | Status | Verified By | Notes |\n"
        "|---|---|---|---|---|---|\n"
        "| discord | 123456789012345678 | sample-dev | verified | sample-owner | Synthetic test account |\n",
        encoding="utf-8",
    )
    for person_id, display, aliases, direct in [
        ("sample-owner", "Sample Owner", "[Owner]", True),
        ("sample-dev", "Sample Developer", "[Developer, Alex Example]", True),
        ("sample-contact", "Sample Contact", "[Contact]", False),
    ]:
        folder = root / person_id
        profile_fm = f"display_name: {display}\naliases: {aliases}\ndirect_user: {str(direct).lower()}\ntrust_tier: tier_2_collaborator"
        write_doc(folder / "PROFILE.md", person_id=person_id, document_type="profile", frontmatter=profile_fm, body="## Known context\n- Synthetic fixture only.\n")
        write_doc(folder / "RELATIONSHIP_TO_OWNER.md", person_id=person_id, document_type="relationship_to_owner", frontmatter="shareable_by_default: false", body="## Owner notes\n- Synthetic fixture only.\n")
        write_doc(folder / "ALIASES.md", person_id=person_id, document_type="aliases", frontmatter=f"aliases: {aliases}\n")
        allowed = "submitted_code\n- project_history\n- self_profile" if person_id == "sample-dev" else "self_profile"
        permissions_fm = f"direct_user: {str(direct).lower()}\ntrust_tier: tier_2_collaborator"
        write_doc(folder / "PERMISSIONS.md", person_id=person_id, document_type="permissions", frontmatter=permissions_fm, body=f"## Allowed context\n- {allowed}\n\n## Denied context\n- platform_private_repos\n")
        write_doc(folder / "MEMORY_POLICY.md", person_id=person_id, document_type="memory_policy")
        write_doc(folder / "INTERACTION_LOG.md", person_id=person_id, document_type="interaction_log", body="# Interaction Log\n\n| Date | Source | Summary | Notes |\n|---|---|---|---|\n")
        write_doc(folder / "NOTES.md", person_id=person_id, document_type="notes", body="## Auto-applied facts\n")
        if direct:
            write_doc(folder / "ROOT.md", person_id=person_id, document_type="root")
            write_doc(folder / "PREFERENCES.md", person_id=person_id, document_type="preferences")
            write_doc(folder / "RELATIONSHIPS" / "owner.md", person_id=person_id, document_type="relationship")
            write_doc(folder / "PROJECTS" / "code-review.md", person_id=person_id, document_type="project", body="# Code Review Lane\n\nSubmitted-code review context.\n")


class TestPersonRootsFramework(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "relationships"
        build_sample_tree(self.root)
        os.environ["PERSON_ROOTS_ROOT"] = str(self.root)

    def tearDown(self) -> None:
        os.environ.pop("PERSON_ROOTS_ROOT", None)
        self.tmp.cleanup()

    def test_resolver_account_acl_and_backend_are_synthetic(self) -> None:
        repo = PersonRootsRepository(self.root)
        self.assertEqual(repo.resolve_name("Alex Example"), "sample-dev")
        self.assertEqual(resolve_account("discord", "123456789012345678", self.root), "sample-dev")
        target = repo.load_person("sample-dev")
        self.assertEqual(evaluate_access(AccessRequest("sample-dev", "sample-dev", "submitted_code", "private", "code_review"), target).decision, ALLOW)
        self.assertEqual(evaluate_access(AccessRequest(None, "sample-dev", "submitted_code", "private", "unknown"), target).decision, DENY)
        self.assertEqual(evaluate_access(AccessRequest("sample-contact", "sample-dev", "submitted_code", "private", "cross_person"), target).decision, NEEDS_OWNER_APPROVAL)
        hook = build_context_decision("sample-dev", "Developer", "submitted_code", "private", "code_review", root=self.root)
        self.assertEqual(hook["decision"], ALLOW)
        result = PersonRootsBackend(self.root).search("Developer code review", requesting_person_id="sample-dev", target_person="sample-dev", context_domain="submitted_code", fact_type="private", purpose="code_review")
        self.assertEqual(result[0]["access_decision"], ALLOW)
        self.assertIn("Code Review Lane", result[0]["snippet"])

    def test_ingest_observer_and_apply_are_guarded(self) -> None:
        source = Path(self.tmp.name) / "source.md"
        source.write_text("PERSON_ROOT: Developer | profile.known_context | Uses sample code reviews.\n", encoding="utf-8")
        observed = observe_source_files([source], incoming_dir=self.root / "_incoming", source_person_id="sample-owner", source_type="owner_account")
        self.assertEqual(observed["candidates"], 1)
        candidates = [
            {"candidate_name": "Developer", "field": "profile.known_context", "value": "Uses sample code reviews.", "source_person_id": "sample-owner", "source_type": "owner_account", "sensitivity": "private"},
            {"candidate_name": "New Person", "field": "profile.known_context", "value": "Needs review.", "source_person_id": "sample-owner", "source_type": "owner_account", "sensitivity": "private"},
        ]
        plan = build_ingest_plan(candidates, self.root)
        self.assertEqual(plan["summary"]["apply"], 1)
        self.assertEqual(plan["summary"]["clarify"], 1)
        applied = ingest_and_apply(candidates[:1], self.root, today="2030-01-01")
        self.assertEqual(applied["apply_result"]["summary"]["applied"], 1)


if __name__ == "__main__":
    unittest.main()
