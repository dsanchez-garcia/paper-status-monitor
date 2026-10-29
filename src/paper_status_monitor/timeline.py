"""Periods of time that a submission spent in each status.

Every row of a workbook is an observed state of a submission. Consecutive rows of a
submission with the same status and revision form one :class:`StatusPeriod`, which
lasts until the next status was recorded. The optional *Time in status* sheet of the
workbooks (``time_in_status`` setting, see :mod:`~paper_status_monitor.storage`)
lists these periods and the total time spent in each status.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from paper_status_monitor.models import (
    DETECTED_AT_COLUMN,
    MANUSCRIPT_NUMBER_COLUMN,
    TRACKER_URL_COLUMN,
    UNAVAILABLE_STATUS,
    base_manuscript_number,
    cell_to_text,
)

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class StatusPeriod:
    """A stretch of time during which a submission kept the same status and revision.

    Attributes:
        submission: Base manuscript number of the submission (its tracking link if
            the rows have no manuscript number, ``""`` if they have neither).
        journal: Journal name.
        revision: Revision number as text (``"0"`` for the original submission).
        status: Status shown by the tracker.
        start: When the status was first recorded.
        end: When the next status was recorded, or ``None`` if the submission is
            still in this status.
    """

    submission: str
    journal: str
    revision: str
    status: str
    start: datetime
    end: datetime | None = None

    @property
    def final(self) -> bool:
        """``True`` if the submission left the tracker: the period has no length."""
        return self.status == UNAVAILABLE_STATUS

    @property
    def ongoing(self) -> bool:
        """``True`` if the submission is still in this status."""
        return self.end is None and not self.final

    def days(self, now: datetime | None = None) -> float | None:
        """Return the length of the period in days.

        Args:
            now: End used for an ongoing period.

        Returns:
            ``None`` for a final period, or for an ongoing one without *now*.
        """
        end = self.end if self.end is not None else now
        if self.final or end is None:
            return None
        return max(0.0, (end - self.start).total_seconds() / _SECONDS_PER_DAY)


def submission_key(record: Mapping[str, Any]) -> str:
    """Return what identifies the submission of a workbook row.

    That is its base manuscript number, else its tracking link, else ``""``.
    """
    number = cell_to_text(record.get(MANUSCRIPT_NUMBER_COLUMN))
    if number:
        return base_manuscript_number(number)
    return cell_to_text(record.get(TRACKER_URL_COLUMN))


def status_periods(records: Iterable[Mapping[str, Any]]) -> list[StatusPeriod]:
    """Split the rows of a workbook into periods of the same status and revision.

    Rows are grouped by submission (see :func:`submission_key`) in order of first
    appearance; the rows of a submission are expected in chronological order, as
    they are written. Rows without a ``Detected at`` date cannot be placed in time
    and are skipped.

    Args:
        records: Workbook rows (column label to value).
    """
    groups: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = {}
    for record in records:
        moment = as_datetime(record.get(DETECTED_AT_COLUMN))
        if moment is not None:
            groups.setdefault(submission_key(record), []).append((moment, record))
    periods: list[StatusPeriod] = []
    for key, rows in groups.items():
        journals = (cell_to_text(row.get("Journal")) for _, row in reversed(rows))
        journal = next((name for name in journals if name), "")
        current: StatusPeriod | None = None
        for moment, row in rows:
            status = cell_to_text(row.get("Status")) or "-"
            revision = cell_to_text(row.get("Revision")) or "0"
            if current is not None and (current.status, current.revision) == (status, revision):
                continue
            if current is not None:
                periods.append(dataclasses.replace(current, end=moment))
            current = StatusPeriod(key, journal, revision, status, moment)
        if current is not None:
            periods.append(current)
    return periods


def total_days(
    periods: Iterable[StatusPeriod], now: datetime | None = None
) -> dict[tuple[str, str], float]:
    """Return the days spent in each status, per submission.

    Args:
        periods: Periods from :func:`status_periods`.
        now: End of the ongoing periods (without it, they are not counted).

    Returns:
        ``{(submission, status): days}``, in order of first appearance. Final
        periods (the submission left the tracker) are left out.
    """
    totals: dict[tuple[str, str], float] = {}
    for period in periods:
        if period.final:
            continue
        key = (period.submission, period.status)
        totals[key] = totals.get(key, 0.0) + (period.days(now) or 0.0)
    return totals


def as_datetime(value: Any) -> datetime | None:
    """Convert a ``Detected at`` cell (a date, a date and time, or ISO text) to a datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).replace(tzinfo=None)
        except ValueError:
            return None
    return None
