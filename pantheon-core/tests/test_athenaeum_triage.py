from __future__ import annotations

from datetime import datetime, timezone

from gods.athenaeum_triage import (
    Issue,
    parse_hades_report,
    render_markdown,
    render_summary,
    triage_report,
)


SAMPLE_HADES = """# 🌙 Hades Nightly Report — 2026-05-16

## ⚠️ Consistency Issues
- **56 files not embedded in ChromaDB**

## 🧠 LLM Compilation
- Sessions compiled: 2
- Articles created: 2
- Transcripts copied: 2
- Remaining backlog: 3769
- ❌ Failed to compile session cron_f08818fa7f4c_20260429_203218 after 3 retries
- ❌ Failed to compile session cron_f08818fa7f4c_20260429_203912 after 3 retries

## 🔗 Entity Extraction
- ⚠️ Files failed: 3

## ❌ Errors (1)
- Shared context import failed

---
_Report generated: 2026-05-16T00:11:17.383164+00:00_
"""


def test_parse_hades_report_extracts_structured_signals():
    parsed = parse_hades_report(SAMPLE_HADES)

    assert parsed.report_date == "2026-05-16"
    assert parsed.unembedded_files == 56
    assert parsed.compilation_backlog == 3769
    assert parsed.failed_compile_sessions == [
        "cron_f08818fa7f4c_20260429_203218",
        "cron_f08818fa7f4c_20260429_203912",
    ]
    assert parsed.entity_files_failed == 3
    assert parsed.run_errors == ["Shared context import failed"]


def test_triage_report_groups_failures_by_actionability():
    report = triage_report(SAMPLE_HADES, previous_failed_sessions=[])

    by_kind = {issue.kind: issue for issue in report.issues}
    assert by_kind["embedding_gap"].severity == "warning"
    assert "spot-fix-embed.py" in by_kind["embedding_gap"].action
    assert by_kind["compile_failures"].severity == "error"
    assert "quarantine" in by_kind["compile_failures"].action.lower()
    assert by_kind["compile_backlog"].severity == "info"
    assert "capacity debt" in by_kind["compile_backlog"].summary.lower()


def test_repeated_compile_failures_are_suppressed_as_known_noise():
    report = triage_report(
        SAMPLE_HADES,
        previous_failed_sessions=[
            "cron_f08818fa7f4c_20260429_203218",
            "cron_f08818fa7f4c_20260429_203912",
        ],
    )

    compile_issue = next(i for i in report.issues if i.kind == "compile_failures")
    assert compile_issue.severity == "known"
    assert compile_issue.notify is False
    assert "already seen" in compile_issue.summary.lower()


def test_render_summary_only_surfaces_notifiable_work():
    report = triage_report(
        SAMPLE_HADES,
        previous_failed_sessions=[
            "cron_f08818fa7f4c_20260429_203218",
            "cron_f08818fa7f4c_20260429_203912",
        ],
    )

    summary = render_summary(report)
    assert "56 files missing embeddings" in summary
    assert "Known stuck compile sessions" in summary
    assert "3 entity files failed" in summary
    assert "3769" not in summary  # backlog is debt, not morning fire


def test_render_markdown_contains_commands_and_report_path():
    report = triage_report(SAMPLE_HADES, previous_failed_sessions=[])
    md = render_markdown(report, generated_at=datetime(2026, 5, 16, tzinfo=timezone.utc))

    assert "# Athenaeum triage" in md
    assert "python3 ~/pantheon/scripts/spot-fix-embed.py" in md
    assert "Failed compile sessions" in md
    assert "cron_f08818fa7f4c_20260429_203218" in md


def test_issue_defaults_to_notify_for_warning_and_error():
    assert Issue(kind="x", severity="warning", title="T", summary="S", action="A").notify is True
    assert Issue(kind="x", severity="info", title="T", summary="S", action="A").notify is False
