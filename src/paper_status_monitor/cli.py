"""Command-line interface (``paper-status-monitor``)."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import logging
import platform
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paper_status_monitor import (
    autostart,
    emails,
    i18n,
    naming,
    notifications,
    organize,
    paths,
    report,
    scheduling,
    state,
    storage,
    tray,
)
from paper_status_monitor import export as history_export
from paper_status_monitor import summary as status_summary
from paper_status_monitor._version import __version__
from paper_status_monitor.client import DEMO_UUID, TrackerClient, TrackerError, parse_uuid
from paper_status_monitor.config import (
    SMTP_PASSWORD_ENV_VAR,
    SUBMISSION_OVERRIDES,
    Config,
    ConfigError,
    SubmissionConfig,
    add_submission,
    check_email_ready,
    describe_columns,
    describe_notify,
    edit_submission,
    find_submission,
    load_config,
    parse_columns_option,
    parse_field_assignment,
    parse_notify,
    remove_submission,
    set_submission_enabled,
    write_config,
)
from paper_status_monitor.models import DETECTED_AT_COLUMN, TRACKER_URL_COLUMN
from paper_status_monitor.monitor import Monitor, RunSummary

log = logging.getLogger("paper_status_monitor")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

DOCS_URL = "https://paper-status-monitor.readthedocs.io"
_STALE_RUN_DAYS = 7


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="paper-status-monitor",
        description=(
            "Monitor the peer-review status of your Elsevier submissions and keep one Excel "
            "history per manuscript."
        ),
        epilog=f"Documentation: {DOCS_URL}",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help=f"configuration file (default: {paths.default_config_path()})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug messages")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    init = commands.add_parser(
        "init",
        help="create a configuration file",
        description="Create a commented configuration file.",
    )
    init.add_argument(
        "--data-dir",
        type=Path,
        default=paths.default_data_dir(),
        metavar="PATH",
        help="folder for the Excel workbooks and the reports (default: %(default)s)",
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.add_argument(
        "--language",
        type=_language_argument,
        default=i18n.DEFAULT_LANGUAGE,
        metavar="CODE",
        help=(
            "language of the reports, notifications, e-mails, summary and window: "
            f"{', '.join(f'{code} ({name})' for code, name in i18n.LANGUAGES.items())} "
            "(default: %(default)s)"
        ),
    )
    init.set_defaults(handler=cmd_init)

    add = commands.add_parser(
        "add",
        help="add a submission to the configuration",
        description="Add a submission, given its tracking link or UUID, to the configuration.",
    )
    add.add_argument("submission", help="tracking link or UUID")
    add.add_argument("--label", default="", help="short name shown in the reports")
    add.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "custom field, usable as {NAME} in the workbook name and written to an extra "
            "column, e.g. --field paper=Tau (repeat for several fields)"
        ),
    )
    add.add_argument(
        "--no-verify", action="store_true", help="do not contact the tracker before adding"
    )
    add.set_defaults(handler=cmd_add)

    which = (
        "SUBMISSION is its tracking link, its UUID, its label or its number in "
        "'paper-status-monitor list'. The comments of the configuration file are kept."
    )
    edit = commands.add_parser(
        "edit",
        help="change the label or the custom fields of a submission",
        description=f"Change the label or the custom fields of a submission. {which} The "
        "previous file is kept as config.toml.bak, and workbooks keep their names until you "
        "run 'paper-status-monitor organize'.",
    )
    edit.add_argument("submission", metavar="SUBMISSION", help="link, UUID, label or number")
    edit.add_argument("--label", help='new short name (--label "" removes it)')
    edit.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="add or change a custom field, e.g. --field paper=Tau (repeat for several fields)",
    )
    edit.add_argument(
        "--remove-field",
        action="append",
        default=[],
        metavar="NAME",
        help="remove a custom field (repeat for several fields)",
    )
    edit.add_argument(
        "--clear-fields",
        action="store_true",
        help="remove every custom field (the fields given with --field are then the only ones)",
    )
    own = edit.add_argument_group(
        "own record and notify settings",
        "Give this submission its own record_* and notify_* settings, which replace the "
        "general settings of the same name. COLUMNS is a comma-separated list of column "
        'names, "all" (only for --*-fields), "none", or "general" to follow the general '
        "setting again.",
    )
    for option, text in (
        ("--record-fields", "only changes in these columns add a row"),
        ("--record-ignore", "changes only in these columns never add a row"),
        ("--notify-fields", "only changes in these columns are reported"),
        ("--notify-ignore", "changes in these columns are never reported"),
    ):
        own.add_argument(option, metavar="COLUMNS", help=text)
    own.add_argument(
        "--use-general-settings",
        action="store_true",
        help="remove every own setting (the ones given in this command are then the only ones)",
    )
    edit.set_defaults(handler=cmd_edit)

    remove = commands.add_parser(
        "remove",
        help="remove a submission from the configuration (its workbook is kept)",
        description=f"Remove a submission from the configuration file. {which} Its workbook "
        "is not deleted, and the previous file is kept as config.toml.bak.",
    )
    remove.add_argument("submission", metavar="SUBMISSION", help="link, UUID, label or number")
    remove.set_defaults(handler=cmd_remove)

    disable = commands.add_parser(
        "disable",
        aliases=["pause"],
        help="pause the monitoring of a submission",
        description=f"Stop checking a submission without removing it (enabled = false). {which}",
    )
    disable.add_argument("submission", metavar="SUBMISSION", help="link, UUID, label or number")
    disable.set_defaults(handler=cmd_disable)

    enable = commands.add_parser(
        "enable",
        aliases=["resume"],
        help="resume the monitoring of a paused submission",
        description=f"Check a paused submission again (enabled = true). {which}",
    )
    enable.add_argument("submission", metavar="SUBMISSION", help="link, UUID, label or number")
    enable.set_defaults(handler=cmd_enable)

    listing = commands.add_parser(
        "list",
        help="list the configured submissions",
        description="List the configured submissions and their last recorded status.",
    )
    listing.set_defaults(handler=cmd_list)

    overview = commands.add_parser(
        "summary",
        help="show one table with the latest status of every submission",
        description=(
            "Show one table with the latest recorded status of every submission, read "
            "from the workbooks (nothing is downloaded). The table does not include the "
            "tracking links, so it can be shared."
        ),
    )
    overview.add_argument(
        "--format",
        choices=status_summary.FORMATS,
        default="text",
        help="output format (default: %(default)s)",
    )
    overview.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="write the table to FILE instead of showing it",
    )
    overview.set_defaults(handler=cmd_summary)

    dump = commands.add_parser(
        "export",
        help="export the recorded history of every submission to CSV or JSON",
        description=(
            "Write the recorded history of every submission, read from the workbooks, as "
            "CSV (one row per observed state) or JSON (grouped by submission). The tracking "
            "links are left out unless --include-links is given."
        ),
    )
    dump.add_argument(
        "--format",
        choices=history_export.FORMATS,
        default="csv",
        help="output format (default: %(default)s)",
    )
    dump.add_argument(
        "-o", "--output", type=Path, metavar="FILE", help="write to FILE instead of showing it"
    )
    dump.add_argument(
        "--include-links",
        action="store_true",
        help="also export the tracking links (they are personal: do not share them)",
    )
    dump.set_defaults(handler=cmd_export)

    check = commands.add_parser(
        "check",
        help="show the current status of one submission (nothing is saved)",
        description=(
            "Show the current status of one submission without saving anything. "
            f"Try it with the public demo submission: {DEMO_UUID}"
        ),
    )
    check.add_argument("submission", help="tracking link or UUID")
    check.add_argument("--json", action="store_true", help="print the raw JSON record")
    check.set_defaults(handler=cmd_check)

    run = commands.add_parser(
        "run",
        help="check all submissions and record the changes",
        description=(
            "Check every enabled submission, append changes to the workbooks and write a "
            "report when something changed. With --every, keep running and check again at "
            "that interval."
        ),
    )
    run.add_argument(
        "--wait",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=(
            "before each check, wait up to SECONDS for the network and the data folder "
            "(useful at login and after the computer wakes up)"
        ),
    )
    run.add_argument(
        "--every",
        metavar="INTERVAL",
        help=(
            "keep running and check again every INTERVAL, e.g. 12h or 1d (minimum "
            f"{scheduling.format_interval(scheduling.MIN_INTERVAL)}), until stopped"
        ),
    )
    run.add_argument(
        "--tray",
        action="store_true",
        help=(
            "with --every, show an icon in the notification area while checking, with the "
            "latest statuses and a menu (Windows)"
        ),
    )
    run.add_argument(
        "--notify",
        metavar="CHANNELS",
        help=(
            'how to tell you about news in this run: "report" (open the report), "toast" '
            '(desktop notification), "email" (send the report), a list such as '
            '"report,toast", or "none"'
        ),
    )
    run.add_argument(
        "--no-open",
        action="store_true",
        help="do not open the report (it is still written), like removing 'report' from --notify",
    )
    run.add_argument(
        "--dry-run", action="store_true", help="show the changes without writing anything"
    )
    selection = run.add_argument_group(
        "what is recorded and notified",
        "Override the record_* and notify_* settings for this run. COLUMNS is a "
        'comma-separated list of column names, e.g. "Status,Reviews completed".',
    )
    selection.add_argument(
        "--record-fields",
        metavar="COLUMNS",
        help='only changes in these columns add a row ("all" for every column)',
    )
    selection.add_argument(
        "--record-ignore",
        metavar="COLUMNS",
        help='changes only in these columns never add a row ("none" to clear the list)',
    )
    selection.add_argument(
        "--notify-fields",
        metavar="COLUMNS",
        help='only changes in these columns are reported, e.g. "Status" ("all" for every column)',
    )
    selection.add_argument(
        "--notify-ignore",
        metavar="COLUMNS",
        help='changes in these columns are never reported ("none" to clear the list)',
    )
    run.set_defaults(handler=cmd_run)

    tidy = commands.add_parser(
        "organize",
        help="rename, merge or split the workbooks to follow the naming template",
        description=(
            "Rename existing workbooks, merge them or split them, so that their names follow "
            "the workbook_name setting. Workbooks that are merged or split are copied to the "
            "'backups' subfolder of the data folder first."
        ),
    )
    tidy.add_argument("--dry-run", action="store_true", help="only show what would be done")
    tidy.set_defaults(handler=cmd_organize)

    gui = commands.add_parser(
        "gui",
        help="open the graphical interface",
        description=(
            "Open a window to manage the submissions, choose what is recorded and "
            "notified, set the workbook names and run checks."
        ),
    )
    gui.set_defaults(handler=cmd_gui)

    auto = commands.add_parser(
        "autostart",
        help="run the monitor automatically at login",
        description=(
            "Manage the launcher that runs the monitor in the background, without a window, "
            "every time you log in (and, with --every, periodically while you stay logged "
            "in): a shortcut in the Startup folder on Windows, an XDG autostart entry on "
            "Linux or a launchd agent on macOS."
        ),
    )
    auto.add_argument("action", choices=["enable", "disable", "status"])
    auto.add_argument(
        "--wait",
        type=int,
        default=autostart.DEFAULT_WAIT,
        metavar="SECONDS",
        help="seconds to wait for the network and the data folder at login (default: %(default)s)",
    )
    auto.add_argument(
        "--every",
        metavar="INTERVAL",
        help=(
            "after the check at login, keep checking every INTERVAL (e.g. 12h or 1d) while "
            "you stay logged in"
        ),
    )
    auto.add_argument(
        "--tray",
        action="store_true",
        help="with --every, show an icon in the notification area while checking (Windows)",
    )
    auto.set_defaults(handler=cmd_autostart)

    mail = commands.add_parser(
        "email",
        help="send a test e-mail, or keep the SMTP password in the system keyring",
        description=(
            "Send a test e-mail with the settings of the [email] table, or store (or delete) "
            "the password of the SMTP server in the system keyring, which needs the keyring "
            "package. The password is never written to the configuration file; the "
            f"{SMTP_PASSWORD_ENV_VAR} environment variable can be used instead."
        ),
    )
    mail.add_argument("action", choices=["test", "set-password", "delete-password"])
    mail.set_defaults(handler=cmd_email)

    doctor = commands.add_parser(
        "doctor",
        help="diagnose configuration, connectivity and autostart problems",
        description="Check the configuration, the data folder, the tracker and the autostart.",
    )
    doctor.set_defaults(handler=cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``paper-status-monitor`` command."""
    _make_streams_safe()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_USAGE
    configure_logging(verbose=args.verbose)
    log.debug("paper-status-monitor %s, command %r", __version__, args.command)
    try:
        return handler(args)
    except ConfigError as exc:
        _error(str(exc))
        return EXIT_USAGE
    except autostart.AutostartError as exc:
        _error(str(exc))
        return EXIT_FAILURE
    except KeyboardInterrupt:
        _error("Interrupted.")
        return 130
    except Exception as exc:
        log.exception("Unexpected error")
        _error(f"Unexpected error: {exc}\nDetails in the log file: {paths.log_file_path()}")
        return EXIT_FAILURE


def configure_logging(*, verbose: bool = False, log_file: Path | None = None) -> None:
    """Log to a rotating file and, when a console exists, to standard error."""
    logger = logging.getLogger("paper_status_monitor")
    for handler in list(logger.handlers):
        if getattr(handler, "_paper_status_monitor", False):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    target = log_file or paths.log_file_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError:
        file_handler = None
    if file_handler is not None:
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        file_handler._paper_status_monitor = True  # type: ignore[attr-defined]
        logger.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.DEBUG if verbose else logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        console._paper_status_monitor = True  # type: ignore[attr-defined]
        logger.addHandler(console)


# --------------------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    """Create a configuration file."""
    path = _config_path(args)
    if path.exists() and not args.force:
        _error(f"A configuration file already exists: {path}\nUse --force to overwrite it.")
        return EXIT_USAGE
    data_dir = args.data_dir.expanduser()
    write_config(path, data_dir, overwrite=True, language=args.language)
    print(f"Configuration file created: {path}")
    print(f"Data folder: {data_dir}")
    if args.language != i18n.DEFAULT_LANGUAGE:
        print(f"Language of the reports and the window: {i18n.language_name(args.language)}")
    print()
    print("Next steps:")
    print("  1. paper-status-monitor add <tracking link>")
    print("  2. paper-status-monitor run")
    print("  3. paper-status-monitor autostart enable   (check at every login)")
    print("Or do everything from a window: paper-status-monitor gui")
    return EXIT_OK


def cmd_add(args: argparse.Namespace) -> int:
    """Add a submission to the configuration file."""
    path = _config_path(args)
    uuid = _parse_uuid_argument(args.submission)
    if uuid is None:
        return EXIT_USAGE
    fields = dict(parse_field_assignment(item) for item in args.field)
    config = load_config(path)  # fail early, before contacting the tracker
    if any(submission.uuid == uuid for submission in config.submissions):
        _error(f"Submission {uuid} is already in {path}")
        return EXIT_USAGE
    if not args.no_verify:
        try:
            with TrackerClient() as client:
                snapshot = client.fetch(uuid)
        except TrackerError as exc:
            _error(f"{exc}\nUse --no-verify to add it anyway.")
            return EXIT_FAILURE
        print(f"Found: {snapshot.display_title}")
        print(f"       {snapshot.journal} - {snapshot.manuscript_number} - {snapshot.status}")
    add_submission(path, uuid, args.label, fields)
    print(f"Added to {path}")
    return EXIT_OK


def cmd_edit(args: argparse.Namespace) -> int:
    """Change the label, the custom fields or the own settings of a submission, keeping
    the comments of the configuration file."""
    path = _config_path(args)
    config = load_config(path)
    submission = find_submission(config, args.submission)
    fields = _edited_fields(submission, args)
    overrides = _edited_overrides(submission, args)
    if args.label is None and fields is None and overrides is None:
        _error(
            "Nothing to change: use --label, --field, --remove-field, --clear-fields, "
            "--record-fields, --record-ignore, --notify-fields, --notify-ignore or "
            "--use-general-settings."
        )
        return EXIT_USAGE
    before, after = edit_submission(
        path, submission.uuid, label=args.label, fields=fields, overrides=overrides
    )
    if before == after:
        print(f"Nothing to change: {before.display_name} already has these values.")
        return EXIT_OK
    print(f"Updated {after.display_name} in {path}")
    changed: set[str] = set()
    if before.label != after.label:
        changed.add("label")
        print(f"  Label:  {after.label or '(none)'}  (was: {before.label or '(none)'})")
    if dict(before.fields) != dict(after.fields):
        changed.update(
            name
            for name in {*before.fields, *after.fields}
            if before.fields.get(name) != after.fields.get(name)
        )
        print(
            f"  Fields: {_describe_fields(after.fields)}  (was: {_describe_fields(before.fields)})"
        )
    if dict(before.overrides) != dict(after.overrides):
        source = "its own settings" if after.overrides else "the general settings"
        for title, columns in (
            ("Records: ", config.recorded_columns_for),
            ("Notifies:", config.notified_columns_for),
        ):
            now, then = describe_columns(columns(after)), describe_columns(columns(before))
            print(f"  {title} {now}  (was: {then})")
        print(f"  It now follows {source}.")
    print(f"Previous configuration: {path.name}.bak")
    used = [name for name in naming.template_placeholders(config.workbook_name) if name in changed]
    if used:
        placeholders = ", ".join(f"{{{name}}}" for name in dict.fromkeys(used))
        print(
            f"The workbook names use {placeholders}: an existing workbook keeps its name until "
            "you run: paper-status-monitor organize"
        )
    return EXIT_OK


def _edited_overrides(
    submission: SubmissionConfig, args: argparse.Namespace
) -> dict[str, tuple[str, ...] | None] | None:
    """Return the own settings asked for by the options of ``edit`` (``None`` = unchanged).

    ``general`` as the value of an option removes that own setting.

    Raises:
        ConfigError: If an option names an unknown column.
    """
    given = {
        key: text for key in SUBMISSION_OVERRIDES if (text := getattr(args, key, None)) is not None
    }
    reset = getattr(args, "use_general_settings", False)
    if not given and not reset:
        return None
    overrides = {} if reset else dict(submission.overrides)
    for key, text in given.items():
        if text.strip().casefold() == "general":
            overrides.pop(key, None)
            continue
        option = "--" + key.replace("_", "-")
        overrides[key] = parse_columns_option(
            text, option=option, allow_all=key.endswith("_fields")
        )
    return overrides


def _edited_fields(submission: SubmissionConfig, args: argparse.Namespace) -> dict[str, str] | None:
    """Return the custom fields asked for by the options of ``edit`` (``None`` = unchanged).

    Raises:
        ConfigError: If an option is invalid or removes a field the submission does not have.
    """
    assignments = dict(parse_field_assignment(item) for item in args.field)
    removed = list(dict.fromkeys(name.strip() for name in args.remove_field))
    if not (assignments or removed or args.clear_fields):
        return None
    both = [name for name in removed if name in assignments]
    if both:
        raise ConfigError(f"--field and --remove-field both name the custom field {both[0]!r}.")
    unknown = [name for name in removed if name not in submission.fields]
    if unknown:
        existing = ", ".join(submission.fields) or "none"
        raise ConfigError(
            f"{submission.display_name} has no custom field {unknown[0]!r} "
            f"(its custom fields: {existing})."
        )
    fields = {} if args.clear_fields else dict(submission.fields)
    for name in removed:
        fields.pop(name, None)
    fields.update(assignments)
    return fields


def _describe_fields(fields: Mapping[str, str]) -> str:
    return ", ".join(f"{name} = {value}" for name, value in fields.items()) or "(none)"


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove a submission from the configuration file (its workbook is kept)."""
    path = _config_path(args)
    submission = find_submission(load_config(path), args.submission)
    remove_submission(path, submission.uuid)
    print(f"Removed {submission.display_name} from {path}")
    print(f"Its workbook was not deleted. Previous configuration: {path.name}.bak")
    return EXIT_OK


def cmd_disable(args: argparse.Namespace) -> int:
    """Pause the monitoring of a submission (``enabled = false``)."""
    return _set_enabled(args, enabled=False)


def cmd_enable(args: argparse.Namespace) -> int:
    """Resume the monitoring of a paused submission (``enabled = true``)."""
    return _set_enabled(args, enabled=True)


def _set_enabled(args: argparse.Namespace, *, enabled: bool) -> int:
    path = _config_path(args)
    submission = find_submission(load_config(path), args.submission)
    _, changed = set_submission_enabled(path, submission.uuid, enabled)
    name = submission.display_name
    if not changed:
        print(f"{name} is already {'monitored' if enabled else 'paused'}.")
    elif enabled:
        print(f"Resumed {name}: it is checked again from the next run.")
    else:
        handle = submission.label if " " not in submission.label else f'"{submission.label}"'
        print(f"Paused {name}: it is no longer checked (its workbook is kept).")
        print(f"Resume it with: paper-status-monitor enable {handle or submission.uuid}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """List the configured submissions and their last recorded status."""
    config = load_config(args.config)
    print(f"Configuration:  {config.path}")
    print(f"Data folder:    {config.data_dir}")
    print(f"Workbook names: {config.workbook_name}")
    if not config.submissions:
        print("\nNo submissions yet. Add one with: paper-status-monitor add <tracking link>")
        return EXIT_OK
    store = storage.WorkbookStore(config.data_dir)
    for index, submission in enumerate(config.submissions, start=1):
        state_note = "" if submission.enabled else "  [paused]"
        print(f"\n{index}. {submission.label or '(no label)'}{state_note}")
        print(f"   {submission.tracker_url}")
        if submission.fields:
            fields = ", ".join(f"{name} = {value}" for name, value in submission.fields.items())
            print(f"   Fields: {fields}")
        if submission.overrides:
            recorded = describe_columns(config.recorded_columns_for(submission))
            notified = describe_columns(config.notified_columns_for(submission))
            print(f"   Own settings: records {recorded}; notifies {notified}")
        print(f"   {_last_recorded(store, submission)}")
    return EXIT_OK


def cmd_summary(args: argparse.Namespace) -> int:
    """Show one table with the latest recorded status of every submission."""
    config = load_config(args.config)
    if not config.data_dir.is_dir() and not config.data_dir.parent.is_dir():
        log.warning("The data folder is not reachable (%s): no status is shown.", config.data_dir)
    rows = status_summary.summary_rows(config)
    with i18n.language(config.language):
        text = status_summary.render_summary(rows, args.format)
    if args.output is None:
        print(text, end="")
        return EXIT_OK
    path = args.output.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        _error(f"Cannot write {path}: {exc}")
        return EXIT_FAILURE
    print(f"Summary written to {path}")
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    """Export the recorded history of every submission to CSV or JSON."""
    config = load_config(args.config)
    histories = history_export.collect_history(config)
    text = history_export.render_export(histories, args.format, include_links=args.include_links)
    if args.output is None:
        print(text, end="")
        return EXIT_OK
    path = args.output.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    except OSError as exc:
        _error(f"Cannot write {path}: {exc}")
        return EXIT_FAILURE
    rows = sum(len(history.rows) for history in histories)
    print(f"{rows} row(s) of {len(histories)} submission(s) written to {path}")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    """Print the current status of one submission without saving anything."""
    uuid = _parse_uuid_argument(args.submission)
    if uuid is None:
        return EXIT_USAGE
    try:
        with TrackerClient() as client:
            if args.json:
                print(json.dumps(client.fetch_json(uuid), indent=2, ensure_ascii=False))
                return EXIT_OK
            snapshot = client.fetch(uuid)
    except TrackerError as exc:
        _error(str(exc))
        return EXIT_FAILURE
    record = snapshot.to_record()
    record[TRACKER_URL_COLUMN] = SubmissionConfig(uuid).tracker_url
    width = max(len(label) for label in record) + 1
    for label, value in record.items():
        print(f"{label + ':':<{width}} {value or '-'}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    """Check every enabled submission and record the changes (once, or periodically)."""
    config = apply_run_overrides(load_config(args.config), args)
    if getattr(args, "tray", False):
        _check_tray_option(args)
    if not getattr(args, "every", None):
        return _check_now(config, args)
    try:
        interval = scheduling.parse_interval(args.every)
    except ValueError as exc:
        raise ConfigError(f"--every: {exc}") from exc
    return _check_periodically(config, args, interval)


def _check_tray_option(args: argparse.Namespace) -> None:
    """Refuse ``--tray`` without ``--every``, or on a system that cannot show the icon.

    Raises:
        ConfigError: With the reason.
    """
    if not args.every:
        raise ConfigError(
            "--tray shows an icon while the periodic checks run: add --every, e.g. --every 12h."
        )
    reason = tray.unavailable_reason()
    if reason:
        raise ConfigError(f"--tray: {reason}")


def _check_now(
    config: Config,
    args: argparse.Namespace,
    *,
    periodic: bool = False,
    on_summary: Callable[[RunSummary], object] | None = None,
) -> int:
    """Run one check of every enabled submission, publish the report and save the summary.

    Args:
        config: Configuration to use.
        args: Options of ``run``.
        periodic: The check is one of the periodic checks of ``run --every``.
        on_summary: Called with the summary of the run, once it is complete.
    """
    if not config.enabled_submissions:
        print("No enabled submissions. Add one with: paper-status-monitor add <tracking link>")
        if periodic:
            log.info("No enabled submissions in the configuration; nothing to check.")
        return EXIT_OK
    monitor = Monitor(config)
    try:
        with state.single_instance():
            if args.wait > 0:
                for problem in monitor.wait_until_ready(args.wait):
                    log.warning(problem)
            summary = monitor.run(dry_run=args.dry_run)
            print(report.render_console(summary))
            if not args.dry_run:
                path = report.publish_report(summary, config)
                if path is not None:
                    print(f"Report: {path}")
                state.save_last_run(summary)
            if on_summary is not None:
                on_summary(summary)
    except state.AlreadyRunningError as exc:
        if periodic:
            log.warning("Check skipped: %s", exc)
        else:
            _error(str(exc))
        return EXIT_FAILURE
    finally:
        monitor.client.close()
    return EXIT_FAILURE if summary.failed else EXIT_OK


def _check_periodically(config: Config, args: argparse.Namespace, interval: timedelta) -> int:
    """Check now and then once every *interval*, until interrupted (``run --every``).

    The configuration file is read again before every check, so changes made in the
    meantime are used; if it has become invalid, the previous settings are kept and
    the problem is logged. With ``--tray``, an icon in the notification area shows
    the latest statuses and lets the user check now or stop (see :mod:`.tray`).
    """
    current = config
    first = True
    wake, stop = threading.Event(), threading.Event()
    icon: tray.TrayIcon | None = None
    if getattr(args, "tray", False):
        icon = tray.TrayIcon(wake=wake, stop=stop, config_path=_explicit_config_path(args))

    def check() -> None:
        nonlocal current, first
        if not first:
            try:
                current = apply_run_overrides(load_config(args.config), args)
            except ConfigError as exc:
                log.error(
                    "The configuration cannot be used (%s); the previous settings are used "
                    "for this check.",
                    exc,
                )
        first = False
        started = datetime.now()
        summaries: list[RunSummary] = []
        if icon is not None:
            icon.update(checking=True, language=current.language, data_dir=current.data_dir)
        try:
            _check_now(current, args, periodic=True, on_summary=summaries.append)
        finally:
            if icon is not None:
                _show_in_tray(
                    icon, current, summaries[-1] if summaries else None, started, interval
                )

    every = scheduling.format_interval(interval)
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(state.periodic_checks_lock())
        except state.AlreadyRunningError as exc:
            log.warning("Periodic checks not started: %s", exc)
            _error(str(exc))
            return EXIT_FAILURE
        loop: dict[str, threading.Event] = {}
        if icon is not None:
            stack.callback(icon.close)
            icon.start(language=current.language, data_dir=current.data_dir)
            loop = {"wake": wake, "stop": stop}
        print(f"Checking now and then every {every}, until stopped (press Ctrl+C to stop).")
        log.info("Periodic checks every %s", every)
        scheduling.run_every(check, interval, **loop)
    return EXIT_OK


def _show_in_tray(
    icon: tray.TrayIcon,
    config: Config,
    summary: RunSummary | None,
    started: datetime,
    interval: timedelta,
) -> None:
    """Show the outcome of a periodic check in the icon (problems are only logged)."""
    try:
        rows = tuple(status_summary.summary_rows(config))
    except Exception:  # never stop the periodic checks because of the icon
        log.exception("The statuses shown by the icon could not be read")
        rows = icon.state.rows
    changes: dict[str, object] = {
        "checking": False,
        "language": config.language,
        "data_dir": config.data_dir,
        "last_check": started,
        "next_check": started + interval,
        "rows": rows,
    }
    if summary is not None:
        changes.update(news=len(summary.changed), failed=len(summary.failed))
        if summary.report_path is not None:
            changes["report"] = summary.report_path
    icon.update(**changes)


def _explicit_config_path(args: argparse.Namespace) -> Path | None:
    """The configuration file given with ``--config``, as an absolute path, or ``None``."""
    return args.config.expanduser().resolve() if args.config else None


def apply_run_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Return *config* with the options of ``run`` that override settings applied.

    They are ``--record-fields``, ``--record-ignore``, ``--notify-fields``,
    ``--notify-ignore``, ``--notify`` and ``--no-open``.

    Raises:
        ConfigError: If an option names an unknown column or notification channel.
    """
    changes: dict[str, object] = {}
    if getattr(args, "record_fields", None) is not None:
        changes["record_fields"] = parse_columns_option(
            args.record_fields, option="--record-fields"
        )
    if getattr(args, "record_ignore", None) is not None:
        changes["record_ignore"] = parse_columns_option(
            args.record_ignore, option="--record-ignore", allow_all=False
        )
    if getattr(args, "notify_fields", None) is not None:
        changes["notify_fields"] = parse_columns_option(
            args.notify_fields, option="--notify-fields"
        )
    if getattr(args, "notify_ignore", None) is not None:
        changes["notify_ignore"] = parse_columns_option(
            args.notify_ignore, option="--notify-ignore", allow_all=False
        )
        changes["ignore_fields"] = ()
    notify = config.notify
    if getattr(args, "notify", None) is not None:
        notify = parse_notify(args.notify, setting="--notify")
        if "email" in notify:
            check_email_ready(config.email, setting="--notify")
    if getattr(args, "no_open", False):
        notify = tuple(channel for channel in notify if channel != "report")
    if notify != config.notify:
        changes["notify"] = notify
    overridden = {key for key in SUBMISSION_OVERRIDES if key in changes}
    if any(overridden & set(submission.overrides) for submission in config.submissions):
        # The options also win over the own settings of the submissions.
        changes["submissions"] = tuple(
            replace(
                submission,
                overrides={k: v for k, v in submission.overrides.items() if k not in overridden},
            )
            for submission in config.submissions
        )
    return replace(config, **changes) if changes else config  # type: ignore[arg-type]


def cmd_organize(args: argparse.Namespace) -> int:
    """Rename or merge workbooks so that their names follow the template."""
    config = load_config(args.config)
    print(f"Workbook names: {config.workbook_name}")
    try:
        with state.single_instance():
            plan = organize.plan_organize(config)
            for line in plan.skipped:
                print(f"Skipped: {line}")
            if not any(name.current is not None for name in plan.names):
                print(f"No recorded submissions found in {config.data_dir}.")
                return EXIT_OK
            if not plan.actions:
                print("Nothing to do: the workbooks follow the naming template.")
                return EXIT_OK
            for action in plan.actions:
                print(action.describe())
            if args.dry_run:
                print("Dry run: nothing was changed. Run without --dry-run to apply the changes.")
                return EXIT_OK
            outcome = organize.apply_organize(plan, config)
    except state.AlreadyRunningError as exc:
        _error(str(exc))
        return EXIT_FAILURE
    print()
    for line in outcome.done:
        print(line)
    if outcome.backup_dir is not None:
        print(f"Copies of the workbooks before merging or splitting: {outcome.backup_dir}")
    for line in outcome.errors:
        _error(line)
    return EXIT_FAILURE if outcome.errors else EXIT_OK


def cmd_gui(args: argparse.Namespace) -> int:
    """Open the graphical interface."""
    from paper_status_monitor import gui  # imported lazily: it is only needed here

    return gui.run_gui(_config_path(args))


def cmd_autostart(args: argparse.Namespace) -> int:
    """Enable, disable or show the launcher that runs the monitor at login."""
    if not autostart.is_supported():
        _error(
            "Built-in autostart is not available on this system. See "
            f"{DOCS_URL}/en/latest/autostart.html"
        )
        return EXIT_USAGE
    if args.action == "enable":
        every = None
        if args.every:
            try:
                every = scheduling.parse_interval(args.every)
            except ValueError as exc:
                raise ConfigError(f"--every: {exc}") from exc
        if args.tray:
            _check_tray_option(args)
        config_path = _explicit_config_path(args)
        load_config(config_path)  # refuse to install a launcher that would fail
        path = autostart.enable(
            wait=args.wait, config_path=config_path, every=every, tray=args.tray
        )
        print(f"Autostart enabled: {path}")
        print(f"Interpreter: {autostart.gui_interpreter()}")
        if every is None:
            print("The monitor will now run in the background every time you log in.")
        else:
            print(
                "The monitor will now run in the background every time you log in, and then "
                f"every {scheduling.format_interval(every)} while you stay logged in "
                "(starting with your next login)."
            )
        if args.tray:
            print(
                "An icon in the notification area shows the latest statuses while the "
                "periodic checks run."
            )
        warning = autostart.session_warning()
        if warning:
            print(f"Warning: {warning}")
        return EXIT_OK
    if args.action == "disable":
        removed = autostart.disable()
        print("Autostart disabled." if removed else "Autostart was not enabled.")
        return EXIT_OK
    info = autostart.status()
    if info is None:
        print("Autostart is not enabled. Enable it with: paper-status-monitor autostart enable")
        return EXIT_OK
    print(f"Launcher:    {info.path}")
    print(f"Interpreter: {info.target}{'' if info.target_exists else '  (MISSING!)'}")
    print(f"Arguments:   {info.arguments}")
    every = info.every
    when = "at login"
    if every is not None:
        when += f", then every {scheduling.format_interval(every)}"
        if info.tray:
            when += ", with an icon in the notification area"
    print(f"Checks:      {when}")
    return EXIT_OK if info.target_exists else EXIT_FAILURE


def cmd_email(args: argparse.Namespace) -> int:
    """Send a test e-mail, or store or delete the SMTP password in the system keyring."""
    config = load_config(args.config)
    settings = config.email
    try:
        if args.action == "test":
            if settings.missing:
                raise ConfigError(
                    f"The [email] table of {config.path} lacks {', '.join(settings.missing)}. "
                    f"See {DOCS_URL}/en/latest/configuration.html#e-mail-notifications"
                )
            password = emails.smtp_password(settings)
            with i18n.language(config.language):
                message = emails.sample_message(settings)
            emails.send(message, settings, password=password)
            print(f"Test e-mail sent to {', '.join(settings.to)} through {settings.smtp_host}.")
            print("Check the inbox (and the spam folder).")
            return EXIT_OK
        if args.action == "set-password":
            if not settings.username:
                raise ConfigError(
                    f"Set 'username' in the [email] table of {config.path} first: the "
                    "password is kept for that user."
                )
            prompt = f"Password of {settings.username} on {settings.smtp_host or 'the server'}: "
            password = getpass.getpass(prompt)
            if not password:
                _error("No password was typed: nothing was stored.")
                return EXIT_USAGE
            emails.store_password(settings, password)
            print(f"The password of {settings.username} is now kept in the system keyring.")
            return EXIT_OK
        removed = emails.delete_password(settings)
    except emails.EmailError as exc:
        _error(str(exc))
        return EXIT_FAILURE
    print("Password removed from the system keyring." if removed else "No password was stored.")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run a series of health checks and print the results."""
    doctor = _Doctor()
    doctor.info(f"paper-status-monitor {__version__}, Python {platform.python_version()}")
    doctor.info(f"Interpreter: {sys.executable}")
    doctor.info(f"Log file: {paths.log_file_path()}")

    config_path = _config_path(args)
    config: Config | None = None
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        doctor.fail(str(exc).splitlines()[0])
    if config is not None:
        enabled = len(config.enabled_submissions)
        if enabled:
            doctor.ok(f"Configuration: {config_path} ({enabled} enabled submission(s))")
        else:
            doctor.warn(f"Configuration: {config_path} has no enabled submissions")
        doctor.info(f"Changes recorded: {describe_columns(config.recorded_columns)}")
        doctor.info(f"Changes notified: {describe_columns(config.notified_columns)}")
        own = [s.display_name for s in config.submissions if s.overrides]
        if own:
            doctor.info(
                f"With their own record/notify settings: {', '.join(own)} "
                "(see: paper-status-monitor list)"
            )
        doctor.info(f"When there is news: {describe_notify(config.notify)}")
        doctor.info(
            "Language of the reports, notifications, e-mails, summary and window: "
            f"{i18n.language_name(config.language)} ({config.language})"
        )
        if "toast" in config.notify:
            problem = notifications.unavailable_reason()
            if problem:
                doctor.warn(f"Desktop notifications: {problem}")
        if "email" in config.notify:
            problem = emails.unavailable_reason(config.email)
            if problem:
                doctor.warn(f"E-mails: {problem}")
            else:
                to = ", ".join(config.email.to)
                doctor.info(f"E-mails are sent to {to} through {config.email.smtp_host}")
        doctor.info(f"Workbook names: {config.workbook_name}")
        if config.time_in_status:
            doctor.info("Workbooks get a 'Time in status' sheet (time_in_status = true)")
        _check_data_dir(doctor, config.data_dir)
        _check_workbook_names(doctor, config)

    try:
        with TrackerClient(timeout=15, retries=0) as client:
            demo = client.fetch(DEMO_UUID)
        doctor.ok(f"Tracker reachable (demo submission status: {demo.status})")
    except TrackerError as exc:
        doctor.fail(f"Tracker not reachable: {exc}")

    if autostart.is_supported():
        _check_autostart(doctor)
    else:
        doctor.info("Autostart: not built in on this platform (see the documentation)")

    _check_last_run(doctor)
    holder = state.periodic_checks_holder()
    if holder:
        doctor.info(f"Periodic checks are running {holder}")
    print()
    print("No problems found." if not doctor.failures else f"{doctor.failures} problem(s) found.")
    return EXIT_FAILURE if doctor.failures else EXIT_OK


# --------------------------------------------------------------------------- helpers


class _Doctor:
    def __init__(self) -> None:
        self.failures = 0

    @staticmethod
    def _line(tag: str, message: str) -> None:
        print(f"[{tag:^4}] {message}")

    def ok(self, message: str) -> None:
        self._line("OK", message)

    def info(self, message: str) -> None:
        self._line("INFO", message)

    def warn(self, message: str) -> None:
        self._line("WARN", message)

    def fail(self, message: str) -> None:
        self.failures += 1
        self._line("FAIL", message)


def _check_data_dir(doctor: _Doctor, data_dir: Path) -> None:
    if not data_dir.is_dir():
        if data_dir.parent.is_dir():
            doctor.warn(f"Data folder {data_dir} does not exist yet (it will be created)")
        else:
            doctor.fail(f"Data folder {data_dir} is not reachable (drive not mounted?)")
        return
    try:
        with tempfile.TemporaryFile(dir=data_dir):
            pass
    except OSError as exc:
        doctor.fail(f"Data folder {data_dir} is not writable: {exc}")
        return
    workbooks = sum(1 for _ in data_dir.glob("*.xlsx"))
    doctor.ok(f"Data folder: {data_dir} ({workbooks} workbook(s))")


def _check_workbook_names(doctor: _Doctor, config: Config) -> None:
    if not config.data_dir.is_dir():
        return
    try:
        plan = organize.plan_organize(config)
    except Exception as exc:  # a diagnosis must never crash
        doctor.warn(f"Could not check the workbook names: {exc}")
        return
    if plan.actions:
        doctor.warn(
            f"{len(plan.actions)} workbook change(s) needed to follow the naming template "
            "(see: paper-status-monitor organize --dry-run)"
        )
    for line in plan.skipped:
        doctor.info(f"Workbook not organized: {line}")


def _check_autostart(doctor: _Doctor) -> None:
    try:
        info = autostart.status()
    except autostart.AutostartError as exc:
        doctor.fail(f"The autostart launcher could not be read: {exc}")
        return
    if info is None:
        doctor.warn("Autostart is not enabled (run: paper-status-monitor autostart enable)")
        return
    if not info.target_exists:
        doctor.fail(
            f"Autostart points to a missing interpreter: {info.target}. "
            "Run 'paper-status-monitor autostart enable' again."
        )
        return
    interpreter = autostart.console_interpreter(info.target)
    try:
        completed = subprocess.run(
            [str(interpreter), "-c", "import paper_status_monitor"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        importable = completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        importable = False
    if not importable:
        doctor.fail(
            f"The interpreter used at login ({interpreter}) cannot import paper_status_monitor. "
            "Install the package in that interpreter or run 'autostart enable' again."
        )
        return
    doctor.ok(f"Autostart enabled: {info.path.name} -> {info.target} {info.arguments}")


def _check_last_run(doctor: _Doctor) -> None:
    last_run = state.load_last_run()
    if not last_run:
        doctor.warn("No completed run recorded yet (run: paper-status-monitor run)")
        return
    finished = str(last_run.get("finished_at", "?"))
    failed = last_run.get("failed", 0)
    message = (
        f"Last run: {finished.replace('T', ' ')} ({last_run.get('checked', 0)} checked, "
        f"{last_run.get('changed', 0)} changed, {failed} failed)"
    )
    try:
        age = datetime.now() - datetime.fromisoformat(finished)
    except ValueError:
        age = None
    if failed:
        doctor.warn(message)
        for name, error in (last_run.get("errors") or {}).items():
            doctor.warn(f"  {name}: {error}")
    elif age is not None and age.days >= _STALE_RUN_DAYS:
        doctor.warn(f"{message} - more than {_STALE_RUN_DAYS} days ago")
    else:
        doctor.ok(message)


def _last_recorded(store: storage.WorkbookStore, submission: SubmissionConfig) -> str:
    try:
        location = store.locate_uuid(submission.uuid)
    except OSError as exc:
        return f"Last recorded status: unavailable ({exc})"
    if location is None or location.last_record is None:
        return "Last recorded status: none yet"
    record = location.last_record
    detected = record.get(DETECTED_AT_COLUMN) or "unknown date"
    return (
        f"Last recorded status: {record.get('Status') or '-'} ({detected}) in {location.path.name}"
    )


def _config_path(args: argparse.Namespace) -> Path:
    return args.config.expanduser() if args.config else paths.default_config_path()


def _language_argument(value: str) -> str:
    """Check the language given on the command line (an argparse ``type``)."""
    try:
        return i18n.normalize_language(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _parse_uuid_argument(value: str) -> str | None:
    try:
        return parse_uuid(value)
    except ValueError as exc:
        _error(str(exc))
        return None


def _error(message: str) -> None:
    log.debug("Reported to the user: %s", message)
    if sys.stderr is not None:
        print(f"Error: {message}", file=sys.stderr)


def _make_streams_safe() -> None:
    """Avoid crashes when printing non-ASCII text to a limited console encoding."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")
