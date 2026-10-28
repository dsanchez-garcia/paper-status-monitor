"""Run bookkeeping: last-run summary, a lock against concurrent runs and the last
state seen of every submission (used to report each change only once)."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from paper_status_monitor import paths
from paper_status_monitor._version import __version__

if TYPE_CHECKING:
    from paper_status_monitor.monitor import RunSummary

log = logging.getLogger(__name__)

#: A lock older than this many seconds is considered stale and removed.
STALE_LOCK_SECONDS = 3600

#: File, in the data folder, with the last state seen of every submission.
SEEN_FILE_NAME = ".paper-status-monitor.json"

_SEEN_FORMAT = 1
_SEEN_NOTE = (
    "Written by paper-status-monitor: the last state seen of every submission, used to "
    "report each change only once. If you delete it, you may be told again about the "
    "latest changes."
)


class AlreadyRunningError(RuntimeError):
    """Another run is in progress (the lock file exists and is recent)."""


@contextmanager
def single_instance(
    lock_path: Path | None = None, stale_after: float = STALE_LOCK_SECONDS
) -> Iterator[None]:
    """Hold an exclusive lock file for the duration of a ``with`` block.

    Raises:
        AlreadyRunningError: If another process holds a recent lock.
    """
    lock = lock_path or paths.lock_file_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except FileNotFoundError:
            age = stale_after
        if age < stale_after:
            raise AlreadyRunningError(
                f"Another run seems to be in progress (lock file {lock}, {age:.0f} s old). "
                "Delete the file if you are sure no other run is active."
            ) from None
        log.warning("Removing stale lock file %s (%.0f s old)", lock, age)
        lock.unlink(missing_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_last_run(summary: RunSummary, path: Path | None = None) -> Path:
    """Store a short JSON summary of *summary* (used by ``paper-status-monitor doctor``)."""
    target = path or paths.state_file_path()
    finished = summary.finished_at or datetime.now()
    data = {
        "last_run": {
            "started_at": summary.started_at.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "version": __version__,
            "checked": len(summary.results),
            "changed": len(summary.changed),
            "recorded": len(summary.recorded),
            "failed": len(summary.failed),
            "errors": {r.submission.display_name: r.error for r in summary.failed},
            "report": str(summary.report_path) if summary.report_path else None,
        }
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_last_run(path: Path | None = None) -> dict[str, Any] | None:
    """Return the summary stored by :func:`save_last_run`, or ``None``."""
    target = path or paths.state_file_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    last_run = data.get("last_run") if isinstance(data, dict) else None
    return last_run if isinstance(last_run, dict) else None


class SeenSnapshots:
    """The last state seen of every submission, kept in :data:`SEEN_FILE_NAME`.

    Changes are reported against this state rather than against the last row of
    the workbook. Both are the same unless a column is reported but not recorded
    (see the ``record_fields`` and ``notify_fields`` settings): without this file,
    such a change would be reported again at every run. The file lives in the
    data folder, next to the workbooks, so that several computers sharing the
    folder do not report the same change twice. Entries are keyed by UUID.

    Args:
        path: Location of the JSON file.
        entries: Initial content (as stored under ``"submissions"``).
    """

    def __init__(self, path: Path, entries: Mapping[str, Any] | None = None) -> None:
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {
            str(uuid).lower(): dict(entry)
            for uuid, entry in (entries or {}).items()
            if isinstance(entry, Mapping)
        }
        self._modified = False

    @classmethod
    def load(cls, path: Path) -> SeenSnapshots:
        """Read the file; a missing or corrupt file gives an empty state (logged)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError) as exc:
            log.warning("Ignoring %s, which cannot be read: %s", path, exc)
            return cls(path)
        submissions = data.get("submissions") if isinstance(data, dict) else None
        return cls(path, submissions if isinstance(submissions, Mapping) else None)

    @property
    def modified(self) -> bool:
        """``True`` if something changed since the file was read or saved."""
        return self._modified

    def values(self, uuid: str) -> dict[str, str] | None:
        """Return the column values last seen for *uuid*, or ``None``."""
        values = self._entries.get(uuid.lower(), {}).get("values")
        if not isinstance(values, Mapping):
            return None
        return {str(label): "" if value is None else str(value) for label, value in values.items()}

    def workbook(self, uuid: str) -> str | None:
        """Return the file name of the workbook where *uuid* was last recorded."""
        name = self._entries.get(uuid.lower(), {}).get("workbook")
        return name if isinstance(name, str) and name else None

    def update(
        self, uuid: str, values: Mapping[str, str], *, key: str = "", workbook: str | None = None
    ) -> None:
        """Remember the state of a submission (the file is written by :meth:`save`)."""
        entry = {"key": key, "workbook": workbook, "values": dict(values)}
        if self._entries.get(uuid.lower()) != entry:
            self._entries[uuid.lower()] = entry
            self._modified = True

    def save(self) -> bool:
        """Write the file atomically if something changed. Return ``True`` if written."""
        if not self._modified:
            return False
        data = {"format": _SEEN_FORMAT, "note": _SEEN_NOTE, "submissions": self._entries}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self._modified = False
        return True
