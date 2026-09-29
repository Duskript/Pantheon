"""Person Roots resolver and account-link tests using stdlib unittest.

Spec sources:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_SCHEMA.md
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md

The resolver maps names/aliases to person folders. Pending account links must not
resolve as active identities because Konan required verified account-origin
privacy before automapping or sharing private context.
"""

import unittest
from pathlib import Path

from lib.person_roots.accounts import parse_account_links, resolve_account
from lib.person_roots.resolver import PersonRootsRepository

ROOT = Path('/home/konan/athenaeum/Codex-User/relationships')


class TestPersonRootsResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = PersonRootsRepository(ROOT)

    def test_resolves_known_aliases_case_insensitively(self) -> None:
        self.assertEqual(self.repo.resolve_name('Alexander'), 'xander')
        self.assertEqual(self.repo.resolve_name('Xander'), 'xander')
        self.assertEqual(self.repo.resolve_name('xander'), 'xander')
        self.assertEqual(self.repo.resolve_name('Finnegan'), 'finn')
        self.assertEqual(self.repo.resolve_name('Finn'), 'finn')
        self.assertEqual(self.repo.resolve_name('Sam'), 'sammy')
        self.assertEqual(self.repo.resolve_name('Sammy'), 'sammy')
        self.assertEqual(self.repo.resolve_name('Jahnavi'), 'jahnavi')
        self.assertEqual(self.repo.resolve_name('Johnavi'), 'jahnavi')
        self.assertEqual(self.repo.resolve_name('Jesus Morales'), 'jesus')
        self.assertEqual(self.repo.resolve_name('digitalon'), 'tallon')
        self.assertEqual(self.repo.resolve_name('DIGITALON'), 'tallon')
        self.assertIsNone(self.repo.resolve_name('No Such Person'))

    def test_candidate_classifier_keeps_confirmed_common_aliases_fast(self) -> None:
        result = self.repo.classify_candidate_name('Sam')
        self.assertEqual(result['decision'], 'known_person')
        self.assertEqual(result['person_id'], 'sammy')
        self.assertFalse(result['requires_clarification'])

    def test_candidate_classifier_keeps_confirmed_full_name_aliases_fast(self) -> None:
        result = self.repo.classify_candidate_name('Jesus Morales')
        self.assertEqual(result['decision'], 'known_person')
        self.assertEqual(result['person_id'], 'jesus')
        self.assertFalse(result['requires_clarification'])

    def test_candidate_classifier_asks_for_unknown_common_names(self) -> None:
        result = self.repo.classify_candidate_name('John')
        self.assertEqual(result['decision'], 'needs_konan_approval')
        self.assertTrue(result['requires_clarification'])

    def test_candidate_classifier_asks_for_names_similar_to_existing_aliases(self) -> None:
        result = self.repo.classify_candidate_name('Samuel')
        self.assertEqual(result['decision'], 'needs_konan_approval')
        self.assertTrue(result['requires_clarification'])
        self.assertIn('sammy', {person['person_id'] for person in result['similar_people']})

    def test_candidate_classifier_pauses_for_distinct_uncommon_candidates(self) -> None:
        result = self.repo.classify_candidate_name('Zephyr Nox')
        self.assertEqual(result['decision'], 'new_candidate')
        self.assertTrue(result['requires_clarification'])

    def test_list_people_and_load_person_from_seed_tree(self) -> None:
        self.assertEqual(
            self.repo.list_people(),
            [
                'amber', 'anand', 'ankit', 'fia', 'finn', 'jahnavi', 'jared',
                'jesus', 'ranjith', 'sammy', 'sanjay-pillai', 'sydney',
                'tallon', 'warren-patterson', 'xander',
            ],
        )
        xander = self.repo.load_person('xander')
        self.assertEqual(xander.person_id, 'xander')
        self.assertEqual(xander.display_name, 'Xander')
        self.assertTrue(xander.direct_user)
        self.assertIn('Alexander', xander.aliases)
        self.assertEqual(xander.trust_tier, 'tier_2_collaborator')

    def test_path_for_guards_against_escape(self) -> None:
        path = self.repo.path_for('xander', 'PROJECTS/code-roast.md')
        self.assertEqual(path, ROOT / 'xander' / 'PROJECTS' / 'code-roast.md')
        with self.assertRaises(ValueError):
            self.repo.path_for('xander', '../fia/PROFILE.md')

    def test_verified_fia_discord_account_resolves_and_pending_links_do_not(self) -> None:
        links = parse_account_links(ROOT)
        self.assertTrue(links)
        self.assertIn('verified', {link.status for link in links})
        self.assertEqual(resolve_account('discord', '1276700977705123872', ROOT), 'fia')
        self.assertIsNone(resolve_account('discord', '(pending — no ID)', ROOT))
        self.assertIsNone(resolve_account('discord', '123456789012345678', ROOT))


if __name__ == '__main__':
    unittest.main()
