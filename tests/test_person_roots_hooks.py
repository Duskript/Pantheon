"""Person Roots Wave 6 hook-point tests using stdlib unittest.

Spec references:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_FUSION_BUILD_PLAN.md
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_BUILD_GATES.md
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md

Wave 6 explicitly avoids live god runtime wiring. The safe deliverable is a
library hook that future gods can call after they know the requester, target
name, purpose, actor god, context domain, and fact sensitivity. The hook must:

1. Resolve target aliases like Alexander -> xander and Finn -> finn.
2. Refuse unknown targets without guessing.
3. Call the ACL evaluator rather than bypassing it.
4. Return a serializable decision object suitable for later gateway/god hooks.
5. Preserve denied-domain behavior even when an actor god is present.

These tests are intentionally narrow so later dashboard/runtime work can use a
stable contract without introducing Discord automation or prompt injection risk.
"""

import unittest

from lib.person_roots.hooks import build_context_decision
from lib.person_roots.schema import ALLOW, DENY, NEEDS_KONAN_APPROVAL

ROOT = '/home/konan/athenaeum/Codex-User/relationships'


class TestPersonRootsHooks(unittest.TestCase):
    def test_marvin_xander_code_roast_alias_allowed(self) -> None:
        result = build_context_decision(
            requesting_person_id='xander',
            target_name='Alexander',
            requested_context_domain='code_submitted_by_xander',
            requested_fact_type='private',
            purpose='code_roast_and_learning',
            actor_god='marvin',
            root=ROOT,
        )
        self.assertEqual(result['target_person_id'], 'xander')
        self.assertEqual(result['decision'], ALLOW)
        self.assertTrue(result['allowed_files'])

    def test_actor_god_does_not_broaden_denied_context(self) -> None:
        result = build_context_decision(
            requesting_person_id='xander',
            target_name='Xander',
            requested_context_domain='pantheon_private_repos',
            requested_fact_type='secret',
            purpose='code_review',
            actor_god='marvin',
            root=ROOT,
        )
        self.assertEqual(result['decision'], DENY)
        self.assertEqual(result['target_person_id'], 'xander')
        self.assertIn('pantheon_private_repos', result['redacted_domains'])

    def test_unknown_target_denies_without_guessing(self) -> None:
        result = build_context_decision(
            requesting_person_id='konan',
            target_name='Mystery Person',
            requested_context_domain='profile',
            requested_fact_type='private',
            purpose='admin_review',
            root=ROOT,
        )
        self.assertEqual(result['decision'], DENY)
        self.assertIsNone(result['target_person_id'])

    def test_public_brand_sensitive_family_context_requires_approval(self) -> None:
        result = build_context_decision(
            requesting_person_id='kairos',
            target_name='Finn',
            requested_context_domain='family_sensitive_fact',
            requested_fact_type='sensitive',
            purpose='public_brand_post',
            actor_god='kairos',
            root=ROOT,
        )
        self.assertEqual(result['decision'], NEEDS_KONAN_APPROVAL)
        self.assertEqual(result['target_person_id'], 'finn')
        self.assertTrue(result['log_required'])


if __name__ == '__main__':
    unittest.main()
