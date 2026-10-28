"""Command-line interface (``paper-status-monitor``)."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import platform
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paper_status_monitor import (
    autostart,
    notifications,
    organize,
    paths,
    report,
    scheduling,
    state,
    storage,
)
from paper_status_monitor import summary as status_summary
from paper_status_monitor._version import __version__
from paper_status_monitor.client import DEMO_UUID, TrackerClient, TrackerError, parse_uuid
from paper_status_monitor.config import (
    Config,
    ConfigError,
    SubmissionConfig,
    add_submission,
    describe_columns,
    describe_notify,
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
from paper_status_monitor.monitor import Monitor

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
            "column, e.g. --field paper=TMY (repeat for several fields)"
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
        "--notify",
        metavar="CHANNELS",
        help=(
            'how to tell you about news in this run: "report" (open the report), "toast" '
            '(desktop notification), "report,toast" or "none"'
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
        help="rename or merge the workbooks to follow the naming template",
        description=(
            "Rename existing workbooks, or merge them, so that their names follow the "
            "workbook_name setting. Merged workbooks are copied to the 'backups' subfolder "
            "of the data folder first."
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
        help="run the monitor automatically at login (Windows)",
        description=(
            "Manage the Startup-folder shortcut that runs the monitor, without a console "
            "window, every time you log in to Windows (and, with --every, periodically "
            "while you stay logged in)."
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
    auto.set_defaults(handler=cmd_autostart)

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
    write_config(path, data_dir, overwrite=True)
    print(f"Configuration file created: {path}")
    print(f"Data folder: {data_dir}")
    print()
    print("Next steps:")
    print("  1. paper-status-monitor add <tracking link>")
    print("  2. paper-status-monitor run")
    print("  3. paper-status-monitor autostart enable   (Windows: check at every login)")
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
        print(f"   {_last_recorded(store, submission)}")
    return EXIT_OK


def cmd_summary(args: argparse.Namespace) -> int:
    """Show one table with the latest recorded status of every submission."""
    config = load_config(args.config)
    if not config.data_dir.is_dir() and not config.data_dir.parent.is_dir():
        log.warning("The data folder is not reachable (%s): no status is shown.", config.data_dir)
    rows = status_summary.summary_rows(config)
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
    if not getattr(args, "every", None):
        return _check_now(config, args)
    try:
        interval = scheduling.parse_interval(args.every)
    except ValueError as exc:
        raise ConfigError(f"--every: {exc}") from exc
    return _check_periodically(config, args, interval)


def _check_now(config: Config, args: argparse.Namespace, *, periodic: bool = False) -> int:
    """Run one check of every enabled submission, publish the report and save the summary."""
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
    the problem is logged.
    """
    current = config
    first = True

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
        _check_now(current, args, periodic=True)

    every = scheduling.format_interval(interval)
    print(f"Checking now and then every {every}, until stopped (press Ctrl+C to stop).")
    log.info("Periodic checks every %s", every)
    scheduling.run_every(check, interval)
    return EXIT_OK


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
    if getattr(args, "no_open", False):
        notify = tuple(channel for channel in notify if channel != "report")
    if notify != config.notify:
        changes["notify"] = notify
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
        print(f"Copies of the workbooks before merging: {outcome.backup_dir}")
    for line in outcome.errors:
        _error(line)
    return EXIT_FAILURE if outcome.errors else EXIT_OK


def cmd_gui(args: argparse.Namespace) -> int:
    """Open the graphical interface."""
    from paper_status_monitor import gui  # imported lazily: it is only needed here

    return gui.run_gui(_config_path(args))


def cmd_autostart(args: argparse.Namespace) -> int:
    """Enable, disable or show the Windows autostart shortcut."""
    if not autostart.is_supported():
        _error(
            "Built-in autostart is only available on Windows. On Linux or macOS see "
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
        config_path = args.config.expanduser().resolve() if args.config else None
        load_config(config_path)  # refuse to install a launcher that would fail
        path = autostart.enable(wait=args.wait, config_path=config_path, every=every)
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
        return EXIT_OK
    if args.action == "disable":
        removed = autostart.disable()
        print("Autostart disabled." if removed else "Autostart was not enabled.")
        return EXIT_OK
    info = autostart.status()
    if info is None:
        print("Autostart is not enabled. Enable it with: paper-status-monitor autostart enable")
        return EXIT_OK
    print(f"Shortcut:    {info.path}")
    print(f"Interpreter: {info.target}{'' if info.target_exists else '  (MISSING!)'}")
    print(f"Arguments:   {info.arguments}")
    every = info.every
    when = "at login"
    if every is not None:
        when += f", then every {scheduling.format_interval(every)}"
    print(f"Checks:      {when}")
    return EXIT_OK if info.target_exists else EXIT_FAILURE


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
        doctor.info(f"When there is news: {describe_notify(config.notify)}")
        if "toast" in config.notify:
            problem = notifications.unavailable_reason()
            if problem:
                doctor.warn(f"Desktop notifications: {problem}")
        doctor.info(f"Workbook names: {config.workbook_name}")
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
        doctor.fail(f"Autostart shortcut could not be read: {exc}")
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
