# Ichor Compressor-Weight Benchmark — Spec Contract

## Source handoff

Original handoff: `~/athenaeum/Codex-Pantheon/design/ichor-context-pack-compressor-augmentation.md`.

This work implements the missing Phase 0/2 measurement gate. It does **not** enable live context-pack injection, change `context.engine`, restart gateways, rotate sessions, or re-enable Hermes LCM.

## Problem

The existing replay and rollout-simulation gates prove that the Ichor context pack can add source-backed recall context safely. They do **not** prove compressor-weight behavior because their default-compressor baseline usually evaluates tiny prompts where `ContextCompressor.should_compress()` is false.

The benchmark must exercise a long transcript where Hermes' built-in `ContextCompressor` really has a compressible middle window and then compare that baseline against Ichor context-pack augmentation metrics.

## Acceptance gates

For each benchmark case:

1. Default compressor baseline is available.
2. Long transcript estimated tokens exceed the compressor threshold.
3. `ContextCompressor.has_content_to_compress(messages)` is true.
4. The benchmark calls `ContextCompressor.compress(...)` on a copied fixture with a deterministic fake summary path, so no provider/API call is made.
5. Default compression reduces token estimate and message count.
6. Ichor context-pack build has `llm_calls == 0`, `api_calls == 0`, `db_writes == 0`.
7. Ichor context pack stays within `max_pack_tokens`.
8. Safety flags stay false: no runtime mutation, session rotation, transcript rewrite, config edit, or gateway restart.
9. No-op benchmark row stays zero-read/zero-injection.
10. Benchmark writes JSON summary + markdown report artifacts.

## Compared modes

- `default_compressor`: built-in `ContextCompressor.compress()` on a synthetic long transcript with deterministic fake summarization.
- `ichor_context_pack`: current Ichor selector/pack builder.
- `hybrid_projection`: default compressed context plus bounded Ichor pack token overhead; this is a measurement projection only, not live wiring.

## Out of scope

- Live profile canary.
- New context engine plugin.
- Fleet defaults.
- Hermes LCM re-enable.
- Real LLM/API compression calls.
