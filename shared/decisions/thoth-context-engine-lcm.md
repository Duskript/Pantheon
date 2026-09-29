
## 2026-08-12T14:28:32Z — LCM remains dormant due RAM bloat

Decision/context: Konan confirmed hermes-lcm previously blew up the system with intense RAM/RSS bloat. Current fleet configs use `context.engine: compressor` and do not enable `hermes-lcm`; existing LCM DBs/symlinks are dormant residue only. Do not re-enable LCM fleet-wide. Any future LCM/context-engine experiment must be explicit, canary-scoped, and load-tested under real inbound traffic before broader rollout.

## 2026-08-12T14:46:03Z — Context replacement must be cache-aware

Konan likes LCM's concept but not its runtime behavior; RAM bloat made it unsafe. Any Ichor-backed context engine must also preserve token/prompt caching economics: keep the static system prompt/tool schema prefix stable, avoid per-turn rewriting of large prefix sections, do deterministic tool-result pruning, and track cache_read/cache_write tokens as a first-class success metric.

## 2026-08-12T15:08:00Z — Context-pack/compression experiments require dry-run gates

Konan explicitly wants the Ichor context-pack/context-compression path locked down before live use. Do not change the default fleet/profile `context.engine` or `compression.*` settings as the first test. First prove the behavior in a dry-run harness or disposable canary profile/session that reads the same inputs but does not rotate sessions, rewrite transcripts, change default compression settings, or restart live god gateways. Promotion requires source-evidence coverage, role-differentiated packs, no unhydrated vector-only claims, bounded memory/RSS behavior, and prompt-cache-aware token accounting.

## 2026-08-12T15:14:34Z — Context-pack engine must not be materially heavier than default compressor

Konan's performance constraint: any replacement/augmentation for the default compressor must be no heavier, or only slightly heavier, than the built-in `ContextCompressor`. Treat this as a hard promotion gate, not a nice-to-have. Measure against the default compressor baseline on the same input: wall time, peak RSS, DB I/O/write count, token overhead, prompt-cache read/write behavior, and number of LLM/API calls. Recommended acceptance target: default-equivalent on idle/ordinary turns, zero LLM calls in retrieval/packing hot path, bounded deterministic DB reads, and no persistent resident indexes/caches unless they are tiny and proven stable under a long god-history canary.
