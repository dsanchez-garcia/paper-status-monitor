"""One table with the latest status of every submission (``paper-status-monitor summary``).

The table is built from the workbooks only (nothing is downloaded) and can be
written as plain text, Markdown or a standalone HTML page, in the current language
(see :mod:`~paper_status_monitor.i18n`). It does not include the tracking links, so
it can be shared.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from paper_status_monitor import i18n, storage
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.i18n import N_, _, ngettext
from paper_status_monitor.models import DETECTED_AT_COLUMN, clean_text

#: Formats accepted by :func:`render_summary`.
FORMATS = ("text", "markdown", "html")

#: Column headings, in order (in English; see :func:`headings`).
HEADINGS = (
    "#",
    N_("Submission"),
    N_("Journal"),
    N_("Manuscript number"),
    N_("Status"),
    N_("Since"),
    N_("Reviews"),
    N_("Last review activity"),
)

_TITLE = N_("Paper status summary")
_REVIEW_COLUMNS = ("Reviews completed", "Review invitations accepted", "Review invitations sent")
_TEXT_WIDTHS = {"Submission": 32, "Journal": 30}


def headings() -> tuple[str, ...]:
    """Return :data:`HEADINGS` in the current language."""
    return tuple(_(heading) for heading in HEADINGS)


@dataclass(frozen=True)
class SummaryRow:
    """The latest recorded state of one configured submission.

    Attributes:
        number: Position in the configuration (as shown by ``list``).
        name: Label, else title, else tracking UUID.
        enabled: ``False`` if the submission is paused.
        recorded: ``False`` if nothing has been recorded for it yet.
        journal: Journal name.
        manuscript_number: Latest manuscript number (with the revision suffix).
        status: Latest recorded status.
        since: Date on which the current status was first recorded (``None`` if unknown).
        days: Days since then (``None`` if unknown).
        reviews: Completed reviews / accepted invitations / invitations sent.
        last_review_activity: As shown on the tracking page.
        last_change: When the last row was recorded (``None`` if unknown).
        workbook: Workbook holding the history (``None`` if not recorded yet).
    """

    number: int
    name: str
    enabled: bool = True
    recorded: bool = False
    journal: str = ""
    manuscript_number: str = ""
    status: str = ""
    since: date | None = None
    days: int | None = None
    reviews: str = ""
    last_review_activity: str = ""
    last_change: datetime | None = None
    workbook: Path | None = None

    @property
    def since_text(self) -> str:
        """The date of :attr:`since` and the days elapsed, e.g. ``"2026-09-01 (57 days)"``."""
        if self.since is None:
            return ""
        if self.days is None:
            return self.since.isoformat()
        text = ngettext("{date} ({count} day)", "{date} ({count} days)", self.days)
        return text.format(date=self.since.isoformat(), count=self.days)

    def cells(self) -> tuple[str, ...]:
        """The values of the row, in the order of :data:`HEADINGS` (in the current language)."""
        name = self.name if self.enabled else _("[paused] {name}").format(name=self.name)
        status = self.status if self.recorded else _("not recorded yet")
        return (
            str(self.number),
            name,
            self.journal,
            self.manuscript_number,
            status,
            self.since_text,
            self.reviews,
            self.last_review_activity,
        )


def summary_rows(
    config: Config,
    store: storage.WorkbookStore | None = None,
    *,
    today: Callable[[], date] = date.today,
) -> list[SummaryRow]:
    """Return one row per configured submission, in configuration order.

    Args:
        config: Configuration (submissions and data folder).
        store: Workbook store to read from (a new one is created if omitted).
        today: Clock for the number of days in the current status (for tests).
    """
    store = store or storage.WorkbookStore(config.data_dir)
    return [
        _row(number, submission, store, today())
        for number, submission in enumerate(config.submissions, start=1)
    ]


def _row(
    number: int, submission: SubmissionConfig, store: storage.WorkbookStore, today: date
) -> SummaryRow:
    location = store.locate_uuid(submission.uuid)
    if location is None or location.last_record is None:
        return SummaryRow(number, submission.display_name, enabled=submission.enabled)
    records = store.submission_records(location.path, location.key, submission.uuid)
    last = records[-1] if records else location.last_record
    status = last.get("Status", "")
    first_in_status = last
    for record in reversed(records):
        if record.get("Status", "") != status:
            break
        first_in_status = record
    started = _moment(first_in_status.get(DETECTED_AT_COLUMN, ""))
    since = started.date() if started is not None else None
    counts = [last.get(column, "") for column in _REVIEW_COLUMNS]
    return SummaryRow(
        number=number,
        name=submission.label or last.get("Title", "") or submission.uuid,
        enabled=submission.enabled,
        recorded=True,
        journal=last.get("Journal", ""),
        manuscript_number=last.get("Manuscript number", ""),
        status=status,
        since=since,
        days=(today - since).days if since is not None else None,
        reviews=" / ".join(count or "-" for count in counts) if any(counts) else "",
        last_review_activity=last.get("Last review activity", ""),
        last_change=_moment(last.get(DETECTED_AT_COLUMN, "")),
        workbook=location.path,
    )


def _moment(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.strip()) if text.strip() else None
    except ValueError:
        return None


def render_summary(
    rows: Sequence[SummaryRow], fmt: str = "text", *, generated_at: datetime | None = None
) -> str:
    """Render the summary as ``"text"``, ``"markdown"`` or ``"html"``, in the current language.

    Raises:
        ValueError: If *fmt* is not one of :data:`FORMATS`.
    """
    moment = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    if fmt == "text":
        return render_text(rows, generated_at=moment)
    if fmt == "markdown":
        return render_markdown(rows, generated_at=moment)
    if fmt == "html":
        return render_html(rows, generated_at=moment)
    raise ValueError(f"Unknown format {fmt!r}: use {', '.join(FORMATS)}.")


def render_text(rows: Sequence[SummaryRow], *, generated_at: str = "") -> str:
    """Render the summary as an aligned plain-text table."""
    lines = [f"{_(_TITLE)} - {generated_at}".rstrip(" -"), ""]
    if not rows:
        return "\n".join([*lines, _("No submissions in the configuration.")]) + "\n"
    table = [headings(), *(_shortened(row.cells()) for row in rows)]
    widths = [max(len(cells[index]) for cells in table) for index in range(len(HEADINGS))]
    for cells in table:
        padded = (cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
        lines.append("  ".join(padded).rstrip())
    return "\n".join(lines) + "\n"


def render_markdown(rows: Sequence[SummaryRow], *, generated_at: str = "") -> str:
    """Render the summary as a Markdown (GitHub-flavoured) table."""
    lines = [f"# {_(_TITLE)}", ""]
    if generated_at:
        lines += [_("Generated on {moment}.").format(moment=generated_at), ""]
    if not rows:
        return "\n".join([*lines, _("No submissions in the configuration.")]) + "\n"
    lines.append("| " + " | ".join(headings()) + " |")
    lines.append("| " + " | ".join("---" for _heading in HEADINGS) + " |")
    for row in rows:
        cells = (cell.replace("|", "\\|") or "-" for cell in row.cells())
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_html(rows: Sequence[SummaryRow], *, generated_at: str = "") -> str:
    """Render the summary as a standalone HTML page."""
    title = html.escape(_(_TITLE))
    head = "".join(f"<th>{html.escape(heading)}</th>" for heading in headings())
    body = []
    for row in rows:
        css = "" if row.enabled else ' class="paused"'
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row.cells())
        body.append(f"<tr{css}>{cells}</tr>")
    table = (
        f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n" + "\n".join(body) + "\n</tbody>\n"
        "</table>"
        if rows
        else f"<p>{html.escape(_('No submissions in the configuration.'))}</p>"
    )
    generated = ""
    if generated_at:
        text = _("Generated on {moment}.").format(moment=generated_at)
        generated = f"<p>{html.escape(text)}</p>\n"
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{i18n.get_language()}">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        "<style>\n"
        "body { font-family: system-ui, sans-serif; margin: 2em; }\n"
        "table { border-collapse: collapse; }\n"
        "th, td { border: 1px solid #c8c8c8; padding: 4px 8px; text-align: left; }\n"
        "th { background: #ddebf7; }\n"
        "tr.paused td { color: #808080; }\n"
        "</style>\n</head>\n<body>\n"
        f"<h1>{title}</h1>\n{generated}{table}\n</body>\n</html>\n"
    )


def _shortened(cells: tuple[str, ...]) -> tuple[str, ...]:
    result = []
    for heading, cell in zip(HEADINGS, cells, strict=True):
        text = clean_text(cell) or "-"
        limit = _TEXT_WIDTHS.get(heading)
        if limit is not None and len(text) > limit:
            text = text[: limit - 1].rstrip() + "…"
        result.append(text)
    return tuple(result)
