#!/usr/bin/env python3
"""
hf_model_review.py — score HuggingFace candidates the way ODS does, then fix
the gaps that make ODS's answer wrong for a speed-sensitive box.

ODS's shipped policy (`context-aware-largest-capable-general-v1`, see
~/ods/scripts/select-model.py) works like this:

  capacity   = vram_mb / 1024                        (12.0 GB on the 3060)
  required   = max(declared vram_required_gb,
                   size_gb + clamp(params_b * 0.12, 0.35, 3.5) * ctx/32768)
  fits       = required <= capacity + 0.25 GB
  filters    = install_recommendation + gguf_url, family profile match,
               tier size ceiling (LLM_MODEL_SIZE_MB from installers/lib/tier-map.sh),
               runtime_profile match, then fits
  score      = specialty_weight      # Code 4.4, Quality 4.1, General 3.8,
                                     # Balanced 3.5, Reasoning 3.3, Fast 2.0, Bootstrap 1.0
               + family_bonus        # +0.25 qwen/auto profile, +0.35 gemma4 profile
               + min(ctx/32768, 4) * 0.18
               + min(size_mb/1024, 48) * 0.24      # "largest capable" bias
               - headroom_penalty    # -0.35 if fill > 98%, -0.15 if > 92%
  tiebreak   = score, then required memory, then context

Three things ODS does NOT model, which we add because Konan's requirement is
">=160K context and >=55 tok/s for agentic work":
  1. THROUGHPUT - ODS never scores tokens_per_sec (it is catalog metadata only).
     Decode is memory-bandwidth bound, so we estimate it from bytes touched per
     token against the 3060's measured practical bandwidth (299 GB/s, calibrated
     from our own 5.93 GB model doing 50.4 t/s). MoE models touch only their
     active parameters, so we scale by active_params_b / total_params_b.
  2. ARCHITECTURE-AWARE KV - ODS estimates KV as params * 0.12 per 32K, which
     ignores hybrid attention. We read the real config.json and compute
     KV/token = 2 * dtype_bytes * full_attn_layers * kv_heads * head_dim,
     counting only layers that actually carry a cache.
  3. QUALITY PROVENANCE - we tag vendor-card claims vs measured-third-party so
     an upgrade is never justified by marketing copy alone.
"""
import json, math, urllib.request, urllib.error

EFFECTIVE_BW_GBPS = 299.0   # calibrated on this 3060 (5.93 GB model @ 50.4 t/s)
COMPUTE_OVERHEAD_GB = 0.9   # CUDA context + compute buffers
CAPACITY_GB = 12.0
FIT_TOLERANCE_GB = 0.25
TARGET_CTX = 163840         # Konan's 160K requirement
SPECIALTY = {"Code": 4.4, "Quality": 4.1, "General": 3.8, "Balanced": 3.5,
             "Reasoning": 3.3, "Fast": 2.0, "Bootstrap": 1.0}

def hf_json(path):
    req = urllib.request.Request("https://huggingface.co/api/" + path, headers={"User-Agent": "hermes-review"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def hf_raw(repo, filename="config.json"):
    url = f"https://huggingface.co/{repo}/raw/main/{filename}"
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-review"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def gguf_size(repo, pattern):
    d = hf_json(f"models/{repo}?blobs=true")
    best = None
    for s in d.get("siblings", []):
        n = s["rfilename"]
        if n.endswith(".gguf") and pattern.lower() in n.lower() and "mmproj" not in n.lower():
            best = (n, (s.get("size") or 0) / 1e9)
    return best

def kv_per_token_gb(cfg):
    """Exact KV bytes/token from the real attention config (hybrid-aware)."""
    tc = cfg.get("text_config", cfg)
    layers = tc.get("num_hidden_layers") or tc.get("n_layer")
    kv_heads = tc.get("num_key_value_heads") or tc.get("n_head_kv")
    head_dim = tc.get("head_dim")
    if not head_dim and tc.get("hidden_size") and tc.get("num_attention_heads"):
        head_dim = tc["hidden_size"] // tc["num_attention_heads"]
    lt = tc.get("layer_types")
    if isinstance(lt, list):
        full = sum(1 for x in lt if "full" in str(x).lower())
    elif tc.get("full_attention_interval"):
        full = math.ceil(tc["num_hidden_layers"] / tc["full_attention_interval"])
    else:
        full = layers  # dense full attention
    if not all([layers, kv_heads, head_dim, full]):
        return None, None
    # q8_0 KV = 1.0625 bytes/elem (llama.cpp block quant), we deploy q8_0
    per_tok = 2 * 1.0625 * full * kv_heads * head_dim / 1e9
    return per_tok, full

CANDIDATES = [
    # label, gguf repo, quant pattern, config repo (base model for architecture), family, specialty, active_b, quality note
    ("Ornith-1.5-9B (CURRENT)", "AtomicChat/Ornith-1.5-9B-GGUF", "AD-Q5_K-Q4_K", "ornith-ai/Ornith-1.5-9B", "ornith", "Code", 9.0,
     "SWE-bench V 70.6 / TB2.1 46.2 (VENDOR); independently disputed"),
    ("Qwen3.8-9B-Distill", "empero-ai/Qwen3.8-9B-Distill-GGUF", "Q4_K_M", "ornith-ai/Ornith-1.5-9B", "qwen", "Reasoning", 9.0,
     "MMLU-CoT 0.751 vs 0.546 base (VENDOR, unverified)"),
    ("Qwen3.5-9B (ODS pick)", "unsloth/Qwen3.5-9B-GGUF", "Q4_K_M", "Qwen/Qwen3.5-9B", "qwen", "General", 9.0,
     "BFCL-v4 66.1 / TAU2 79.1 (vendor); 45 t/s median measured 3060"),
    ("gemma-4-12B-it", "unsloth/gemma-4-12b-it-GGUF", "Q4_K_M", "google/gemma-4-12B-it", "gemma4", "Quality", 12.0,
     "Tau2 conflict: vendor 69.0 vs AA 36.3 vs community ~15"),
    ("granite-4.2-8b", "ibm-granite/granite-4.2-8b-GGUF", "Q4_K_M", "ibm-granite/granite-4.2-8b", "granite", "Balanced", 8.0,
     "SWE-V 47.67 / tau3 66.34 (vendor)"),
    ("Ornith-1.5-35B-A3B (MoE, IQ2)", "cognitivers/Ornith-1.5-35B-A3B-Abliterated-12GB-GGUF", "IQ2_XXS", "ornith-ai/Ornith-1.5-35B-A3B", "ornith", "Quality", 3.0,
     "HellaSwag 71.75 (-9.0 vs Q8, vendor)"),
    ("Qwen3.8-4B-Distill (speed)", "empero-ai/Qwen3.8-4B-Distill-GGUF", "Q4_K_M", "ornith-ai/Ornith-1.5-9B", "qwen", "Fast", 4.0,
     "no published agentic numbers"),
    ("Qwen3.5-4B (speed)", "unsloth/Qwen3.5-4B-GGUF", "Q4_K_M", "Qwen/Qwen3.5-4B", "qwen", "Fast", 4.0,
     "BFCL-v4 50.3 / TAU2 79.9 (vendor)"),
]

rows = []
for label, repo, pat, cfg_repo, family, specialty, active_b, quality in CANDIDATES:
    row = {"candidate": label, "repo": repo, "family": family, "specialty": specialty, "quality": quality}
    try:
        got = gguf_size(repo, pat)
        row["gguf"] = got[0] if got else "NOT FOUND"
        row["size_gb"] = round(got[1], 2) if got else None
    except Exception as e:
        row["size_gb"] = None; row["error"] = f"size:{type(e).__name__}"
    per_tok = full = None
    try:
        cfg = hf_raw(cfg_repo)
        per_tok, full = kv_per_token_gb(cfg)
        tc = cfg.get("text_config", cfg)
        row["layers"] = tc.get("num_hidden_layers")
        row["full_attn_layers"] = full
    except Exception as e:
        row["cfg_error"] = f"{type(e).__name__}"
    if row.get("size_gb") and per_tok:
        row["kv_160k_gb"] = round(per_tok * TARGET_CTX, 2)
        row["required_gb"] = round(row["size_gb"] + row["kv_160k_gb"] + COMPUTE_OVERHEAD_GB, 2)
        row["fits_12gb_160k"] = row["required_gb"] <= CAPACITY_GB + FIT_TOLERANCE_GB
        # ODS score, using ITS KV estimate so the comparison to its own answer is honest
        ods_kv = min(max(active_b * 0.12, 0.35), 3.5) * (TARGET_CTX / 32768.0)
        row["ods_est_kv_gb"] = round(ods_kv, 2)
        row["ods_required_gb"] = round(max(row["size_gb"] + ods_kv, row["size_gb"]), 2)
        row["ods_fits"] = row["ods_required_gb"] <= CAPACITY_GB + FIT_TOLERANCE_GB
        ctx = 262144 if "Ornith" in label or "Qwen3.5-9B" in label else 131072
        s = SPECIALTY.get(specialty, 2.5)
        s += 0.25 if family in ("qwen", "ornith") else (0.35 if family == "gemma4" else 0)
        s += min(ctx / 32768, 4.0) * 0.18
        s += min(row["size_gb"] * 1024 / 1024, 48.0) * 0.24
        fill = row["required_gb"] / CAPACITY_GB
        s -= 0.35 if fill > 0.98 else (0.15 if fill > 0.92 else 0.0)
        row["ods_score"] = round(s, 2)
        # Throughput lane: decode is memory-bandwidth bound. A dense model reads
        # essentially all of its weights per token; a MoE reads only the active
        # experts, so scale by active/total - floored at 0.6 GB because attention
        # and shared weights still have to be read every token.
        if "A3B" in label:
            total_b = max(float(active_b) * 11.5, 1.0)   # ~34.7B for a 3B-active A3B
            ratio = max(min(float(active_b) / total_b, 1.0), 0.10)
            bytes_per_tok = max(row["size_gb"] * ratio, 0.60)
        else:
            bytes_per_tok = row["size_gb"]
        row["bytes_per_token_gb"] = round(bytes_per_tok, 2)
        row["est_decode_tps"] = round(EFFECTIVE_BW_GBPS / bytes_per_tok, 1)
    rows.append(row)

print("=" * 100)
print("HF MODEL REVIEW — ODS rules + throughput/KV/quality lanes | target: 12GB VRAM, 160K ctx, agentic")
print("=" * 100)
hdr = f"{'candidate':28s} {'size':>6s} {'full':>5s} {'KV@160K':>8s} {'req':>6s} {'fit':>4s} {'ODS':>5s} {'est t/s':>8s}"
print(hdr)
for r in sorted(rows, key=lambda x: -(x.get("ods_score") or 0)):
    if not r.get("size_gb"):
        print(f"{r['candidate'][:28]:28s}  no GGUF size ({r.get('error','?')})")
        continue
    print(f"{r['candidate'][:28]:28s} {r['size_gb']:6.2f} {str(r.get('full_attn_layers')):>5s} "
          f"{r.get('kv_160k_gb', 0):8.2f} {r.get('required_gb', 0):6.2f} "
          f"{'YES' if r.get('fits_12gb_160k') else 'NO':>4s} {r.get('ods_score', 0):5.2f} {r.get('est_decode_tps', 0):8.1f}")
print()
print("=== ODS's own verdict on each (its KV estimate + its fit test) ===")
for r in rows:
    if r.get("size_gb"):
        print(f"  {r['candidate'][:30]:30s} ODS est KV@160K={r.get('ods_est_kv_gb')}GB  "
              f"required={r.get('ods_required_gb')}GB  fits={r.get('ods_fits')}  "
              f"(exact KV={r.get('kv_160k_gb')}GB, real required={r.get('required_gb')}GB)")
print()
print("=== quality provenance (never upgrade on vendor copy alone) ===")
for r in rows:
    print(f"  {r['candidate'][:30]:30s} {r['quality']}")
json.dump(rows, open("/home/konan/hf-model-review.json", "w"), indent=1)
print("\nwrote /home/konan/hf-model-review.json")
