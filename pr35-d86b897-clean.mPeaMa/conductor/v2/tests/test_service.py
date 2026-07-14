"""Unit tests for conductor.v2.service — ConductorService daemon.

The service wires engine + gateway + nats + webhook + delivery together.
We test it with NATS disabled (no broker in test env) and a tmp base
dir so nothing leaks to production. Gateway is mocked via
unittest.mock.patch('v2.service.GatewayClient') because we never want
tests to hit the real Hermes api_server.

Tested responsibilities (per spec section 6 "single process"):

  - Construction loads rules/workflows from the configured dirs
  - status() returns a coherent dict before/after start
  - start() with unreachable gateway doesn't crash the daemon
  - start() with healthy gateway brings engine + webhook online
  - stop() cancels tasks and closes gateway client
  - --check mode runs validation and returns 0 or 2

The service is the integration point. The other modules (engine,
gateway, webhook, nats, delivery) have their own focused test files.
Here we verify they wire up correctly.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import service as svc_mod  # noqa: E402


class TestServiceConstruction(unittest.TestCase):
    """Just construct a ConductorService — don't start it."""

    def test_default_construction(self):
        svc = svc_mod.ConductorService(enable_nats=False, enable_webhook=False, enable_api=False)
        self.assertTrue(svc.enable_nats is False)
        self.assertTrue(svc.enable_webhook is False)
        self.assertEqual(svc.webhook_port, 8088)
        # Gateway not yet built
        self.assertIsNone(svc.gw)
        self.assertIsNone(svc.engine)
        # Rules/workflows are loaded
        self.assertIsNotNone(svc.rules)
        self.assertIsNotNone(svc.workflows)

    def test_status_before_start(self):
        svc = svc_mod.ConductorService(enable_nats=False, enable_webhook=False, enable_api=False)
        s = svc.status()
        self.assertEqual(s["engine"], "not started")
        self.assertEqual(s["webhook"], "disabled")
        self.assertEqual(s["nats"], "disabled")


class TestServiceWithUnreachableGateway(unittest.IsolatedAsyncioTestCase):
    """start() with a fake gateway that fails health. Should NOT crash
    the service — engine should still be ready."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        import os
        os.environ["CONDUCTOR_BASE_DIR"] = str(self.tmp.root)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_start_with_unreachable_gateway_does_not_crash(self):
        # Mock GatewayClient.__aenter__ to succeed but health() to fail
        with patch("v2.service.GatewayClient") as MockGW:
            instance = MockGW.return_value
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            instance.health = AsyncMock(side_effect=Exception("connection refused"))
            instance._client = MagicMock()
            svc = svc_mod.ConductorService(enable_nats=False, enable_webhook=False, enable_api=False)
            results = await svc.start()
        # Gateway reported unreachable
        self.assertEqual(results["gateway"]["status"], "unreachable")
        # But engine still ready
        self.assertEqual(results["engine"]["status"], "ready")
        # Webhook + nats disabled
        self.assertEqual(results["webhook"]["status"], "disabled")
        self.assertEqual(results["nats"]["status"], "disabled")
        # Engine is set
        self.assertIsNotNone(svc.engine)
        # Clean up
        await svc.stop()


class TestServiceWithMockGateway(unittest.IsolatedAsyncioTestCase):
    """start() with a working mock gateway + webhook on a custom port."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        import os
        os.environ["CONDUCTOR_BASE_DIR"] = str(self.tmp.root)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_start_with_mock_gateway_and_webhook(self):
        with patch("v2.service.GatewayClient") as MockGW:
            instance = MockGW.return_value
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            instance.health = AsyncMock(return_value={"status": "ok"})
            instance._client = MagicMock()

            svc = svc_mod.ConductorService(
                enable_nats=False,
                enable_webhook=True,
                enable_api=False,
                webhook_port=18099,  # unused port to avoid conflicts
            )
            results = await svc.start()
        self.assertEqual(results["gateway"]["status"], "connected")
        self.assertEqual(results["engine"]["status"], "ready")
        self.assertEqual(results["webhook"]["status"], "started")
        # The webhook is listening on the port
        self.assertIn("18099", str(results["webhook"].get("port", svc.webhook_port)))
        # Status dict
        s = svc.status()
        self.assertEqual(s["engine"], "ready")
        self.assertIn("18099", s["webhook"])
        await svc.stop()

    async def test_stop_cancels_tasks_and_closes_clients(self):
        with patch("v2.service.GatewayClient") as MockGW:
            instance = MockGW.return_value
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            instance.health = AsyncMock(return_value={"status": "ok"})
            instance._client = MagicMock()
            svc = svc_mod.ConductorService(enable_nats=False, enable_webhook=False, enable_api=False)
            await svc.start()
        # Some tasks were started (file watcher)
        self.assertGreater(len(svc._tasks), 0)
        await svc.stop()
        # After stop, all tasks should be done (cancelled)
        for t in svc._tasks:
            self.assertTrue(t.done() or t.cancelled())


class TestCheckOnly(unittest.TestCase):
    """The --check CLI mode validates config without starting."""

    def test_check_only_returns_0_or_2(self):
        import os
        os.environ["CONDUCTOR_BASE_DIR"] = str(Path(tempfile.mkdtemp(prefix="conductor_v2_check_")))

        # Just make sure _check_only runs without raising
        result = asyncio.run(svc_mod._check_only())
        # 0 = all good (gateway reachable), 2 = gateway unreachable
        # Both are valid — depends on whether Thoth is up
        self.assertIn(result, (0, 2))


if __name__ == "__main__":
    unittest.main()
