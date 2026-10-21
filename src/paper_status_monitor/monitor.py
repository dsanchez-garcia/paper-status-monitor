"""Orchestration: check every configured submission and record what changed."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_status_monitor import storage
from paper_status_monitor.client import SubmissionNotFoundError, TrackerClient, TrackerError
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import (
    DETECTED_AT_COLUMN,
    TRACKER_URL_COLUMN,
    UNAVAILABLE_STATUS,
    Change,
    Snapshot,
    diff_snapshots,
)

log = logging.getLogger(__name__)


@dataclass
class SubmissionResult:
    """Outcome of checking one submission.

    Attributes:
        submission: The configured submission.
        snapshot: State fetched from the tracker (``None`` if the check failed).
        workbook: Workbook that holds (or would hold) the history.
        changes: Changes worth reporting (ignored columns are excluded).
        is_new: ``True`` the first time a submission is recorded.
        error: Human-readable error message if the check failed.
    """

    submission: SubmissionConfig
    snapshot: Snapshot | None = None
    workbook: Path | None = None
    changes: list[Change] = field(default_factory=list)
    is_new: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        """``True`` if the submission was checked successfully."""
        return self.error is None

    @property
    def needs_attention(self) -> bool:
        """``True`` if the submission is new or has reportable changes."""
        return self.ok and (self.is_new or bool(self.changes))

    @property
    def name(self) -> str:
        """Best available name: displayed title, label or UUID."""
        if self.snapshot is not None and self.snapshot.title:
            return self.snapshot.display_title
        return self.submission.display_name


@dataclass
class RunSummary:
    """Outcome of a complete run."""

    started_at: datetime
    finished_at: datetime | None = None
    results: list[SubmissionResult] = field(default_factory=list)
    report_path: Path | None = None

    @property
    def changed(self) -> list[SubmissionResult]:
        """Submissions that are new or changed."""
        return [result for result in self.results if result.needs_attention]

    @property
    def failed(self) -> list[SubmissionResult]:
        """Submissions that could not be checked."""
        return [result for result in self.results if not result.ok]


class Monitor:
    """Check submissions, update their workbooks and collect the changes.

    Args:
        config: Validated configuration.
        client: Tracker client; a default :class:`TrackerClient` is created if omitted.
        now: Clock used for the ``Detected at`` column (injectable for tests).
    """

    def __init__(
        self,
        config: Config,
        client: TrackerClient | None = None,
        *,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.client = (
            client if client is not None else TrackerClient(timeout=config.request_timeout)
        )
        self._now = now

    def wait_until_ready(
        self,
        timeout: float,
        *,
        interval: float = 5.0,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> list[str]:
        """Wait until the data folder exists and the tracker host is reachable.

        This is useful right after logging in, when cloud drives (Google Drive,
        OneDrive...) and the network may not be ready yet.

        Returns:
            Problems still present when *timeout* expired (empty if all is ready).
        """
        deadline = clock() + timeout
        data_ready = network_ready = False
        while True:
            data_ready = data_ready or self._data_dir_ready()
            network_ready = network_ready or self.client.is_reachable()
            if (data_ready and network_ready) or clock() >= deadline:
                break
            sleep(interval)
        problems = []
        if not data_ready:
            problems.append(f"The data folder is not available: {self.config.data_dir}")
        if not network_ready:
            problems.append("The tracker could not be reached (is the computer online?).")
        return problems

    def _data_dir_ready(self) -> bool:
        data_dir = self.config.data_dir
        if data_dir.is_dir():
            return True
        if data_dir.parent.is_dir():
            try:
                data_dir.mkdir(exist_ok=True)
            except OSError:
                return False
            return True
        return False

    def run(self, *, dry_run: bool = False) -> RunSummary:
        """Check every enabled submission.

        Args:
            dry_run: Fetch and compare, but do not write anything.
        """
        summary = RunSummary(started_at=self._timestamp())
        submissions = self.config.enabled_submissions
        if not submissions:
            log.info("No enabled submissions in the configuration; nothing to do.")
        for submission in submissions:
            result = self.check(submission, dry_run=dry_run)
            summary.results.append(result)
        summary.finished_at = self._timestamp()
        log.info(
            "Run finished: %d checked, %d new or changed, %d failed",
            len(summary.results),
            len(summary.changed),
            len(summary.failed),
        )
        return summary

    def check(self, submission: SubmissionConfig, *, dry_run: bool = False) -> SubmissionResult:
        """Check one submission and append a row to its workbook if something changed."""
        result = SubmissionResult(submission)
        try:
            try:
                snapshot = self.client.fetch(submission.uuid)
            except SubmissionNotFoundError as exc:
                self._handle_not_found(result, exc, dry_run=dry_run)
            else:
                self._record_snapshot(result, snapshot, dry_run=dry_run)
        except TrackerError as exc:
            result.error = str(exc)
        except Exception as exc:  # keep going with the other submissions
            log.exception("Unexpected error while checking %s", submission.display_name)
            result.error = f"{type(exc).__name__}: {exc}"
        self._log_result(result)
        return result

    def _record_snapshot(
        self, result: SubmissionResult, snapshot: Snapshot, *, dry_run: bool
    ) -> None:
        result.snapshot = snapshot
        key = snapshot.base_manuscript_number or result.submission.uuid
        path = storage.find_workbook(self.config.data_dir, key)
        previous = storage.last_record(path) if path is not None else None
        if path is None:
            path = self.config.data_dir / storage.workbook_name(
                key, snapshot.journal, snapshot.title
            )
        result.workbook = path
        if previous is None:
            result.is_new = True
            all_changes: list[Change] = []
        else:
            all_changes = diff_snapshots(Snapshot.from_record(previous), snapshot)
        result.changes = self._reportable(all_changes)
        if (result.is_new or all_changes) and not dry_run:
            storage.append_record(path, self._row(snapshot, result.submission))

    def _handle_not_found(
        self, result: SubmissionResult, error: SubmissionNotFoundError, *, dry_run: bool
    ) -> None:
        """Record that a known submission disappeared from the tracker (once)."""
        path = storage.find_workbook_by_uuid(self.config.data_dir, result.submission.uuid)
        previous = storage.last_record(path) if path is not None else None
        if path is None or previous is None:
            result.error = str(error)
            return
        before = Snapshot.from_record(previous)
        result.workbook = path
        if before.status == UNAVAILABLE_STATUS:
            result.snapshot = before
            return
        after = before.replace(status=UNAVAILABLE_STATUS, status_code="")
        result.snapshot = after
        result.changes = self._reportable(diff_snapshots(before, after))
        if not dry_run:
            storage.append_record(path, self._row(after, result.submission))

    def _reportable(self, changes: list[Change]) -> list[Change]:
        ignored = {label.casefold() for label in self.config.ignore_fields}
        return [change for change in changes if change.field.casefold() not in ignored]

    def _row(self, snapshot: Snapshot, submission: SubmissionConfig) -> dict[str, Any]:
        row: dict[str, Any] = {DETECTED_AT_COLUMN: self._timestamp()}
        row.update(snapshot.to_record())
        row[TRACKER_URL_COLUMN] = submission.tracker_url
        return row

    def _timestamp(self) -> datetime:
        return self._now().replace(microsecond=0)

    @staticmethod
    def _log_result(result: SubmissionResult) -> None:
        if not result.ok:
            log.error("%s: %s", result.submission.display_name, result.error)
        elif result.is_new:
            log.info("%s: now tracked in %s", result.name, result.workbook)
        elif result.changes:
            log.info("%s: %s", result.name, "; ".join(str(c) for c in result.changes))
        else:
            log.info("%s: no changes", result.name)
