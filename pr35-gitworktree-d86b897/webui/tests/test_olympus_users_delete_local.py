"""Regression test for the DELETE /api/olympus/users/{id} local handler.

Bug context: the webui's handle_delete dispatched DELETE /api/olympus/users/{id}
to a proxy at 127.0.0.1:8788, which is the Olympus backend service that was
built but never deployed. Every DELETE request returned 502 "Olympus backend
unreachable" because nothing is listening on :8788. The local ``delete_user``
function in ``api/olympus_users.py`` was the actual source of truth (494
lines of full user CRUD, feature flags, role hierarchy, session-to-user
mapping) but was never reachable from the web.

Fix: handle_delete now dispatches DELETE /api/olympus/users/{id} to the
local ``delete_user`` function before the proxy fallback. When auth is
disabled (no ``HERMES_WEBUI_PASSWORD`` set), the caller is treated as owner
for permission purposes -- matching pre-proxy behavior for local-mode
installs.

This test is a static-source regression test: it reads
``webui/api/routes.py`` and confirms the dispatch wiring is correct. Static
testing is used instead of dynamic import because ``routes.py`` is part of
the ``api`` package and its top-level imports pull in heavy dependencies
that would require the venv. The behavior itself was already verified
end-to-end with curl: ``DELETE /api/olympus/users/<id>`` returns
``{"ok": true, "deleted": <id>}`` in 1-3ms with no proxy 502.

Run:
  ``python3 -m pytest webui/tests/test_olympus_users_delete_local.py -v``
or
  ``python3 webui/tests/test_olympus_users_delete_local.py``
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ROUTES_PATH = REPO / "webui" / "api" / "routes.py"


def _load_routes_source() -> str:
    """Read the routes module source as text.

    Returns the full text of ``webui/api/routes.py``. The file is
    always present in this repo, so a missing-file error is acceptable
    to surface.
    """
    return ROUTES_PATH.read_text(encoding="utf-8")


def _block_in_handle_delete(source: str, marker: str) -> int:
    """Return the offset of ``marker`` inside handle_delete, or -1.

    We scope searches to handle_delete's body so the GET/POST proxy blocks
    don't accidentally satisfy the assertion.
    """
    handle_start = source.find("def handle_delete")
    if handle_start == -1:
        return -1
    next_def = source.find("\ndef ", handle_start + 1)
    if next_def == -1:
        next_def = len(source)
    block = source[handle_start:next_def]
    return block.find(marker)


class TestDeleteUserLocalHandler(unittest.TestCase):
    """Static checks that the local DELETE /api/olympus/users/ handler exists
    and is registered before the dead :8788 proxy."""

    @classmethod
    def setUpClass(cls):
        cls.source = _load_routes_source()

    def test_local_block_appears_before_proxy(self):
        """The local handler must dispatch before the proxy to avoid 502s."""
        local_idx = self.source.find('if parsed.path.startswith("/api/olympus/users/")')
        # Note: the proxy block in the source uses an em-dash (U+2014), not
        # a regular hyphen. We must match it exactly.
        proxy_idx = self.source.find("# \u2500\u2500 Olympus routes \u2014 proxy")
        self.assertNotEqual(local_idx, -1, "local /api/olympus/users/ block missing")
        self.assertNotEqual(proxy_idx, -1, "olympus proxy block missing")
        self.assertLess(
            local_idx,
            proxy_idx,
            "local handler must be registered before the proxy",
        )

    def test_handle_delete_local_block_uses_local_module(self):
        """The DELETE handler must import delete_user from api.olympus_users."""
        marker = 'if parsed.path.startswith("/api/olympus/users/")'
        idx = _block_in_handle_delete(self.source, marker)
        self.assertNotEqual(idx, -1, "no local /api/olympus/users/ block in handle_delete")
        handle_start = self.source.find("def handle_delete")
        next_def = self.source.find("\ndef ", handle_start + 1)
        if next_def == -1:
            next_def = len(self.source)
        block = self.source[handle_start:next_def]
        self.assertIn(
            "from api.olympus_users import delete_user",
            block,
            "DELETE handler must import delete_user from api.olympus_users",
        )

    def test_resolve_acting_user_helper_exists(self):
        """The new _resolve_acting_user helper must be defined at module scope."""
        self.assertIn(
            "def _resolve_acting_user(",
            self.source,
            "_resolve_acting_user helper missing from routes module",
        )

    def test_auth_disabled_branch_present(self):
        """The local DELETE must check is_auth_enabled() and default to owner
        when auth is off (no HERMES_WEBUI_PASSWORD), so local-mode installs
        don't get 401."""
        handle_start = self.source.find("def handle_delete")
        next_def = self.source.find("\ndef ", handle_start + 1)
        if next_def == -1:
            next_def = len(self.source)
        block = self.source[handle_start:next_def]
        marker = 'if parsed.path.startswith("/api/olympus/users/")'
        idx = block.find(marker)
        self.assertNotEqual(idx, -1, "local DELETE block missing")
        window = block[idx:idx + 1500]
        self.assertIn("is_auth_enabled", window, "must check is_auth_enabled()")
        self.assertIn('"role": "owner"', window, "must default to owner role")

    def test_no_more_dead_proxy_for_olympus_delete(self):
        """The DELETE dispatch must NOT reach the proxy for olympus users.
        Confirmed by checking the local block comes first."""
        handle_start = self.source.find("def handle_delete")
        next_def = self.source.find("\ndef ", handle_start + 1)
        if next_def == -1:
            next_def = len(self.source)
        block = self.source[handle_start:next_def]
        local_idx = block.find('if parsed.path.startswith("/api/olympus/users/")')
        proxy_idx = block.find("# \u2500\u2500 Olympus routes \u2014 proxy")
        self.assertNotEqual(local_idx, -1)
        self.assertNotEqual(proxy_idx, -1)
        self.assertLess(local_idx, proxy_idx)


if __name__ == "__main__":
    unittest.main()
