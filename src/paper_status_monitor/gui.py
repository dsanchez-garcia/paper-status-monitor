"""Graphical interface: ``paper-status-monitor gui`` (or ``paper-status-monitor-gui``).

The window has four tabs:

* **Submissions** - add, edit, remove, pause and check the monitored submissions,
  including their custom fields (for example ``paper = TMY``), and see the latest
  status of all of them in one table (*Summary*);
* **Notifications** - choose, column by column, which changes add a row to the
  workbook (*Record*) and which are reported (*Notify*), and how you are told about
  the news (open the report, a desktop notification, or both);
* **Workbooks** - the data folder and the workbook name template, with a preview
  of the resulting names and a button to rename or merge existing workbooks;
* **Run** - check every submission now (or do a dry run), open the last report,
  set the request timeout and manage the Windows autostart, including periodic
  checks while you stay logged in.

Settings are written to the configuration file when you click *Save* (the previous
file is kept as ``config.toml.bak``). The window uses :mod:`tkinter`, part of the
standard library. This module holds the logic that does not depend on widgets, so
it can be tested without a display; the widgets live in a private module that is
only imported when the window opens.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path

from paper_status_monitor import naming, organize, scheduling
from paper_status_monitor.config import (
    Config,
    ConfigError,
    SubmissionConfig,
    parse_config,
    split_columns,
)
from paper_status_monitor.models import Snapshot, clean_text

log = logging.getLogger(__name__)

#: Workbook name templates offered by the window (label to template).
NAME_PRESETS: dict[str, str] = {
    "Manuscript number - Journal - Title (default)": naming.DEFAULT_WORKBOOK_NAME,
    "Paper - Journal - Manuscript number": "{paper} - {journal} - {manuscript_number}",
    "Paper - Date of submission - Journal": "{paper} - {date_of_submission} - {journal}",
    "One workbook per paper (all journals)": "{paper}",
    "Journal acronym - Manuscript number - Title": (
        "{journal_acronym} - {manuscript_number} - {title}"
    ),
}

#: Fictional data used to preview the name of submissions that are not recorded yet.
EXAMPLE_SNAPSHOT = Snapshot(
    title="A study of something important",
    journal="Journal of Examples",
    manuscript_number="ABC-D-26-00001",
    first_author="Ada Example",
    corresponding_author="Ada Example",
    date_of_submission="3rd March 2026",
)

_INSTALL_TK_HINT = (
    "The graphical interface needs tkinter, which is not included in this Python "
    "installation. On Debian or Ubuntu install it with: sudo apt install python3-tk. "
    "Everything is also available from the command line: paper-status-monitor --help"
)


def parse_fields_text(text: str) -> dict[str, str]:
    """Parse custom fields written one per line as ``name = value``.

    Empty lines and lines starting with ``#`` are ignored; ``name: value`` is also
    accepted and quotes around the value are removed.

    Raises:
        ConfigError: If a line has no ``=``, a name is invalid or repeated.
    """
    fields: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        separator = "=" if "=" in line else ":" if ":" in line else ""
        if not separator:
            raise ConfigError(
                f"Custom fields, line {number}: {line!r} must look like 'paper = TMY'."
            )
        name, _, value = (part.strip() for part in line.partition(separator))
        try:
            naming.check_custom_field_name(name)
        except ValueError as exc:
            raise ConfigError(f"Custom fields, line {number}: {exc}") from exc
        if name in fields:
            raise ConfigError(f"The custom field {name!r} is written twice.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[name] = clean_text(value)
    return fields


def format_fields_text(fields: Mapping[str, str]) -> str:
    """Return custom fields as text for :func:`parse_fields_text`, one per line."""
    return "\n".join(f"{name} = {value}" for name, value in fields.items())


def format_fields_inline(fields: Mapping[str, str]) -> str:
    """Return custom fields on one line, e.g. ``"paper=TMY, project=X"``."""
    return ", ".join(f"{name}={value}" for name, value in fields.items())


def build_config(
    *,
    data_dir: str,
    workbook_name: str,
    recorded: Iterable[str],
    notified: Iterable[str],
    notify: Iterable[str],
    notify_on_errors: bool,
    request_timeout: str | float,
    submissions: Sequence[SubmissionConfig],
    path: Path | None = None,
) -> Config:
    """Validate the values shown in the window and return the configuration.

    Args:
        data_dir: Data folder, as typed.
        workbook_name: Workbook name template.
        recorded: Columns whose changes add a row.
        notified: Columns whose changes are reported.
        notify: How the user is told about news (``"report"``, ``"toast"``).
        notify_on_errors: Report submissions that cannot be checked.
        request_timeout: Seconds per request, possibly as text.
        submissions: Submissions, in order.
        path: Configuration file (used to resolve a relative data folder).

    Raises:
        ConfigError: With a message that can be shown to the user.
    """
    try:
        timeout = float(str(request_timeout).strip().replace(",", "."))
    except ValueError:
        raise ConfigError("The timeout must be a number of seconds, for example 30.") from None
    record_fields, record_ignore = split_columns(recorded)
    notify_fields, notify_ignore = split_columns(notified)
    data = {
        "data_dir": data_dir.strip(),
        "workbook_name": workbook_name,
        "record_fields": "all" if record_fields is None else list(record_fields),
        "record_ignore": list(record_ignore),
        "notify_fields": "all" if notify_fields is None else list(notify_fields),
        "notify_ignore": list(notify_ignore),
        "notify": list(notify),
        "notify_on_errors": notify_on_errors,
        "request_timeout": timeout,
        "submissions": [
            {
                "uuid": submission.uuid,
                "label": submission.label,
                "enabled": submission.enabled,
                "fields": dict(submission.fields),
            }
            for submission in submissions
        ],
    }
    return parse_config(data, base_dir=path.parent if path else None, path=path)


def preview_rows(
    config: Config, names: Sequence[organize.WorkbookName] | None = None
) -> list[tuple[str, str, str]]:
    """Return the rows of the name preview: submission, current workbook, new name.

    Submissions that have not been recorded yet are previewed with
    :data:`EXAMPLE_SNAPSHOT`.
    """
    names = organize.workbook_names(config) if names is None else names
    rows = []
    for item in names:
        submission = item.submission
        if item.current is None:
            example = naming.workbook_file_name(config.workbook_name, EXAMPLE_SNAPSHOT, submission)
            rows.append((submission.display_name, "(not recorded yet)", f"{example} (example)"))
        else:
            rows.append((submission.display_name, item.current.name, item.expected or ""))
    return rows


def parse_hours(text: str) -> timedelta | None:
    """Parse the interval of the periodic checks, typed in hours (``0`` = none).

    Raises:
        ConfigError: If the text is not a number of hours or is below the minimum.
    """
    value = text.strip().replace(",", ".") or "0"
    try:
        hours = float(value)
    except ValueError:
        hours = -1.0
    if not math.isfinite(hours) or hours < 0:
        raise ConfigError(
            "The interval must be a number of hours, for example 12 (0 = only at login)."
        )
    if hours == 0:
        return None
    interval = timedelta(minutes=round(hours * 60))
    if interval < scheduling.MIN_INTERVAL:
        minimum = scheduling.format_interval(scheduling.MIN_INTERVAL)
        raise ConfigError(
            f"Checking every {value} hours is too often: the minimum is {minimum}. Review "
            "statuses change over days, and frequent checks only load the tracker."
        )
    return interval


def format_hours(interval: timedelta | None) -> str:
    """Write an interval in hours for :func:`parse_hours` (``None`` gives ``"0"``)."""
    if interval is None:
        return "0"
    hours = interval.total_seconds() / 3600
    return str(int(hours)) if hours.is_integer() else f"{hours:.2f}".rstrip("0")


def placeholders_help(custom_fields: Iterable[str] = ()) -> str:
    """Return the text that lists the placeholders available for workbook names."""
    builtin = "  ".join(f"{{{name}}}" for name in naming.PLACEHOLDERS)
    custom = "  ".join(f"{{{name}}}" for name in sorted(set(custom_fields)))
    return (
        f"Placeholders: {builtin}\n"
        f"Custom fields: {custom or 'none yet (add them to a submission, e.g. paper = TMY)'}\n"
        "Write {title:.40} to keep only the first 40 characters. Submissions whose names "
        "coincide share a workbook, so {paper} keeps all the submissions of a paper (to "
        "any journal) in one file. Existing workbooks keep their names until you click "
        "'Organize workbooks'."
    )


def run_gui(config_path: Path | None = None) -> int:
    """Open the window and return an exit code when it is closed.

    Args:
        config_path: Configuration file; defaults to the usual location. It is
            created when the user saves if it does not exist yet.
    """
    from paper_status_monitor import paths

    try:
        import tkinter
    except ImportError:
        _report_error(_INSTALL_TK_HINT)
        return 1
    from paper_status_monitor import _gui_app

    try:
        return _gui_app.launch(config_path or paths.default_config_path())
    except tkinter.TclError as exc:
        _report_error(f"The window could not be opened ({exc}). Is a graphical display available?")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``paper-status-monitor-gui`` command (no console window)."""
    from paper_status_monitor import paths
    from paper_status_monitor.cli import configure_logging

    parser = argparse.ArgumentParser(
        prog="paper-status-monitor-gui",
        description="Open the graphical interface of paper-status-monitor.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help=f"configuration file (default: {paths.default_config_path()})",
    )
    args = parser.parse_args(argv)
    configure_logging()
    return run_gui(args.config.expanduser() if args.config else None)


def _report_error(message: str) -> None:
    log.error(message)
    if sys.stderr is not None:
        print(f"Error: {message}", file=sys.stderr)
