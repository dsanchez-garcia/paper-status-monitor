from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from paper_status_monitor import paths, state
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import SubmissionConfig
from paper_status_monitor.monitor import RunSummary, SubmissionResult


def test_single_instance_lock(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    with state.single_instance(lock):
        assert lock.exists()
        with pytest.raises(state.AlreadyRunningError), state.single_instance(lock):
            pass
    assert not lock.exists()


def test_stale_lock_is_replaced(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    lock.write_text("12345", encoding="ascii")
    past = time.time() - 2 * state.STALE_LOCK_SECONDS
    os.utime(lock, (past, past))
    with state.single_instance(lock):
        assert lock.read_text(encoding="ascii") == str(os.getpid())
    assert not lock.exists()


def test_default_lock_location() -> None:
    with state.single_instance():
        assert paths.lock_file_path().exists()


def test_last_run_round_trip(tmp_path: Path) -> None:
    summary = RunSummary(
        started_at=datetime(2026, 1, 2, 9, 30),
        finished_at=datetime(2026, 1, 2, 9, 31),
        results=[
            SubmissionResult(SubmissionConfig(DEMO_UUID, label="Demo"), error="offline"),
            SubmissionResult(SubmissionConfig(DEMO_UUID), is_new=True),
        ],
    )
    path = state.save_last_run(summary, tmp_path / "state.json")
    last_run = state.load_last_run(path)
    assert last_run is not None
    assert last_run["finished_at"] == "2026-01-02T09:31:00"
    assert last_run["checked"] == 2
    assert last_run["changed"] == 1
    assert last_run["recorded"] == 1
    assert last_run["failed"] == 1
    assert last_run["errors"] == {"Demo": "offline"}


def test_load_last_run_handles_missing_or_corrupt_files(tmp_path: Path) -> None:
    assert state.load_last_run(tmp_path / "missing.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert state.load_last_run(corrupt) is None


def test_seen_snapshots_round_trip(tmp_path: Path) -> None:
    path = tmp_path / state.SEEN_FILE_NAME
    seen = state.SeenSnapshots.load(path)
    assert seen.values(DEMO_UUID) is None
    assert seen.workbook(DEMO_UUID) is None
    assert seen.save() is False  # nothing to write
    assert not path.exists()

    seen.update(DEMO_UUID.upper(), {"Status": "Under Review"}, key="X-1", workbook="TMY.xlsx")
    assert seen.modified
    assert seen.save() is True
    assert not seen.modified

    loaded = state.SeenSnapshots.load(path)
    assert loaded.values(DEMO_UUID) == {"Status": "Under Review"}
    assert loaded.workbook(DEMO_UUID) == "TMY.xlsx"
    loaded.update(DEMO_UUID, {"Status": "Under Review"}, key="X-1", workbook="TMY.xlsx")
    assert not loaded.modified  # same state: the file is not rewritten
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == 1
    assert "report each change only once" in data["note"]
    assert not list(tmp_path.glob("*.tmp-*"))


@pytest.mark.parametrize(
    "text", ["{not json", "[1, 2]", '{"submissions": 3}', '{"submissions": {"x": "y"}}']
)
def test_seen_snapshots_tolerate_damaged_files(tmp_path: Path, text: str) -> None:
    path = tmp_path / state.SEEN_FILE_NAME
    path.write_text(text, encoding="utf-8")
    seen = state.SeenSnapshots.load(path)
    assert seen.values(DEMO_UUID) is None
    assert seen.values("x") is None
