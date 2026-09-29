#!/usr/bin/env python3
"""phone_screen.py — canonical screen-reading backend for the Pantheon phone gateway.

Why this exists
---------------
Two ways to read a phone screen, with different costs and failure modes:

  Tier 1  ARTEMIS accessibility helper  (com.artemis.helper, loopback HTTP)
          Light: needs no `app_process` server, and never touches `UiDevice`,
          so it sidesteps the Android 17 `d.info` crash by construction.
          Read-only.

  Tier 2  uiautomator2 `dump_hierarchy()`
          Heavier, holds the UiAutomation connection, but it is the only path
          that can act (tap/type/swipe) and the reliable fallback.

CRITICAL: the two CANNOT serve at the same moment. Android unbinds every
accessibility service while a UiAutomation connection is alive, so a running
uiautomator2 server makes the helper silent (0 bytes). This module detects that
and falls back instead of returning an empty screen as if it were real.

API
---
    from phone_screen import PhoneScreen
    ps = PhoneScreen()                       # resolves device + tooling itself
    ps.hierarchy_xml()                       # helper first, uia2 fallback
    ps.hierarchy_xml(backend="uia2")         # force
    ps.foreground_app()                      # {'package':..., 'backend':...}
    ps.probe()                               # health of both backends

CLI:
    python3 phone_screen.py --probe
    python3 phone_screen.py --hierarchy [--backend helper|uia2|auto]
    python3 phone_screen.py --foreground
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── PYTHONPATH fix: strip Hermes vendor (its py311 PIL breaks the 3.12 venv) ──
_HERMES_VENDOR = str(Path.home() / ".hermes" / "vendor")
sys.path = [p for p in sys.path if _HERMES_VENDOR not in p]

HELPER_DIR = Path(
    os.environ.get("PANTHEON_PHONE_HELPER_DIR", str(Path.home() / "phone-apks" / "artemis"))
)
TOKEN_FILE = HELPER_DIR / "session.token"
PORTS_FILE = HELPER_DIR / "attached-ports.txt"

#: uiautomator2's device server listens here; its presence suppresses the helper.
UIA2_SERVER_PORT = 9008
HELPER_DEVICE_PORT = 18888

PREFERRED_CODENAME = "tokay"          # Pixel 9 = the gateway
PREFERRED_TAILSCALE_HOST = "pixel-9"  # stable across DHCP
LAST_KNOWN_LAN = "192.168.1.11:5555"  # may be stale — last resort only


def resolve_adb() -> str:
    """Locate the adb binary.

    adb is NOT on PATH on this host, which is why subprocess(["adb", ...]) fails
    with FileNotFoundError. Resolve it explicitly.
    """
    explicit = os.environ.get("PANTHEON_ADB_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("adb")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "adb", Path("/usr/bin/adb")):
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("adb not found; set PANTHEON_ADB_BIN to its full path")


def resolve_device(adb: str | None = None) -> str:
    """Resolve the phone address WITHOUT hardcoding a LAN IP.

    The Pixel 9's LAN address drifted .18 -> .19 -> .11 in one month, so a
    constant is a time bomb. Order: env override, Tailscale, a transport adb
    already knows, then last-known LAN.
    """
    env = os.environ.get("PANTHEON_PHONE_ADB_ADDR")
    if env:
        return env

    tailscale = shutil.which("tailscale")
    if tailscale:
        try:
            out = subprocess.run(
                [tailscale, "status"], capture_output=True, text=True, timeout=10
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == PREFERRED_TAILSCALE_HOST:
                    return f"{parts[0]}:5555"
        except (subprocess.SubprocessError, OSError):
            pass

    if adb:
        try:
            out = subprocess.run(
                [adb, "devices", "-l"], capture_output=True, text=True, timeout=10
            ).stdout
            for line in out.splitlines():
                if f"device:{PREFERRED_CODENAME}" in line or "model:Pixel_9" in line:
                    return line.split()[0]
        except (subprocess.SubprocessError, OSError):
            pass

    return LAST_KNOWN_LAN


def _read_ports() -> dict[str, int]:
    """Parse serial -> host port from attached-ports.txt."""
    ports: dict[str, int] = {}
    if not PORTS_FILE.is_file():
        return ports
    for line in PORTS_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                ports[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return ports


class PhoneScreen:
    """Screen reader over the two backends, with honest failure reporting."""

    def __init__(self, device: str | None = None) -> None:
        self.adb = resolve_adb()
        self.device = device or resolve_device(self.adb)
        self._ports = _read_ports()
        self.token = (
            TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.is_file() else ""
        )

    # ── helper (tier 1) ────────────────────────────────────────────────────
    @property
    def helper_port(self) -> int:
        """Host port tunnelled to this device's helper."""
        if self.device in self._ports:
            return self._ports[self.device]
        env = os.environ.get("PANTHEON_HELPER_PORT")
        if env:
            return int(env)
        return HELPER_DEVICE_PORT

    def _helper_get(self, path: str, timeout: float = 12.0) -> str | None:
        url = f"http://127.0.0.1:{self.helper_port}{path}"
        req = urllib.request.Request(url)
        if self.token:
            req.add_header("X-Artemis-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            return None

    def helper_ping(self) -> dict[str, Any] | None:
        """Liveness + version. Returns None when the helper is unreachable."""
        raw = self._helper_get("/ping", timeout=6.0)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def helper_hierarchy(self) -> str | None:
        """Hierarchy served by the accessibility service. None on failure."""
        return self._helper_get("/hierarchy.xml")

    # ── uiautomator2 (tier 2) ──────────────────────────────────────────────
    def uia2_hierarchy(self) -> str | None:
        """dump_hierarchy() through the venv. None on failure.

        Uses dump_hierarchy deliberately: `d.info` is broken on Android 17
        (ApplicationSharedMemory not initialized).
        """
        venv_py = Path.home() / ".phone-control-venv" / "bin" / "python3"
        if not venv_py.is_file():
            return None
        code = (
            "import uiautomator2 as u2, sys\n"
            f"d = u2.connect({self.device!r})\n"
            "sys.stdout.write(d.dump_hierarchy())\n"
        )
        env = {**os.environ, "PYTHONPATH": ""}
        try:
            res = subprocess.run(
                [str(venv_py), "-c", code],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return res.stdout or None

    # ── holder detection ───────────────────────────────────────────────────
    def uiautomation_holder(self) -> str | None:
        """Return the UiAutomation holder's command line, or None.

        Must use `ps -A -o args`: on Android 17 `ps -A` shows the holder as a bare
        `app_process`, hiding the marker. A bare `com.github.uiautomator` process
        is NOT proof of a holder, so only server markers count.
        """
        try:
            res = subprocess.run(
                [self.adb, "-s", self.device, "shell", "ps", "-A", "-o", "args"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        for line in res.stdout.splitlines():
            if re.search(r"uia2\.Main|io\.appium\.uiautomator2", line) and "grep" not in line:
                return line.strip()
        return None

    # ── unified read ───────────────────────────────────────────────────────
    def hierarchy_xml(self, backend: str = "auto") -> tuple[str, str]:
        """Read the hierarchy. Returns (xml, backend_used).

        Raises RuntimeError (never returns an empty string as if it were a real
        screen) when nothing could be read — an empty tree is a failure signal,
        and silently treating it as "blank screen" is how suppression bugs hide.
        """
        if backend in ("auto", "helper"):
            xml = self.helper_hierarchy()
            if xml and "<hierarchy" in xml and len(xml) > 200:
                return xml, "helper"
            if backend == "helper":
                holder = self.uiautomation_holder()
                detail = f" — UiAutomation holder: {holder}" if holder else ""
                raise RuntimeError(
                    f"ARTEMIS helper returned nothing on {self.device}"
                    f" (port {self.helper_port}){detail}. "
                    "A holder suppresses it; or the service is not enabled."
                )

        xml = self.uia2_hierarchy()
        if xml and "<hierarchy" in xml:
            return xml, "uia2"
        raise RuntimeError(f"could not read the hierarchy on {self.device} via any backend")

    def foreground_app(self, backend: str = "auto") -> dict[str, Any]:
        """Best-effort current package, from the hierarchy."""
        xml, used = self.hierarchy_xml(backend)
        match = re.search(r'package="([^"]+)"[^>]*window-active="true"', xml)
        if not match:
            match = re.search(r'package="([^"]+)"', xml)
        return {
            "package": match.group(1) if match else None,
            "backend": used,
            "nodes": xml.count("<node"),
            "bytes": len(xml),
        }

    def probe(self) -> dict[str, Any]:
        """Health of everything, without raising — for monitoring and the daemon."""
        ping = self.helper_ping()
        holder = self.uiautomation_holder()
        result: dict[str, Any] = {
            "device": self.device,
            "adb": self.adb,
            "helper_port": self.helper_port,
            "helper": "ok" if ping and ping.get("success") else "unreachable",
            "helper_version": (ping or {}).get("version_name"),
            "uiautomation_holder": holder or "none",
        }
        try:
            xml, used = self.hierarchy_xml()
            result["read"] = f"ok via {used}"
            result["nodes"] = xml.count("<node")
        except RuntimeError as exc:
            result["read"] = f"FAILED: {exc}"
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Pantheon phone screen backend")
    parser.add_argument("--device", help="ADB address (default: auto-resolve)")
    parser.add_argument("--probe", action="store_true", help="report backend health")
    parser.add_argument("--hierarchy", action="store_true", help="dump hierarchy XML")
    parser.add_argument("--foreground", action="store_true", help="report foreground app")
    parser.add_argument("--backend", choices=["auto", "helper", "uia2"], default="auto")
    args = parser.parse_args()

    ps = PhoneScreen(args.device)

    # A failed read is a real result, not a crash. Report it on stderr with a
    # non-zero exit instead of dumping a traceback at whoever is debugging a
    # phone — and never print an empty hierarchy, because an empty tree looks
    # exactly like a blank screen, which is how suppression bugs hide.
    try:
        if args.probe:
            print(json.dumps(ps.probe(), indent=2))
            return 0
        if args.foreground:
            print(json.dumps(ps.foreground_app(args.backend), indent=2))
            return 0
        if args.hierarchy:
            xml, used = ps.hierarchy_xml(args.backend)
            sys.stderr.write(f"[backend: {used}, {xml.count('<node')} nodes]\n")
            print(xml)
            return 0
    except RuntimeError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
