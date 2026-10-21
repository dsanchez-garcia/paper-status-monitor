from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from paper_status_monitor import storage
from paper_status_monitor.models import COLUMNS, DETECTED_AT_COLUMN, TRACKER_URL_COLUMN
from paper_status_monitor.storage import (
    MAX_STEM_LENGTH,
    SHEET_TITLE,
    WorkbookLockedError,
    append_record,
    find_workbook,
    find_workbook_by_uuid,
    last_record,
    read_records,
    sanitize_filename,
    workbook_name,
)

URL = "https://track.authorhub.elsevier.com/?uuid=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def record(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        DETECTED_AT_COLUMN: datetime(2026, 1, 2, 9, 30),
        "Title": "A study",
        "Revision": "0",
        "Status": "Under Review",
        "Status code": "3",
        "Reviews completed": "0",
        "Review invitations sent": "2+",
        "Manuscript number": "ABC-D-26-00001",
        TRACKER_URL_COLUMN: URL,
    }
    base.update(values)
    return base


def test_sanitize_filename() -> None:
    assert sanitize_filename('What? A "great": paper/study*  ') == "What A great paperstudy"
    assert sanitize_filename("Ends with dots...") == "Ends with dots"


def test_workbook_name() -> None:
    assert workbook_name("ABC-D-26-00001", "Journal: X", "A study") == (
        "ABC-D-26-00001 - Journal X - A study.xlsx"
    )
    assert workbook_name("ABC-D-26-00001") == "ABC-D-26-00001.xlsx"


def test_workbook_name_is_truncated_on_a_word_boundary() -> None:
    name = workbook_name("ABC-D-26-00001", "Journal", "word " * 100)
    stem = name.removesuffix(".xlsx")
    assert len(stem) <= MAX_STEM_LENGTH
    assert stem.startswith("ABC-D-26-00001 - Journal - word")
    assert stem.endswith("word")


def test_workbook_name_requires_a_key() -> None:
    with pytest.raises(ValueError, match="key"):
        workbook_name("???")


def test_append_creates_a_formatted_workbook(tmp_path: Path) -> None:
    path = tmp_path / "data" / "ABC-D-26-00001 - J - A study.xlsx"
    append_record(path, record())

    workbook = load_workbook(path)
    sheet = workbook[SHEET_TITLE]
    header = [cell.value for cell in sheet[1]]
    assert tuple(header) == COLUMNS
    assert sheet.freeze_panes == "A2"
    values = {label: sheet.cell(2, index + 1).value for index, label in enumerate(header)}
    assert values["Status code"] == 3  # numeric columns are real numbers
    assert values["Reviews completed"] == 0
    assert values["Review invitations sent"] == "2+"
    assert values["Manuscript number"] == "ABC-D-26-00001"
    assert values[DETECTED_AT_COLUMN] == datetime(2026, 1, 2, 9, 30)
    assert sheet.cell(2, header.index(TRACKER_URL_COLUMN) + 1).hyperlink.target == URL
    workbook.close()
    assert not list(path.parent.glob(".*.tmp-*"))  # temporary file cleaned up


def test_read_records_returns_strings(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    append_record(path, record())
    append_record(path, record(**{"Reviews completed": "1", DETECTED_AT_COLUMN: None}))
    records = read_records(path)
    assert len(records) == 2
    assert records[0]["Status code"] == "3"
    assert records[0][DETECTED_AT_COLUMN] == "2026-01-02 09:30:00"
    assert records[1]["Reviews completed"] == "1"
    assert records[1][DETECTED_AT_COLUMN] == ""
    assert last_record(path) == records[1]


def test_appending_to_a_legacy_workbook_adds_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Title", "Status", "Manuscript number"])
    sheet.append(["Old title", "Under Review", "ABC-D-26-00001"])
    workbook.save(path)

    append_record(path, record(Title="New title"))

    records = read_records(path)
    assert records[0] == {
        "Title": "Old title",
        "Status": "Under Review",
        "Manuscript number": "ABC-D-26-00001",
        **{label: "" for label in COLUMNS if label not in {"Title", "Status", "Manuscript number"}},
    }
    assert records[1]["Title"] == "New title"
    assert records[1]["Status code"] == "3"
    header = [cell.value for cell in load_workbook(path).worksheets[0][1]]
    assert header[:3] == ["Title", "Status", "Manuscript number"]
    assert set(COLUMNS) <= set(header)


def test_empty_workbook_has_no_last_record(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    Workbook().save(path)
    assert read_records(path) == []
    assert last_record(path) is None


def test_find_workbook(tmp_path: Path) -> None:
    assert find_workbook(tmp_path / "missing", "ABC-D-26-00001") is None
    (tmp_path / "ABC-D-26-00001 - Journal - Old title.xlsx").touch()
    (tmp_path / "ABC-D-26-000012 - Journal - Other.xlsx").touch()
    (tmp_path / "~$ABC-D-26-00001 - Journal - Old title.xlsx").touch()
    (tmp_path / "ABC-D-26-00001 - notes.txt").touch()
    found = find_workbook(tmp_path, "ABC-D-26-00001")
    assert found is not None
    assert found.name == "ABC-D-26-00001 - Journal - Old title.xlsx"
    assert find_workbook(tmp_path, "abc-d-26-00001") == found
    assert find_workbook(tmp_path, "XYZ-D-26-00001") is None


def test_find_workbook_prefers_the_most_recent_duplicate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    older = tmp_path / "ABC-D-26-00001 - Journal - Title.xlsx"
    newer = tmp_path / "ABC-D-26-00001 - Journal - Title (1).xlsx"
    older.touch()
    newer.touch()
    past = time.time() - 3600
    os.utime(older, (past, past))
    with caplog.at_level(logging.WARNING):
        assert find_workbook(tmp_path, "ABC-D-26-00001") == newer
    assert "Found 2 workbooks" in caplog.text


def test_find_workbook_by_uuid(tmp_path: Path) -> None:
    append_record(tmp_path / "one.xlsx", record())
    append_record(tmp_path / "two.xlsx", record(**{TRACKER_URL_COLUMN: "https://example.org"}))
    (tmp_path / "broken.xlsx").write_text("not a workbook", encoding="utf-8")
    found = find_workbook_by_uuid(tmp_path, "AAAAAAAA-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert found == tmp_path / "one.xlsx"
    assert find_workbook_by_uuid(tmp_path, "11111111-2222-3333-4444-555555555555") is None


def test_locked_workbook_raises_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(src: object, dst: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(storage.os, "replace", locked)
    monkeypatch.setattr(storage, "_REPLACE_DELAY", 0)
    path = tmp_path / "book.xlsx"
    with pytest.raises(WorkbookLockedError, match="open in Excel"):
        append_record(path, record())
    assert not path.exists()
    assert not list(tmp_path.glob(".*.tmp-*"))
