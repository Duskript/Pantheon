"""Contract tests for the Discord portal intake (Phase 3, fork A).

PURE UNIT TESTS — a fake CDP transport stands in for the browser, so nothing here
launches a Chromium or touches discord.com.

Pinned here:
  * a redesigned portal **stops the run** with a named defect, before any click
  * the token is read from the token-reset *response body*, never from the DOM
  * no token ever reaches shareable output (report / CLI)
  * no CDP endpoint ⇒ the manual path is printed, not a silent no-op
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT = REPO / "client-kit"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


pi = _load("portal_intake", KIT / "portal_intake.py")

TOKEN = "MTQ5OTg0NTA2.sEcReT.partOfATokenThatMustNeverPrint"


class FakeCdp:
    """A CDP transport that answers from a script instead of a browser."""

    def __init__(self, *, present: set[str] | None = None, path: str = "/applications/1499845064359280710",
                 bodies: list[dict] | None = None, raise_on_evaluate: bool = False):
        self.present = present if present is not None else set(pi.SELECTORS) - {"new_application"}
        self.path = path
        self.bodies = bodies if bodies is not None else [{"token": TOKEN}]
        self.raise_on_evaluate = raise_on_evaluate
        self.calls: list[tuple[str, str]] = []

    def navigate(self, url):
        self.calls.append(("navigate", url))

    def evaluate(self, expression):
        self.calls.append(("evaluate", expression))
        if self.raise_on_evaluate:
            raise RuntimeError("cdp blew up")
        if expression == "location.pathname":
            return self.path
        for name, selector in pi.SELECTORS.items():
            if json.dumps(selector) in expression:
                return name in self.present
        return False

    def click(self, selector):
        self.calls.append(("click", selector))

    def fill(self, selector, text):
        self.calls.append(("fill", f"{selector}={text}"))

    def network_bodies(self, url_pattern):
        self.calls.append(("network_bodies", url_pattern))
        return self.bodies


# ── readiness ──────────────────────────────────────────────────────────────

def test_no_cdp_endpoint_means_the_manual_path_not_a_silent_no_op():
    readiness = pi.PortalIntake(None).readiness()
    assert readiness["ready"] is False
    assert "cookie jar" in readiness["reason"]
    assert "cdp_url" in readiness["fix"]
    assert readiness["fallback"] == pi.MANUAL_STEPS


def test_manual_steps_are_the_real_portal_checklist():
    joined = " ".join(pi.MANUAL_STEPS)
    assert "Reset Token" in joined
    assert "Message Content Intent" in joined and "Server Members Intent" in joined
    assert "30–45 s" in joined


# ── health check ───────────────────────────────────────────────────────────

def test_health_check_passes_when_every_selector_is_present():
    cdp = FakeCdp(present=set(pi.SELECTORS))
    health = pi.PortalIntake(cdp).health_check()
    assert health["missing"] == []
    assert sorted(health["present"]) == sorted(pi.SELECTORS)
    assert cdp.calls[0] == ("navigate", pi.PORTAL_URL)


def test_health_check_names_what_moved_instead_of_guessing():
    cdp = FakeCdp(present=set(pi.SELECTORS) - {"reset_token", "bot_tab"})
    intake = pi.PortalIntake(cdp)
    with pytest.raises(pi.PortalError) as exc:
        intake.health_check()
    message = str(exc.value)
    assert "reset_token" in message and "bot_tab" in message
    assert "manual path" in message
    assert intake.report.health["missing"] == ["bot_tab", "reset_token"]


def test_a_failing_evaluate_counts_as_a_missing_selector():
    with pytest.raises(pi.PortalError):
        pi.PortalIntake(FakeCdp(raise_on_evaluate=True)).health_check()


def test_health_check_runs_before_any_creation():
    """A rotated portal must not leave half-created applications behind."""
    cdp = FakeCdp(present=set())
    intake = pi.PortalIntake(cdp)
    with pytest.raises(pi.PortalError):
        intake.health_check()
    assert intake.report.created == []
    assert not any(call[0] == "click" for call in cdp.calls)


# ── token capture ──────────────────────────────────────────────────────────

def test_token_comes_from_the_response_body_not_the_dom():
    cdp = FakeCdp()
    token = pi.PortalIntake(cdp).capture_token("1499845064359280710")
    assert token == TOKEN
    assert ("network_bodies", "/applications/1499845064359280710/bot/reset") in cdp.calls
    assert not any("token" in call[1] for call in cdp.calls if call[0] == "evaluate")


def test_a_missing_or_malformed_token_is_refused_with_the_fallback():
    for bodies in ([], [{"token": "not-a-token"}], [{"no_token": True}]):
        with pytest.raises(pi.PortalError) as exc:
            pi.PortalIntake(FakeCdp(bodies=bodies)).capture_token("1")
        assert "manual path" in str(exc.value)


def test_the_report_never_carries_a_token():
    intake = pi.PortalIntake(FakeCdp())
    intake.report.created.append("Hermes")
    intake.capture_token("1499845064359280710")
    blob = json.dumps(intake.report.public())
    assert TOKEN not in blob
    assert "token" not in blob.lower()


# ── application creation ───────────────────────────────────────────────────

def test_create_application_returns_the_client_id_and_leaks_nothing():
    cdp = FakeCdp(path="/developers/applications/1499845064359280710/bot")
    intake = pi.PortalIntake(cdp)
    client_id = intake.create_application("Rheta")
    assert client_id == "1499845064359280710"
    assert intake.report.created == ["Rheta"]
    assert intake.report.client_ids == {"Rheta": "1499845064359280710"}
    assert TOKEN not in json.dumps(intake.report.public())
    assert any(call[0] == "fill" for call in cdp.calls)


def test_create_application_refuses_when_the_id_cannot_be_read():
    with pytest.raises(pi.PortalError) as exc:
        pi.PortalIntake(FakeCdp(path="/developers/applications")).create_application("Rheta")
    assert "could not read the new application id" in str(exc.value)


def test_actions_without_a_transport_are_refused():
    intake = pi.PortalIntake(None)
    for call in (intake.health_check, lambda: intake.create_application("x"),
                 lambda: intake.capture_token("1")):
        with pytest.raises(pi.PortalError):
            call()


# ── config + CLI ───────────────────────────────────────────────────────────

def test_cdp_url_is_read_from_the_hermes_config(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text(yaml.safe_dump({"browser": {"cdp_url": "  "}}), encoding="utf-8")
    url, why = pi._cdp_from_config(empty)
    assert url is None and "cdp_url is empty" in why

    configured = tmp_path / "set.yaml"
    configured.write_text(yaml.safe_dump(
        {"browser": {"cdp_url": "http://127.0.0.1:9222"}}), encoding="utf-8")
    url, why = pi._cdp_from_config(configured)
    assert url == "http://127.0.0.1:9222" and why == ""

    url, why = pi._cdp_from_config(tmp_path / "missing.yaml")
    assert url is None and "no config at" in why


def test_cli_prints_the_manual_path_when_there_is_no_browser(tmp_path, capsys):
    empty = tmp_path / "empty.yaml"
    empty.write_text(yaml.safe_dump({"browser": {"cdp_url": ""}}), encoding="utf-8")
    code = pi.main(["--config", str(empty)])
    assert code == 2
    out = capsys.readouterr().out
    assert "manual path" in out
    for step in pi.MANUAL_STEPS:
        assert step.split(".")[0] in out
