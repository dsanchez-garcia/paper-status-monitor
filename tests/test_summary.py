from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from paper_status_monitor import summary
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import TRACKER_URL_COLUMN
from paper_status_monitor.storage import append_record

OTHER_UUID = "11111111-2222-3333-4444-555555555555"
TODAY = date(2026, 3, 3)
GENERATED = datetime(2026, 3, 3, 10, 0)


def record(moment: str, status: str, **values: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Detected at": datetime.fromisoformat(moment),
        "Title": "A study of something important",
        "Status": status,
        "Journal": "Journal of Examples",
        "Manuscript number": "ABC-D-26-00001",
        TRACKER_URL_COLUMN: f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}",
    }
    row.update(values)
    return row


@pytest.fixture
def config(tmp_path: Path) -> Config:
    workbook = tmp_path / "data" / "ABC-D-26-00001.xlsx"
    append_record(workbook, record("2026-01-10 09:00", "Under Review"))
    append_record(workbook, record("2026-02-01 09:00", "Required Reviews Complete"))
    append_record(
        workbook,
        record(
            "2026-02-03 09:00",
            "Required Reviews Complete",
            **{
                "Manuscript number": "ABC-D-26-00001R1",
                "Revision": "1",
                "Reviews completed": "2",
                "Review invitations accepted": "2",
                "Review invitations sent": "2+",
                "Last review activity": "2nd February 2026",
            },
        ),
    )
    return Config(
        data_dir=tmp_path / "data",
        submissions=(
            SubmissionConfig(DEMO_UUID, label="TMY | paper"),
            SubmissionConfig(OTHER_UUID, enabled=False),
        ),
    )


def rows_of(config: Config) -> list[summary.SummaryRow]:
    return summary.summary_rows(config, today=lambda: TODAY)


def test_summary_rows(config: Config) -> None:
    first, second = rows_of(config)
    assert first.number == 1
    assert first.name == "TMY | paper"
    assert first.recorded
    assert first.status == "Required Reviews Complete"
    assert first.since == date(2026, 2, 1)  # when the current status was first seen
    assert first.days == 30
    assert first.since_text == "2026-02-01 (30 days)"
    assert first.manuscript_number == "ABC-D-26-00001R1"
    assert first.reviews == "2 / 2 / 2+"
    assert first.last_review_activity == "2nd February 2026"
    assert first.last_change == datetime(2026, 2, 3, 9, 0)
    assert first.workbook is not None
    assert first.workbook.name == "ABC-D-26-00001.xlsx"

    assert second.recorded is False
    assert second.name == OTHER_UUID
    assert second.cells()[1] == f"[paused] {OTHER_UUID}"
    assert second.cells()[4] == "not recorded yet"


def test_render_text(config: Config) -> None:
    text = summary.render_summary(rows_of(config), "text", generated_at=GENERATED)
    lines = text.splitlines()
    assert lines[0] == "Paper status summary - 2026-03-03 10:00"
    assert lines[2].split()[:3] == ["#", "Submission", "Journal"]
    assert "Required Reviews Complete" in lines[3]
    assert "2026-02-01 (30 days)" in lines[3]
    assert lines[3].index("Journal of Examples") == lines[2].index("Journal")  # aligned
    assert lines[4].split()[:2] == ["2", "[paused]"]
    assert "…" in lines[4]  # long names are shortened
    assert "not recorded yet" in lines[4]


def test_render_markdown(config: Config) -> None:
    text = summary.render_summary(rows_of(config), "markdown", generated_at=GENERATED)
    assert text.startswith("# Paper status summary\n\nGenerated on 2026-03-03 10:00.\n")
    assert "| 1 | TMY \\| paper | Journal of Examples | ABC-D-26-00001R1 |" in text
    assert (
        f"| 2 | [paused] {OTHER_UUID} | - | - | not recorded yet | - | - | - |" in text.splitlines()
    )


def test_render_html(config: Config) -> None:
    page = summary.render_summary(rows_of(config), "html", generated_at=GENERATED)
    assert page.startswith("<!DOCTYPE html>")
    assert "<td>TMY | paper</td>" in page
    assert '<tr class="paused">' in page
    assert "track.authorhub" not in page  # tracking links are personal: not in the summary
    escaped = summary.render_html([summary.SummaryRow(1, "R&D <paper>", recorded=True)])
    assert "<td>R&amp;D &lt;paper&gt;</td>" in escaped


def test_text_summary_shortens_long_names(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path, submissions=(SubmissionConfig(DEMO_UUID, label="x" * 60),))
    text = summary.render_text(summary.summary_rows(config))
    assert "x" * 31 + "…" in text


@pytest.mark.parametrize("fmt", summary.FORMATS)
def test_empty_summary(fmt: str) -> None:
    assert "No submissions in the configuration." in summary.render_summary([], fmt)


def test_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unknown format"):
        summary.render_summary([], "pdf")


def test_since_text() -> None:
    row = summary.SummaryRow(1, "x", since=date(2026, 3, 2), days=1)
    assert row.since_text == "2026-03-02 (1 day)"
    assert summary.SummaryRow(1, "x", since=date(2026, 3, 2)).since_text == "2026-03-02"
    assert summary.SummaryRow(1, "x").since_text == ""
