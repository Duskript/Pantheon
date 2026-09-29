"""Person Roots admin/status tests using stdlib unittest.

The dashboard surface stays local and read-only. These tests verify that it
summarizes the live tree, queue folders, blockers, and text rendering without
starting a web UI or mutating relationship files.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from lib.person_roots.admin_status import build_status, render_status_text

ROOT = '/home/konan/athenaeum/Codex-User/relationships'
REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPersonRootsAdminStatus(unittest.TestCase):
    def test_status_counts_seed_tree_and_direct_users(self) -> None:
        status = build_status(ROOT)
        self.assertEqual(status['person_count'], 15)
        self.assertEqual(status['direct_users'], ['fia', 'xander'])
        self.assertEqual(
            status['people'],
            [
                'amber', 'anand', 'ankit', 'fia', 'finn', 'jahnavi', 'jared',
                'jesus', 'ranjith', 'sammy', 'sanjay-pillai', 'sydney',
                'tallon', 'warren-patterson', 'xander',
            ],
        )

    def test_status_reports_verified_and_pending_account_links(self) -> None:
        status = build_status(ROOT)
        self.assertEqual(status['pending_account_links'], 1)
        self.assertEqual(status['verified_account_links'], 1)
        by_person = {link['person_id']: link for link in status['account_links']}
        self.assertEqual(by_person['fia']['status'], 'verified')
        self.assertEqual(by_person['fia']['account_id'], '1276700977705123872')
        self.assertIn('Live Discord guild member verified as Fia', by_person['fia']['notes'])
        self.assertEqual(by_person['xander']['status'], 'pending')

    def test_status_reports_privacy_health_flags(self) -> None:
        status = build_status(ROOT)
        self.assertTrue(status['validator_passed'])
        self.assertEqual(status['warnings'], [])
        self.assertEqual(status['errors'], [])

    def test_status_reports_queue_counts_and_blockers(self) -> None:
        status = build_status(ROOT)
        self.assertIn('queues', status)
        self.assertIn('incoming_count', status['queues'])
        self.assertIn('pending_count', status['queues'])
        self.assertIn('processed_count', status['queues'])
        self.assertTrue(any('xander has pending discord account link' in blocker for blocker in status['blockers']))
        self.assertTrue(any('Provide and verify xander discord account ID.' == action for action in status['next_actions']))

    def test_render_status_text_mentions_core_dashboard_fields(self) -> None:
        text = render_status_text(build_status(ROOT))
        self.assertIn('Person Roots Admin Dashboard', text)
        self.assertIn('People: 15', text)
        self.assertIn('Account links: 1 verified / 1 pending', text)
        self.assertIn('Validator: PASS', text)

    def test_status_cli_json_and_text_smoke(self) -> None:
        json_proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / 'scripts' / 'person-roots-status.py'), '--format', 'json'],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(json_proc.returncode, 0, json_proc.stderr)
        self.assertEqual(json.loads(json_proc.stdout)['person_count'], 15)

        text_proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / 'scripts' / 'person-roots-status.py'), '--format', 'text'],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(text_proc.returncode, 0, text_proc.stderr)
        self.assertIn('Person Roots Admin Dashboard', text_proc.stdout)


if __name__ == '__main__':
    unittest.main()
