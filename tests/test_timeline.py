from __future__ import annotations

from datetime import date, datetime
from typing import Any

from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKER_URL_COLUMN, UNAVAILABLE_STATUS
from paper_status_monitor.timeline import as_datetime, status_periods, submission_key, total_days

URL = "https://track.authorhub.elsevier.com/?uuid=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NUMBER = "ABC-D-26-00001"


def row(
    day: int,
    status: str,
    *,
    revision: str = "0",
    number: str = NUMBER,
    journal: str = "Journal A",
    **extra: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        DETECTED_AT_COLUMN: datetime(2026, 1, day, 9, 0),
        "Status": status,
        "Revision": revision,
        "Manuscript number": number,
        "Journal": journal,
    }
    record.update(extra)
    return record


def test_rows_with_the_same_status_and_revision_form_one_period() -> None:
    rows = [
        row(1, "Under Review"),
        row(5, "Under Review", **{"Reviews completed": "1"}),  # another column changed
        row(11, "Required Reviews Complete"),
        row(15, "Review Complete"),
        row(25, "Under Review", revision="1", number=f"{NUMBER}R1"),
    ]
    periods = status_periods(rows)

    summary = [(p.status, p.revision, p.start.day, p.end.day if p.end else None) for p in periods]
    assert summary == [
        ("Under Review", "0", 1, 11),
        ("Required Reviews Complete", "0", 11, 15),
        ("Review Complete", "0", 15, 25),
        ("Under Review", "1", 25, None),
    ]
    assert {(p.submission, p.journal) for p in periods} == {(NUMBER, "Journal A")}
    assert periods[0].days() == 10.0
    assert periods[-1].ongoing
    assert periods[-1].days() is None
    assert periods[-1].days(datetime(2026, 1, 30, 9, 0)) == 5.0


def test_the_submissions_of_a_shared_workbook_are_kept_apart() -> None:
    rows = [
        row(1, "Under Review"),
        row(2, "Under Review", number="XYZ-D-26-00002", journal="Journal B"),
        row(3, "Review Complete"),
    ]
    periods = status_periods(rows)
    assert [(p.submission, p.journal, p.status, p.ongoing) for p in periods] == [
        (NUMBER, "Journal A", "Under Review", False),
        (NUMBER, "Journal A", "Review Complete", True),
        ("XYZ-D-26-00002", "Journal B", "Under Review", True),
    ]


def test_undated_rows_are_skipped_and_old_rows_are_identified_by_their_link() -> None:
    rows = [
        {DETECTED_AT_COLUMN: "", "Status": "Under Review", TRACKER_URL_COLUMN: URL},
        {
            DETECTED_AT_COLUMN: "2026-01-02 09:00:00",
            "Status": "Under Review",
            TRACKER_URL_COLUMN: URL,
        },
        {DETECTED_AT_COLUMN: "not a date", "Status": "Review Complete", TRACKER_URL_COLUMN: URL},
    ]
    [period] = status_periods(rows)
    assert (period.submission, period.journal, period.status, period.revision) == (
        URL,
        "",
        "Under Review",
        "0",
    )
    assert period.start == datetime(2026, 1, 2, 9, 0)
    assert status_periods([]) == []


def test_leaving_the_tracker_ends_the_last_period() -> None:
    under_review, final = status_periods([row(1, "Under Review"), row(9, UNAVAILABLE_STATUS)])
    assert under_review.days() == 8.0
    assert final.final
    assert not final.ongoing
    assert final.days(datetime(2026, 2, 1)) is None
    assert total_days([under_review, final]) == {(NUMBER, "Under Review"): 8.0}


def test_total_days_adds_up_the_periods_of_each_status() -> None:
    periods = status_periods(
        [
            row(1, "Under Review"),
            row(3, "Review Complete"),
            row(4, "Under Review", revision="1"),
            row(10, "Review Complete", revision="1"),
        ]
    )
    assert total_days(periods) == {(NUMBER, "Under Review"): 8.0, (NUMBER, "Review Complete"): 1.0}
    now = datetime(2026, 1, 12, 9, 0)
    assert total_days(periods, now) == {
        (NUMBER, "Under Review"): 8.0,
        (NUMBER, "Review Complete"): 3.0,
    }


def test_rows_out_of_order_never_give_negative_days() -> None:
    first, _ = status_periods([row(9, "Under Review"), row(2, "Review Complete")])
    assert first.days() == 0.0


def test_submission_key_and_as_datetime() -> None:
    assert submission_key({"Manuscript number": f"{NUMBER}R2", TRACKER_URL_COLUMN: URL}) == NUMBER
    assert submission_key({TRACKER_URL_COLUMN: URL}) == URL
    assert submission_key({}) == ""
    assert as_datetime(date(2026, 1, 2)) == datetime(2026, 1, 2)
    assert as_datetime(datetime(2026, 1, 2, 9, 30)) == datetime(2026, 1, 2, 9, 30)
    assert as_datetime("2026-01-02T09:30:00+01:00") == datetime(2026, 1, 2, 9, 30)
    assert as_datetime("  ") is None
    assert as_datetime(None) is None
    assert as_datetime(42) is None
