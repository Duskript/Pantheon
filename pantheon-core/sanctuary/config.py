from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

SANCTUARIES_DIR = Path(
    os.environ.get(
        "PANTHEON_SANCTUARIES_DIR",
        Path(__file__).resolve().parents[2]
        / "Athenaeum/Codex-Pantheon/harnesses/sanctuaries",
    )
)


@dataclass
class VaultLogging:
    enabled: bool
    path: str
    format: str = "markdown"
    filename: str = "timestamp"


@dataclass
class SanctuaryUI:
    accent_color: str = "#6b7280"
    icon: str = "⚡"
    description: str = ""


@dataclass
class SanctuaryConfig:
    id: str
    name: str
    god: str
    harness: str
    model: str
    context_window: int
    vault_logging: VaultLogging
    ui: SanctuaryUI
    studio: str | None = None


def _parse(path: Path) -> SanctuaryConfig:
    data = yaml.safe_load(path.read_text())
    vl = data.get("vault_logging", {})
    ui = data.get("ui", {})
    return SanctuaryConfig(
        id=path.stem,
        name=data["name"],
        god=data["god"],
        studio=data.get("studio"),
        harness=data["harness"],
        model=data.get("model", "gemma4"),
        context_window=data.get("context_window", 8192),
        vault_logging=VaultLogging(
            enabled=vl.get("enabled", False),
            path=vl.get("path", ""),
            format=vl.get("format", "markdown"),
            filename=vl.get("filename", "timestamp"),
        ),
        ui=SanctuaryUI(
            accent_color=ui.get("accent_color", "#6b7280"),
            icon=ui.get("icon", "⚡"),
            description=ui.get("description", ""),
        ),
    )


def load_sanctuary(sanctuary_id: str) -> SanctuaryConfig | None:
    path = SANCTUARIES_DIR / f"{sanctuary_id}.yaml"
    if not path.exists():
        return None
    return _parse(path)


def load_all_sanctuaries() -> list[SanctuaryConfig]:
    if not SANCTUARIES_DIR.exists():
        return []
    return [_parse(p) for p in sorted(SANCTUARIES_DIR.glob("*.yaml"))]
