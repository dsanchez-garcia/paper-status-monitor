"""Export the recorded history to CSV or JSON (``paper-status-monitor export``).

The rows are read from the workbooks (nothing is downloaded), for people who prefer
other tools than Excel. The tracking links, which are personal, are left out unless
they are asked for, so an export can be shared.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from paper_status_monitor import naming, storage
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import COLUMNS, TRACKER_URL_COLUMN

#: Formats accepted by :func:`render_export`.
FORMATS = ("csv", "json")


@dataclass(frozen=True)
class SubmissionHistory:
    """The recorded rows of one configured submission.

    Attributes:
        number: Position in the configuration (as shown by ``list``).
        submission: The configured submission.
        rows: Its rows, oldest first (column label to text).
    """

    number: int
    submission: SubmissionConfig
    rows: tuple[dict[str, str], ...] = ()

    def name(self, *, include_links: bool = False) -> str:
        """The label; without one, the UUID if links are exported, else ``Submission N``."""
        if self.submission.label:
            return self.submission.label
        return self.submission.uuid if include_links else f"Submission {self.number}"


def collect_history(
    config: Config, store: storage.WorkbookStore | None = None
) -> list[SubmissionHistory]:
    """Return the recorded rows of every configured submission, in configuration order."""
    store = store or storage.WorkbookStore(config.data_dir)
    histories = []
    for number, submission in enumerate(config.submissions, start=1):
        location = store.locate_uuid(submission.uuid)
        rows: tuple[dict[str, str], ...] = ()
        if location is not None:
            rows = tuple(store.submission_records(location.path, location.key, submission.uuid))
        histories.append(SubmissionHistory(number, submission, rows))
    return histories


def export_columns(
    histories: Sequence[SubmissionHistory], *, include_links: bool = False
) -> list[str]:
    """Return the columns of an export: the workbook columns, then the custom fields."""
    columns = [column for column in COLUMNS if include_links or column != TRACKER_URL_COLUMN]
    custom = sorted(
        {
            naming.custom_field_column(name)
            for history in histories
            for name in history.submission.fields
        }
    )
    return [*columns, *custom]


def render_csv(histories: Sequence[SubmissionHistory], *, include_links: bool = False) -> str:
    """One row per observed state, with the name of the submission in the first column."""
    columns = export_columns(histories, include_links=include_links)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Submission", *columns])
    for history in histories:
        name = history.name(include_links=include_links)
        for row in history.rows:
            writer.writerow([name, *(row.get(column, "") for column in columns)])
    return buffer.getvalue()


def render_json(
    histories: Sequence[SubmissionHistory],
    *,
    include_links: bool = False,
    generated_at: datetime | None = None,
) -> str:
    """The rows grouped by submission, with its custom fields."""
    columns = export_columns(histories, include_links=include_links)
    submissions = []
    for history in histories:
        entry: dict[str, object] = {
            "submission": history.name(include_links=include_links),
            "fields": dict(history.submission.fields),
        }
        if include_links:
            entry["tracker_url"] = history.submission.tracker_url
        entry["rows"] = [
            {column: row.get(column, "") for column in columns} for row in history.rows
        ]
        submissions.append(entry)
    moment = (generated_at or datetime.now()).isoformat(timespec="seconds")
    data = {"generated_at": moment, "submissions": submissions}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_export(
    histories: Sequence[SubmissionHistory], fmt: str = "csv", *, include_links: bool = False
) -> str:
    """Render the history as ``"csv"`` or ``"json"``.

    Raises:
        ValueError: If *fmt* is not one of :data:`FORMATS`.
    """
    if fmt == "csv":
        return render_csv(histories, include_links=include_links)
    if fmt == "json":
        return render_json(histories, include_links=include_links)
    raise ValueError(f"Unknown format {fmt!r}: use {', '.join(FORMATS)}.")
