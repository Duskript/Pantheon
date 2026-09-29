"""Person Roots ACL tests using stdlib unittest.

Spec sources:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_BUILD_GATES.md

These tests cover the Gate 5 access matrix. The privacy invariant is that
Pantheon may know more than it shares: access is scoped by requester, target,
context domain, fact sensitivity, purpose, and actor god.
"""

import unittest

from lib.person_roots.acl import evaluate_access
from lib.person_roots.resolver import PersonRootsRepository
from lib.person_roots.schema import ALLOW, DENY, NEEDS_KONAN_APPROVAL, AccessRequest

RELATIONSHIPS_ROOT = '/home/konan/athenaeum/Codex-User/relationships'


class TestPersonRootsAcl(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = PersonRootsRepository(RELATIONSHIPS_ROOT)

    def test_konan_reads_any_person_root_allowed(self) -> None:
        target = self.repo.load_person('xander')
        decision = evaluate_access(
            AccessRequest('konan', 'xander', 'relationship_to_konan', 'sensitive', 'admin_review'),
            target,
        )
        self.assertEqual(decision.decision, ALLOW)
        self.assertTrue('Konan' in decision.reason or 'owner' in decision.reason.lower())

    def test_unknown_user_denied_konan_private_relationship_notes(self) -> None:
        target = self.repo.load_person('xander')
        decision = evaluate_access(
            AccessRequest(None, 'xander', 'konan_private_relationship_notes', 'sensitive', 'chat'),
            target,
        )
        self.assertEqual(decision.decision, DENY)

    def test_xander_code_roast_context_allowed_for_own_code(self) -> None:
        target = self.repo.load_person('xander')
        decision = evaluate_access(
            AccessRequest('xander', 'xander', 'code_submitted_by_xander', 'private', 'code_roast_and_learning', actor_god='marvin'),
            target,
        )
        self.assertEqual(decision.decision, ALLOW)

    def test_xander_denied_pantheon_private_repo_context_even_with_god(self) -> None:
        target = self.repo.load_person('xander')
        decision = evaluate_access(
            AccessRequest('xander', 'xander', 'pantheon_private_repos', 'secret', 'code_review', actor_god='marvin'),
            target,
        )
        self.assertEqual(decision.decision, DENY)

    def test_fia_own_pantheon_help_allowed(self) -> None:
        target = self.repo.load_person('fia')
        decision = evaluate_access(
            AccessRequest('fia', 'fia', 'her_own_pantheon_usage', 'private', 'general_pantheon_help'),
            target,
        )
        self.assertEqual(decision.decision, ALLOW)

    def test_fia_private_notes_about_other_person_not_allowed(self) -> None:
        target = self.repo.load_person('xander')
        decision = evaluate_access(
            AccessRequest('fia', 'xander', 'private_notes_about_other_people', 'sensitive', 'chat'),
            target,
        )
        self.assertIn(decision.decision, {DENY, NEEDS_KONAN_APPROVAL})

    def test_public_brand_sensitive_family_fact_needs_konan_approval(self) -> None:
        target = self.repo.load_person('finn')
        decision = evaluate_access(
            AccessRequest('kairos', 'finn', 'family_sensitive_fact', 'sensitive', 'public_brand_post', actor_god='kairos'),
            target,
        )
        self.assertEqual(decision.decision, NEEDS_KONAN_APPROVAL)


if __name__ == '__main__':
    unittest.main()
