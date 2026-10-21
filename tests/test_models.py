from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from paper_status_monitor.models import (
    COLUMNS,
    DEFAULT_STATUS_LABEL,
    TRACKED_COLUMNS,
    Change,
    Snapshot,
    cell_to_text,
    clean_text,
    diff_snapshots,
    format_tracker_date,
    ordinal,
    status_label,
    strip_revision_prefix,
)


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (10, "10th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (101, "101st"),
        (111, "111th"),
        (112, "112th"),
    ],
)
def test_ordinal(number: int, expected: str) -> None:
    assert ordinal(number) == expected


def test_format_tracker_date_matches_the_official_page() -> None:
    assert format_tracker_date(1652787284, timezone.utc) == "17th May 2022"
    assert format_tracker_date("1583240028", timezone.utc) == "3rd March 2020"


@pytest.mark.parametrize("value", [None, 0, "", "not a number", True])
def test_format_tracker_date_empty_values(value: object) -> None:
    assert format_tracker_date(value) == ""


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (3, "Under Review"),
        (4, "Required Reviews Complete"),
        (23, "Under Review"),
        (8, "Review Complete"),
        (None, ""),
    ],
)
def test_status_label(code: int | None, label: str) -> None:
    assert status_label(code) == label


def test_snapshot_from_demo_payload(demo_payload: dict) -> None:
    snapshot = Snapshot.from_api(demo_payload, tz=timezone.utc)
    assert snapshot.title.startswith("Influence of submission trackers")
    assert snapshot.revision == "0"
    assert snapshot.status == "Under Review"
    assert snapshot.status_code == "3"
    assert snapshot.last_review_activity == "17th May 2022"
    assert snapshot.reviews_completed == "1"
    assert snapshot.review_invitations_accepted == "2"
    assert snapshot.review_invitations_sent == "2+"
    assert snapshot.journal == "The International Journal of Submission Trackers"
    assert snapshot.corresponding_author == "Maximilian Spillage"
    assert snapshot.first_author == "Zachary Mindwarp"
    assert snapshot.date_of_submission == "3rd March 2020"
    assert snapshot.manuscript_number == "SUBTRAK-D-22-00128"
    assert snapshot.base_manuscript_number == "SUBTRAK-D-22-00128"
    assert snapshot.display_title == snapshot.title


def test_snapshot_revision_handling(make_payload) -> None:
    snapshot = Snapshot.from_api(make_payload(LatestRevisionNumber=2, Status=29), tz=timezone.utc)
    assert snapshot.revision == "2"
    assert snapshot.revision_number == 2
    assert snapshot.manuscript_number == "SUBTRAK-D-22-00128R2"
    assert snapshot.base_manuscript_number == "SUBTRAK-D-22-00128"
    assert snapshot.display_title.startswith("[2nd revision] Influence")
    assert snapshot.status == DEFAULT_STATUS_LABEL
    assert snapshot.status_code == "29"


def test_snapshot_tolerates_missing_fields() -> None:
    snapshot = Snapshot.from_api({"ManuscriptTitle": "  A   title  "})
    assert snapshot.title == "A title"
    assert snapshot.revision == "0"
    assert snapshot.status == ""
    assert snapshot.last_review_activity == ""
    assert snapshot.reviews_completed == ""
    assert snapshot.manuscript_number == ""


def test_record_round_trip(demo_payload: dict) -> None:
    snapshot = Snapshot.from_api(demo_payload, tz=timezone.utc)
    record = snapshot.to_record()
    assert tuple(record) == TRACKED_COLUMNS
    assert Snapshot.from_record(record) == snapshot


def test_from_record_with_excel_types_and_missing_columns() -> None:
    snapshot = Snapshot.from_record({"Title": "T", "Reviews completed": 2, "Revision": None})
    assert snapshot.reviews_completed == "2"
    assert snapshot.revision == "0"
    assert snapshot.status_code == ""


def test_columns_layout() -> None:
    assert COLUMNS[0] == "Detected at"
    assert COLUMNS[-1] == "Tracker URL"
    assert COLUMNS[1:-1] == TRACKED_COLUMNS


def test_diff_snapshots(demo_payload: dict) -> None:
    old = Snapshot.from_api(demo_payload, tz=timezone.utc)
    new = old.replace(status="Required Reviews Complete", status_code="4", reviews_completed="2")
    changes = diff_snapshots(old, new)
    assert changes == [
        Change("Status", "Under Review", "Required Reviews Complete"),
        Change("Status code", "3", "4"),
        Change("Reviews completed", "1", "2"),
    ]
    assert str(changes[2]) == "Reviews completed: '1' → '2'"
    assert diff_snapshots(old, new, ignore=["status code", "Reviews completed"]) == changes[:1]
    assert diff_snapshots(old, old) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (3, "3"),
        (3.0, "3"),
        (2.5, "2.5"),
        (True, "TRUE"),
        (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02 03:04:05"),
        (date(2026, 1, 2), "2026-01-02"),
        ("  a \n b  ", "a b"),
    ],
)
def test_cell_to_text(value: object, expected: str) -> None:
    assert cell_to_text(value) == expected


def test_clean_text_and_strip_revision_prefix() -> None:
    assert clean_text(None) == ""
    assert strip_revision_prefix("[1st revision] My paper") == "My paper"
    assert strip_revision_prefix("[12th Revision]   My paper") == "My paper"
    assert strip_revision_prefix("My [1st revision] paper") == "My [1st revision] paper"
