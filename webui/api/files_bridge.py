
"""files_bridge.py — Read-only file browser adapter for Olympus UI.

Safe allowlisted roots only. Path traversal protected. No write/delete.

Endpoints:
  GET /api/files/roots              → list of safe root directories
  GET /api/files/list?root=&path=   → directory listing
  GET /api/files/read?root=&path=   → file content (text only, max 1MB)
"""

from __future__ import annotations

import os
import mimetypes
from pathlib import Path

from api.helpers import bad, j, safe_resolve

SAFE_ROOTS = {
    "athenaeum": os.path.expanduser("~/pantheon/athenaeum"),
    "exports": os.path.expanduser("~/pantheon/god-exports"),
    "cron-output": os.path.expanduser("~/.hermes/cron/output"),
    "home-config": os.path.expanduser("~/.hermes"),
}

MAX_READ_BYTES = 1_048_576  # 1 MB
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".tsx",
                   ".html", ".css", ".toml", ".ini", ".cfg", ".log", ".csv", ".xml",
                   ".sh", ".bash", ".env", ".gitignore", ".dockerignore"}


def _validate_root(root_name):
    if root_name not in SAFE_ROOTS:
        raise ValueError("unknown root: {}".format(root_name))
    root_path = SAFE_ROOTS[root_name]
    if not os.path.isdir(root_path):
        raise ValueError("root directory not found: {}".format(root_name))
    return root_path


def handle_files(handler, parsed):
    from urllib.parse import parse_qs
    path = parsed.path
    qs = parse_qs(parsed.query or "")

    if path == "/api/files/roots":
        roots = []
        for name, dirpath in SAFE_ROOTS.items():
            exists = os.path.isdir(dirpath)
            roots.append({"name": name, "path": dirpath, "exists": exists})
        return j(handler, {"roots": roots})

    root_name = (qs.get("root") or [None])[0]

    if path == "/api/files/list":
        if not root_name:
            return bad(handler, "Missing ?root= parameter")
        try:
            root_path = _validate_root(root_name)
            rel = (qs.get("path") or [""])[0]
            target = safe_resolve(Path(root_path), rel)
            if not target.is_dir():
                return bad(handler, "Not a directory", status=400)
            entries = []
            for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                entries.append({
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size_bytes": entry.stat().st_size if entry.is_file() else None,
                })
            return j(handler, {
                "root": root_name,
                "path": str(target.relative_to(Path(root_path))),
                "entries": entries,
            })
        except ValueError as e:
            return bad(handler, str(e), status=400)
        except Exception as e:
            return bad(handler, "Failed to list directory: {}".format(e), status=500)

    if path == "/api/files/read":
        if not root_name:
            return bad(handler, "Missing ?root= parameter")
        try:
            root_path = _validate_root(root_name)
            rel = (qs.get("path") or [None])[0]
            if not rel:
                return bad(handler, "Missing ?path= parameter")
            target = safe_resolve(Path(root_path), rel)
            if not target.is_file():
                return bad(handler, "Not a file", status=400)
            if target.stat().st_size > MAX_READ_BYTES:
                return bad(handler, "File too large (max 1 MB)", status=413)
            ext = target.suffix.lower()
            is_text = ext in TEXT_EXTENSIONS or ext == ""
            content = target.read_text(encoding="utf-8", errors="replace") if is_text else None
            return j(handler, {
                "root": root_name,
                "path": str(target.relative_to(Path(root_path))),
                "name": target.name,
                "size_bytes": target.stat().st_size,
                "is_text": is_text,
                "content": content,
            })
        except ValueError as e:
            return bad(handler, str(e), status=400)
        except Exception as e:
            return bad(handler, "Failed to read file: {}".format(e), status=500)

    return False
