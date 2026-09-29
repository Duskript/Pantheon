"""Person Roots clarification prompt tests using stdlib unittest.

Spec behavior under test
------------------------
Person Roots auto-ingestion should not create a durable backlog every time an
unknown person name appears. Konan asked for the interactive Hermes clarification
feature instead: when a name is new, common, or similar to an existing root, the
runtime should pause immediately and ask whether to create, merge/alias, or
ignore. Confirmed aliases stay fast and should not interrupt the agent.

These tests cover the serializable bridge payload consumed by the future runtime
integration. The module does not call the real clarify tool during tests; it
returns arguments shaped like ``clarify(question=..., choices=...,
multi_select=False)`` so the gateway/agent layer can ask the user in the active
chat.
"""

import unittest
from pathlib import Path

from lib.person_roots.clarification import (
    build_name_clarification,
    build_name_clarify_tool_args,
)

ROOT = Path('/home/konan/athenaeum/Codex-User/relationships')


class TestPersonRootsClarification(unittest.TestCase):
    def test_known_alias_does_not_pause(self) -> None:
        payload = build_name_clarification('Sam', root=ROOT)
        self.assertFalse(payload['should_pause'])
        self.assertIsNone(payload['clarify_args'])
        self.assertEqual(payload['classification']['person_id'], 'sammy')

    def test_similar_name_builds_clarify_tool_payload(self) -> None:
        args = build_name_clarify_tool_args('Samuel', 'Samuel is coming over later.', root=ROOT)
        self.assertIsNotNone(args)
        assert args is not None
        self.assertIn('Samuel', args['question'])
        self.assertIn('Sammy', args['question'])
        self.assertIn("Treat 'Samuel' as Sammy (sammy) / add alias", args['choices'])
        self.assertIn("Create a new Person Root for 'Samuel'", args['choices'])
        self.assertIn("Ignore 'Samuel' this time", args['choices'])
        self.assertFalse(args['multi_select'])
        self.assertLessEqual(len(args['choices']), 4)

    def test_distinct_new_name_also_pauses_instead_of_backlogging(self) -> None:
        payload = build_name_clarification('Zephyr Nox', root=ROOT)
        self.assertTrue(payload['should_pause'])
        self.assertEqual(payload['classification']['decision'], 'new_candidate')
        self.assertTrue(payload['classification']['requires_clarification'])
        self.assertIn(
            "Create a new Person Root for 'Zephyr Nox'",
            payload['clarify_args']['choices'],
        )

    def test_common_unknown_name_pauses_with_context(self) -> None:
        payload = build_name_clarification('John', 'John helped with the printer.', root=ROOT)
        self.assertTrue(payload['should_pause'])
        self.assertIn('Context: John helped with the printer.', payload['clarify_args']['question'])
        self.assertIn("Create a new Person Root for 'John'", payload['clarify_args']['choices'])


if __name__ == '__main__':
    unittest.main()
