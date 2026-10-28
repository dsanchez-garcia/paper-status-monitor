"""Contract tests: the real tracker still answers in the format this package expects.

They need the network, so they are deselected by default. Run them with::

    python -m pytest -m network

The scheduled workflow ``.github/workflows/contract.yml`` runs them every week and
opens an issue when they fail twice in a row, which usually means that the tracker
changed its data format. Only the public demo submission and an obviously fake UUID
are requested.
"""

from __future__ import annotations

import warnings
from datetime import timezone
from typing import Any

import pytest

from paper_status_monitor.client import DEMO_UUID, SubmissionNotFoundError, TrackerClient
from paper_status_monitor.models import (
    DEFAULT_STATUS_LABEL,
    STATUS_LABELS,
    Snapshot,
    parse_tracker_date,
)

pytestmark = pytest.mark.network

#: A UUID that no submission has: it must answer HTTP 404, like a finished submission.
UNKNOWN_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

#: Fields of the JSON record read by :meth:`Snapshot.from_api`.
FIELDS = (
    "ManuscriptTitle",
    "PubdNumber",
    "JournalName",
    "FirstAuthor",
    "CorrespondingAuthor",
    "Status",
    "LatestRevisionNumber",
    "LastUpdated",
    "SubmissionDate",
    "ReviewSummary",
)

#: Fields that hold numbers (status code, revision number and Unix timestamps).
NUMERIC_FIELDS = ("Status", "LatestRevisionNumber", "LastUpdated", "SubmissionDate")

#: Fields of ``ReviewSummary``.
SUMMARY_FIELDS = ("ReviewsCompleted", "ReviewInvitationsAccepted", "ReviewInvitationsSent")


@pytest.fixture(scope="module")
def live_payload() -> dict[str, Any]:
    """The demo record, downloaded once for the whole module."""
    with TrackerClient(timeout=30) as client:
        return client.fetch_json(DEMO_UUID)


def test_demo_record_has_the_fields_read_by_the_monitor(live_payload: dict[str, Any]) -> None:
    missing = [name for name in FIELDS if name not in live_payload]
    assert missing == [], f"the tracker no longer returns {missing}"
    summary = live_payload["ReviewSummary"]
    assert isinstance(summary, dict), f"ReviewSummary is no longer an object: {summary!r}"
    missing_summary = [name for name in SUMMARY_FIELDS if name not in summary]
    assert missing_summary == [], f"ReviewSummary no longer has {missing_summary}"


@pytest.mark.parametrize("name", NUMERIC_FIELDS)
def test_numeric_fields_are_still_numbers(live_payload: dict[str, Any], name: str) -> None:
    value = live_payload.get(name)
    assert type(value) is int, f"{name} is now {value!r}"


def test_live_record_converts_like_the_official_page(live_payload: dict[str, Any]) -> None:
    snapshot = Snapshot.from_api(live_payload, tz=timezone.utc)
    assert snapshot.title
    assert snapshot.journal
    assert snapshot.manuscript_number
    assert snapshot.status in {*STATUS_LABELS.values(), DEFAULT_STATUS_LABEL}
    assert snapshot.status_code.isdigit()
    assert parse_tracker_date(snapshot.date_of_submission) is not None
    assert parse_tracker_date(snapshot.last_review_activity) is not None
    assert snapshot.reviews_completed
    assert snapshot.review_invitations_sent


def test_stored_copy_of_the_demo_record_is_up_to_date(
    live_payload: dict[str, Any], demo_payload: dict[str, Any]
) -> None:
    """The offline tests use ``tests/data/demo_submission.json``: keep it in line."""
    removed = sorted(set(demo_payload) - set(live_payload))
    assert removed == [], f"fields of the stored copy missing from the tracker: {removed}"
    added = sorted(set(live_payload) - set(demo_payload))
    if added:
        warnings.warn(f"the tracker returns new fields: {added}", stacklevel=1)
    live = Snapshot.from_api(live_payload, tz=timezone.utc)
    stored = Snapshot.from_api(demo_payload, tz=timezone.utc)
    assert live == stored, "the demo record changed: update tests/data/demo_submission.json"


def test_unknown_submissions_answer_not_found() -> None:
    """Finished submissions are detected through this answer (HTTP 404)."""
    with TrackerClient(timeout=30) as client, pytest.raises(SubmissionNotFoundError):
        client.fetch_json(UNKNOWN_UUID)
