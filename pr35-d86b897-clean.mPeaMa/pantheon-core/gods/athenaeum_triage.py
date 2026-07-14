"""Athenaeum failure triage helpers.

Turns the Hades markdown report into a small, actionable health card. This
module is intentionally dependency light so it can run from cron, tests, and
standalone scripts without waking the whole Pantheon stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Iterable, Sequence


SEVERITY_ORDER = {"error": 0, "warning": 1, "known": 2, "info": 3}


@dataclass
class ParsedHadesReport:
    report_date: str | None = None
    unembedded_files: int = 0
    chroma_orphans: int = 0
    missing_indexes: list[str] = field(default_factory=list)
    compilation_backlog: int = 0
    failed_compile_sessions: list[str] = field(default_factory=list)
    entity_files_failed: int = 0
    extraction_error: str | None = None
    run_errors: list[str] = field(default_factory=list)


@dataclass
class Issue:
    kind: str
    severity: str
    title: str
    summary: str
    action: str
    details: list[str] = field(default_factory=list)
    notify: bool | None = None

    def __post_init__(self) -> None:
        if self.notify is None:
            self.notify = self.severity in {"warning", "error"}


@dataclass
class TriageReport:
    report_date: str | None
    status: str
    issues: list[Issue]
    parsed: ParsedHadesReport

    @property
    def notifiable_issues(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.notify]


def parse_hades_report(markdown: str) -> ParsedHadesReport:
    """Extract stable signals from a Hades markdown report."""
    parsed = ParsedHadesReport()

    title = re.search(r"Hades Nightly Report\s+[—-]\s+(\d{4}-\d{2}-\d{2})", markdown)
    if title:
        parsed.report_date = title.group(1)
    else:
        generated = re.search(r"Report generated:\s*(\d{4}-\d{2}-\d{2})", markdown)
        if generated:
            parsed.report_date = generated.group(1)

    unembedded = re.search(r"\*\*(\d+) files not embedded in ChromaDB\*\*", markdown)
    if unembedded:
        parsed.unembedded_files = int(unembedded.group(1))

    orphans = re.search(r"\*\*(\d+) ChromaDB entries orphaned\*\*", markdown)
    if orphans:
        parsed.chroma_orphans = int(orphans.group(1))

    backlog = re.search(r"Remaining backlog:\s*(\d+)", markdown)
    if backlog:
        parsed.compilation_backlog = int(backlog.group(1))

    parsed.failed_compile_sessions = re.findall(
        r"Failed to compile session\s+([A-Za-z0-9_.:-]+)\s+after\s+\d+\s+retries",
        markdown,
    )

    entity_failed = re.search(r"Files failed:\s*(\d+)", markdown)
    if entity_failed:
        parsed.entity_files_failed = int(entity_failed.group(1))

    extraction_error = re.search(r"## 🔗 Entity Extraction[\s\S]*?- ❌ Error:\s*(.+?)(?:\n|$)", markdown)
    if extraction_error:
        parsed.extraction_error = extraction_error.group(1).strip()

    parsed.missing_indexes = _section_bullets(markdown, "Missing INDEX.md")
    parsed.run_errors = _section_bullets(markdown, "❌ Errors")
    return parsed


def triage_report(markdown: str, previous_failed_sessions: Sequence[str] | None = None) -> TriageReport:
    """Build actionable issues from Hades markdown."""
    parsed = parse_hades_report(markdown)
    previous = set(previous_failed_sessions or [])
    issues: list[Issue] = []

    if parsed.unembedded_files:
        issues.append(Issue(
            kind="embedding_gap",
            severity="warning",
            title="Search coverage degraded",
            summary=f"{parsed.unembedded_files} files missing embeddings. Semantic search may miss recent Athenaeum writes.",
            action="Run `python3 ~/pantheon/scripts/spot-fix-embed.py`, then run Hades health checks again.",
            details=[f"Missing file count: {parsed.unembedded_files}"],
        ))

    if parsed.chroma_orphans:
        issues.append(Issue(
            kind="chroma_orphans",
            severity="warning",
            title="Chroma has orphaned entries",
            summary=f"{parsed.chroma_orphans} ChromaDB records point at files that no longer exist.",
            action="Rebuild or compact the affected Chroma collections after confirming no active writes are running.",
            details=[f"Orphan count: {parsed.chroma_orphans}"],
        ))

    if parsed.failed_compile_sessions:
        repeated = [sid for sid in parsed.failed_compile_sessions if sid in previous]
        new = [sid for sid in parsed.failed_compile_sessions if sid not in previous]
        if new:
            issues.append(Issue(
                kind="compile_failures",
                severity="error",
                title="Failed compile sessions",
                summary=f"{len(new)} compile sessions failed after retries. Quarantine repeat offenders so they stop blocking the morning signal.",
                action="Inspect the session payloads. If they are malformed old cron transcripts, quarantine them in the known failed sessions state and keep retry noise suppressed.",
                details=new,
            ))
        if repeated:
            issues.append(Issue(
                kind="compile_failures",
                severity="known",
                title="Known stuck compile sessions",
                summary=f"{len(repeated)} stuck compile sessions were already seen before. Keep them visible in the report, but do not treat them as fresh morning breakage.",
                action="No immediate action unless the count grows or these sessions become important to recover.",
                details=repeated,
                notify=False,
            ))

    if parsed.entity_files_failed:
        issues.append(Issue(
            kind="entity_file_failures",
            severity="warning",
            title="Entity extraction had file failures",
            summary=f"{parsed.entity_files_failed} entity files failed during extraction.",
            action="Run `python3 ~/athenaeum/scripts/extract-entities.py --dry-run` to isolate bad files before the next pre-Hades pass.",
            details=[f"Failed file count: {parsed.entity_files_failed}"],
        ))

    if parsed.extraction_error:
        issues.append(Issue(
            kind="extraction_error",
            severity="error",
            title="Entity extraction crashed",
            summary=parsed.extraction_error,
            action="Run `python3 -u ~/athenaeum/scripts/extract-entities.py --workers 4` directly to get the full traceback.",
            details=[parsed.extraction_error],
        ))

    if parsed.missing_indexes:
        issues.append(Issue(
            kind="missing_indexes",
            severity="warning",
            title="Missing INDEX files",
            summary=f"{len(parsed.missing_indexes)} Athenaeum directories still lack INDEX.md files.",
            action="Run Hades health checks or create the missing INDEX.md files manually if permissions blocked auto creation.",
            details=parsed.missing_indexes,
        ))

    if parsed.run_errors:
        issues.append(Issue(
            kind="hades_run_errors",
            severity="error",
            title="Hades run errors",
            summary=f"{len(parsed.run_errors)} run level errors were reported.",
            action="Read the latest Hades report and gateway cron logs before trusting downstream Athenaeum state.",
            details=parsed.run_errors,
        ))

    if parsed.compilation_backlog:
        issues.append(Issue(
            kind="compile_backlog",
            severity="info",
            title="Compilation backlog",
            summary=f"{parsed.compilation_backlog} sessions remain uncompiled. Treat this as capacity debt, not a daily failure.",
            action="Increase compile limit only after gateway memory is stable. This does not need morning intervention.",
            details=[f"Backlog: {parsed.compilation_backlog}"],
            notify=False,
        ))

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.kind))
    status = "green"
    if any(issue.severity == "error" for issue in issues):
        status = "error"
    elif any(issue.severity == "warning" for issue in issues):
        status = "warning"
    elif any(issue.severity == "known" for issue in issues):
        status = "known"
    elif issues:
        status = "info"

    return TriageReport(report_date=parsed.report_date, status=status, issues=issues, parsed=parsed)


def render_summary(report: TriageReport) -> str:
    """Render a terse morning briefing block."""
    if not report.issues:
        return "Athenaeum triage: all clear."

    lines = [f"Athenaeum triage: {report.status.upper()}"]
    for issue in report.issues:
        if issue.kind == "compile_backlog":
            continue
        if issue.kind == "compile_failures" and issue.severity == "known":
            lines.append(f"Known stuck compile sessions: {len(issue.details)}, unchanged. No morning action.")
            continue
        lines.append(f"{issue.title}: {issue.summary}")
    return "\n".join(lines)


def render_markdown(report: TriageReport, generated_at: datetime | None = None) -> str:
    """Render a durable markdown report."""
    generated_at = generated_at or datetime.now(timezone.utc)
    lines = [
        "# Athenaeum triage",
        "",
        f"Generated: {generated_at.isoformat()}",
        f"Hades report date: {report.report_date or 'unknown'}",
        f"Status: {report.status}",
        "",
    ]

    if not report.issues:
        lines.append("All clear. Hades found no actionable Athenaeum failures.")
    else:
        for issue in report.issues:
            lines.extend([
                f"## {issue.title}",
                "",
                f"Severity: {issue.severity}",
                f"Notify: {'yes' if issue.notify else 'no'}",
                "",
                issue.summary,
                "",
                f"Action: {issue.action}",
            ])
            if issue.details:
                lines.append("")
                lines.append("Details:")
                for detail in issue.details[:20]:
                    lines.append(f"- {detail}")
                if len(issue.details) > 20:
                    lines.append(f"- and {len(issue.details) - 20} more")
            lines.append("")

    lines.append("---")
    lines.append("Generated by `athenaeum-triage.py`.")
    return "\n".join(lines)


def load_known_failed_sessions(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    sessions = payload.get("known_failed_compile_sessions", [])
    return [str(s) for s in sessions if s]


def save_known_failed_sessions(path: Path, sessions: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = sorted({str(s) for s in sessions if s})
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "known_failed_compile_sessions": unique,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _section_bullets(markdown: str, heading_contains: str) -> list[str]:
    lines = markdown.splitlines()
    in_section = False
    bullets: list[str] = []
    for line in lines:
        if line.startswith("## ") and heading_contains in line:
            in_section = True
            continue
        if in_section and (line.startswith("## ") or line.startswith("---")):
            break
        if not in_section:
            continue
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("- ").strip()
        item = re.sub(r"^[❌⚠️✅]\s*", "", item).strip()
        if item:
            bullets.append(item)
    return bullets
