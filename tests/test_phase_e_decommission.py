from __future__ import annotations

import json
import unittest
from pathlib import Path

MANIFEST = Path('/home/konan/pantheon/scripts/pantheon-cron-manifest.json')
RETIRED = {'Shared Context Digest', 'Ichor Subconscious Engine'}


class TestPhaseEDecommission(unittest.TestCase):
    def test_pantheon_cron_manifest_drops_retired_ichor_jobs(self) -> None:
        data = json.loads(MANIFEST.read_text())
        names = {job.get('name') for job in data.get('hermes_cron_jobs', []) if isinstance(job, dict)}
        retired_still_present = sorted(RETIRED.intersection(names))
        self.assertFalse(retired_still_present, f'Retired jobs still present: {retired_still_present}')


if __name__ == '__main__':
    unittest.main()
