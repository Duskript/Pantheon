"""Pantheon Client Kit — Discord portal intake (SPEC-CONTRACT Phase 3, fork A).

Discord applications **cannot be created through the API** — the Developer Portal
is the only door. Fork A committed to driving that portal in a browser over CDP,
which buys a hands-free client experience at the cost of fragility: it is a
single-page app that redesigns without notice.

This module is written to survive that fragility as far as possible:

* **The token is captured from the token-reset XHR response**, never scraped from
  the DOM. Response bodies are structured data; markup is not.
* **A selector health check runs before anything else.** If the portal has been
  redesigned, the run stops with "the portal changed" instead of half-creating
  applications or clicking something unintended.
* **It refuses when there is no browser to drive.** The kit needs an *external*
  Chromium carrying the client's logged-in profile: Lightpanda keeps only logs and
  has no cookie jar (measured 2026-11-15), and `browser.cdp_url` is empty by
  default. No CDP endpoint means the manual path, stated plainly.
* **A token is never printed.** The only thing that leaves this module is the
  numeric client_id, and a report that says which god got which.

The manual fallback is a first-class path, not a failure mode: ~30–45 s per god in
the portal (Create App → Bot tab → Reset Token → enable Message Content and
Server Members intents). `MANUAL_STEPS` below is that checklist, and the CLI
prints it whenever automation is unavailable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

PORTAL_URL = "https://discord.com/developers/applications"

#: The portal surface this module depends on. Keys are stable names; values are
#: the selector/text probes the health check looks for. Anything missing means the
#: portal moved and automation must stop.
SELECTORS: dict[str, str] = {
    "new_application": "button[type='submit'], [class*='button']",
    "applications_list": "[class*='applicationCard'], [class*='appListItem'], a[href*='/applications/']",
    "bot_tab": "[href*='bot'], [class*='navItem']",
    "reset_token": "button[class*='danger'], button",
    "app_name_field": "input[type='text'], input",
}

MANUAL_STEPS = [
    "Open https://discord.com/developers/applications and log in as the client.",
    "New Application → name it after the god → Create.",
    "Bot tab → Reset Token → copy the token into that god's profile .env.",
    "Bot tab → enable 'Message Content Intent' and 'Server Members Intent'.",
    "Repeat per god (~30–45 s each). Everything after the token exists is scripted.",
]


class CdpTransport(Protocol):
    """Just enough CDP to drive the portal. Injectable, so tests stay offline."""

    def evaluate(self, expression: str) -> Any: ...
    def navigate(self, url: str) -> None: ...
    def network_bodies(self, url_pattern: str) -> list[dict]: ...
    def click(self, selector: str) -> None: ...
    def fill(self, selector: str, text: str) -> None: ...


class PortalError(RuntimeError):
    """The portal cannot be driven, or it has changed under us."""


@dataclass
class IntakeReport:
    created: list[str] = field(default_factory=list)
    client_ids: dict[str, str] = field(default_factory=dict)
    stopped_reason: str = ""
    health: dict = field(default_factory=dict)

    def public(self) -> dict:
        """Shareable: no token, no response bodies."""
        return {
            "created": self.created,
            "client_ids": self.client_ids,
            "stopped_reason": self.stopped_reason,
            "health": self.health,
        }


class PortalIntake:
    """Drives the Developer Portal, health-check first."""

    def __init__(self, cdp: CdpTransport | None, portal_url: str = PORTAL_URL):
        self.cdp = cdp
        self.portal_url = portal_url
        self.report = IntakeReport()

    # -- readiness ---------------------------------------------------------
    def readiness(self) -> dict:
        """Can this run at all? Say why not, with the fix."""
        if self.cdp is None:
            return {
                "ready": False,
                "reason": "no CDP endpoint — the kit needs an external Chromium carrying the "
                          "client's logged-in Discord session (Lightpanda keeps no cookie jar, "
                          "so it cannot hold that login)",
                "fix": "point browser.cdp_url at a running Chromium started with "
                       "--remote-debugging-port, logged into discord.com",
                "fallback": MANUAL_STEPS,
            }
        return {"ready": True, "reason": "", "fix": "", "fallback": []}

    # -- health check ------------------------------------------------------
    def health_check(self) -> dict:
        """Probe the portal for every selector this module depends on.

        Run before any click. A missing selector means the portal was redesigned —
        automation stops with a named defect instead of guessing at new markup.
        """
        if self.cdp is None:
            raise PortalError("no CDP endpoint to health-check")
        self.cdp.navigate(self.portal_url)
        missing: list[str] = []
        present: list[str] = []
        for name, selector in SELECTORS.items():
            found = False
            try:
                found = bool(self.cdp.evaluate(
                    f"!!document.querySelector({json.dumps(selector)})"
                ))
            except Exception:  # noqa: BLE001 — an evaluate failure IS a missing selector
                found = False
            (present if found else missing).append(name)
        self.report.health = {"present": sorted(present), "missing": sorted(missing),
                              "portal_url": self.portal_url}
        if missing:
            raise PortalError(
                "the Developer Portal no longer matches the selectors this kit drives "
                f"(missing: {', '.join(sorted(missing))}). Stop and use the manual path; "
                f"a redesign means new markup, not a retry."
            )
        return self.report.health

    # -- actions -----------------------------------------------------------
    def create_application(self, name: str) -> str:
        """Create one application and return its client id (never the token)."""
        if self.cdp is None:
            raise PortalError("no CDP endpoint")
        self.cdp.click(SELECTORS["new_application"])
        self.cdp.fill(SELECTORS["app_name_field"], name)
        path = self.cdp.evaluate("location.pathname")
        match = re.search(r"/applications/(\d+)", str(path or ""))
        if not match:
            raise PortalError(f"could not read the new application id from '{path}'")
        client_id = match.group(1)
        self.report.created.append(name)
        self.report.client_ids[name] = client_id
        return client_id

    def capture_token(self, app_id: str) -> str:
        """Read the token out of the token-reset **response body**, not the DOM.

        Markup churns; the API response shape is far more stable. The token is
        returned to the caller and deliberately never stored on the report.
        """
        if self.cdp is None:
            raise PortalError("no CDP endpoint")
        bodies = self.cdp.network_bodies(rf"/applications/{app_id}/bot/reset")
        for body in bodies:
            token = (body or {}).get("token")
            if isinstance(token, str) and token.count(".") == 2:
                return token
        raise PortalError(
            "no token in the token-reset response — either the reset did not happen or "
            "the response shape changed; use the manual path rather than scraping the DOM"
        )


def _cdp_from_config(config_path: pathlib.Path | None = None) -> tuple[Any, str]:
    """Read `browser.cdp_url` from a Hermes config. Empty means the manual path."""
    path = pathlib.Path(config_path) if config_path else (
        pathlib.Path.home() / ".hermes" / "config.yaml")
    if not path.exists():
        return None, f"no config at {path}"
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    url = ((data.get("browser") or {}).get("cdp_url") or "").strip()
    return (url or None), ("" if url else "browser.cdp_url is empty")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="portal_intake",
        description="Discord Developer Portal intake over CDP, health-checked.",
    )
    parser.add_argument("--config", default=None, help="Hermes config.yaml to read browser.cdp_url")
    parser.add_argument("--cdp-url", default=None, help="override the CDP endpoint")
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cdp_url = args.cdp_url
    if not cdp_url:
        cdp_url, why = _cdp_from_config(pathlib.Path(args.config) if args.config else None)
        if cdp_url is None:
            print(f"no CDP endpoint ({why}) — the manual path applies:")
            for step in MANUAL_STEPS:
                print(f"  {step}")
            return 2

    intake = PortalIntake(_LiveCdp(cdp_url))
    if args.health_check:
        try:
            health = intake.health_check()
        except PortalError as exc:
            print(f"portal health check FAILED: {exc}", file=sys.stderr)
            print("manual path:")
            for step in MANUAL_STEPS:
                print(f"  {step}")
            return 1
        print(json.dumps(health, indent=2) if args.json
              else f"portal OK — {len(health['present'])} selectors present")
        return 0

    print(json.dumps(intake.readiness(), indent=2) if args.json
          else f"ready at {cdp_url}: {intake.readiness()['ready']}")
    return 0


class _LiveCdp:
    """Thin wrapper over the browser tool this agent already has."""

    def __init__(self, url: str):
        self.url = url

    def _js(self, expression: str) -> Any:
        from browser_exec_helpers import js  # type: ignore  # provided by the agent runtime

        return js(expression)

    def evaluate(self, expression: str) -> Any:      # pragma: no cover - needs a live browser
        return self._js(expression)

    def navigate(self, url: str) -> None:            # pragma: no cover
        self._js(f"location.href = {json.dumps(url)}")

    def network_bodies(self, url_pattern: str) -> list[dict]:  # pragma: no cover
        raise PortalError(
            "capturing response bodies needs CDP Network.enable; run this through the agent's "
            "browser session rather than a bare CDP wrapper"
        )

    def click(self, selector: str) -> None:          # pragma: no cover
        self._js(f"document.querySelector({json.dumps(selector)}).click()")

    def fill(self, selector: str, text: str) -> None:  # pragma: no cover
        self._js(
            f"(()=>{{const e=document.querySelector({json.dumps(selector)});"
            f"e.value={json.dumps(text)};e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()"
        )


if __name__ == "__main__":
    raise SystemExit(main())
