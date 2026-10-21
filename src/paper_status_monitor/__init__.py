"""Monitor the peer-review status of Elsevier submissions.

``paper-status-monitor`` reads the public *Track your submission* service used by
Elsevier journals, keeps one Excel workbook per manuscript with the history of
every change, and writes a short report whenever something changes.

Typical use from Python::

    from paper_status_monitor import Monitor, load_config

    summary = Monitor(load_config()).run()
    for result in summary.changed:
        print(result.name, [str(change) for change in result.changes])
"""

from __future__ import annotations

from paper_status_monitor._version import __version__
from paper_status_monitor.client import (
    DEMO_UUID,
    InvalidResponseError,
    SubmissionNotFoundError,
    TrackerClient,
    TrackerError,
    TrackerUnavailableError,
    parse_uuid,
    tracker_url,
)
from paper_status_monitor.config import Config, ConfigError, SubmissionConfig, load_config
from paper_status_monitor.models import Change, Snapshot, diff_snapshots
from paper_status_monitor.monitor import Monitor, RunSummary, SubmissionResult

__all__ = [
    "DEMO_UUID",
    "Change",
    "Config",
    "ConfigError",
    "InvalidResponseError",
    "Monitor",
    "RunSummary",
    "Snapshot",
    "SubmissionConfig",
    "SubmissionNotFoundError",
    "SubmissionResult",
    "TrackerClient",
    "TrackerError",
    "TrackerUnavailableError",
    "__version__",
    "diff_snapshots",
    "load_config",
    "parse_uuid",
    "tracker_url",
]
