"""Person Roots proposal/source-authority tests using stdlib unittest.

Spec source:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md

The proposal layer classifies possible facts as allow, deny, or
needs_konan_approval. It does not mutate person folders. This protects Konan's
relationship canon from being overwritten by direct users, public sources, or god
subagents that only observed partial context.
"""

import unittest

from lib.person_roots.proposals import propose_update
from lib.person_roots.schema import ALLOW, DENY, NEEDS_KONAN_APPROVAL


class TestPersonRootsProposals(unittest.TestCase):
    def test_konan_low_risk_private_relationship_fact_allowed(self) -> None:
        update = propose_update('xander', 'relationship_to_konan.summary', 'son', 'konan', 'konan_account', 'private')
        self.assertEqual(update.decision, ALLOW)

    def test_direct_user_cannot_overwrite_konan_relationship_canon(self) -> None:
        update = propose_update(
            'xander',
            'relationship_to_konan.summary',
            'Konan thinks this new thing',
            'xander',
            'direct_user_account',
            'private',
        )
        self.assertEqual(update.decision, NEEDS_KONAN_APPROVAL)

    def test_direct_user_can_update_own_preferences_low_risk(self) -> None:
        update = propose_update('xander', 'preferences.editor', 'VS Code', 'xander', 'direct_user_account', 'basic')
        self.assertEqual(update.decision, ALLOW)

    def test_public_web_denied_for_private_person_facts(self) -> None:
        update = propose_update('fia', 'profile.private_context', 'untrusted public claim', None, 'public_web_social', 'private')
        self.assertEqual(update.decision, DENY)

    def test_god_subagent_requires_approval_for_relationship_fact(self) -> None:
        update = propose_update('amber', 'relationship_to_konan.category', 'collaborator', 'hermes', 'god_subagent', 'private')
        self.assertEqual(update.decision, NEEDS_KONAN_APPROVAL)

    def test_konan_sensitive_cross_person_fact_requires_approval(self) -> None:
        update = propose_update('finn', 'relationship_to_konan.sensitive_note', 'sensitive family detail', 'konan', 'konan_account', 'sensitive')
        self.assertEqual(update.decision, NEEDS_KONAN_APPROVAL)


if __name__ == '__main__':
    unittest.main()
