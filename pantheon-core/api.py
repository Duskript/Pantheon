from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from sanctuary.config import load_all_sanctuaries, load_sanctuary, SanctuaryConfig
from harness.loader import load_harness
from vault.writer import VaultWriter

app = FastAPI()


def _vault_writer() -> VaultWriter:
    root = os.environ.get("ATHENAEUM_ROOT", "/Athenaeum")
    return VaultWriter(root)


@app.get("/sanctuaries")
def get_sanctuaries() -> dict[str, list[dict[str, Any]]]:
    sanctuaries = load_all_sanctuaries()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for s in sanctuaries:
        entry = {"id": s.id, "name": s.name, "ui": vars(s.ui)}
        grouped.setdefault(s.god, []).append(entry)
    return grouped


@app.get("/sanctuary/{sanctuary_id}/prompt")
def get_prompt(sanctuary_id: str) -> dict[str, str]:
    s = load_sanctuary(sanctuary_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Sanctuary not found")
    harness = load_harness(s.harness)
    return {"prompt": harness.get("identity", ""), "god": s.god}


class LogTurn(BaseModel):
    session_id: str
    role: str
    content: str


@app.post("/sanctuary/{sanctuary_id}/log")
def log_turn(sanctuary_id: str, body: LogTurn) -> dict[str, str]:
    s = load_sanctuary(sanctuary_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Sanctuary not found")
    _vault_writer().append_turn(body.session_id, s, body.role, body.content)
    return {"status": "ok"}
