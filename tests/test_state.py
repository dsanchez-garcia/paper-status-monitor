from __future__ import annotations

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
    assert last_run["failed"] == 1
    assert last_run["errors"] == {"Demo": "offline"}


def test_load_last_run_handles_missing_or_corrupt_files(tmp_path: Path) -> None:
    assert state.load_last_run(tmp_path / "missing.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert state.load_last_run(corrupt) is None
