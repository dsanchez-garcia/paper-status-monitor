from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from paper_status_monitor import export
from paper_status_monitor.client import DEMO_UUID, tracker_url
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKER_URL_COLUMN
from paper_status_monitor.storage import append_record

OTHER_UUID = "11111111-2222-3333-4444-555555555555"
THIRD_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def recorded(tmp_path: Path) -> Config:
    """Two submissions recorded in one workbook, and a third one not recorded yet."""
    workbook = tmp_path / "data" / "Tau.xlsx"
    for day, status in ((1, "Under Review"), (9, "Review Complete")):
        row = {
            DETECTED_AT_COLUMN: datetime(2026, 1, day, 9, 0),
            "Status": status,
            "Journal": "Journal A",
            "Manuscript number": "ABC-D-26-00001",
            TRACKER_URL_COLUMN: tracker_url(DEMO_UUID),
            "Paper": "Tau",
        }
        append_record(workbook, row)
    other = {
        DETECTED_AT_COLUMN: datetime(2026, 2, 1, 9, 0),
        "Status": "Under Review",
        "Journal": "Journal B",
        "Manuscript number": "XYZ-D-26-00002",
        TRACKER_URL_COLUMN: tracker_url(OTHER_UUID),
    }
    append_record(workbook, other)
    return Config(
        data_dir=workbook.parent,
        submissions=(
            SubmissionConfig(DEMO_UUID, label="Tau paper", fields={"paper": "Tau"}),
            SubmissionConfig(OTHER_UUID),
            SubmissionConfig(THIRD_UUID, label="Not recorded yet"),
        ),
    )


def test_collect_history(tmp_path: Path) -> None:
    histories = export.collect_history(recorded(tmp_path))
    assert [len(history.rows) for history in histories] == [2, 1, 0]
    assert [history.name() for history in histories] == [
        "Tau paper",
        "Submission 2",
        "Not recorded yet",
    ]
    assert histories[1].name(include_links=True) == OTHER_UUID


def test_csv_export_leaves_the_links_out(tmp_path: Path) -> None:
    text = export.render_export(export.collect_history(recorded(tmp_path)), "csv")
    header, *rows = list(csv.reader(io.StringIO(text)))
    assert header[:3] == ["Submission", DETECTED_AT_COLUMN, "Title"]
    assert header[-1] == "Paper"
    assert TRACKER_URL_COLUMN not in header
    status = header.index("Status")
    assert [(row[0], row[1], row[status], row[-1]) for row in rows] == [
        ("Tau paper", "2026-01-01 09:00:00", "Under Review", "Tau"),
        ("Tau paper", "2026-01-09 09:00:00", "Review Complete", "Tau"),
        ("Submission 2", "2026-02-01 09:00:00", "Under Review", ""),
    ]
    assert DEMO_UUID not in text
    assert OTHER_UUID not in text


def test_json_export_with_the_links(tmp_path: Path) -> None:
    histories = export.collect_history(recorded(tmp_path))
    moment = datetime(2026, 3, 1, 8, 0)
    data = json.loads(export.render_json(histories, include_links=True, generated_at=moment))
    assert data["generated_at"] == "2026-03-01T08:00:00"
    first, second, third = data["submissions"]
    assert (first["submission"], first["fields"]) == ("Tau paper", {"paper": "Tau"})
    assert first["tracker_url"] == tracker_url(DEMO_UUID)
    assert [row["Status"] for row in first["rows"]] == ["Under Review", "Review Complete"]
    assert first["rows"][0][TRACKER_URL_COLUMN] == tracker_url(DEMO_UUID)
    assert second["submission"] == OTHER_UUID
    assert third["rows"] == []


def test_unknown_export_format() -> None:
    with pytest.raises(ValueError, match="Unknown format 'xml'"):
        export.render_export([], "xml")
