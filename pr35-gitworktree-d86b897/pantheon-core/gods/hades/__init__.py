"""Hades — nightly Athenaeum consolidation pipeline.

Runs as a cron job. Performs:
  1. Health checks — ChromaDB vs filesystem consistency, INDEX coverage
  2. Embed backfill — push unembedded filesystem files into ChromaDB
  3. Distillation — extract canonical knowledge from vault sessions
  4. Archive management — identify stale/unlinked content (scan only, no moves)
  5. Suggestions loading
  6. Report generation + Hermes mailbox delivery
  7. Heartbeat for the Fates watchdog

Refactored 2026-06-03 from a 1,284-line monolith into a navigable package.
Behavior is identical to the prior version; structure now mirrors the 6 phases
so an agent fixing a bug in (say) `distill_sessions` doesn't have to scroll
past the entire embedding pipeline. The CLI entry point at `scripts/hades`
is unchanged.

Submodule layout:
  - `paths`   — filesystem constants (ATHENAEUM_ROOT, CHROMA_DIR, etc.)
  - `models`  — HadesReport dataclass, INDEX_DESCRIPTION
  - `health`  — Phase 1: codex walking, INDEX auto-create, stale detection
  - `embed`   — Phase 2: _Embedder, ChromaDB client, embed_missing_files
  - `distill` — Phase 3: distill_sessions, run_distillation
  - `archive` — Phase 4: run_archive (scan-only; reports candidates)
  - `mailbox` — Phase 5+6: deliver_to_mailbox, load_suggestions, _seq_id

The `run_hades()` orchestrator in `__main__` runs the 6 phases in sequence.
Each phase is independently catchable so a downstream failure doesn't
abort the whole sweep.

For the original design intent (the 4-god distributed model: Hades +
Charon + Fates + Mnemosyne cooperation) see the SUPERSEDED Phase 3 spec at
`planning/agent-zero-fork/phases/03-underworld/03-SPEC.md` and the
explanation in `Codex-Pantheon/architecture/hades-pipeline.md`.
"""

from .paths import (  # noqa: F401  (re-exported)
    ATHENAEUM_ROOT,
    ARCHIVE_DIR_NAME,
    CHROMA_DIR,
    DISTILLED_DIR_NAME,
    EMBEDDABLE_EXTS,
    GRAPH_DB,
    HERMES_INBOX,
    INDEX_DESCRIPTION,
    KNOWN_CODEXES,
    REAL_HOME,
    SESSIONS_DIR_NAME,
    STALE_THRESHOLD_DAYS,
    SUGGEST_FILE,
    SYSTEM_CODEXES,
)
from .models import HadesReport  # noqa: F401
from .health import (  # noqa: F401
    _walk_codex_files,
    ensure_index_files,
    find_stale_files,
    run_health_checks,
)
from .embed import (  # noqa: F401
    _embed_file,
    _get_chroma_client,
    _partition_for,
    _recheck_embedded_counts,
    embed_missing_files,
)
from .embed import _Embedder  # noqa: F401
from .distill import distill_sessions, run_distillation  # noqa: F401
from .archive import run_archive  # noqa: F401
from .mailbox import (  # noqa: F401
    _seq_id,
    deliver_to_mailbox,
    load_suggestions,
    main,
)
from .orchestrator import run_hades  # noqa: F401
