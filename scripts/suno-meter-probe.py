#!/usr/bin/env python3
"""Suno download-meter probe. Prints verdicts only — never key material or tokens."""
import json, os, sys, base64, urllib.request, urllib.error

BASE = "https://studio-api-prod.suno.com/api"
CLIP = os.environ.get("SUNO_CLIP") or "c676197b-dd48-45da-8409-ae0ffeb4f21d"
COOKIE = os.environ.get("SUNO_COOKIE", "").strip()

def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("Origin", "https://suno.com")
    r.add_header("Referer", "https://suno.com/")
    r.add_header("User-Agent", "Mozilla/5.0 (Linux; Android 14) SunoLocalPlayer/1.94.0")
    if COOKIE:
        r.add_header("Cookie", COOKIE)
        m = [c.strip() for c in COOKIE.split(";") if c.strip().startswith("__session=")]
        if m:
            r.add_header("Authorization", "Bearer " + m[0].split("=", 1)[1])
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, f"<{type(e).__name__}: {e}>"

def verdict(label, status, body, secret_fields=()):
    try: j = json.loads(body)
    except Exception: j = None
    safe = {}
    if isinstance(j, dict):
        for k, v in j.items():
            if k in secret_fields:
                if isinstance(v, str):
                    nb = len(base64.b64decode(v + "=" * (-len(v) % 4))) if v else 0
                    safe[k] = f"<redacted len={len(v)}chars/{nb}bytes>"
                else: safe[k] = "<redacted>"
            else: safe[k] = v
    print(f"\n[{label}] HTTP {status}")
    print("  fields:", json.dumps(safe)[:300] if safe is not None else body[:200])
    return status, j

print(f"authenticated: {'yes' if COOKIE else 'NO (expect 401s)'}")

s, b = req("POST", "/download/authorize", {"clip_id": CLIP, "item_type": "clip", "surface": "clip"})
verdict("A. download/authorize", s, b)

s, b = req("GET", f"/download/clip/{CLIP}?format=m4a")
verdict("B. download/clip (no prior authorize)", s, b)

s, b = req("POST", "/mango/rights", {"content_params": {"content_id": CLIP, "content_type": "clip"}, "version": "1.0.0"})
st, j = verdict("C. mango/rights", s, b, secret_fields=("key", "iv", "glt"))
if isinstance(j, dict):
    ok = True
    for f in ("key", "iv"):
        v = j.get(f) or ""
        try: nb = len(base64.b64decode(v + "=" * (-len(v) % 4)))
        except Exception: nb = -1
        real = (nb == 16)
        ok = ok and real
        print(f"    {f}: {nb} bytes -> {'REAL 16-byte AES material' if real else 'NOT 16 bytes => decoy/dummy payload'}")
    print(f"\n  VERDICT C: {'real per-track key+iv' if ok else 'decoy response — request is not being honoured'}")
