#!/usr/bin/env python3
"""Phase D comparison report generator.

Reads comparison-mode JSONL logs from Pantheon core hooks and produces a
compact markdown report plus a machine-readable JSON summary.

The report is intentionally simple: we count hooks, track block events, and
flag malformed entries as divergences so the daily cron can spot drift fast.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_COMPARISON_DIR = Path.home() / ".hermes" / "hooks" / "pantheon-core" / "comparison"
DEFAULT_REPORT_DIR = DEFAULT_COMPARISON_DIR / "reports"


@dataclass(frozen=True)
class ComparisonEntry:
    path: Path
    line_number: int
    data: dict[str, Any]


def _iter_jsonl_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())


def load_comparison_entries(comparison_dir: Path = DEFAULT_COMPARISON_DIR) -> list[ComparisonEntry]:
    entries: list[ComparisonEntry] = []
    for path in _iter_jsonl_files(comparison_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = {"error": "invalid_json", "raw": line}
            if not isinstance(data, dict):
                data = {"error": "non_object_entry", "raw": data}
            entries.append(ComparisonEntry(path=path, line_number=idx, data=data))
    return entries


def summarize_comparison_logs(comparison_dir: Path = DEFAULT_COMPARISON_DIR) -> dict[str, Any]:
    entries = load_comparison_entries(comparison_dir)
    hook_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    blocked_count = 0
    error_count = 0
    accordion_expansion_count = 0
    memory_injection_count = 0

    for entry in entries:
        data = entry.data
        hook = str(data.get("hook") or data.get("event") or "unknown")
        if data.get("error") or hook == "unknown":
            error_count += 1
            continue
        hook_counts[hook] += 1
        source = str(data.get("source") or "")
        if source:
            source_counts[source] += 1
        if hook == "pre_tool_call":
            result = data.get("result")
            if isinstance(result, dict):
                passed = result.get("passed")
                if passed is False:
                    blocked_count += 1
            elif str(data.get("action") or "") == "block":
                blocked_count += 1
        if hook == "accordion_expand" or source == "accordion":
            accordion_expansion_count += 1
        if hook == "pre_llm_call" and source == "pantheon-core":
            memory_injection_count += 1

    divergence_count = blocked_count + error_count
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "comparison_dir": str(comparison_dir),
        "total_entries": len(entries),
        "hook_counts": dict(sorted(hook_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "blocked_count": blocked_count,
        "error_count": error_count,
        "divergence_count": divergence_count,
        "accordion_expansion_count": accordion_expansion_count,
        "memory_injection_count": memory_injection_count,
        "files_seen": sorted({str(entry.path) for entry in entries}),
    }
    return report


def render_comparison_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Pantheon Comparison Report",
        "",
        f"Generated: {summary['generated_at']}",
        f"Comparison dir: `{summary['comparison_dir']}`",
        f"Total entries: **{summary['total_entries']}**",
        f"blocked_count: **{summary['blocked_count']}**",
        f"error_count: **{summary['error_count']}**",
        f"divergence_count: **{summary['divergence_count']}**",
        f"accordion_expansion_count: **{summary['accordion_expansion_count']}**",
        f"memory_injection_count: **{summary['memory_injection_count']}**",
        "",
        "## Hook counts",
    ]
    hook_counts = summary.get("hook_counts") or {}
    if hook_counts:
        for hook, count in hook_counts.items():
            lines.append(f"- `{hook}`: {count}")
    else:
        lines.append("- _no comparison entries found_")

    lines.extend([
        "",
        "## Source counts",
    ])
    source_counts = summary.get("source_counts") or {}
    if source_counts:
        for source, count in source_counts.items():
            lines.append(f"- `{source}`: {count}")
    else:
        lines.append("- _no sources recorded_")

    files_seen = summary.get("files_seen") or []
    lines.extend([
        "",
        "## Files seen",
    ])
    if files_seen:
        for path in files_seen:
            lines.append(f"- `{path}`")
    else:
        lines.append("- _none_")

    return "\n".join(lines).strip() + "\n"


def write_comparison_report(comparison_dir: Path = DEFAULT_COMPARISON_DIR, output_root: Path = DEFAULT_REPORT_DIR) -> Path:
    summary = summarize_comparison_logs(comparison_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    report_path = output_root / f"comparison-report-{stamp}.md"
    report_path.write_text(render_comparison_report(summary), encoding="utf-8")
    (output_root / "latest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_root / "latest.md").write_text(render_comparison_report(summary), encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pantheon comparison report generator")
    parser.add_argument("--comparison-dir", default=str(DEFAULT_COMPARISON_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--write", action="store_true", help="Write report files to the output root")
    args = parser.parse_args(argv)

    comparison_dir = Path(args.comparison_dir).expanduser()
    output_root = Path(args.output_root).expanduser()
    summary = summarize_comparison_logs(comparison_dir)
    if args.write:
        report_path = write_comparison_report(comparison_dir, output_root)
        summary["report_path"] = str(report_path)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(render_comparison_report(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
