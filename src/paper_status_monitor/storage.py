"""Excel storage: one workbook per manuscript, one row per observed state.

A workbook is identified by the *base* manuscript number (without the ``R1``,
``R2``... revision suffix), so every revision of a manuscript submitted to one
journal is appended to the same file. The file name also contains the journal and
the title to make it easy to recognise, e.g.::

    ABC-D-24-00001 - Journal of Examples - A study of something.xlsx

Only the ``"ABC-D-24-00001 - "`` prefix is used to find the file again, so later
changes in the title do not create new files.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from paper_status_monitor.models import (
    COLUMNS,
    DETECTED_AT_COLUMN,
    NUMERIC_COLUMNS,
    TRACKER_URL_COLUMN,
    cell_to_text,
)

log = logging.getLogger(__name__)

#: Name of the worksheet that holds the history.
SHEET_TITLE = "History"

#: Maximum length of a workbook file name without the extension.
MAX_STEM_LENGTH = 150

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_HEADER_FONT = Font(bold=True)
_HEADER_FILL = PatternFill("solid", start_color="DDEBF7", end_color="DDEBF7")
_HEADER_ALIGNMENT = Alignment(wrap_text=True, vertical="center")
_COLUMN_WIDTHS = {
    DETECTED_AT_COLUMN: 18,
    "Title": 60,
    "Revision": 10,
    "Status": 26,
    "Status code": 10,
    "Last review activity": 22,
    "Reviews completed": 11,
    "Review invitations accepted": 12,
    "Review invitations sent": 12,
    "Journal": 32,
    "Corresponding author": 24,
    "First author": 24,
    "Date of submission": 22,
    "Manuscript number": 20,
    TRACKER_URL_COLUMN: 45,
}
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY = 0.5


class WorkbookLockedError(OSError):
    """The workbook could not be written, typically because it is open in Excel."""


def sanitize_filename(text: str) -> str:
    """Remove characters that are not allowed in Windows file names."""
    cleaned = _INVALID_CHARS.sub("", text)
    cleaned = " ".join(cleaned.split())
    return cleaned.strip(" .")


def workbook_name(key: str, journal: str = "", title: str = "") -> str:
    """Return the file name of a new workbook.

    Args:
        key: Base manuscript number (or the tracking UUID if it is unknown).
        journal: Journal name, added for readability.
        title: Manuscript title, added for readability (truncated if needed).

    Raises:
        ValueError: If *key* is empty after sanitisation.
    """
    clean_key = sanitize_filename(key)
    if not clean_key:
        raise ValueError("A workbook key (manuscript number or UUID) is required.")
    parts = [clean_key, *(p for p in (sanitize_filename(journal), sanitize_filename(title)) if p)]
    stem = " - ".join(parts)
    if len(stem) > MAX_STEM_LENGTH:
        cut = stem[:MAX_STEM_LENGTH]
        if " " in cut[len(clean_key) + 3 :]:
            cut = cut.rsplit(" ", 1)[0]
        stem = cut.rstrip(" .-")
    return f"{stem}.xlsx"


def _workbook_files(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if (
            path.suffix.lower() == ".xlsx"
            and not path.name.startswith(("~$", "."))
            and path.is_file()
        ):
            yield path


def find_workbook(directory: Path, key: str) -> Path | None:
    """Return the existing workbook for *key* in *directory*, or ``None``.

    A workbook matches when its name is ``"<key>.xlsx"``, starts with
    ``"<key> - "`` or is a sync-client duplicate such as ``"<key> (1).xlsx"``.
    If several files match, the most recently modified one is returned and a
    warning is logged.
    """
    prefix = sanitize_filename(key).casefold()
    if not prefix:
        return None
    matches = [
        path
        for path in _workbook_files(directory)
        if path.stem.casefold() == prefix
        or path.stem.casefold().startswith((f"{prefix} - ", f"{prefix} ("))
    ]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if len(matches) > 1:
        log.warning(
            "Found %d workbooks for %s; using the most recently modified one (%s). "
            "Please merge or delete the others: %s",
            len(matches),
            key,
            matches[0].name,
            ", ".join(p.name for p in matches[1:]),
        )
    return matches[0]


def find_workbook_by_uuid(directory: Path, uuid: str) -> Path | None:
    """Return the workbook whose ``Tracker URL`` column mentions *uuid*, or ``None``."""
    needle = uuid.casefold()
    for path in _workbook_files(directory):
        try:
            records = read_records(path)
        except Exception as exc:  # unreadable or foreign workbook: skip it
            log.debug("Skipping %s while looking for %s: %s", path.name, uuid, exc)
            continue
        if any(needle in record.get(TRACKER_URL_COLUMN, "").casefold() for record in records):
            return path
    return None


def _history_sheet(workbook: Workbook) -> Worksheet:
    if SHEET_TITLE in workbook.sheetnames:
        return workbook[SHEET_TITLE]
    return workbook.worksheets[0]


def read_records(path: Path) -> list[dict[str, str]]:
    """Read every data row of a workbook as a mapping of column label to string."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = _history_sheet(workbook).iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            return []
        labels = [cell_to_text(value) for value in header]
        records = []
        for row in rows:
            values = [cell_to_text(value) for value in row]
            if not any(values):
                continue
            values += [""] * (len(labels) - len(values))
            records.append({label: values[i] for i, label in enumerate(labels) if label})
        return records
    finally:
        workbook.close()


def last_record(path: Path) -> dict[str, str] | None:
    """Return the last data row of a workbook, or ``None`` if it has no data rows."""
    records = read_records(path)
    return records[-1] if records else None


def append_record(path: Path, record: Mapping[str, Any]) -> None:
    """Append one row to the workbook at *path*, creating the file if needed.

    Values are written under the matching header. Columns missing from an older
    workbook are added at the end of the header, so files written by previous
    versions keep working. The file is replaced atomically.

    Raises:
        WorkbookLockedError: If the file cannot be replaced (e.g. open in Excel).
    """
    if path.exists():
        workbook = load_workbook(path)
        sheet = _history_sheet(workbook)
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = SHEET_TITLE
    try:
        header = _ensure_header(sheet, [*COLUMNS, *record.keys()])
        row = _last_used_row(sheet) + 1
        for label, value in record.items():
            cell = sheet.cell(row=row, column=header.index(label) + 1, value=_to_cell(label, value))
            if isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
            elif label == TRACKER_URL_COLUMN and isinstance(value, str) and value:
                cell.hyperlink = value
                cell.style = "Hyperlink"
        last_column = get_column_letter(len(header))
        sheet.auto_filter.ref = f"A1:{last_column}{row}"
        sheet.freeze_panes = "A2"
        _save_atomic(workbook, path)
    finally:
        workbook.close()


def _ensure_header(sheet: Worksheet, labels: list[str]) -> list[str]:
    """Make sure every label is present in the first row; return the header."""
    if sheet.max_row == 1 and sheet.max_column == 1 and sheet.cell(1, 1).value is None:
        header: list[str] = []
    else:
        header = [cell_to_text(cell.value) for cell in sheet[1]]
        while header and not header[-1]:
            header.pop()
    for label in labels:
        if label in header:
            continue
        header.append(label)
        column = len(header)
        cell = sheet.cell(row=1, column=column, value=label)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT
        width = _COLUMN_WIDTHS.get(label, 18)
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[1].height = 30
    return header


def _last_used_row(sheet: Worksheet) -> int:
    for row in range(sheet.max_row, 0, -1):
        if any(cell.value not in (None, "") for cell in sheet[row]):
            return row
    return 0


def _to_cell(label: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if not text:
        return None
    if label in NUMERIC_COLUMNS and text.isascii() and text.isdigit():
        return int(text)
    return text


def _save_atomic(workbook: Workbook, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp-{os.getpid()}.xlsx")
    try:
        workbook.save(temporary)
        for attempt in range(1, _REPLACE_ATTEMPTS + 1):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                if attempt == _REPLACE_ATTEMPTS:
                    raise WorkbookLockedError(
                        f"Cannot write {path.name}: the file is in use. Is it open in Excel?"
                    ) from exc
                time.sleep(_REPLACE_DELAY)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                log.debug("Could not remove temporary file %s", temporary)
