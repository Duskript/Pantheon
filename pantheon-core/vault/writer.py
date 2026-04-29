from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sanctuary.config import SanctuaryConfig


class VaultWriter:
    def __init__(self, athenaeum_root: str) -> None:
        self._root = Path(athenaeum_root)
        self._sessions: dict[str, Path | None] = {}

    def append_turn(
        self,
        session_id: str,
        sanctuary: SanctuaryConfig,
        role: str,
        content: str,
    ) -> None:
        if not sanctuary.vault_logging.enabled:
            return
        path = self._get_or_create(session_id, sanctuary)
        role_label = "User" if role == "user" else sanctuary.god
        turn = f"\n[{role_label}]: {content}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(turn)

    def _get_or_create(self, session_id: str, sanctuary: SanctuaryConfig) -> Path:
        if session_id not in self._sessions:
            self._sessions[session_id] = self._create_session_file(sanctuary)
        return self._sessions[session_id]

    def _create_session_file(self, sanctuary: SanctuaryConfig) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
        filename = f"{timestamp}.md"
        rel_path = sanctuary.vault_logging.path.strip("/")
        path = self._root / rel_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._build_header(sanctuary, timestamp), encoding="utf-8")
        return path

    def _build_header(self, sanctuary: SanctuaryConfig, timestamp: str) -> str:
        lines = [
            "---",
            f"sanctuary: {sanctuary.name}",
            f"god: {sanctuary.god}",
        ]
        if sanctuary.studio:
            lines.append(f"studio: {sanctuary.studio}")
        lines += [f"timestamp: {timestamp}", "---\n"]
        return "\n".join(lines)
