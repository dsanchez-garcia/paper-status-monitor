from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from paper_status_monitor import organize
from paper_status_monitor.client import DEMO_UUID, tracker_url
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKER_URL_COLUMN
from paper_status_monitor.storage import append_record, read_records

OTHER_UUID = "11111111-2222-3333-4444-555555555555"
THIRD_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NOW = datetime(2026, 10, 28, 9, 0, 0)
ENERGY = "ENB-D-26-00001 - Energy and Buildings - Typical meteorological years.xlsx"
BUILDING = "BAE-D-26-00002 - Building and Environment - Typical meteorological years.xlsx"


def row(uuid: str, number: str, journal: str, when: datetime, status: str = "Under Review"):
    return {
        DETECTED_AT_COLUMN: when,
        "Title": "Typical meteorological years",
        "Status": status,
        "Journal": journal,
        "Date of submission": "3rd March 2026",
        "Manuscript number": number,
        TRACKER_URL_COLUMN: tracker_url(uuid),
    }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Two submissions of one paper, recorded with the default names."""
    folder = tmp_path / "data"
    energy = folder / ENERGY
    append_record(
        energy, row(DEMO_UUID, "ENB-D-26-00001", "Energy and Buildings", datetime(2026, 1, 5))
    )
    append_record(
        energy,
        row(
            DEMO_UUID,
            "ENB-D-26-00001",
            "Energy and Buildings",
            datetime(2026, 3, 1),
            "Review Complete",
        ),
    )
    building = folder / BUILDING
    append_record(
        building,
        row(OTHER_UUID, "BAE-D-26-00002", "Building and Environment", datetime(2026, 4, 2)),
    )
    return folder


def make_config(data_dir: Path, template: str) -> Config:
    return Config(
        data_dir=data_dir,
        workbook_name=template,
        submissions=(
            SubmissionConfig(DEMO_UUID, label="Energy", fields={"paper": "TMY"}),
            SubmissionConfig(OTHER_UUID, label="B&E", fields={"paper": "TMY"}, enabled=False),
        ),
    )


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.glob("*.xlsx"))


def test_nothing_to_do_when_the_names_follow_the_template(data_dir: Path) -> None:
    plan = organize.plan_organize(
        make_config(data_dir, "{manuscript_number} - {journal} - {title}")
    )
    assert plan.actions == []
    assert plan.skipped == []
    assert [name.current.name for name in plan.names if name.current] == [ENERGY, BUILDING]
    assert [name.needs_change for name in plan.names] == [False, False]


def test_rename_to_follow_the_template(data_dir: Path) -> None:
    config = make_config(data_dir, "{paper} - {journal_acronym} - {manuscript_number}")
    plan = organize.plan_organize(config)
    assert [action.kind for action in plan.actions] == ["rename", "rename"]
    assert plan.actions[0].describe() == (
        f"Rename  {ENERGY}\n    ->  TMY - ENB - ENB-D-26-00001.xlsx"
    )
    assert plan.actions[0].submissions == ("Energy",)

    outcome = organize.apply_organize(plan, config, now=lambda: NOW)

    assert outcome.errors == []
    assert outcome.backup_dir is None  # renaming needs no copies
    assert len(outcome.done) == 2
    assert names(data_dir) == ["TMY - BAE - BAE-D-26-00002.xlsx", "TMY - ENB - ENB-D-26-00001.xlsx"]
    assert organize.plan_organize(config).actions == []


def test_merge_the_submissions_of_a_paper(data_dir: Path) -> None:
    config = make_config(data_dir, "{paper}")
    plan = organize.plan_organize(config)
    [action] = plan.actions
    assert action.kind == "merge"
    assert action.target == data_dir / "TMY.xlsx"
    assert action.sources == (data_dir / ENERGY, data_dir / BUILDING)
    assert action.describe().splitlines()[0] == "Merge into  TMY.xlsx"

    outcome = organize.apply_organize(plan, config, now=lambda: NOW)

    assert outcome.errors == []
    assert names(data_dir) == ["TMY.xlsx"]
    rows = read_records(data_dir / "TMY.xlsx")
    assert [(r["Manuscript number"], r["Status"]) for r in rows] == [
        ("ENB-D-26-00001", "Under Review"),
        ("ENB-D-26-00001", "Review Complete"),
        ("BAE-D-26-00002", "Under Review"),
    ]
    assert outcome.backup_dir == data_dir / "backups" / "organize-2026-10-28_09-00-00"
    assert sorted(path.name for path in outcome.backup_dir.iterdir()) == [BUILDING, ENERGY]
    assert organize.plan_organize(config).actions == []


def test_merge_into_an_existing_shared_workbook(data_dir: Path) -> None:
    shared = data_dir / "TMY.xlsx"
    append_record(shared, row(THIRD_UUID, "XYZ-D-26-00003", "Journal X", datetime(2026, 9, 1)))
    base = make_config(data_dir, "{paper}")
    third = SubmissionConfig(THIRD_UUID, fields={"paper": "TMY"})
    config = replace(base, submissions=(*base.submissions, third))
    plan = organize.plan_organize(config)
    [action] = plan.actions
    assert action.kind == "merge"
    assert action.sources == (data_dir / ENERGY, data_dir / BUILDING)
    assert "(existing workbook)" in action.describe()

    outcome = organize.apply_organize(plan, config, now=lambda: NOW)

    assert outcome.errors == []
    assert [r["Manuscript number"] for r in read_records(shared)] == [
        "ENB-D-26-00001",
        "ENB-D-26-00001",
        "BAE-D-26-00002",
        "XYZ-D-26-00003",
    ]
    assert outcome.backup_dir is not None
    assert (outcome.backup_dir / "TMY.xlsx").is_file()


def test_workbooks_with_other_submissions_are_left_alone(data_dir: Path) -> None:
    append_record(
        data_dir / ENERGY, row(THIRD_UUID, "XYZ-D-26-00003", "Journal X", datetime(2026, 5, 1))
    )
    plan = organize.plan_organize(make_config(data_dir, "{paper}"))
    [skipped] = plan.skipped
    assert skipped.startswith(ENERGY)
    assert "not in the configuration" in skipped
    [action] = plan.actions
    assert (action.kind, action.sources) == ("rename", (data_dir / BUILDING,))


def test_a_workbook_is_never_split(data_dir: Path) -> None:
    config = make_config(data_dir, "{paper}")
    organize.apply_organize(organize.plan_organize(config), config, now=lambda: NOW)
    split = replace(
        config,
        submissions=(
            SubmissionConfig(DEMO_UUID, fields={"paper": "TMY"}),
            SubmissionConfig(OTHER_UUID, fields={"paper": "Other"}),
        ),
    )
    plan = organize.plan_organize(split)
    assert plan.actions == []
    [skipped] = plan.skipped
    assert "different workbooks" in skipped


def test_chained_renames_are_done_in_two_steps(tmp_path: Path) -> None:
    append_record(tmp_path / "X.xlsx", row(DEMO_UUID, "ENB-D-26-00001", "E", datetime(2026, 1, 1)))
    append_record(tmp_path / "Y.xlsx", row(OTHER_UUID, "BAE-D-26-00002", "B", datetime(2026, 1, 2)))
    config = Config(
        data_dir=tmp_path,
        workbook_name="{paper}",
        submissions=(
            SubmissionConfig(DEMO_UUID, fields={"paper": "Y"}),
            SubmissionConfig(OTHER_UUID, fields={"paper": "Z"}),
        ),
    )
    plan = organize.plan_organize(config)
    assert [action.kind for action in plan.actions] == ["rename"]
    assert "run 'organize' again" in plan.skipped[0]
    organize.apply_organize(plan, config)
    organize.apply_organize(organize.plan_organize(config), config)
    assert names(tmp_path) == ["Y.xlsx", "Z.xlsx"]
    assert read_records(tmp_path / "Y.xlsx")[0]["Manuscript number"] == "ENB-D-26-00001"


def test_failed_actions_are_reported_and_the_others_still_run(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(data_dir, "{paper} - {journal_acronym}")
    real_replace = os.replace
    calls: list[object] = []

    def flaky(source: object, target: object) -> None:
        calls.append(target)
        if len(calls) == 1:
            raise PermissionError("the file is in use")
        real_replace(source, target)

    monkeypatch.setattr(organize.os, "replace", flaky)
    outcome = organize.apply_organize(organize.plan_organize(config), config)
    assert len(outcome.errors) == 1
    assert "Close the workbooks in Excel" in outcome.errors[0]
    assert len(outcome.done) == 1


def test_submissions_not_recorded_yet(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "empty", submissions=(SubmissionConfig(DEMO_UUID),))
    plan = organize.plan_organize(config)
    assert plan.actions == []
    [name] = plan.names
    assert name.current is None
    assert not name.needs_change
