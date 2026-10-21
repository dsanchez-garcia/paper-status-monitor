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
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paper_status_monitor import autostart, paths, report, state, storage
from paper_status_monitor._version import __version__
from paper_status_monitor.client import DEMO_UUID, TrackerClient, TrackerError, parse_uuid
from paper_status_monitor.config import (
    Config,
    ConfigError,
    SubmissionConfig,
    add_submission,
    load_config,
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
    init.set_defaults(handler=cmd_init)

    add = commands.add_parser(
        "add",
        help="add a submission to the configuration",
        description="Add a submission, given its tracking link or UUID, to the configuration.",
    )
    add.add_argument("submission", help="tracking link or UUID")
    add.add_argument("--label", default="", help="short name shown in the reports")
    add.add_argument(
        "--no-verify", action="store_true", help="do not contact the tracker before adding"
    )
    add.set_defaults(handler=cmd_add)

    listing = commands.add_parser(
        "list",
        help="list the configured submissions",
        description="List the configured submissions and their last recorded status.",
    )
    listing.set_defaults(handler=cmd_list)

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
            "report when something changed."
        ),
    )
    run.add_argument(
        "--wait",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait up to SECONDS for the network and the data folder (useful at login)",
    )
    run.add_argument("--no-open", action="store_true", help="do not open the report")
    run.add_argument(
        "--dry-run", action="store_true", help="show the changes without writing anything"
    )
    run.set_defaults(handler=cmd_run)

    auto = commands.add_parser(
        "autostart",
        help="run the monitor automatically at login (Windows)",
        description=(
            "Manage the Startup-folder shortcut that runs the monitor, without a console "
            "window, every time you log in to Windows."
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
    return EXIT_OK


def cmd_add(args: argparse.Namespace) -> int:
    """Add a submission to the configuration file."""
    path = _config_path(args)
    uuid = _parse_uuid_argument(args.submission)
    if uuid is None:
        return EXIT_USAGE
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
    add_submission(path, uuid, args.label)
    print(f"Added to {path}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """List the configured submissions and their last recorded status."""
    config = load_config(args.config)
    print(f"Configuration: {config.path}")
    print(f"Data folder:   {config.data_dir}")
    if not config.submissions:
        print("\nNo submissions yet. Add one with: paper-status-monitor add <tracking link>")
        return EXIT_OK
    for index, submission in enumerate(config.submissions, start=1):
        state_note = "" if submission.enabled else "  [disabled]"
        print(f"\n{index}. {submission.label or '(no label)'}{state_note}")
        print(f"   {submission.tracker_url}")
        print(f"   {_last_recorded(config, submission)}")
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
    """Check every enabled submission and record the changes."""
    config = load_config(args.config)
    if not config.enabled_submissions:
        print("No enabled submissions. Add one with: paper-status-monitor add <tracking link>")
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
                _publish_report(
                    summary, config, open_report=config.open_report and not args.no_open
                )
                state.save_last_run(summary)
    except state.AlreadyRunningError as exc:
        _error(str(exc))
        return EXIT_FAILURE
    finally:
        monitor.client.close()
    return EXIT_FAILURE if summary.failed else EXIT_OK


def cmd_autostart(args: argparse.Namespace) -> int:
    """Enable, disable or show the Windows autostart shortcut."""
    if not autostart.is_supported():
        _error(
            "Built-in autostart is only available on Windows. On Linux or macOS see "
            f"{DOCS_URL}/en/latest/autostart.html"
        )
        return EXIT_USAGE
    if args.action == "enable":
        config_path = args.config.expanduser().resolve() if args.config else None
        load_config(config_path)  # refuse to install a launcher that would fail
        path = autostart.enable(wait=args.wait, config_path=config_path)
        print(f"Autostart enabled: {path}")
        print(f"Interpreter: {autostart.gui_interpreter()}")
        print("The monitor will now run in the background every time you log in.")
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
        _check_data_dir(doctor, config.data_dir)

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


def _publish_report(summary: RunSummary, config: Config, *, open_report: bool) -> None:
    include_errors = config.notify_on_errors
    if not report.should_write_report(summary, include_errors=include_errors):
        return
    try:
        path = report.write_report(
            summary,
            config.reports_dir,
            fallback_directory=paths.fallback_reports_dir(),
            include_errors=include_errors,
        )
    except OSError as exc:
        log.error("The report could not be written: %s", exc)
        return
    summary.report_path = path
    log.info("Report written to %s", path)
    print(f"Report: {path}")
    if open_report:
        report.open_path(path)


def _last_recorded(config: Config, submission: SubmissionConfig) -> str:
    try:
        path = storage.find_workbook_by_uuid(config.data_dir, submission.uuid)
        record = storage.last_record(path) if path is not None else None
    except OSError as exc:
        return f"Last recorded status: unavailable ({exc})"
    if path is None or record is None:
        return "Last recorded status: none yet"
    detected = record.get(DETECTED_AT_COLUMN) or "unknown date"
    return f"Last recorded status: {record.get('Status') or '-'} ({detected}) in {path.name}"


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
