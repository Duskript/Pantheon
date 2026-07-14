"""Hades — backwards-compat shim. The real code lives in `hades/`.

After the 2026-06-03 navigability refactor, this file is a thin
re-export layer. Anything that did:

    from hades import run_hades
    import hades
    from pantheon_core.gods import hades

still works — the `hades/` package is importable as `hades` because
of how Python's package resolution works (when both `hades.py` and
`hades/__init__.py` exist, the package wins; this shim is a safety
net for any callers that pinned to the old module path).

For new code, prefer importing from the submodules directly:

    from gods.hades.health import run_health_checks
    from gods.hades.embed import embed_missing_files
"""

from .hades import *  # noqa: F401,F403
from .hades import (  # noqa: F401  (re-exported at top level)
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
    HadesReport,
    _Embedder,
    _embed_file,
    _get_chroma_client,
    _partition_for,
    _recheck_embedded_counts,
    _walk_codex_files,
    deliver_to_mailbox,
    distill_sessions,
    embed_missing_files,
    ensure_index_files,
    find_stale_files,
    load_suggestions,
    main,
    run_archive,
    run_distillation,
    run_hades,
    run_health_checks,
)
from .hades.mailbox import _seq_id  # noqa: F401
from .hades.orchestrator import run_hades as _run_hades  # noqa: F401
