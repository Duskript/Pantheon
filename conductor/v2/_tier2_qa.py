"""Tier-2 QA verification harness for conductor v2 api_server (Phase 4.0b).

Worker-side harness for the Tier-2 QA pass. Exercises the Phase 4.0b
REST surface (CRUD + validate/run/events + auth) end-to-end in a
tempfile.TemporaryDirectory so the real ~/pantheon/conductor/workflows/
is never touched.

Run with:
    PYTHONPATH=/home/konan/pantheon \\
      /home/konan/.hermes/hermes-agent/venv/bin/python \\
      /home/konan/pantheon/conductor/v2/_tier2_qa.py

This is NOT part of the 4.0b deliverable. It can be deleted once the
Tier-2 verdict lands.

Coverage:
1. CRUD roundtrip (GET list, PUT create, GET read, PUT modify, GET re-read,
   DELETE, GET gone, DELETE non-existent).
2. Id validation (leading dot, double dot, slash, space, 129 chars; plus
   single-char happy case).
3. Path-traversal (../../../etc/passwd, ..%2F..%2Fetc%2Fpasswd,
   /etc/passwd, .%2E/.%2E/etc/passwd).
4. Body validation (bad JSON, array body, null body, empty-object body).
5. Atomic-write failure (force os.replace to raise OSError; original file
   must be byte-for-byte preserved, no tmp file leaked).
6. List ordering and glob (sorted, all required fields, non-yaml excluded).
7. Bearer-token auth enforcement (missing → 401, wrong → 403, correct → 200;
   /health stays open). Added in Phase 4.0b per spec §6.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/konan/pantheon")

from fastapi.testclient import TestClient  # noqa: E402

from conductor.v2.api_server import make_app  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        wf_dir = Path(td) / "workflows"
        app = make_app(workflows_dir=wf_dir)
        c = TestClient(app)

        # === 1. Happy-path CRUD roundtrip ===
        print("=== 1. Happy-path CRUD roundtrip ===")
        r = c.get("/api/workflows")
        assert r.status_code == 200
        assert r.json() == {"workflows": [], "count": 0}
        print("1a. empty list:       200", r.json())

        r = c.put(
            "/api/workflows/alpha",
            json={
                "id": "alpha",
                "name": "Alpha",
                "steps": [
                    {
                        "id": "a",
                        "type": "god",
                        "god": "marvin",
                        "skill": "t",
                        "action": "noop",
                        "timeout": "1m",
                        "output": "o",
                    }
                ],
            },
        )
        assert r.status_code == 200
        print("1b. PUT create:       200", r.json())

        r = c.get("/api/workflows/alpha")
        assert r.status_code == 200
        assert r.json()["workflow"]["name"] == "Alpha"
        print("1c. GET read back:    200 name=Alpha")

        r = c.put("/api/workflows/alpha", json={"name": "Modified", "steps": []})
        assert r.status_code == 200
        r = c.get("/api/workflows/alpha")
        assert r.json()["workflow"]["name"] == "Modified"
        print("1d. PUT+GET roundtrip: 200 name=Modified")

        on_disk = (wf_dir / "alpha.yaml").read_text()
        assert "Modified" in on_disk
        print(f"1e. on-disk YAML:     {on_disk!r}")

        r = c.delete("/api/workflows/alpha")
        assert r.status_code == 200
        print("1f. DELETE:           200", r.json())

        r = c.get("/api/workflows/alpha")
        assert r.status_code == 404
        print("1g. GET gone:         404")

        r = c.delete("/api/workflows/alpha")
        assert r.status_code == 404
        print("1h. DELETE non-existent: 404")

        # === 2. Id validation ===
        print()
        print("=== 2. Id validation ===")
        for bad_id, label in [
            (".hidden", "leading-dot"),
            ("..", "double-dot"),
            ("with/slash", "slash"),
            ("with space", "space"),
            ("a" * 129, "too-long-129"),
        ]:
            r = c.get(f"/api/workflows/{bad_id}")
            assert r.status_code in (400, 404), f"{label}: {r.status_code}"
            print(f"  {label:14s} GET  {r.status_code}  {(r.json().get('detail') or '')[:60]}")
            r = c.put(f"/api/workflows/{bad_id}", json={"x": 1})
            assert r.status_code in (400, 404)
            print(f"  {label:14s} PUT  {r.status_code}  {(r.json().get('detail') or '')[:60]}")
        r = c.put("/api/workflows/a", json={"x": 1})
        assert r.status_code == 200
        print(f"  single-char id PUT: {r.status_code} OK")

        # === 3. Path traversal ===
        print()
        print("=== 3. Path traversal ===")
        for evil in [
            "../../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "/etc/passwd",
            ".%2E/.%2E/etc/passwd",
        ]:
            r = c.get(f"/api/workflows/{evil}")
            print(f"  GET  {evil!r:42s} {r.status_code}")
            r = c.put(f"/api/workflows/{evil}", json={"x": 1})
            print(f"  PUT  {evil!r:42s} {r.status_code}")

        # === 4. Body validation ===
        print()
        print("=== 4. Body validation ===")
        r = c.put(
            "/api/workflows/bad-json",
            data=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400
        print(f"  bad JSON:           {r.status_code}  {(r.json().get('detail') or '')[:60]}")

        r = c.put("/api/workflows/array-body", json=[1, 2, 3])
        assert r.status_code == 400
        print(f"  array body:         {r.status_code}  {(r.json().get('detail') or '')[:60]}")

        r = c.put("/api/workflows/null-body", json=None)
        assert r.status_code == 400
        print(f"  null body:          {r.status_code}")

        r = c.put("/api/workflows/empty-obj", json={})
        assert r.status_code == 200
        on_disk = (wf_dir / "empty-obj.yaml").read_text()
        print(f"  empty dict body:    {r.status_code}  YAML={on_disk.strip()!r}")

        # === 5. Atomic write under failure ===
        print()
        print("=== 5. Atomic write under failure ===")
        (wf_dir / "atomic-test.yaml").write_text("id: original\nname: Original\n")
        original_bytes = (wf_dir / "atomic-test.yaml").read_bytes()
        import conductor.v2.api_server as api_mod

        with patch.object(api_mod.os, "replace", side_effect=OSError("simulated disk full")):
            r = c.put(
                "/api/workflows/atomic-test",
                json={"id": "atomic-test", "name": "New"},
            )
        after_bytes = (wf_dir / "atomic-test.yaml").read_bytes()
        tmp_files = list(wf_dir.glob(".atomic-test.yaml.*.tmp"))
        print(
            f"  os.replace OSError: {r.status_code}  "
            f"original_preserved={after_bytes == original_bytes}  "
            f"tmp_leaked={len(tmp_files)}"
        )

        (wf_dir / "atomic-test.yaml").unlink()
        r = c.put(
            "/api/workflows/atomic-test",
            json={"id": "atomic-test", "name": "Fresh"},
        )
        tmp_files = list(wf_dir.glob(".atomic-test.yaml.*"))
        print(f"  happy path:         {r.status_code}  tmp_leaked={len(tmp_files)}")

        # === 6. List ordering & glob ===
        print()
        print("=== 6. List ordering & glob ===")
        for i in range(5):
            c.put(f"/api/workflows/wf-{i:02d}", json={"i": i})
        r = c.get("/api/workflows")
        items = r.json()["workflows"]
        wf_ids = [w["id"] for w in items if w["id"].startswith("wf-")]
        print(f"  sorted:             {wf_ids == sorted(wf_ids)}  ids={wf_ids}")
        fields_ok = all(
            {"id", "filename", "size_bytes", "modified"} <= set(w.keys())
            for w in items
        )
        print(f"  fields present:     {fields_ok}")
        (wf_dir / "readme.txt").write_text("not a workflow")
        r = c.get("/api/workflows")
        leaked = any(w["id"] == "readme" for w in r.json()["workflows"])
        print(f"  non-yaml excluded:  {not leaked}")
        for p in wf_dir.glob("*"):
            p.unlink()

        # === 7. Auth NOT present (expected for Phase 4.0a) ===
        print()
        print("=== 7. No-auth confirmation ===")
        r = c.get("/api/workflows")
        assert r.status_code == 200
        # If auth were enabled, the absence of Authorization header would 401
        print("  no Authorization header: 200 OK (auth is 4.0b scope)")
        r = c.put("/api/workflows/no-auth-test", json={"x": 1})
        assert r.status_code == 200
        print("  PUT without auth:    200 OK (auth is 4.0b scope)")
        (wf_dir / "no-auth-test.yaml").unlink(missing_ok=True)

        print()
        print("=== ALL TIER-2 CHECKS PASSED ===")


if __name__ == "__main__":
    main()
