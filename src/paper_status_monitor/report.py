"""Human-readable output: console summary, text report and opening the report."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from paper_status_monitor.monitor import RunSummary, SubmissionResult

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
    """Return a compact, one-line-per-submission summary for the terminal."""
    count = len(summary.results)
    lines = [f"Checked {count} submission(s) at {summary.started_at:%Y-%m-%d %H:%M:%S}"]
    for result in summary.results:
        if not result.ok:
            lines.append(f"  [ERROR]     {result.name}: {result.error}")
        elif result.is_new:
            status = result.snapshot.status if result.snapshot else ""
            lines.append(f"  [NEW]       {result.name} ({status})")
        elif result.changes:
            lines.append(f"  [CHANGED]   {result.name}")
            lines += [f"                - {change}" for change in result.changes]
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
