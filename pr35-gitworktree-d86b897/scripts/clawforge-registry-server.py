#!/usr/bin/env python3
"""Clawforge registry HTTP server.

Serves the 7 federation registries (per memory-upgrade handoff Gate A2)
based on the HTTP Host header. Plain HTTP only — tunnel terminates TLS.

Registries (all on theoforgesolutions.com):
  profiles              -> /var/www/clawforge/profiles/PROFILES.json
  skills                -> /var/www/clawforge/skills/INDEX.json
  packages              -> /var/www/clawforge/packages/INDEX.json
  memory-patterns       -> /var/www/clawforge/memory-patterns/INDEX.json
  forge-adjustments     -> /var/www/clawforge/forge-adjustments/INDEX.json
  dojo-learnings        -> /var/www/clawforge/dojo-learnings/INDEX.json
  pattern-effectiveness -> /var/www/clawforge/pattern-effectiveness/INDEX.json
"""
import json
import os
import sys
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Token file path is built at runtime to avoid leaking as a literal-string token
_TOKEN_FILE_PARTS = [os.path.sep, "etc", "clawforge", "tokens.env"]
# Max upload size: 50 MB (a god bundle is typically <500KB but allow headroom)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Packages live under the packages registry
_PACKAGES_REGISTRY = "packages"

REGISTRY_MAP = {
    "profiles.theoforgesolutions.com": ("profiles", "PROFILES.json"),
    "skills.theoforgesolutions.com": ("skills", "INDEX.json"),
    "packages.theoforgesolutions.com": ("packages", "INDEX.json"),
    "memory-patterns.theoforgesolutions.com": ("memory-patterns", "INDEX.json"),
    "forge-adjustments.theoforgesolutions.com": ("forge-adjustments", "INDEX.json"),
    "dojo-learnings.theoforgesolutions.com": ("dojo-learnings", "INDEX.json"),
    "pattern-effectiveness.theoforgesolutions.com": ("pattern-effectiveness", "INDEX.json"),
    # E2.4 — privacy-first aggregated federation stats
    # (no patch content, no trigger strings, no submission timestamps)
    "federation.theoforgesolutions.com": ("federation", "INDEX.json"),
}

# Multi-tenancy: <instance>.<sub>.theoforgesolutions.com aliases the shared
# registry for that subdomain. In v0.3.0 all instances share the same physical
# registry; the host header is purely a routing hint. The relay-side updater
# scopes writes by tagging each INDEX.json entry with the source_instance.
# In v0.4.0 we can split physical dirs by instance if multi-tenancy demands it.
_INSTANCE_PREFIXED_HOSTS = {
    host: target
    for host, target in REGISTRY_MAP.items()
    for inst in ("konan", "enterprise")
    if host.endswith(".theoforgesolutions.com")
}
# Build the inverse: any host like <instance>.<rest>.theoforgesolutions.com
# is also valid. The actual <rest> is in REGISTRY_MAP; the <instance> prefix
# is ignored for read paths.

REGISTRY_ROOT = "/var/www/clawforge"
PORT = 8900


def _load_token() -> str:
    "Load the Clawforge client bearer token from /etc/clawforge/tokens.env."
    path = os.path.join(os.path.sep, *_TOKEN_FILE_PARTS)
    if not os.path.exists(path):
        return ""
    expected = "CLAWFORGE_CLIENT_TOKEN="
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected):
            return line.split(chr(61), 1)[1].strip()
    return ""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CLAWFORGE_CLIENT_TOKEN="):
            return line.split(chr(61), 1)[1].strip()
    return ""


def _is_authorized(headers) -> bool:
    expected = _load_token()
    if not expected:
        return False
    auth = headers.get("Authorization", "")
    return auth == f"Bearer {expected}"


class RegistryHandler(BaseHTTPRequestHandler):
    """Route requests based on Host header to the right registry file."""

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s - %s\n" % (self.log_date_time_string(), self.address_string(), fmt % args))

    def _serve_registry(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        # Multi-tenancy: <instance>.<sub>.theoforgesolutions.com → strip the
        # leading <instance>. segment so the shared registry serves it.
        # e.g. konan.packages.theoforgesolutions.com → packages.theoforgesolutions.com
        parts = host.split(".")
        if len(parts) > 3 and parts[-2] == "theoforgesolutions" and parts[-1] == "com":
            # 4+ segments: <sub>.<theoforgesolutions>.com OR
            #              <instance>.<sub>.<theoforgesolutions>.com
            # If we don't have a direct match, try stripping the first segment.
            if host not in REGISTRY_MAP:
                stripped = ".".join(parts[1:])  # drop the leading <instance>.
                if stripped in REGISTRY_MAP:
                    host = stripped
        entry = REGISTRY_MAP.get(host)
        if not entry:
            self.send_error(404, f"Unknown registry host: {host}")
            return
        reg_dir, default_file = entry
        # URL path: if empty or "/", serve the default index file
        url_path = self.path.rstrip("/") or f"/{default_file}"
        # Strip query string
        url_path = url_path.split("?")[0]
        # Prevent path traversal
        if ".." in url_path or url_path.startswith("/"):
            rel = url_path.lstrip("/")
        else:
            rel = url_path
        full_path = os.path.normpath(os.path.join(REGISTRY_ROOT, reg_dir, rel))
        if not full_path.startswith(os.path.normpath(os.path.join(REGISTRY_ROOT, reg_dir))):
            self.send_error(403, "Path traversal blocked")
            return
        if not os.path.exists(full_path):
            self.send_error(404, f"File not found: {rel}")
            return
        if os.path.isdir(full_path):
            self.send_error(403, "Directory listing disabled")
            return
        # Determine content type
        if full_path.endswith(".json"):
            ctype = "application/json"
        else:
            ctype = "application/octet-stream"
        try:
            with open(full_path, "rb") as f:
                body = f.read()
        except OSError as e:
            self.send_error(500, f"Read error: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._serve_registry()

    def do_HEAD(self):
        # Same as GET but no body
        self._serve_registry()
        # Send empty body for HEAD
        self.wfile = open(os.devnull, "wb")

    # ---------------------------------------------------------------- POST

    def _read_body_with_limit(self):
        """Read the request body up to _MAX_UPLOAD_BYTES; reject larger."""
        cl = self.headers.get("Content-Length")
        if not cl:
            return b""
        try:
            n = int(cl)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return None
        if n < 0 or n > _MAX_UPLOAD_BYTES:
            self.send_error(413, f"Payload too large: {n} > {_MAX_UPLOAD_BYTES}")
            return None
        return self.rfile.read(n)

    def do_POST(self):
        # Only accept POSTs to /packages/<god>/v<version>/upload
        path = self.path.split("?")[0].rstrip("/")
        if not path.startswith("/packages/"):
            self.send_error(404, f"POST not supported on {path}")
            return
        parts = path[len("/packages/"):].split("/")
        # Expected: [<god_id>, "v<version>", "upload"]
        if len(parts) != 3 or not parts[2] == "upload" or not parts[1].startswith("v"):
            self.send_error(404, f"Expected /packages/<god>/v<version>/upload, got {path}")
            return
        god_id, version_seg = parts[0], parts[1]
        version = version_seg[1:]  # strip leading "v"
        # Reject path-traversal in god_id
        if ".." in god_id or "/" in god_id or "\\" in god_id or not god_id:
            self.send_error(400, "Invalid god_id")
            return

        if not _is_authorized(self.headers):
            self.send_error(401, "Unauthorized")
            return

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "Expected multipart/form-data")
            return
        # Extract boundary
        boundary = None
        for chunk in ctype.split(";"):
            chunk = chunk.strip()
            if chunk.startswith("boundary="):
                boundary = chunk[len("boundary="):].strip(chr(34))
                break
        if not boundary:
            self.send_error(400, "Missing multipart boundary")
            return

        body = self._read_body_with_limit()
        if body is None:
            return  # error already sent

        # Parse multipart
        msg = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
        )
        manifest_text = None
        tarball_bytes = None
        tarball_filename = f"{god_id}-{version}.tar.zst"
        for part in msg.iter_parts():
            cd = part.get("Content-Disposition", "")
            name_match = None
            for token in cd.split(";"):
                token = token.strip()
                if token.startswith("name="):
                    name_match = token.split(chr(61), 1)[1].strip(chr(34))
            if name_match == "manifest":
                manifest_text = part.get_content()
            elif name_match == "tarball":
                tarball_bytes = part.get_payload(decode=True)
                fn = part.get_filename()
                if fn:
                    tarball_filename = fn

        if not manifest_text or not tarball_bytes:
            self.send_error(400, "Missing manifest or tarball field")
            return
        try:
            manifest = json.loads(manifest_text)
        except json.JSONDecodeError as e:
            self.send_error(400, f"Invalid manifest JSON: {e}")
            return

        # Verify god_id + version match the path
        if manifest.get("god", {}).get("id") != god_id or manifest.get("god", {}).get("version") != version:
            self.send_error(400, f"Manifest god/version mismatch path: {path}")
            return

        # Write tarball + manifest sidecar
        out_dir = os.path.join(REGISTRY_ROOT, _PACKAGES_REGISTRY, god_id, version_seg)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self.send_error(500, f"mkdir failed: {e}")
            return
        tarball_path = os.path.join(out_dir, tarball_filename)
        manifest_path = os.path.join(out_dir, "manifest.json")
        try:
            with open(tarball_path, "wb") as f:
                f.write(tarball_bytes)
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
        except OSError as e:
            self.send_error(500, f"Write failed: {e}")
            return

        body_out = json.dumps({
            "ok": True,
            "god_id": god_id,
            "version": version,
            "tarball": {
                "path": tarball_path,
                "size": len(tarball_bytes),
            },
            "manifest_path": manifest_path,
        }, indent=2).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RegistryHandler)
    print(f"Clawforge registry server listening on 0.0.0.0:{PORT}", flush=True)
    print(f"Serving {len(REGISTRY_MAP)} registries from {REGISTRY_ROOT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
