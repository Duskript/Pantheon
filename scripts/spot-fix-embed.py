#!/usr/bin/env python3
"""Spot-fix: embed only files missing from ChromaDB."""
import json, logging, os, sys, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("spot-fix")

R = os.path.expanduser("~konan")
ATH = Path(f"{R}/athenaeum")
CHR = f"{R}/.hermes/pantheon/chroma"
CODEXES = ["Codex-Forge","Codex-Pantheon","Codex-Infrastructure","Codex-SKC","Codex-Fiction","Codex-Asclepius","Codex-General","Codex-Claude","Codex-User","Codex-Work","Codex-Apollo","Codex-God-Apollo","Codex-God-Hephaestus"]
EXTS = {".md",".txt",".json",".yaml",".yml"}
EM = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
EU = "https://openrouter.ai/api/v1/embeddings"
CS, MC = 256, 20

ef = Path(f"{R}/.hermes/.env")
if ef.exists():
    for line in ef.read_text().split("\n"):
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
KEY = os.environ.get("OPENROUTER_API_KEY", "")

def get_embedded_set():
    import chromadb
    c = chromadb.PersistentClient(path=CHR)
    s = set()
    for col in c.list_collections():
        if col.count() == 0: continue
        r = col.get(include=["metadatas"])
        if r and r.get("metadatas"):
            for m in r["metadatas"]:
                if m and "source" in m: s.add(m["source"])
    return s

def get_files():
    f = []
    for cn in CODEXES:
        d = ATH / cn
        if not d.exists(): continue
        for p in d.rglob("*"):
            if not p.is_file(): continue
            if p.suffix.lower() not in EXTS: continue
            rel = p.relative_to(ATH)
            parts = rel.parts
            if "archive" in parts or "distilled" in parts or "sessions" in parts: continue
            f.append((cn, str(p)))
    return f

def embed(text):
    if not KEY: return None
    import requests
    try:
        r = requests.post(EU, headers={"Authorization": f"Bearer {KEY}", "Content-Type":"application/json"}, json={"model":EM,"input":text}, timeout=30)
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]
    except Exception as e:
        logger.warning("embed fail: %s", e)
        return None

def chunk(text):
    w = text.split()
    c, cur, cc = [], [], 0
    for x in w:
        if cc + len(x) + 1 > CS and cur:
            c.append(" ".join(cur)); cur, cc = [], 0
        cur.append(x); cc += len(x) + 1
    if cur: c.append(" ".join(cur))
    return c[:MC]

def avg_vec(vv):
    if not vv: return None
    if len(vv) == 1: return vv[0]
    d = len(vv[0])
    a = [0.0]*d
    for v in vv:
        for i in range(d): a[i] += v[i]
    return [x/len(vv) for x in a]

def main():
    if not KEY: logger.error("No key"); sys.exit(1)
    logger.info("Scanning...")
    emb = get_embedded_set()
    logger.info("  %d embedded paths", len(emb))
    af = get_files()
    logger.info("  %d files on disk", len(af))
    miss = [(c, p, os.path.getsize(p)) for c, p in af if p not in emb]
    logger.info("  %d missing", len(miss))
    if not miss: logger.info("Gap closed!"); return
    bc = {}
    for c, p, s in miss: bc.setdefault(c, []).append(p)
    for c, fs in sorted(bc.items()):
        logger.info("  %s: %d files", c, len(fs))
    import chromadb
    cli = chromadb.PersistentClient(path=CHR)
    ok, fail = 0, 0
    for cn, ap, sz in miss:
        logger.info("[%d/%d] %s...", ok+fail+1, len(miss), ap)
        try:
            txt = Path(ap).read_text()
            if not txt.strip(): continue
            chunks = chunk(txt)
            vv = []
            for ck in chunks:
                v = embed(ck)
                if v: vv.append(v)
            if not vv: fail += 1; continue
            av = avg_vec(vv)
            if not av: fail += 1; continue
            sn = cn.lower().replace("-","_")
            cn2 = f"pantheon_{sn}"
            try: col = cli.get_collection(name=cn2)
            except: col = cli.create_collection(name=cn2, metadata={"hnsw:space":"cosine"})
            rp = str(Path(ap).relative_to(ATH))
            col.add(embeddings=[av], ids=[f"{sn}:{rp}"], metadatas=[{"source":ap,"codex":cn,"filename":Path(ap).name}])
            ok += 1
            time.sleep(0.2)
        except Exception as e:
            logger.warning("Fail: %s", e)
            fail += 1
    logger.info("Done! OK=%d Fail=%d", ok, fail)

if __name__ == "__main__":
    main()
