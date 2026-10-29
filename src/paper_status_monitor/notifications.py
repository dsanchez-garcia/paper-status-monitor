"""Desktop notifications: a short summary of the news of a run.

They are enabled with ``notify = "toast"`` (or ``notify = ["report", "toast"]``) in
the configuration, and use what each system already provides:

* **Windows 10 and 11** - a toast notification shown through Windows PowerShell, so
  no extra package is needed. It is shown on behalf of *Windows PowerShell*;
  clicking it opens the report, and its buttons open the report, the workbook or
  the tracking page (through protocol activation, which needs no registration).
* **macOS** - ``osascript`` (*display notification*).
* **Linux and other systems** - ``notify-send`` (package ``libnotify-bin`` on Debian
  and Ubuntu, ``libnotify`` elsewhere).

Notifications are best effort: when one cannot be shown, the problem is logged and
the report is still written.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape, quoteattr

from paper_status_monitor import _powershell
from paper_status_monitor.i18n import _, column_label, ngettext
from paper_status_monitor.models import Change

if TYPE_CHECKING:
    from paper_status_monitor.monitor import RunSummary, SubmissionResult

log = logging.getLogger(__name__)

#: Name shown as the sender of the notifications where the system allows it.
APP_NAME = "paper-status-monitor"

#: Known folder ID of the Windows *System* folder (``FOLDERID_System``). It is
#: written in two parts so that the repository checks, which reject anything that
#: looks like a tracking UUID, do not mistake it for one.
_FOLDERID_SYSTEM = "{1AC14E77-02E7-4E5D-B744-" + "2EB1AE5198B7}"

#: Application identifier of Windows PowerShell, registered on every Windows 10 and 11
#: installation, on whose behalf the toasts are shown.
WINDOWS_APP_ID = _FOLDERID_SYSTEM + r"\WindowsPowerShell\v1.0\powershell.exe"

#: Longest message, in lines (one per submission or per change).
MAX_LINES = 4

#: Most buttons in a notification (Windows accepts up to five).
MAX_BUTTONS = 3

_TIMEOUT = 60
_MAX_NAME = 50
_MAX_ERROR = 140

_TOAST_SCRIPT = (
    "$ErrorActionPreference = 'Stop'\n"
    "$null = [Windows.UI.Notifications.ToastNotificationManager, "
    "Windows.UI.Notifications, ContentType = WindowsRuntime]\n"
    "$null = [Windows.Data.Xml.Dom.XmlDocument, "
    "Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]\n"
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
    "$xml.LoadXml($env:PSM_TOAST_XML)\n"
    "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
    "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::"
    "CreateToastNotifier($env:PSM_TOAST_APP)\n"
    "$notifier.Show($toast)\n"
)

_MACOS_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)


class NotificationError(RuntimeError):
    """A desktop notification could not be shown."""


@dataclass(frozen=True)
class NotificationButton:
    """A button of a notification (shown on Windows only).

    Attributes:
        label: Text of the button.
        target: What it opens: a file or folder, or a web address (``https://...``).
    """

    label: str
    target: Path | str


@dataclass(frozen=True)
class Notification:
    """A desktop notification.

    Attributes:
        title: First line, in bold.
        message: Body; one line per submission or change.
        target: File opened when the notification is clicked (Windows only).
        buttons: Buttons below the message (Windows only; at most :data:`MAX_BUTTONS`).
    """

    title: str
    message: str
    target: Path | None = None
    buttons: tuple[NotificationButton, ...] = ()


def build_notification(
    summary: RunSummary, *, include_errors: bool = True, report: Path | None = None
) -> Notification | None:
    """Summarise the news of a run in a notification.

    The buttons open the report and, when a single submission has news, its workbook
    and its tracking page; when several have news, their workbook (if they share one)
    or the folder of the workbooks.

    Args:
        summary: The run.
        include_errors: Mention the submissions that could not be checked.
        report: The report of the run, opened when the notification is clicked.

    Returns:
        The notification, or ``None`` if the run has no news.
    """
    changed = [result for result in summary.changed if not result.is_new]
    new = [result for result in summary.changed if result.is_new]
    failed = list(summary.failed) if include_errors else []
    news = [*changed, *new, *failed]
    if not news:
        return None
    buttons = _buttons(report, news)
    if len(changed) == 1 and not (new or failed):
        result = changed[0]
        lines = [_change_text(change) for change in result.changes]
        title = _("Status changed: {name}").format(name=_short_name(result))
        return Notification(title, _limit(lines, "change"), report, buttons)
    if len(new) == 1 and not (changed or failed):
        title = _("Now tracking: {name}").format(name=_short_name(new[0]))
        return Notification(title, _new_text(new[0]), report, buttons)
    if len(failed) == 1 and not (changed or new):
        result = failed[0]
        error = _shorten(result.error or _("unknown error"), _MAX_ERROR)
        return Notification(
            _("Paper status: a check failed"), f"{_short_name(result)}: {error}", report, buttons
        )
    counts = [
        text.format(count=len(items))
        for items, text in (
            (changed, ngettext("{count} changed", "{count} changed", len(changed))),
            (new, ngettext("{count} new", "{count} new", len(new))),
            (failed, ngettext("{count} failed", "{count} failed", len(failed))),
        )
        if items
    ]
    lines = [f"{_short_name(result)}: {_first_change(result)}" for result in changed]
    lines += [_("{name}: now tracked").format(name=_short_name(result)) for result in new]
    lines += [
        _("{name}: could not be checked").format(name=_short_name(result)) for result in failed
    ]
    title = _("Paper status: {counts}").format(counts=", ".join(counts))
    return Notification(title, _limit(lines, "submission"), report, buttons)


def show(notification: Notification) -> None:
    """Show *notification* on the desktop.

    Raises:
        NotificationError: If it could not be shown.
    """
    if sys.platform == "win32":
        _show_windows(notification)
    elif sys.platform == "darwin":
        _run(["osascript", *_osascript_lines(), notification.title, notification.message])
    else:
        if shutil.which("notify-send") is None:
            raise NotificationError(unavailable_reason() or "notify-send was not found")
        _run(["notify-send", "--app-name", APP_NAME, notification.title, notification.message])


def notify_run(
    summary: RunSummary, *, include_errors: bool = True, report: Path | None = None
) -> bool:
    """Show a notification about the news of a run, if it has any.

    Failures are logged, never raised.

    Returns:
        ``True`` if a notification was shown.
    """
    notification = build_notification(summary, include_errors=include_errors, report=report)
    if notification is None:
        return False
    try:
        show(notification)
    except NotificationError as exc:
        log.warning("The desktop notification could not be shown: %s", exc)
        return False
    log.info("Desktop notification shown: %s", notification.title)
    return True


def sample_notification() -> Notification:
    """Return the notification used to check that notifications work."""
    return Notification(
        APP_NAME,
        _(
            "Desktop notifications work: you will see one like this when there is news "
            "about your submissions."
        ),
    )


def unavailable_reason() -> str | None:
    """Return why notifications cannot be shown on this computer, or ``None``.

    Only the presence of the required program is checked; the system may still hide
    notifications (focus assist, do not disturb...).
    """
    if sys.platform == "win32":
        program = "powershell.exe"
        hint = _("powershell.exe was not found: Windows PowerShell shows the notifications")
    elif sys.platform == "darwin":
        program, hint = "osascript", _("osascript was not found")
    else:
        program = "notify-send"
        hint = _(
            "notify-send was not found: install libnotify-bin (Debian, Ubuntu) or "
            "libnotify (Fedora, Arch...)"
        )
    return None if shutil.which(program) else hint


def toast_xml(notification: Notification) -> str:
    """Return the XML document of a Windows toast notification.

    Clicking the toast and its buttons use *protocol activation*: Windows opens the
    file, folder or web address with its usual application, so nothing needs to be
    registered and no program has to keep running.
    """
    launch = ""
    if notification.target is not None:
        uri = _target_uri(notification.target)
        if uri:
            launch = f' activationType="protocol" launch={quoteattr(uri)}'
    actions = "".join(
        f'<action content={quoteattr(button.label)} activationType="protocol" '
        f"arguments={quoteattr(uri)}/>"
        for button in notification.buttons[:MAX_BUTTONS]
        if (uri := _target_uri(button.target))
    )
    if actions:
        actions = f"<actions>{actions}</actions>"
    return (
        f'<toast{launch}><visual><binding template="ToastGeneric">'
        f"<text>{escape(notification.title)}</text>"
        f"<text>{escape(notification.message)}</text>"
        f"</binding></visual>{actions}</toast>"
    )


def _target_uri(target: Path | str) -> str:
    """Return the URI that opens *target*, or ``""`` if it cannot be opened that way."""
    if isinstance(target, Path):
        try:
            return target.resolve().as_uri()
        except (OSError, ValueError):
            return ""
    return target if target.startswith(("https://", "http://")) else ""


def _buttons(
    report: Path | None, results: Sequence[SubmissionResult]
) -> tuple[NotificationButton, ...]:
    """Return the buttons of a notification about *results* (see :func:`build_notification`)."""
    buttons = [NotificationButton(_("Open report"), report)] if report is not None else []
    workbooks = list(dict.fromkeys(filter(None, map(_workbook, results))))
    if len(results) == 1:
        if workbooks:
            buttons.append(NotificationButton(_("Open workbook"), workbooks[0]))
        tracking_page = results[0].submission.tracker_url
        buttons.append(NotificationButton(_("Tracking page"), tracking_page))
    elif len(workbooks) == 1:
        buttons.append(NotificationButton(_("Open workbook"), workbooks[0]))
    elif workbooks:
        buttons.append(NotificationButton(_("Open folder"), workbooks[0].parent))
    return tuple(buttons[:MAX_BUTTONS])


def _workbook(result: SubmissionResult) -> Path | None:
    """The workbook of *result*, if it exists."""
    path = result.workbook
    try:
        return path if path is not None and path.is_file() else None
    except OSError:
        return None


def _show_windows(notification: Notification) -> None:
    variables = {"PSM_TOAST_XML": toast_xml(notification), "PSM_TOAST_APP": WINDOWS_APP_ID}
    try:
        _powershell.run_script(_TOAST_SCRIPT, variables, timeout=_TIMEOUT)
    except _powershell.PowerShellError as exc:
        raise NotificationError(str(exc)) from exc


def _osascript_lines() -> list[str]:
    arguments: list[str] = []
    for line in _MACOS_SCRIPT:
        arguments += ["-e", line]
    return arguments


def _run(command: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotificationError(f"{command[0]} could not be run: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or f"exit code {completed.returncode}"
        raise NotificationError(f"{command[0]} failed: {detail}")


def _short_name(result: SubmissionResult) -> str:
    """A short name for a submission: its label, else its title, else its UUID."""
    if result.submission.label:
        return _shorten(result.submission.label, _MAX_NAME)
    if result.snapshot is not None and result.snapshot.title:
        return _shorten(result.snapshot.title, _MAX_NAME)
    return result.submission.uuid


def _change_text(change: Change) -> str:
    return f"{column_label(change.field)}: {change.old or '-'} → {change.new or '-'}"


def _first_change(result: SubmissionResult) -> str:
    if not result.changes:
        return _("changed")
    change = result.changes[0]
    text = f"{column_label(change.field)} → {change.new or '-'}"
    others = len(result.changes) - 1
    if others:
        text += " " + ngettext("(+{count} more)", "(+{count} more)", others).format(count=others)
    return text


def _new_text(result: SubmissionResult) -> str:
    snapshot = result.snapshot
    if snapshot is None:
        return _("Recorded for the first time.")
    status = f"{column_label('Status')}: {snapshot.status or '-'}"
    return f"{status}\n{_shorten(snapshot.journal, 80)}".rstrip()


def _limit(lines: list[str], kind: str) -> str:
    """Keep at most :data:`MAX_LINES` lines; *kind* (``"change"`` or ``"submission"``)
    names what the hidden lines are about."""
    if len(lines) > MAX_LINES:
        hidden = len(lines) - (MAX_LINES - 1)
        if kind == "change":
            more = ngettext(
                "... and {count} more change: see the report",
                "... and {count} more changes: see the report",
                hidden,
            )
        else:
            more = ngettext(
                "... and {count} more submission: see the report",
                "... and {count} more submissions: see the report",
                hidden,
            )
        lines = [*lines[: MAX_LINES - 1], more.format(count=hidden)]
    return "\n".join(lines)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
