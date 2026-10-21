"""Data model: snapshots of a submission and the changes between two snapshots.

A :class:`Snapshot` holds exactly what the official *Track your submission* page
shows for a manuscript. Every value is kept as a display string so that it can be
stored in Excel and compared without type surprises.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

#: Labels shown by the official tracking page for specific status codes.
#: Every other code is displayed as :data:`DEFAULT_STATUS_LABEL` by that page.
STATUS_LABELS: dict[int, str] = {
    3: "Under Review",
    4: "Required Reviews Complete",
    23: "Under Review",
}

#: Label the official page uses for any status code not in :data:`STATUS_LABELS`.
DEFAULT_STATUS_LABEL = "Review Complete"

#: Status recorded when the tracker stops returning data for a known submission.
UNAVAILABLE_STATUS = "No longer available in the tracker"

#: Mapping of :class:`Snapshot` attribute names to workbook column labels.
FIELD_LABELS: dict[str, str] = {
    "title": "Title",
    "revision": "Revision",
    "status": "Status",
    "status_code": "Status code",
    "last_review_activity": "Last review activity",
    "reviews_completed": "Reviews completed",
    "review_invitations_accepted": "Review invitations accepted",
    "review_invitations_sent": "Review invitations sent",
    "journal": "Journal",
    "corresponding_author": "Corresponding author",
    "first_author": "First author",
    "date_of_submission": "Date of submission",
    "manuscript_number": "Manuscript number",
}

#: Columns compared between two snapshots to detect changes.
TRACKED_COLUMNS: tuple[str, ...] = tuple(FIELD_LABELS.values())

#: Metadata column with the local date and time at which a row was recorded.
DETECTED_AT_COLUMN = "Detected at"

#: Metadata column with the link to the official tracking page.
TRACKER_URL_COLUMN = "Tracker URL"

#: All workbook columns, in order. Metadata columns are never compared.
COLUMNS: tuple[str, ...] = (DETECTED_AT_COLUMN, *TRACKED_COLUMNS, TRACKER_URL_COLUMN)

#: Columns whose purely numeric values are written to Excel as numbers.
NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {
        "Revision",
        "Status code",
        "Reviews completed",
        "Review invitations accepted",
        "Review invitations sent",
    }
)

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_REVISION_SUFFIX = re.compile(r"R(\d+)$")
_REVISION_PREFIX = re.compile(r"^\[\d+(?:st|nd|rd|th) revision\]\s*", re.IGNORECASE)


def ordinal(number: int) -> str:
    """Return the English ordinal of *number* (``1`` -> ``"1st"``, ``12`` -> ``"12th"``)."""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def format_tracker_date(timestamp: Any, tz: tzinfo | None = None) -> str:
    """Format a Unix timestamp the way the tracking page does (``"25th January 2025"``).

    Args:
        timestamp: Seconds since the epoch, as returned by the tracker.
        tz: Time zone used for the conversion. ``None`` uses the local time zone,
            which is what the browser does on the official page.

    Returns:
        The formatted date, or an empty string when *timestamp* is empty or zero.
    """
    seconds = _to_number(timestamp)
    if not seconds:
        return ""
    try:
        moment = datetime.fromtimestamp(seconds, tz=tz)
    except (OverflowError, OSError, ValueError):
        return str(timestamp)
    return f"{ordinal(moment.day)} {_MONTHS[moment.month - 1]} {moment.year}"


def status_label(code: int | None) -> str:
    """Return the label the official page shows for a numeric status *code*."""
    if code is None:
        return ""
    return STATUS_LABELS.get(code, DEFAULT_STATUS_LABEL)


def clean_text(value: Any) -> str:
    """Convert *value* to a single-line string with collapsed whitespace."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def cell_to_text(value: Any) -> str:
    """Normalise a value read from Excel (or from the API) to a comparable string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return clean_text(value)


def strip_revision_prefix(title: str) -> str:
    """Remove a leading ``"[1st revision] "``-style prefix from a displayed title."""
    return _REVISION_PREFIX.sub("", title)


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


@dataclass(frozen=True)
class Snapshot:
    """What the tracking page shows for a submission at a given moment.

    Attributes mirror the workbook columns listed in :data:`FIELD_LABELS`. All
    values are display strings (for example ``revision="1"`` or
    ``review_invitations_sent="2+"``).
    """

    title: str = ""
    revision: str = "0"
    status: str = ""
    status_code: str = ""
    last_review_activity: str = ""
    reviews_completed: str = ""
    review_invitations_accepted: str = ""
    review_invitations_sent: str = ""
    journal: str = ""
    corresponding_author: str = ""
    first_author: str = ""
    date_of_submission: str = ""
    manuscript_number: str = ""

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], tz: tzinfo | None = None) -> Snapshot:
        """Build a snapshot from the JSON document returned by the tracker API.

        The conversion reproduces the official page: the revision number is
        appended to the manuscript number (``"ABC-D-24-00001R1"``), status codes
        are translated with :func:`status_label` and timestamps are formatted with
        :func:`format_tracker_date`.
        """
        revision = _to_int(payload.get("LatestRevisionNumber")) or 0
        number = clean_text(payload.get("PubdNumber"))
        code = _to_int(payload.get("Status"))
        summary = payload.get("ReviewSummary")
        if not isinstance(summary, Mapping):
            summary = {}
        return cls(
            title=clean_text(payload.get("ManuscriptTitle")),
            revision=str(revision),
            status=status_label(code),
            status_code="" if code is None else str(code),
            last_review_activity=format_tracker_date(payload.get("LastUpdated"), tz),
            reviews_completed=clean_text(summary.get("ReviewsCompleted")),
            review_invitations_accepted=clean_text(summary.get("ReviewInvitationsAccepted")),
            review_invitations_sent=clean_text(summary.get("ReviewInvitationsSent")),
            journal=clean_text(payload.get("JournalName")),
            corresponding_author=clean_text(payload.get("CorrespondingAuthor")),
            first_author=clean_text(payload.get("FirstAuthor")),
            date_of_submission=format_tracker_date(payload.get("SubmissionDate"), tz),
            manuscript_number=f"{number}R{revision}" if number and revision > 0 else number,
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Snapshot:
        """Build a snapshot from a workbook row (a mapping of column label to value).

        Missing columns become empty strings, so rows written by older versions
        can still be compared.
        """
        values = {attr: cell_to_text(record.get(label)) for attr, label in FIELD_LABELS.items()}
        if not values["revision"]:
            values["revision"] = "0"
        return cls(**values)

    def to_record(self) -> dict[str, str]:
        """Return the snapshot as a mapping of column label to value."""
        return {label: getattr(self, attr) for attr, label in FIELD_LABELS.items()}

    def replace(self, **changes: str) -> Snapshot:
        """Return a copy of the snapshot with some attributes replaced."""
        return dataclasses.replace(self, **changes)

    @property
    def revision_number(self) -> int:
        """Revision number as an integer (``0`` for the original submission)."""
        return _to_int(self.revision) or 0

    @property
    def base_manuscript_number(self) -> str:
        """Manuscript number without the revision suffix (``"ABC-D-24-00001"``).

        It identifies one manuscript in one journal and is therefore used as the
        key of the workbook: every revision of the manuscript shares it.
        """
        return _REVISION_SUFFIX.sub("", self.manuscript_number)

    @property
    def display_title(self) -> str:
        """Title as shown by the tracking page, e.g. ``"[1st revision] My paper"``."""
        number = self.revision_number
        return self.title if number == 0 else f"[{ordinal(number)} revision] {self.title}"


@dataclass(frozen=True)
class Change:
    """A difference in one column between two snapshots."""

    field: str
    old: str
    new: str

    def __str__(self) -> str:
        return f"{self.field}: '{self.old}' → '{self.new}'"


def diff_snapshots(old: Snapshot, new: Snapshot, ignore: Iterable[str] = ()) -> list[Change]:
    """Return the list of tracked columns whose value differs between two snapshots.

    Args:
        old: Previously recorded snapshot.
        new: Freshly fetched snapshot.
        ignore: Column labels (case-insensitive) that should not be compared.
    """
    ignored = {label.casefold() for label in ignore}
    before, after = old.to_record(), new.to_record()
    return [
        Change(label, before[label], after[label])
        for label in TRACKED_COLUMNS
        if label.casefold() not in ignored and before[label] != after[label]
    ]
