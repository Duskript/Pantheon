#!/usr/bin/env python3
"""Fetch Suno aligned (timed) lyrics and write LRC + word-timing JSON.

Endpoint (requires an authenticated Suno session):
    GET /api/gen/<clip_id>/aligned_lyrics/v2
    -> { aligned_words: [ {word, start_s, end_s, p_align, success}, ... ],
         is_streamed: bool, waveform_data: ... }

Outputs per track:
    <out>/audio/<id>.lrc          line-level LRC (works in every player)
    <out>/audio/<id>.words.json   raw word timings (karaoke apps / re-sync)
    plus hardlinks inside every playlist folder that contains the track.

Word timing is converted to lines by pausing on gaps / punctuation / length.
An enhanced-LRC variant with per-word <mm:ss.xx> tags is written as <id>.enh.lrc.

Usage:
    suno-lyrics.py --cookie-db /path/Cookies            # chromium cookie sqlite
    suno-lyrics.py --cookie-file /sdcard/sunocookie.txt # netscape cookies.txt
    SUNO_COOKIE='__session=...; __client=...' suno-lyrics.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://studio-api-prod.suno.com/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
GAP_LINE = 0.65      # seconds of silence that starts a new line
PAUSE_PUNCT = 0.28   # pause after . ! ? , ; : needed to break a line
MAX_LINE = 68        # characters before forcing a wrap

_lock = threading.Lock()


def log(m: str) -> None:
    with _lock:
        print(m, flush=True)


def ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"


def load_cookie(args) -> str:
    if args.cookie:
        return args.cookie
    if os.environ.get("SUNO_COOKIE"):
        return os.environ["SUNO_COOKIE"]
    if args.cookie_db:
        con = sqlite3.connect(f"file:{args.cookie_db}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("select name,value from cookies where host_key like '%suno%' and value!=''")
        return "; ".join(f"{n}={v}" for n, v in cur.fetchall())
    if args.cookie_file:
        out = []
        for line in open(args.cookie_file, encoding="utf-8", errors="replace"):
            f = line.strip().split("\t")
            if len(f) >= 7 and not line.startswith("#"):
                out.append(f"{f[5]}={f[6]}")
        return "; ".join(out)
    raise SystemExit("need --cookie-db / --cookie-file / SUNO_COOKIE")


def get(clip: str, cookie: str) -> tuple[int, bytes]:
    for n in range(4):
        req = urllib.request.Request(f"{API}/gen/{clip}/aligned_lyrics/v2")
        req.add_header("Cookie", cookie)
        req.add_header("Origin", "https://suno.com")
        req.add_header("Referer", "https://suno.com/")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", UA)
        m = re.search(r"(?:^|;\s*)__session=([^;]+)", cookie)
        if m:
            req.add_header("Authorization", "Bearer " + m.group(1))
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (n + 1))
                continue
            return e.code, body
        except Exception:
            time.sleep(1.5 * (n + 1))
    return -1, b""


def group_lines(words: list[dict]) -> list[tuple[float, list[dict]]]:
    lines: list[tuple[float, list[dict]]] = []
    cur: list[dict] = []
    for w in words:
        text = (w.get("word") or "")
        if not text:
            continue
        if not cur:
            cur = [w]
            continue
        prev = cur[-1]
        gap = float(w.get("start_s") or 0) - float(prev.get("end_s") or prev.get("start_s") or 0)
        joined = "".join(x.get("word") or "" for x in cur)
        punct = joined.rstrip()[-1:] in ".!?,;:"
        if gap > GAP_LINE or (punct and gap > PAUSE_PUNCT) or len(joined) > MAX_LINE:
            lines.append((float(cur[0].get("start_s") or 0), cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append((float(cur[0].get("start_s") or 0), cur))
    return lines


def build_lrc(words: list[dict]) -> tuple[str, str]:
    lines = group_lines(words)
    plain = ["[ar:]", "[re:Suno]", ""]
    enh = list(plain)
    for start, toks in lines:
        body = "".join(t.get("word") or "" for t in toks).strip()
        if not body:
            continue
        plain.append(f"[{ts(start)}]{body}")
        words_tagged = "".join(
            f"<{ts(float(t.get('start_s') or 0))}>{(t.get('word') or '')}" for t in toks
        )
        enh.append(f"[{ts(start)}]{words_tagged.strip()}")
    return "\n".join(plain) + "\n", "\n".join(enh) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="/home/konan/.hermes/cache/scratch/p9_lib.json")
    ap.add_argument("--out", default=os.path.expanduser("~/Music/Suno"))
    ap.add_argument("--cookie")
    ap.add_argument("--cookie-db")
    ap.add_argument("--cookie-file")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cookie = load_cookie(args)
    lib = json.load(open(args.lib))
    adir = os.path.join(args.out, "audio")
    os.makedirs(adir, exist_ok=True)

    uniq: dict[str, dict] = {}
    for pl in lib:
        for t in pl.get("tracks") or []:
            uniq.setdefault(t["id"], t)
    ids = [c for c in uniq if args.force or not os.path.exists(os.path.join(adir, c + ".lrc"))]
    ids = ids[: args.limit or None]
    log(f"tracks={len(uniq)}  to fetch={len(ids)}  workers={args.workers}")

    stats = {"ok": 0, "none": 0, "fail": 0}
    fails: list[tuple[str, str]] = []

    def work(cid: str):
        st, body = get(cid, cookie)
        if st != 200:
            return cid, "fail", f"HTTP {st}"
        try:
            j = json.loads(body)
        except Exception:
            return cid, "fail", "bad json"
        words = [w for w in (j.get("aligned_words") or []) if (w.get("word") or "").strip()]
        if not words:
            return cid, "none", "no aligned words"
        lrc, enh = build_lrc(words)
        with open(os.path.join(adir, cid + ".lrc"), "w", encoding="utf-8") as f:
            f.write(lrc)
        with open(os.path.join(adir, cid + ".enh.lrc"), "w", encoding="utf-8") as f:
            f.write(enh)
        with open(os.path.join(adir, cid + ".words.json"), "w", encoding="utf-8") as f:
            json.dump({"words": words, "is_streamed": j.get("is_streamed")}, f)
        return cid, "ok", f"{len(words)} words / {lrc.count(chr(10)) - 3} lines"

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, c): c for c in ids}
        for i, fut in enumerate(as_completed(futs), 1):
            cid, status, detail = fut.result()
            stats[status] = stats.get(status, 0) + 1
            if status == "fail":
                fails.append((cid, detail))
            if status != "ok" or i % 25 == 0:
                log(f"[{i}/{len(ids)}] {status:4s} {detail:28s} {uniq[cid].get('title','')[:44]}")

    # relink sidecars into playlist folders
    for pl in lib:
        pdir = os.path.join(args.out, re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", pl.get("title") or pl["id"][:8]))
        if not os.path.isdir(pdir):
            continue
        for n, t in enumerate(pl.get("tracks") or [], 1):
            base = f"{n:02d} - " + re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (t.get("title") or t["id"][:8]))[:120]
            for ext in (".lrc", ".enh.lrc", ".words.json"):
                src = os.path.join(adir, t["id"] + ext)
                dst = os.path.join(pdir, base + ext)
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        os.link(src, dst)
                    except OSError:
                        with open(src, "rb") as fi, open(dst, "wb") as fo:
                            fo.write(fi.read())

    log(f"DONE ok={stats['ok']} none={stats.get('none',0)} fail={stats['fail']}")
    for cid, d in fails[:15]:
        log(f"  FAIL {cid} {d}")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
