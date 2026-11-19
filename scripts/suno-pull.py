#!/usr/bin/env python3
"""Suno library puller.

Audio path (no auth, no download credits):
  1. POST /api/mango/rights {content_id, content_type:"clip", version:"1.0.0"} -> {key, iv, glt}
  2. GCM key = SHA-256(glt)
  3. unwrap key/iv: AES-GCM, nonce = blob[:12], aad = content_id  -> 16-byte AES-CTR material
  4. GET https://d2lwuy8qc234o3.cloudfront.net/1/clip/<id>.m4a   (public, unmetered)
  5. AES-CTR decrypt -> full master

Aligned (timed) lyrics need an authenticated session:
  GET /api/gen/<clip_id>/aligned_lyrics/v2 -> {aligned_words:[...], is_streamed, waveform_data}
  Run with --cookie-file and a fresh __session to produce .lrc.

Layout:
  <out>/audio/<id>.m4a        unique audio (downloaded once)
  <out>/audio/<id>.jpg        cover art
  <out>/audio/<id>.txt        plain lyrics
  <out>/audio/<id>.lrc        timed lyrics (later phase)
  <out>/<playlist>/NN - Title.m4a   hardlink to audio
  <out>/<playlist>/NN - Title.lrc|.txt
  <out>/<playlist>/playlist.m3u
  <out>/manifest.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API = "https://studio-api-prod.suno.com/api"
CDN = "https://d2lwuy8qc234o3.cloudfront.net/1/clip"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def http(url: str, body: dict | None = None, cookie: str | None = None,
         attempts: int = 5) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    last = (-1, b"")
    for n in range(attempts):
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", "https://suno.com")
        req.add_header("Referer", "https://suno.com/")
        req.add_header("User-Agent", UA)
        if cookie:
            req.add_header("Cookie", cookie)
            m = re.search(r"(?:^|;\s*)__session=([^;]+)", cookie)
            if m:
                req.add_header("Authorization", "Bearer " + m.group(1))
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            last = (e.code, e.read())
            if e.code in (429, 500, 502, 503, 504) or e.code == 403:
                time.sleep(1.5 * (n + 1))
                continue
            return last
        except Exception:
            last = (-1, b"")
            time.sleep(1.5 * (n + 1))
    return last


def unwrap(clip: str) -> tuple[bytes, bytes]:
    st, body = http(f"{API}/mango/rights",
                    {"content_params": {"content_id": clip, "content_type": "clip"},
                     "version": "1.0.0"})
    if st != 200:
        raise RuntimeError(f"rights HTTP {st}: {body[:120]!r}")
    j = json.loads(body)
    gcm = AESGCM(hashlib.sha256(j["glt"].encode()).digest())
    aad = clip.encode()
    kb, ib = base64.b64decode(j["key"]), base64.b64decode(j["iv"])
    return gcm.decrypt(kb[:12], kb[12:], aad), gcm.decrypt(ib[:12], ib[12:], aad)


def fetch_track(clip: str, outdir: str) -> str:
    dst = os.path.join(outdir, f"{clip}.m4a")
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        with open(dst, "rb") as f:
            if b"ftyp" in f.read(64):
                return "skip"
    key, iv = unwrap(clip)
    st, enc = http(f"{CDN}/{clip}.m4a")
    if st != 200:
        raise RuntimeError(f"cdn HTTP {st}")
    dec = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    plain = dec.update(enc) + dec.finalize()
    if b"ftyp" not in plain[:64]:
        raise RuntimeError("decrypt produced no ftyp")
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(plain)
    os.replace(tmp, dst)
    return f"ok {len(plain)/1e6:.1f}MB"


def fetch_cover(url: str, dst: str) -> None:
    if not url or os.path.exists(dst):
        return
    st, data = http(url)
    if st == 200 and data:
        with open(dst + ".part", "wb") as f:
            f.write(data)
        os.replace(dst + ".part", dst)


def safe(name: str, fallback: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:120] or fallback)


def lrc_from_aligned(payload: dict) -> str:
    """NetworkLyricChunk list -> LRC. Handles a few plausible key spellings."""
    out = []
    for ch in payload.get("aligned_words") or []:
        start = ch.get("start_s", ch.get("start_ms", ch.get("start")))
        end = ch.get("end_s", ch.get("end_ms", ch.get("end")))
        text = ch.get("word") or ch.get("text") or ch.get("chunk") or ""
        if start is None or not text:
            continue
        if isinstance(start, float) and start < 1000 and "start_ms" not in ch and "start_s" not in ch:
            start = start
        ms = int(float(start) * 1000) if float(start) < 100000 else int(float(start))
        m, s = divmod(ms // 1000, 60)
        out.append(f"[{m:02d}:{s:02d}.{ms % 1000:03d}]{text}  "
                   + ("" if end is None else ""))
    return "\n".join(out) + "\n" if out else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="/home/konan/.hermes/cache/scratch/p9_lib.json")
    ap.add_argument("--out", default=os.path.expanduser("~/Music/Suno"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--lyrics-only", action="store_true")
    args = ap.parse_args()

    lib = json.load(open(args.lib))
    adir = os.path.join(args.out, "audio")
    os.makedirs(adir, exist_ok=True)

    # index unique tracks (first occurrence wins for metadata)
    uniq: dict[str, dict] = {}
    for pl in lib:
        for t in pl.get("tracks") or []:
            uniq.setdefault(t["id"], t)
    ids = list(uniq)[: args.limit or None]
    log(f"unique tracks: {len(uniq)}  processing: {len(ids)}  workers={args.workers}")

    stats = {"ok": 0, "skip": 0, "fail": 0}
    failures: list[tuple[str, str]] = []

    def work(cid: str) -> tuple[str, str, str]:
        try:
            return cid, "ok", fetch_track(cid, adir)
        except Exception as e:  # noqa: BLE001 - report, never abort the batch
            return cid, "fail", f"{type(e).__name__}: {e}"

    if not args.lyrics_only:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, cid): cid for cid in ids}
            for i, fut in enumerate(as_completed(futs), 1):
                cid, status, detail = fut.result()
                if status == "ok":
                    stats["ok" if "skip" not in detail else "skip"] += 1
                else:
                    stats["fail"] += 1
                    failures.append((cid, detail))
                if status != "ok" or i % 25 == 0 or i == len(ids):
                    t = uniq[cid]
                    log(f"[{i}/{len(ids)}] {status:4s} {detail:22s} {t.get('title','')[:52]}")

    # covers + plain lyrics + manifest
    for cid, t in uniq.items():
        if cid not in ids:
            continue
        fetch_cover(t.get("image_url") or "", os.path.join(adir, f"{cid}.jpg"))
        txt = os.path.join(adir, f"{cid}.txt")
        if not os.path.exists(txt) and (t.get("lyrics") or "").strip():
            with open(txt, "w", encoding="utf-8") as f:
                f.write(t["lyrics"])

    # playlist folders with hardlinks (fall back to copy across filesystems)
    for pl in lib:
        pdir = os.path.join(args.out, safe(pl.get("title"), pl["id"][:8]))
        os.makedirs(pdir, exist_ok=True)
        m3u = ["#EXTM3U"]
        for n, t in enumerate(pl.get("tracks") or [], 1):
            src = os.path.join(adir, f"{t['id']}.m4a")
            if not os.path.exists(src):
                continue
            base = f"{n:02d} - {safe(t.get('title'), t['id'][:8])}"
            link = os.path.join(pdir, base + ".m4a")
            if not os.path.exists(link):
                try:
                    os.link(src, link)
                except OSError:
                    with open(src, "rb") as fi, open(link, "wb") as fo:
                        fo.write(fi.read())
            for ext in (".txt", ".lrc"):
                s2 = os.path.join(adir, t["id"] + ext)
                if os.path.exists(s2):
                    d2 = os.path.join(pdir, base + ext)
                    if not os.path.exists(d2):
                        try:
                            os.link(s2, d2)
                        except OSError:
                            with open(s2, "rb") as fi, open(d2, "wb") as fo:
                                fo.write(fi.read())
            dur = int((t.get("duration_ms") or 0) / 1000)
            m3u.append(f"#EXTINF:{dur},{t.get('title','')}")
            m3u.append(os.path.basename(link))
        with open(os.path.join(pdir, "playlist.m3u"), "w", encoding="utf-8") as f:
            f.write("\n".join(m3u) + "\n")

    manifest = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tracks": len(uniq), "stats": stats,
                "failures": failures,
                "playlists": [{"title": p.get("title"), "id": p["id"],
                               "tracks": len(p.get("tracks") or [])} for p in lib]}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    log(f"\nDONE ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}")
    for cid, d in failures[:20]:
        log(f"  FAIL {cid} {d}")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
