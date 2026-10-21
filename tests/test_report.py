from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from paper_status_monitor import report
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import SubmissionConfig
from paper_status_monitor.models import Change, Snapshot
from paper_status_monitor.monitor import RunSummary, SubmissionResult

STARTED = datetime(2026, 1, 2, 9, 30, 0)


@pytest.fixture
def snapshot(demo_payload: dict) -> Snapshot:
    return Snapshot.from_api(demo_payload)


def make_summary(snapshot: Snapshot) -> RunSummary:
    changed = SubmissionResult(
        SubmissionConfig(DEMO_UUID, label="Demo"),
        snapshot=snapshot,
        workbook=Path("book.xlsx"),
        changes=[Change("Reviews completed", "1", "2")],
    )
    new = SubmissionResult(
        SubmissionConfig("11111111-2222-3333-4444-555555555555"),
        snapshot=replace(snapshot, title="Another paper", revision="1"),
        is_new=True,
    )
    failed = SubmissionResult(
        SubmissionConfig("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", label="Broken"),
        error="The tracker answered HTTP 503; try again later.",
    )
    unchanged = SubmissionResult(SubmissionConfig(DEMO_UUID), snapshot=snapshot)
    return RunSummary(started_at=STARTED, results=[changed, new, failed, unchanged])


def test_render_report_sections(snapshot: Snapshot) -> None:
    text = report.render_report(make_summary(snapshot))
    assert "Run started: 2026-01-02 09:30:00" in text
    assert "CHANGES (1)" in text
    assert "  - Reviews completed: '1' → '2'" in text
    assert "NOW TRACKING (1)" in text
    assert "[1st revision] Another paper" in text
    assert "ERRORS (1)" in text
    assert "HTTP 503" in text
    assert "Label: Demo" in text
    assert f"Tracker: https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}" in text


def test_render_report_without_errors(snapshot: Snapshot) -> None:
    text = report.render_report(make_summary(snapshot), include_errors=False)
    assert "ERRORS" not in text


def test_render_report_without_news() -> None:
    summary = RunSummary(started_at=STARTED)
    assert "No changes." in report.render_report(summary)


def test_should_write_report(snapshot: Snapshot) -> None:
    summary = make_summary(snapshot)
    assert report.should_write_report(summary)
    only_errors = RunSummary(started_at=STARTED, results=[summary.results[2]])
    assert report.should_write_report(only_errors)
    assert not report.should_write_report(only_errors, include_errors=False)
    assert not report.should_write_report(RunSummary(started_at=STARTED))


def test_render_console(snapshot: Snapshot) -> None:
    text = report.render_console(make_summary(snapshot))
    assert text.splitlines()[0] == "Checked 4 submission(s) at 2026-01-02 09:30:00"
    assert "[CHANGED]" in text
    assert "[NEW]" in text
    assert "[ERROR]     Broken: The tracker answered HTTP 503" in text
    assert "[NO CHANGE]" in text


def test_write_report(tmp_path: Path, snapshot: Snapshot) -> None:
    path = report.write_report(make_summary(snapshot), tmp_path / "reports")
    assert path == tmp_path / "reports" / "changes_2026-01-02_09-30-00.txt"
    assert "CHANGES (1)" in path.read_text(encoding="utf-8")


def test_write_report_uses_the_fallback_folder(tmp_path: Path, snapshot: Snapshot) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where a folder is expected", encoding="utf-8")
    path = report.write_report(
        make_summary(snapshot), blocked / "reports", fallback_directory=tmp_path / "fallback"
    )
    assert path.parent == tmp_path / "fallback"


def test_write_report_raises_when_nothing_is_writable(tmp_path: Path, snapshot: Snapshot) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")
    # The exact OSError subclass depends on the platform (FileNotFoundError on
    # Windows, NotADirectoryError on Linux).
    with pytest.raises(OSError):  # noqa: PT011
        report.write_report(make_summary(snapshot), blocked / "reports")


def test_open_path_reports_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("no default application")

    monkeypatch.setattr(report.os, "startfile", fail, raising=False)
    monkeypatch.setattr(report.subprocess, "Popen", fail)
    assert report.open_path(tmp_path / "report.txt") is False
