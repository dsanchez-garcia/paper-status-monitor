from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from paper_status_monitor.client import (
    DEMO_UUID,
    SubmissionNotFoundError,
    TrackerUnavailableError,
)
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKER_URL_COLUMN, UNAVAILABLE_STATUS
from paper_status_monitor.monitor import Monitor
from paper_status_monitor.storage import read_records

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


def workbooks(config: Config) -> list[Path]:
    return sorted(config.data_dir.glob("*.xlsx"))


def test_first_run_creates_one_workbook(config, fake_client, make_payload, clock) -> None:
    fake_client.queue(DEMO_UUID, make_payload())
    summary = Monitor(config, fake_client, now=clock).run()

    [result] = summary.results
    assert result.ok
    assert result.is_new
    assert result.changes == []
    assert summary.changed == [result]
    [path] = workbooks(config)
    assert path == result.workbook
    assert path.name.startswith(
        "SUBTRAK-D-22-00128 - The International Journal of Submission Trackers - Influence"
    )
    [row] = read_records(path)
    assert row[DETECTED_AT_COLUMN] == "2026-01-02 09:30:00"
    assert row["Status"] == "Under Review"
    assert row[TRACKER_URL_COLUMN].endswith(DEMO_UUID)


def test_unchanged_status_adds_no_row(config, fake_client, make_payload, clock) -> None:
    fake_client.queue(DEMO_UUID, make_payload(), make_payload())
    monitor = Monitor(config, fake_client, now=clock)
    monitor.run()
    summary = monitor.run()

    [result] = summary.results
    assert result.ok
    assert not result.is_new
    assert result.changes == []
    assert summary.changed == []
    assert len(read_records(workbooks(config)[0])) == 1


def test_changes_are_detected_and_appended(config, fake_client, make_payload, clock) -> None:
    fake_client.queue(
        DEMO_UUID,
        make_payload(),
        make_payload(Status=4, LastUpdated=1652887284, ReviewsCompleted_summary="2"),
    )
    monitor = Monitor(config, fake_client, now=clock)
    monitor.run()
    clock.advance(days=1)
    summary = monitor.run()

    [result] = summary.results
    assert [str(change) for change in result.changes] == [
        "Status: 'Under Review' → 'Required Reviews Complete'",
        "Status code: '3' → '4'",
        "Last review activity: '17th May 2022' → '18th May 2022'",
        "Reviews completed: '1' → '2'",
    ]
    rows = read_records(workbooks(config)[0])
    assert [row["Status"] for row in rows] == ["Under Review", "Required Reviews Complete"]
    assert rows[1][DETECTED_AT_COLUMN] == "2026-01-03 09:30:00"


def test_revisions_share_the_same_workbook(config, fake_client, make_payload, clock) -> None:
    fake_client.queue(
        DEMO_UUID,
        make_payload(),
        make_payload(LatestRevisionNumber=1, Status=3, ReviewsCompleted_summary="0"),
    )
    monitor = Monitor(config, fake_client, now=clock)
    monitor.run()
    summary = monitor.run()

    [result] = summary.results
    assert not result.is_new
    fields = [change.field for change in result.changes]
    assert fields == ["Revision", "Reviews completed", "Manuscript number"]
    [path] = workbooks(config)
    rows = read_records(path)
    assert [row["Manuscript number"] for row in rows] == [
        "SUBTRAK-D-22-00128",
        "SUBTRAK-D-22-00128R1",
    ]


def test_ignored_fields_are_recorded_but_not_reported(
    config, fake_client, make_payload, clock
) -> None:
    config = replace(config, ignore_fields=("Status code",))
    fake_client.queue(DEMO_UUID, make_payload(Status=8), make_payload(Status=9))
    monitor = Monitor(config, fake_client, now=clock)
    monitor.run()
    summary = monitor.run()

    assert summary.results[0].changes == []
    assert summary.changed == []
    rows = read_records(workbooks(config)[0])
    assert [row["Status code"] for row in rows] == ["8", "9"]


def test_unknown_uuid_is_an_error(config, fake_client) -> None:
    fake_client.queue(DEMO_UUID, SubmissionNotFoundError("HTTP 404"))
    summary = Monitor(config, fake_client).run()

    [result] = summary.results
    assert not result.ok
    assert "404" in (result.error or "")
    assert summary.failed == [result]
    assert workbooks(config) == []


def test_known_submission_disappearing_is_recorded_once(
    config, fake_client, make_payload, clock
) -> None:
    fake_client.queue(
        DEMO_UUID,
        make_payload(Status=29),
        SubmissionNotFoundError("HTTP 404"),
        SubmissionNotFoundError("HTTP 404"),
    )
    monitor = Monitor(config, fake_client, now=clock)
    monitor.run()
    second = monitor.run()
    third = monitor.run()

    [result] = second.results
    assert result.ok
    assert [str(change) for change in result.changes] == [
        f"Status: 'Review Complete' → '{UNAVAILABLE_STATUS}'",
        "Status code: '29' → ''",
    ]
    assert third.results[0].ok
    assert third.results[0].changes == []
    rows = read_records(workbooks(config)[0])
    assert [row["Status"] for row in rows] == ["Review Complete", UNAVAILABLE_STATUS]


def test_network_errors_do_not_write_anything(config, fake_client) -> None:
    fake_client.queue(DEMO_UUID, TrackerUnavailableError("offline"))
    summary = Monitor(config, fake_client).run()
    assert summary.failed
    assert summary.results[0].error == "offline"
    assert workbooks(config) == []


def test_one_failure_does_not_stop_the_others(config, fake_client, make_payload) -> None:
    config = replace(
        config,
        submissions=(SubmissionConfig(OTHER_UUID), *config.submissions),
    )
    fake_client.queue(OTHER_UUID, TrackerUnavailableError("offline"))
    fake_client.queue(DEMO_UUID, make_payload())
    summary = Monitor(config, fake_client).run()
    assert [result.ok for result in summary.results] == [False, True]
    assert len(workbooks(config)) == 1


def test_unexpected_errors_are_captured(config, fake_client, make_payload, monkeypatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("paper_status_monitor.storage.append_record", explode)
    fake_client.queue(DEMO_UUID, make_payload())
    summary = Monitor(config, fake_client).run()
    assert summary.results[0].error == "RuntimeError: disk on fire"


def test_dry_run_writes_nothing(config, fake_client, make_payload) -> None:
    fake_client.queue(DEMO_UUID, make_payload())
    summary = Monitor(config, fake_client).run(dry_run=True)
    assert summary.results[0].is_new
    assert not config.data_dir.exists()


def test_disabled_submissions_are_skipped(config, fake_client) -> None:
    config = replace(config, submissions=(SubmissionConfig(DEMO_UUID, enabled=False),))
    summary = Monitor(config, fake_client).run()
    assert summary.results == []
    assert fake_client.calls == []


def test_wait_until_ready_creates_the_data_folder(config, fake_client) -> None:
    config.data_dir.parent.mkdir(parents=True, exist_ok=True)
    problems = Monitor(config, fake_client).wait_until_ready(timeout=0)
    assert problems == []
    assert config.data_dir.is_dir()


def test_wait_until_ready_reports_problems_after_the_timeout(tmp_path, fake_client) -> None:
    config = Config(data_dir=tmp_path / "not" / "mounted" / "data")
    fake_client.reachable = False
    sleeps: list[float] = []
    now = iter([0.0, 0.0, 6.0, 12.0])

    problems = Monitor(config, fake_client).wait_until_ready(
        timeout=10, interval=6, sleep=sleeps.append, clock=lambda: next(now)
    )

    assert sleeps == [6, 6]
    assert len(problems) == 2
    assert "data folder" in problems[0]
    assert "tracker" in problems[1]


@pytest.mark.parametrize("label", ["", "My paper"])
def test_result_name_falls_back_to_label_or_uuid(config, fake_client, label) -> None:
    config = replace(config, submissions=(SubmissionConfig(DEMO_UUID, label=label),))
    fake_client.queue(DEMO_UUID, TrackerUnavailableError("offline"))
    [result] = Monitor(config, fake_client).run().results
    assert result.name == (label or DEMO_UUID)
