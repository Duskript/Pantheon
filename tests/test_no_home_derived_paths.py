"""No module-level path constant may be derived from `$HOME`.

A god's gateway session runs with `HOME` set to its **profile sandbox**
(`~/.hermes/profiles/<god>/home`). So anything derived from `$HOME` —
`Path.home()`, `os.path.expanduser("~")`, `Path(os.path.expanduser("~"))` —
silently resolves to a *different* tree depending on who asks.

This already happened in production, three times:

  * the **mistake ledger forked**, splitting the category counts that are its only
    discriminating signal — and hiding a real recurrence because the halves were
    written from different environments;
  * the **harness store** pointed at `profiles/<god>/home/pantheon-harness-store`,
    a different git repo;
  * a **shadow `ichor.db`** (48.8 MB of schema, 1 event) plus a shadow chroma store
    with real vectors were created inside thoth's sandbox.

The read direction is the dangerous one: a module that resolves to the shadow DB
reads an EMPTY database and computes a confident result from zero rows.

`_REAL_HOME = os.path.expanduser("~")` is NOT a fix — "~" follows `$HOME`. Only
`pwd.getpwuid(os.getuid())` and `os.path.expanduser("~<user>")` are immune.

WHY THESE RUN IN A SUBPROCESS
------------------------------
The module-level constants are computed at import, so testing them requires
`importlib.reload`. But **reload re-creates exception classes**, so a test holding
`HarnessStoreError` from an earlier import no longer matches the reloaded module's
class — and `pytest.raises(HarnessStoreError)` silently stops catching, failing
four unrelated tests elsewhere in the session. (Cost an hour to find.)

So the reload-based assertions run in a **subprocess**, where the reload cannot
leak into the pytest session's module identity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

PY = sys.executable

SITES = [
    ("lib.pantheon_path", "_REAL_HOME"),
    ("lib.ichor.harness_store", "STORE_DIR"),
    ("lib.ichor.harness_store", "LIVE_ROOT"),
    ("lib.ichor.edit_ledger", "LEDGER_PATH"),
    ("lib.ichor.edit_ledger", "FREEZE_PATH"),
    ("lib.ichor.mistakes", "LEDGER_PATH"),
    ("lib.ichor.entities.schema", "DB_PATH"),
    ("lib.ichor_benchmarks", "_ICHOR_DB"),
    ("lib.ichor_hybrid", "_PANTHEON_LIB"),
    ("lib.ichor_mcp", "_ICHOR_DB"),
    ("lib.ichor.vector_backend", "_DB_PATH"),
    ("lib.ichor.schema_v2", "DB_PATH"),
    ("lib.ichor_decay", "DEFAULT_DB"),
    ("lib.ichor_eviction", "DEFAULT_DB"),
]

_PROBE = """
import importlib, json, sys
out = {}
for modname, attr in json.loads(sys.argv[1]):
    m = importlib.import_module(modname)
    out[f"{modname}.{attr}"] = str(getattr(m, attr))
print(json.dumps(out))
"""


def _probe_with_home(sandbox: Path) -> dict:
    env = dict(os.environ, HOME=str(sandbox))
    for var in ("ICHOR_MISTAKE_LEDGER", "ICHOR_HARNESS_STORE", "ICHOR_LIVE_ROOT",
                "ICHOR_EDIT_LEDGER", "ICHOR_FREEZE_STATE"):
        env.pop(var, None)
    r = subprocess.run([PY, "-c", _PROBE, json.dumps(SITES)],
                       cwd=_ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout)


def test_no_path_constant_follows_a_sandboxed_home(tmp_path):
    """A god session must resolve the SAME paths as everyone else."""
    sandbox = tmp_path / "profiles" / "thoth" / "home"
    sandbox.mkdir(parents=True)
    values = _probe_with_home(sandbox)
    forked = {k: v for k, v in values.items() if str(sandbox) in v}
    assert not forked, f"these constants forked into the sandbox: {forked}"
    assert all("profiles/thoth/home" not in v for v in values.values())


def test_every_listed_site_produced_a_value(tmp_path):
    """Guards against a rename silently dropping a site from the sweep."""
    sandbox = tmp_path / "profiles" / "thoth" / "home"
    sandbox.mkdir(parents=True)
    values = _probe_with_home(sandbox)
    assert len(values) == len(SITES)


def test_expanduser_tilde_is_not_a_fix(tmp_path):
    """Documents WHY the naive alternative is wrong, so it isn't reintroduced."""
    sandbox = tmp_path / "profiles" / "thoth" / "home"
    sandbox.mkdir(parents=True)
    env = dict(os.environ, HOME=str(sandbox))
    r = subprocess.run([PY, "-c",
                        "import os;print(os.path.expanduser('~'));print(os.path.expanduser('~konan'))"],
                       capture_output=True, text=True, env=env)
    tilde, user = r.stdout.strip().splitlines()
    assert tilde == str(sandbox), "'~' follows $HOME (vulnerable)"
    assert user != str(sandbox), "'~<user>' uses pwd (immune)"


def test_account_home_is_the_shared_primitive():
    from lib.pantheon_path import account_home
    assert account_home().is_dir()
    assert not str(account_home()).startswith("/tmp")
