#!/usr/bin/env python3
"""Import JanitorAI characters into a local SillyTavern install.

Why this exists: SillyTavern's built-in "JanitorAI Character (Direct Link or UUID)"
importer calls https://api.jannyai.com/api/v1/download, which now sits behind a
Cloudflare bot challenge and returns 403 from any non-browser client. That path is
dead. jannyai.com (the JanitorAI mirror) still serves the full character definition
server-rendered in a collapsed <details> block, but it is Cloudflare-protected against
plain HTTP clients too, so a real browser is required to read it.

This script drives a browser (Browserbase cloud, or a local Chrome over CDP) to read
the definition, builds a Tavern V2 character card, and POSTs it into SillyTavern's
/api/characters/import endpoint, then applies the real avatar via /api/characters/edit-avatar.

Usage:
    janitorai-import.py <url-or-uuid> [<url-or-uuid> ...]
    janitorai-import.py --cdp http://127.0.0.1:9222 <url>
    janitorai-import.py --st http://127.0.0.1:8001 <url>

Exit codes: 0 all imported, 1 at least one failure, 2 bad usage.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid as uuidlib
from http.cookiejar import CookieJar

DEFAULT_ST = os.environ.get("SILLYTAVERN_URL", "http://127.0.0.1:8001")
JANNYAI_HOST = "https://jannyai.com"
UUID_RE = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", re.I)
DEFINITION_LABELS = ("Personality", "Scenario", "First Message", "Example Dialogs")

# Script injected into the loaded character page. Returns a JSON string so the
# caller can parse it without another round trip.
EXTRACT_JS = r"""
(async () => {
  const out = { ok: false, pairs: [], name: '', description: '', avatar: '', creator: '', reason: '' };
  const det = document.querySelector('details');
  if (!det) { out.reason = 'no definition block on page'; return JSON.stringify(out); }
  det.open = true;
  for (const li of det.querySelectorAll('li')) {
    const t = (li.innerText || '').trim();
    const i = t.indexOf(':');
    if (i > 0 && i < 30) out.pairs.push([t.slice(0, i).trim(), t.slice(i + 1).trim()]);
  }
  const h1 = document.querySelector('h1');
  out.name = h1 ? h1.innerText.trim() : '';
  const meta = document.querySelector('meta[name="description"]');
  out.description = meta ? meta.content : '';
  const img = [...document.querySelectorAll('img')].find(i => (i.src || '').includes('bot-avatars'));
  if (img) {
    out.avatar = img.src;
    try {
      const r = await fetch(img.src);
      const blob = await r.blob();
      const fr = new FileReader();
      out.avatarB64 = await new Promise(res => { fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
    } catch (e) { out.avatarErr = String(e); }
  }
  const m = document.body.innerText.match(/Creator:\s*(@[^\n]+)/);
  out.creator = m ? m[1].trim() : '';
  out.ok = out.pairs.length > 0;
  if (!out.ok) out.reason = 'definition block present but empty (creator may hide it)';
  return JSON.stringify(out);
})()
"""



def _load_env_file(path: str) -> None:
    """Populate os.environ from a KEY=VALUE file without overriding real env vars."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def normalize_target(raw: str) -> dict:
    """Accept a janitorai/jannyai URL, or a bare UUID. Returns {uuid, url}."""
    m = UUID_RE.search(raw)
    if not m:
        raise ValueError(f"no character UUID found in {raw!r}")
    char_uuid = m.group(0)
    slug = ""
    slug_match = re.search(r"_character-([^\s?#/]+)", raw)
    if slug_match:
        slug = slug_match.group(1)
    url = f"{JANNYAI_HOST}/characters/{char_uuid}"
    if slug:
        url += f"_character-{slug}"
    return {"uuid": char_uuid, "url": url}


def build_card(info: dict) -> dict:
    pairs = {k: v for k, v in info["pairs"]}
    name = (info.get("name") or "").strip() or f"JannyAI {info['uuid'][:8]}"
    notes = "Imported from JannyAI (JanitorAI mirror)"
    if info.get("creator"):
        notes += f" — creator {info['creator']}"
    data = {
        "name": name,
        "description": (info.get("description") or "").strip(),
        "personality": pairs.get("Personality", ""),
        "scenario": pairs.get("Scenario", ""),
        "first_mes": pairs.get("First Message", ""),
        "mes_example": pairs.get("Example Dialogs", ""),
        "creator_notes": notes,
        "system_prompt": "",
        "post_history_instructions": "",
        "alternate_greetings": [],
        "character_book": None,
        "tags": ["janitorai-import"],
        "creator": info.get("creator", ""),
        "character_version": "1.0",
        "extensions": {"jannyai_uuid": info["uuid"]},
    }
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "name": name,
        "description": data["description"],
        "personality": data["personality"],
        "scenario": data["scenario"],
        "first_mes": data["first_mes"],
        "mes_example": data["mes_example"],
        "creatorcomment": notes,
        "avatar": "none",
        "talkativeness": "0.5",
        "fav": False,
        "tags": ["janitorai-import"],
        "data": data,
    }


class SillyTavern:
    """Minimal SillyTavern client: CSRF token + session cookie, then import."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self.token = self._csrf()

    def _csrf(self) -> str:
        with self.opener.open(self.base + "/csrf-token", timeout=30) as r:
            return json.loads(r.read())["token"]

    def _request(self, path: str, data, ctype: str):
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        req.add_header("Content-Type", ctype)
        req.add_header("X-CSRF-Token", self.token)
        return self.opener.open(req, timeout=120)

    def alive(self) -> bool:
        try:
            with self.opener.open(self.base + "/", timeout=20) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def import_card(self, card: dict, card_path: str) -> str:
        raw = json.dumps(card, ensure_ascii=False).encode()
        body, ctype = _multipart(
            {"file_type": "json", "user_name": "Konan"},
            {"avatar": (os.path.basename(card_path), raw, "application/json")},
        )
        with self._request("/api/characters/import", body, ctype) as r:
            payload = json.loads(r.read())
        if payload.get("error") or not payload.get("file_name"):
            raise RuntimeError(f"import rejected: {payload}")
        return payload["file_name"]

    def set_avatar(self, avatar_url: str, image: bytes, filename: str) -> None:
        body, ctype = _multipart(
            {"avatar_url": avatar_url, "user_name": "Konan"},
            {"avatar": (filename, image, "image/jpeg")},
        )
        with self._request("/api/characters/edit-avatar", body, ctype) as r:
            if r.status != 200:
                raise RuntimeError(f"edit-avatar returned {r.status}")

    def find_character(self, name: str) -> dict | None:
        with self._request("/api/characters/all", body, "application/json") as r:
            chars = json.loads(r.read())
        return next((c for c in chars if c.get("name") == name), None)


def _multipart(fields: dict, files: dict):
    boundary = "----ST" + uuidlib.uuid4().hex
    buf = b""
    for k, v in fields.items():
        buf += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, (fn, data, ctype) in files.items():
        buf += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
            f"filename=\"{fn}\"\r\nContent-Type: {ctype}\r\n\r\n"
        ).encode() + data + b"\r\n"
    buf += f"--{boundary}--\r\n".encode()
    return buf, f"multipart/form-data; boundary={boundary}"


def browserbase_page(url: str, timeout_ms: int = 90000) -> str:
    """Open `url` in a Browserbase cloud browser and return the extracted JSON.

    Browserbase is used because jannyai.com's Cloudflare bot challenge rejects both
    plain HTTP clients and locally-run headless/headed Chrome.
    """
    _load_env_file(os.path.expanduser("~/.hermes/.env"))
    api_key = os.environ.get("BROWSERBASE_API_KEY", "")
    project = os.environ.get("BROWSERBASE_PROJECT_ID", "")
    if not api_key or not project:
        raise RuntimeError(
            "BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID not set. "
            "Pass --cdp to drive a local browser instead."
        )
    from playwright.sync_api import sync_playwright

    req = urllib.request.Request(
        "https://api.browserbase.com/v1/sessions",
        data=json.dumps({"projectId": project}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-BB-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=60) as r:
        session = json.loads(r.read())

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(session["connectUrl"], timeout=timeout_ms)
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            for _ in range(14):
                page.wait_for_timeout(2000)
                if "just a moment" not in page.title().lower():
                    break
            page.wait_for_selector("details", timeout=timeout_ms)
            return page.evaluate(EXTRACT_JS)
        finally:
            browser.close()


def cdp_page(url: str, cdp_url: str, timeout_ms: int = 90000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=timeout_ms)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        for _ in range(14):
            page.wait_for_timeout(2000)
            if "just a moment" not in page.title().lower():
                break
        page.wait_for_selector("details", timeout=timeout_ms)
        return page.evaluate(EXTRACT_JS)


def import_one(target: str, st: SillyTavern, fetcher, outdir: str) -> dict:
    info = normalize_target(target)
    raw = fetcher(info["url"])
    if isinstance(raw, str):
        raw = json.loads(raw)
    info.update(raw)
    if not info.get("ok"):
        return {"uuid": info["uuid"], "status": "skipped", "reason": info.get("reason", "unknown")}

    card = build_card(info)
    card_path = os.path.join(outdir, f"{card['name'].replace('/', '_')}.card.json")
    with open(card_path, "w", encoding="utf-8") as fh:
        json.dump(card, fh, indent=2, ensure_ascii=False)
    json.load(open(card_path, encoding="utf-8"))  # validate before upload

    file_name = st.import_card(card, card_path)
    result = {"uuid": info["uuid"], "name": card["name"], "status": "imported", "card": card_path}

    b64 = info.get("avatarB64")
    if b64 and b64.startswith("data:"):
        image = base64.b64decode(b64.split(",", 1)[1])
        ext = "png" if "png" in b64[:40] else "jpg"
        st.set_avatar(file_name + ".png", image, f"{file_name}.{ext}")
        result["avatar"] = f"{len(image)} bytes"
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Import JanitorAI characters into SillyTavern.")
    ap.add_argument("targets", nargs="+", help="JanitorAI/JannyAI character URL or UUID")
    ap.add_argument("--st", default=DEFAULT_ST, help=f"SillyTavern base URL (default {DEFAULT_ST})")
    ap.add_argument("--cdp", default="", help="Drive a local Chrome over CDP at this URL instead of Browserbase")
    ap.add_argument("--outdir", default="/tmp", help="Where to write .card.json files (default /tmp)")
    args = ap.parse_args(argv)

    st = SillyTavern(args.st)
    if not st.alive():
        print(f"SillyTavern is not responding at {args.st}", file=sys.stderr)
        return 2

    if args.cdp:
        def fetcher(url):
            return cdp_page(url, args.cdp)
    else:
        def fetcher(url):
            return browserbase_page(url)

    failures = 0
    for target in args.targets:
        try:
            res = import_one(target, st, fetcher, args.outdir)
        except Exception as exc:  # noqa: BLE001 — one bad character must not stop the batch
            failures += 1
            print(json.dumps({"target": target, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
            continue
        print(json.dumps(res, ensure_ascii=False))
        if res.get("status") != "imported":
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
