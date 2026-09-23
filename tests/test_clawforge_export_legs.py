"""Three-leg export parity for the Clawforge Pass 3 exporters.

THE DEFECT THESE TESTS LOCK DOWN
--------------------------------
`adjustment_exporter` grew three export legs (local artifact / local relay /
federation). `pattern_exporter` and `learning_exporter` did not: they published
straight to a hardcoded peer address, had no local leg at all, and had no
sharing gate. Fixing one file left the class open, because the next lane is
cloned from whichever copy is nearest.

So these tests assert the CLASS, not the instance:

  1. Every lane runs its local legs and reports them — even when
     `pattern_sharing` is off. A cross-instance privacy switch must never
     disable local self-improvement.
  2. Every lane refuses to reach a peer that was not explicitly configured.
  3. No lane carries a hardcoded peer address.

(3) reads the lane sources rather than calling them. That is deliberate and
narrow: the failure it guards is a *literal network destination* appearing in a
lane, which is a privacy/egress contract rather than an implementation detail.
The behavioral tests below catch a lane that stops delegating to
`clawforge.legs`; the source check catches one that starts publishing on its own.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lib"))

from clawforge import legs  # noqa: E402
from clawforge import (  # noqa: E402
    adjustment_exporter,
    learning_exporter,
    pattern_exporter,
)

LANES = {
    "forge": adjustment_exporter,
    "memory": pattern_exporter,
    "dojo": learning_exporter,
}

#: The peer address that used to be the silent default destination.
PEER_ADDRESS = "100.100.46.52"

LANE_SOURCES = [
    REPO / "lib" / "clawforge" / "legs.py",
    REPO / "lib" / "clawforge" / "adjustment_exporter.py",
    REPO / "lib" / "clawforge" / "learning_exporter.py",
    REPO / "lib" / "clawforge" / "pattern_exporter.py",
    REPO / "scripts" / "clawforge-pass3-smoke.py",
]


class _FakeConn:
    """Records what a lane published, and to which endpoint."""

    def __init__(self, url: str, name: str = "", token: str = ""):
        self.url = url
        self.name = name
        self.token = token
        self.messages: list[tuple[str, dict]] = []

    async def publish(self, subject: str, data: bytes) -> None:
        self.messages.append((subject, json.loads(data.decode("utf-8"))))

    async def flush(self) -> None:
        return None

    async def drain(self) -> None:
        return None


def _fake_nats_module(connections: list[_FakeConn]) -> types.ModuleType:
    mod = types.ModuleType("nats")

    async def connect(url, name="", token="", **kwargs):  # noqa: ANN001, ANN003
        conn = _FakeConn(url, name, token)
        connections.append(conn)
        return conn

    mod.connect = connect  # type: ignore[attr-defined]
    return mod


class _LegsTestCase(unittest.TestCase):
    """Isolates config + artifact paths, stubs NATS, clears the peer env var."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self._orig_config = legs.CLAWFORGE_CONFIG
        self._orig_artifact_dir = legs.LOCAL_ARTIFACT_DIR
        legs.LOCAL_ARTIFACT_DIR = self.tmp / "artifacts"
        self.addCleanup(self._restore_paths)

        self.connections: list[_FakeConn] = []
        self._orig_nats = sys.modules.get("nats")
        sys.modules["nats"] = _fake_nats_module(self.connections)
        self.addCleanup(self._restore_nats)

        self._orig_host = os.environ.pop("CLAWFORGE_NATS_HOST", None)
        os.environ.pop("CLAWFORGE_NATS_PORT", None)
        self.addCleanup(self._restore_env)

    def _restore_paths(self) -> None:
        legs.CLAWFORGE_CONFIG = self._orig_config
        legs.LOCAL_ARTIFACT_DIR = self._orig_artifact_dir

    def _restore_nats(self) -> None:
        if self._orig_nats is None:
            sys.modules.pop("nats", None)
        else:
            sys.modules["nats"] = self._orig_nats

    def _restore_env(self) -> None:
        if self._orig_host is not None:
            os.environ["CLAWFORGE_NATS_HOST"] = self._orig_host

    def set_config(self, text: str) -> None:
        path = self.tmp / "clawforge.yaml"
        path.write_text(text)
        legs.CLAWFORGE_CONFIG = path

    def run_lane(self, name: str, **kwargs):
        return asyncio.run(LANES[name].run(days=7, **kwargs))


# ---------------------------------------------------------------------------
# 1. Parity: every lane runs the local legs and reports them
# ---------------------------------------------------------------------------

class TestLaneParity(_LegsTestCase):
    def test_every_lane_runs_the_local_legs_and_reports_them(self):
        """A lane that does not delegate to `run_legs` cannot produce this dict.

        The local relay connection name is per-lane (`clawforge-<lane>-local`),
        so this also pins that each lane publishes exactly once, to its own
        endpoint, and that the lane's `share` default is off when the config
        carries no `pattern_sharing` block.
        """
        self.set_config("relay:\n  host: 127.0.0.1\n  port: 4222\n")
        for name in LANES:
            with self.subTest(lane=name):
                self.connections.clear()
                result = self.run_lane(name)
                self.assertEqual(result["exporter"], name)
                self.assertIn("entry", result)
                self.assertTrue(result["published_local"], "local leg did not run")
                self.assertFalse(result["published_remote"], "reached a peer unasked")
                self.assertTrue(Path(result["artifact"]).exists(), "no local artifact")
                self.assertEqual(
                    [c.name for c in self.connections], ["clawforge-" + name + "-local"]
                )

    def test_local_legs_run_even_when_sharing_is_explicitly_off(self):
        """The original defect: a privacy switch disabled local self-improvement."""
        self.set_config(
            "relay:\n  host: 127.0.0.1\n"
            "pattern_sharing:\n  enabled: false\n"
            "  dojo_learnings: false\n"
            "  memory_patterns: false\n"
            "  forge_adjustments: false\n"
        )
        for name in LANES:
            with self.subTest(lane=name):
                result = self.run_lane(name)
                self.assertTrue(result["published_local"], "local leg gated by sharing")
                self.assertFalse(result["published_remote"])
                self.assertTrue(any("pattern_sharing" in n for n in result["notes"]))

    def test_no_lane_hardcodes_a_peer_address(self):
        for path in LANE_SOURCES:
            with self.subTest(source=path.name):
                self.assertNotIn(
                    PEER_ADDRESS,
                    path.read_text(),
                    msg=(
                        path.name + " carries a hardcoded peer address. The peer "
                        "belongs in `federation:` in clawforge.yaml or "
                        "CLAWFORGE_NATS_HOST — never in a lane's source."
                    ),
                )


# ---------------------------------------------------------------------------
# 2. Sharing gates: master switch AND per-lane opt-in
# ---------------------------------------------------------------------------

class TestSharingGates(_LegsTestCase):
    def test_master_switch_alone_does_not_share(self):
        self.set_config("pattern_sharing:\n  enabled: true\n")
        for name in LANES:
            with self.subTest(lane=name):
                self.assertFalse(legs.sharing_allowed_for(name))

    def test_opt_in_alone_does_not_share(self):
        self.set_config("pattern_sharing:\n  dojo_learnings: true\n")
        self.assertFalse(legs.sharing_allowed_for("dojo"))

    def test_master_plus_opt_in_shares_only_that_lane(self):
        self.set_config(
            "pattern_sharing:\n  enabled: true\n  dojo_learnings: true\n"
        )
        self.assertTrue(legs.sharing_allowed_for("dojo"))
        self.assertFalse(legs.sharing_allowed_for("memory"))
        self.assertFalse(legs.sharing_allowed_for("forge"))

    def test_missing_config_is_not_an_error(self):
        """An absent `pattern_sharing` block must not break anything."""
        legs.CLAWFORGE_CONFIG = self.tmp / "absent.yaml"
        self.assertEqual(legs.config(), {})
        self.assertFalse(legs.sharing_enabled())
        self.assertEqual(legs.local_nats_url(), "nats://127.0.0.1:4222")


# ---------------------------------------------------------------------------
# 3. Federation target is explicit or refused — never defaulted
# ---------------------------------------------------------------------------

class TestFederationTargetIsExplicit(_LegsTestCase):
    def test_refuses_when_no_peer_is_configured(self):
        self.set_config("relay:\n  host: 127.0.0.1\n  port: 4222\n")
        with self.assertRaises(SystemExit) as ctx:
            legs.federation_target()
        self.assertIn("no peer configured", str(ctx.exception))

    def test_env_names_the_peer(self):
        self.set_config("relay:\n  host: 127.0.0.1\n")
        os.environ["CLAWFORGE_NATS_HOST"] = "peer.example"
        os.environ["CLAWFORGE_NATS_PORT"] = "4333"
        self.addCleanup(os.environ.pop, "CLAWFORGE_NATS_HOST", None)
        self.addCleanup(os.environ.pop, "CLAWFORGE_NATS_PORT", None)
        with mock.patch.object(legs, "load_token", return_value="tok"):
            url, token = legs.federation_target()
        self.assertEqual(url, "nats://peer.example:4333")
        self.assertEqual(token, "tok")

    def test_config_names_the_peer(self):
        self.set_config("federation:\n  host: peer.local\n  port: 4223\n")
        with mock.patch.object(legs, "load_token", return_value="tok"):
            url, _ = legs.federation_target()
        self.assertEqual(url, "nats://peer.local:4223")

    def test_loopback_relay_is_not_reused_as_the_peer(self):
        """The local relay must never double as the federation destination."""
        self.set_config("relay:\n  host: 127.0.0.1\n  port: 4222\n")
        with self.assertRaises(SystemExit):
            legs.federation_target()


# ---------------------------------------------------------------------------
# 4. The federation leg is gated, the local legs are not
# ---------------------------------------------------------------------------

class TestFederationLegGating(_LegsTestCase):
    def test_sharing_on_without_a_peer_does_not_reach_out(self):
        self.set_config(
            "pattern_sharing:\n  enabled: true\n  dojo_learnings: true\n"
        )
        result = self.run_lane("dojo")
        self.assertTrue(result["published_local"])
        self.assertFalse(result["published_remote"])
        self.assertTrue(any("federation" in n for n in result["notes"]))
        self.assertEqual(
            [c.name for c in self.connections], ["clawforge-dojo-local"]
        )

    def test_sharing_on_with_a_peer_publishes_to_both_legs(self):
        self.set_config(
            "pattern_sharing:\n  enabled: true\n  dojo_learnings: true\n"
            "federation:\n  host: peer.local\n  port: 4222\n"
        )
        with mock.patch.object(legs, "load_token", return_value="tok"):
            result = self.run_lane("dojo")
        self.assertTrue(result["published_local"])
        self.assertTrue(result["published_remote"])
        self.assertEqual(
            sorted(c.name for c in self.connections),
            ["clawforge-dojo-federation", "clawforge-dojo-local"],
        )
        remote = [c for c in self.connections if c.name.endswith("federation")][0]
        self.assertEqual(remote.url, "nats://peer.local:4222")
        self.assertEqual(remote.token, "tok")

    def test_each_lane_uses_its_own_sharing_opt_in(self):
        """Arming one lane must not arm the others."""
        self.set_config(
            "pattern_sharing:\n  enabled: true\n  memory_patterns: true\n"
            "federation:\n  host: peer.local\n  port: 4222\n"
        )
        with mock.patch.object(legs, "load_token", return_value="tok"):
            memory = self.run_lane("memory")
            self.connections.clear()
            dojo = self.run_lane("dojo")
        self.assertTrue(memory["published_remote"], "memory lane should be armed")
        self.assertFalse(dojo["published_remote"], "dojo lane was not armed")


if __name__ == "__main__":
    unittest.main()
