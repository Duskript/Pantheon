"""Pantheon's ``hermes_cli`` extension package — kanban contract module.

This package exists so the HephaestusBuildCard contract and its 12 contract
tests are runnable from the repository root:

    cd /home/konan/pantheon && python3 -m pytest hermes_cli/kanban_contract_test.py

Why it no longer stands alone
-----------------------------
``~/pantheon`` is prepended to ``sys.path`` by the Ichor plugin, so this
directory WINS the ``hermes_cli`` import whenever Pantheon is first. A 4-module
stub winning over the real 189-module package is how ``hermes_cli.config``,
``.auth`` and ``._subprocess_compat`` became unimportable for tooling that ran
without the editable-install finder (Ichor audit item 10, 2026-09-20) -- and it
silently skipped the real package's import-time ``_ensure_utf8()`` guard, which
protects every CLI subcommand on a non-UTF-8 locale.

The contract module cannot simply be moved: ``god-packages/shared-skills/
spec-to-kanban-dispatch`` documents ``from hermes_cli.kanban_contract import
validate_card`` for every god, and the live fleet tree ships no such module.

So on import this package locates the REAL ``hermes_cli`` elsewhere on
``sys.path``, executes its ``__init__`` (keeping the package's real identity,
version and import-time behaviour), and ADOPTS its directory into ``__path__``
next to this one. Pantheon's contract module stays importable, the real
package's modules stay importable, and nothing is shadowed.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Fallbacks, used only when no real hermes_cli exists on sys.path at all. They
# are deliberately NOT the version of any tree -- a stub that claims a real
# version is what made the original collision invisible.
__version__ = "0.0.0+pantheon-stub"
__release_date__ = "unknown"

def _find_real_package_init() -> str | None:
    """Locate the real ``hermes_cli/__init__.py``, ignoring this directory.

    Two discovery paths, because either alone misses the live fleet:
      * a ``sys.path`` entry containing ``hermes_cli/__init__.py`` (PYTHONPATH
        deployments, the vendored checkout);
      * a meta-path finder that maps the package WITHOUT a path entry -- which
        is how the fleet is actually installed (editable install). Scanning
        ``sys.path`` alone found nothing there and the adoption silently did not
        happen; the fleet's own ``hermes_cli`` was reachable only through the
        editable finder.
    """
    for entry in sys.path:
        if not entry:
            continue
        candidate = os.path.join(entry, "hermes_cli", "__init__.py")
        if os.path.isfile(candidate) and os.path.dirname(os.path.abspath(candidate)) != _HERE:
            return os.path.abspath(candidate)

    for finder in list(sys.meta_path):
        if finder.__class__.__module__.startswith(__name__.split(".")[0]):
            continue
        try:
            spec = finder.find_spec("hermes_cli", None)
        except Exception:
            continue
        origin = getattr(spec, "origin", None) or ""
        if origin.endswith("__init__.py") and os.path.dirname(os.path.abspath(origin)) != _HERE:
            return os.path.abspath(origin)
    return None


_REAL_INIT = _find_real_package_init()

# Our own directory first (so kanban_contract/kanban_config resolve), then the
# real package's -- both halves of the namespace stay importable.
__path__ = [_HERE]

if _REAL_INIT:
    try:
        _spec = importlib.util.spec_from_file_location(
            "_pantheon_hermes_cli_real", _REAL_INIT
        )
        _real = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_real)
        for _name, _value in vars(_real).items():
            if _name.startswith("__") and _name not in ("__version__", "__release_date__"):
                continue
            globals()[_name] = _value
        _real_dir = os.path.dirname(_REAL_INIT)
        if _real_dir not in __path__:
            __path__.append(_real_dir)
    except Exception:  # pragma: no cover - never break an import over this
        # A broken adoption must degrade to the old stub behaviour rather than
        # take down every process that imports hermes_cli.
        pass
