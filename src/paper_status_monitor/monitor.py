"""Orchestration: check every configured submission and record what changed.

For every submission, the state fetched from the tracker is compared twice:

* with the **last row recorded** for the submission, to decide whether a row is
  added to the workbook (columns chosen by ``record_fields`` / ``record_ignore``);
* with the **last state seen** (:class:`~paper_status_monitor.state.SeenSnapshots`),
  to decide what is reported (columns chosen by ``notify_fields`` /
  ``notify_ignore``).

Both comparisons give the same result unless a column is reported but not
recorded; keeping the last state seen makes sure such a change is reported once.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_status_monitor import naming, storage
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
from paper_status_monitor.state import SEEN_FILE_NAME, SeenSnapshots

log = logging.getLogger(__name__)


@dataclass
class SubmissionResult:
    """Outcome of checking one submission.

    Attributes:
        submission: The configured submission.
        snapshot: State fetched from the tracker (``None`` if the check failed).
        workbook: Workbook that holds (or would hold) the history.
        changes: Changes worth reporting (columns that are not notified are excluded).
        is_new: ``True`` the first time a submission is recorded.
        error: Human-readable error message if the check failed.
        recorded_changes: Changes that added a row to the workbook (in a dry run,
            that would have added one).
    """

    submission: SubmissionConfig
    snapshot: Snapshot | None = None
    workbook: Path | None = None
    changes: list[Change] = field(default_factory=list)
    is_new: bool = False
    error: str | None = None
    recorded_changes: list[Change] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` if the submission was checked successfully."""
        return self.error is None

    @property
    def needs_attention(self) -> bool:
        """``True`` if the submission is new or has reportable changes."""
        return self.ok and (self.is_new or bool(self.changes))

    @property
    def recorded(self) -> bool:
        """``True`` if a row was added to the workbook (or would be, in a dry run)."""
        return self.ok and (self.is_new or bool(self.recorded_changes))

    @property
    def unreported_changes(self) -> list[Change]:
        """Recorded changes in columns that are not notified."""
        reported = {change.field for change in self.changes}
        return [change for change in self.recorded_changes if change.field not in reported]

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
        """Submissions that are new or have reportable changes."""
        return [result for result in self.results if result.needs_attention]

    @property
    def recorded(self) -> list[SubmissionResult]:
        """Submissions for which a row was added to the workbook."""
        return [result for result in self.results if result.recorded]

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
        self._store: storage.WorkbookStore | None = None
        self._seen: SeenSnapshots | None = None

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
        with self._session(dry_run=dry_run):
            for submission in submissions:
                summary.results.append(self._check(submission, dry_run=dry_run))
        summary.finished_at = self._timestamp()
        log.info(
            "Run finished: %d checked, %d new or changed, %d recorded, %d failed",
            len(summary.results),
            len(summary.changed),
            len(summary.recorded),
            len(summary.failed),
        )
        return summary

    def check(self, submission: SubmissionConfig, *, dry_run: bool = False) -> SubmissionResult:
        """Check one submission and append a row to its workbook if something changed."""
        if self._store is not None:  # called from run()
            return self._check(submission, dry_run=dry_run)
        with self._session(dry_run=dry_run):
            return self._check(submission, dry_run=dry_run)

    @contextmanager
    def _session(self, *, dry_run: bool) -> Iterator[None]:
        """Share the workbook cache and the last state seen between checks."""
        self._store = storage.WorkbookStore(self.config.data_dir)
        self._seen = SeenSnapshots.load(self.config.data_dir / SEEN_FILE_NAME)
        seen = self._seen
        try:
            yield
        finally:
            self._store = self._seen = None
            if not dry_run:
                try:
                    seen.save()
                except OSError as exc:
                    log.warning(
                        "Could not save %s (%s); the latest changes may be reported again.",
                        seen.path,
                        exc,
                    )

    def _check(self, submission: SubmissionConfig, *, dry_run: bool) -> SubmissionResult:
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
        store, seen = self._require_session()
        submission = result.submission
        result.snapshot = snapshot
        key = snapshot.base_manuscript_number or submission.uuid
        target = naming.workbook_file_name(self.config.workbook_name, snapshot, submission)
        location = store.locate(key, submission.uuid, target, hint=seen.workbook(submission.uuid))
        result.workbook = location.path
        if location.last_record is None:
            result.is_new = True
        else:
            before = Snapshot.from_record(location.last_record)
            result.recorded_changes = _only(
                diff_snapshots(before, snapshot), self.config.recorded_columns
            )
            result.changes = _only(
                diff_snapshots(self._reference(submission.uuid, before), snapshot),
                self.config.notified_columns,
            )
            if location.path.name != target:
                log.info(
                    "%s is recorded in %s; with the current naming template it would be %s. "
                    "Run 'paper-status-monitor organize' to rename the workbooks.",
                    result.name,
                    location.path.name,
                    target,
                )
        if dry_run:
            return
        if result.is_new or result.recorded_changes:
            store.append(location.path, self._row(snapshot, submission))
        seen.update(submission.uuid, snapshot.to_record(), key=key, workbook=location.path.name)

    def _handle_not_found(
        self, result: SubmissionResult, error: SubmissionNotFoundError, *, dry_run: bool
    ) -> None:
        """Record that a known submission disappeared from the tracker (once)."""
        store, seen = self._require_session()
        uuid = result.submission.uuid
        location = store.locate_uuid(uuid, hint=seen.workbook(uuid))
        if location is None or location.last_record is None:
            result.error = str(error)
            return
        before = Snapshot.from_record(location.last_record)
        result.workbook = location.path
        if before.status == UNAVAILABLE_STATUS:
            result.snapshot = before
            if not dry_run:
                seen.update(uuid, before.to_record(), key=location.key, workbook=location.path.name)
            return
        after = before.replace(status=UNAVAILABLE_STATUS, status_code="")
        result.snapshot = after
        result.recorded_changes = diff_snapshots(before, after)  # always recorded, once
        result.changes = _only(
            diff_snapshots(self._reference(uuid, before), after), self.config.notified_columns
        )
        if dry_run:
            return
        store.append(location.path, self._row(after, result.submission))
        seen.update(uuid, after.to_record(), key=location.key, workbook=location.path.name)

    def _reference(self, uuid: str, recorded: Snapshot) -> Snapshot:
        """State that notifications are compared with: last seen, else last recorded."""
        _, seen = self._require_session()
        values = seen.values(uuid)
        return Snapshot.from_record(values) if values is not None else recorded

    def _require_session(self) -> tuple[storage.WorkbookStore, SeenSnapshots]:
        if self._store is None or self._seen is None:  # pragma: no cover - programming error
            raise RuntimeError("Monitor checks must run inside a session.")
        return self._store, self._seen

    def _row(self, snapshot: Snapshot, submission: SubmissionConfig) -> dict[str, Any]:
        row: dict[str, Any] = {DETECTED_AT_COLUMN: self._timestamp()}
        row.update(snapshot.to_record())
        row[TRACKER_URL_COLUMN] = submission.tracker_url
        row.update(naming.custom_field_columns(submission.fields))
        return row

    def _timestamp(self) -> datetime:
        return self._now().replace(microsecond=0)

    @staticmethod
    def _log_result(result: SubmissionResult) -> None:
        if not result.ok:
            log.error("%s: %s", result.submission.display_name, result.error)
            return
        if result.is_new:
            log.info("%s: now tracked in %s", result.name, result.workbook)
            return
        if result.changes:
            log.info("%s: %s", result.name, "; ".join(str(c) for c in result.changes))
        if result.unreported_changes:
            log.info(
                "%s: recorded without notification: %s",
                result.name,
                "; ".join(str(c) for c in result.unreported_changes),
            )
        if not result.changes and not result.recorded_changes:
            log.info("%s: no changes", result.name)


def _only(changes: list[Change], columns: Iterable[str]) -> list[Change]:
    selected = set(columns)
    return [change for change in changes if change.field in selected]
