"""Human-readable output: console summary, text report, notifications and opening files."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from paper_status_monitor import notifications, paths
from paper_status_monitor.config import Config
from paper_status_monitor.monitor import RunSummary, SubmissionResult
from paper_status_monitor.naming import custom_field_column

log = logging.getLogger(__name__)

_RULE = "-" * 72


def should_write_report(summary: RunSummary, *, include_errors: bool = True) -> bool:
    """Return ``True`` if the run produced something worth a report."""
    return bool(summary.changed) or (include_errors and bool(summary.failed))


def _details(result: SubmissionResult) -> list[str]:
    lines = []
    snapshot = result.snapshot
    if snapshot is not None:
        lines.append(f"  Journal: {snapshot.journal or '-'}")
        lines.append(f"  Manuscript number: {snapshot.manuscript_number or '-'}")
    if result.submission.label:
        lines.append(f"  Label: {result.submission.label}")
    for name, value in result.submission.fields.items():
        lines.append(f"  {custom_field_column(name)}: {value or '-'}")
    lines.append(f"  Tracker: {result.submission.tracker_url}")
    if result.workbook is not None:
        lines.append(f"  Workbook: {result.workbook}")
    return lines


def render_report(summary: RunSummary, *, include_errors: bool = True) -> str:
    """Return the text of the change report for *summary*."""
    lines = [
        "Paper status monitor - report",
        f"Run started: {summary.started_at:%Y-%m-%d %H:%M:%S}",
        "",
    ]
    changed = [result for result in summary.changed if not result.is_new]
    new = [result for result in summary.changed if result.is_new]
    if changed:
        lines += [_RULE, f"CHANGES ({len(changed)})", _RULE, ""]
        for result in changed:
            lines.append(result.name)
            lines += [f"  - {change}" for change in result.changes]
            lines += [*_details(result), ""]
    if new:
        lines += [_RULE, f"NOW TRACKING ({len(new)})", _RULE, ""]
        for result in new:
            lines.append(result.name)
            snapshot = result.snapshot
            if snapshot is not None:
                lines.append(f"  Status: {snapshot.status or '-'}")
                if snapshot.last_review_activity:
                    lines.append(f"  Last review activity: {snapshot.last_review_activity}")
                lines.append(
                    "  Reviews completed / invitations accepted / invitations sent: "
                    f"{snapshot.reviews_completed or '-'} / "
                    f"{snapshot.review_invitations_accepted or '-'} / "
                    f"{snapshot.review_invitations_sent or '-'}"
                )
            lines += [*_details(result), ""]
    if include_errors and summary.failed:
        lines += [_RULE, f"ERRORS ({len(summary.failed)})", _RULE, ""]
        for result in summary.failed:
            lines.append(result.name)
            lines.append(f"  {result.error}")
            lines += [*_details(result), ""]
    if not (changed or new or (include_errors and summary.failed)):
        lines.append("No changes.")
    return "\n".join(lines).rstrip() + "\n"


def render_console(summary: RunSummary) -> str:
    """Return a compact, one-line-per-submission summary for the terminal.

    Submissions with reportable changes are tagged ``[CHANGED]``; those with
    changes that were recorded without being reported are tagged ``[RECORDED]``.
    """
    count = len(summary.results)
    lines = [f"Checked {count} submission(s) at {summary.started_at:%Y-%m-%d %H:%M:%S}"]
    indent = " " * 16
    for result in summary.results:
        if not result.ok:
            lines.append(f"  [ERROR]     {result.name}: {result.error}")
        elif result.is_new:
            status = result.snapshot.status if result.snapshot else ""
            lines.append(f"  [NEW]       {result.name} ({status})")
        elif result.changes:
            lines.append(f"  [CHANGED]   {result.name}")
            lines += [f"{indent}- {change}" for change in result.changes]
            lines += [f"{indent}- {change} (not notified)" for change in result.unreported_changes]
        elif result.recorded_changes:
            lines.append(f"  [RECORDED]  {result.name} (not notified)")
            lines += [f"{indent}- {change}" for change in result.recorded_changes]
        else:
            lines.append(f"  [NO CHANGE] {result.name}")
    return "\n".join(lines)


def write_report(
    summary: RunSummary,
    directory: Path,
    *,
    fallback_directory: Path | None = None,
    include_errors: bool = True,
) -> Path:
    """Write the report to ``directory/changes_<timestamp>.txt`` and return its path.

    If *directory* cannot be written (for instance, a cloud drive that is not
    mounted), the report is written to *fallback_directory* instead.
    """
    text = render_report(summary, include_errors=include_errors)
    stem = f"changes_{summary.started_at:%Y-%m-%d_%H-%M-%S}"
    candidates = [directory] + ([fallback_directory] if fallback_directory else [])
    last_error: OSError | None = None
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{stem}.txt"
            counter = 2
            while path.exists():
                path = folder / f"{stem}_{counter}.txt"
                counter += 1
            path.write_text(text, encoding="utf-8")
            return path
        except OSError as exc:
            log.warning("Could not write the report to %s: %s", folder, exc)
            last_error = exc
    assert last_error is not None
    raise last_error


def publish_report(
    summary: RunSummary, config: Config, *, channels: Iterable[str] | None = None
) -> Path | None:
    """Write the report of a run if it has news, and tell the user about it.

    The report goes to :attr:`Config.reports_dir`, or to the local fallback folder
    if the data folder is not available. Then, depending on *channels*, it is
    opened (``"report"``) and a desktop notification is shown (``"toast"``; see
    :mod:`~paper_status_monitor.notifications`). Failures are logged, never raised.

    Args:
        summary: The run.
        config: Configuration (reports folder, ``notify_on_errors``).
        channels: How to tell the user; defaults to :attr:`Config.notify`.

    Returns:
        The report written (also stored in ``summary.report_path``), or ``None``.
    """
    chosen = set(config.notify if channels is None else channels)
    include_errors = config.notify_on_errors
    if not should_write_report(summary, include_errors=include_errors):
        return None
    path: Path | None = None
    try:
        path = write_report(
            summary,
            config.reports_dir,
            fallback_directory=paths.fallback_reports_dir(),
            include_errors=include_errors,
        )
    except OSError as exc:
        log.error("The report could not be written: %s", exc)
    else:
        summary.report_path = path
        log.info("Report written to %s", path)
        if "report" in chosen:
            open_path(path)
    if "toast" in chosen:
        notifications.notify_run(summary, include_errors=include_errors, report=path)
    return path


def open_path(path: Path) -> bool:
    """Open *path* with the default application. Return ``False`` on failure."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        log.warning("Could not open %s: %s", path, exc)
        return False
    return True
