from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from paper_status_monitor import _powershell, notifications
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import SubmissionConfig
from paper_status_monitor.models import Change, Snapshot
from paper_status_monitor.monitor import RunSummary, SubmissionResult
from paper_status_monitor.notifications import Notification, NotificationButton

STARTED = datetime(2026, 1, 2, 9, 30, 0)
OTHER_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def snapshot(demo_payload: dict) -> Snapshot:
    return Snapshot.from_api(demo_payload)


def changed(snapshot: Snapshot, label: str = "Demo", *changes: Change) -> SubmissionResult:
    return SubmissionResult(
        SubmissionConfig(DEMO_UUID, label=label),
        snapshot=snapshot,
        changes=list(changes) or [Change("Status", "Under Review", "Required Reviews Complete")],
    )


def new(snapshot: Snapshot) -> SubmissionResult:
    return SubmissionResult(SubmissionConfig(OTHER_UUID), snapshot=snapshot, is_new=True)


def failed(label: str = "Broken") -> SubmissionResult:
    return SubmissionResult(
        SubmissionConfig(DEMO_UUID, label=label),
        error="The tracker answered HTTP 503; try again later.",
    )


def summary(*results: SubmissionResult) -> RunSummary:
    return RunSummary(started_at=STARTED, results=list(results))


# ------------------------------------------------------------------ content


def test_no_news_no_notification(snapshot: Snapshot) -> None:
    quiet = SubmissionResult(SubmissionConfig(DEMO_UUID), snapshot=snapshot)
    assert notifications.build_notification(summary(quiet)) is None
    assert notifications.build_notification(summary(failed()), include_errors=False) is None


def test_one_changed_submission(snapshot: Snapshot, tmp_path: Path) -> None:
    result = changed(
        snapshot,
        "Tau paper",
        Change("Status", "Under Review", "Required Reviews Complete"),
        Change("Reviews completed", "1", "2"),
    )
    report = tmp_path / "changes.txt"
    notification = notifications.build_notification(summary(result), report=report)
    assert notification == Notification(
        "Status changed: Tau paper",
        "Status: Under Review → Required Reviews Complete\nReviews completed: 1 → 2",
        report,
        (
            NotificationButton("Open report", report),
            NotificationButton("Tracking page", result.submission.tracker_url),
        ),
    )


def test_buttons_open_the_report_the_workbook_and_the_tracking_page(
    snapshot: Snapshot, tmp_path: Path
) -> None:
    workbook = tmp_path / "Tau.xlsx"
    workbook.write_bytes(b"")
    report = tmp_path / "changes.txt"
    result = replace(changed(snapshot, "Tau"), workbook=workbook)
    notification = notifications.build_notification(summary(result), report=report)
    assert notification is not None
    assert notification.buttons == (
        NotificationButton("Open report", report),
        NotificationButton("Open workbook", workbook),
        NotificationButton("Tracking page", result.submission.tracker_url),
    )
    missing = replace(result, workbook=tmp_path / "not written yet.xlsx")
    labels = [button.label for button in notifications.build_notification(summary(missing)).buttons]
    assert labels == ["Tracking page"]  # no report, and the workbook does not exist
    broken = notifications.build_notification(summary(failed()), report=report)
    assert [button.label for button in broken.buttons] == ["Open report", "Tracking page"]


def test_buttons_of_several_submissions(snapshot: Snapshot, tmp_path: Path) -> None:
    shared, other = tmp_path / "Tau.xlsx", tmp_path / "Epsilon.xlsx"
    for path in (shared, other):
        path.write_bytes(b"")
    report = tmp_path / "changes.txt"
    first = replace(changed(snapshot, "Tau R1"), workbook=shared)
    second = replace(new(snapshot), workbook=shared)
    together = notifications.build_notification(summary(first, second), report=report)
    assert together.buttons == (
        NotificationButton("Open report", report),
        NotificationButton("Open workbook", shared),
    )
    apart = replace(second, workbook=other)
    separate = notifications.build_notification(summary(first, apart, failed()), report=report)
    assert separate.buttons == (
        NotificationButton("Open report", report),
        NotificationButton("Open folder", tmp_path),
    )


def test_one_new_submission(snapshot: Snapshot) -> None:
    notification = notifications.build_notification(summary(new(snapshot)))
    assert notification is not None
    assert notification.title.startswith("Now tracking: Influence of submission trackers")
    assert notification.title.endswith("…")  # long titles are shortened
    assert notification.message == (
        "Status: Under Review\nThe International Journal of Submission Trackers"
    )


def test_one_failed_check() -> None:
    notification = notifications.build_notification(summary(failed()))
    assert notification is not None
    assert notification.title == "Paper status: a check failed"
    assert notification.message == "Broken: The tracker answered HTTP 503; try again later."


def test_several_submissions(snapshot: Snapshot) -> None:
    two_changes = changed(
        snapshot, "Tau", Change("Status", "a", "b"), Change("Reviews completed", "1", "2")
    )
    notification = notifications.build_notification(
        summary(two_changes, new(snapshot), failed("Epsilon"))
    )
    assert notification is not None
    assert notification.title == "Paper status: 1 changed, 1 new, 1 failed"
    lines = notification.message.splitlines()
    assert lines[0] == "Tau: Status → b (+1 more)"
    assert lines[1].endswith(": now tracked")
    assert lines[2] == "Epsilon: could not be checked"


def test_long_lists_are_cut(snapshot: Snapshot) -> None:
    results = [changed(snapshot, f"Paper {number}") for number in range(6)]
    notification = notifications.build_notification(summary(*results))
    assert notification is not None
    lines = notification.message.splitlines()
    assert len(lines) == notifications.MAX_LINES
    assert lines[-1] == "... and 3 more submissions: see the report"


def test_names_fall_back_to_the_title_and_the_uuid(snapshot: Snapshot) -> None:
    titled = changed(replace(snapshot, title="Short title"), "")
    assert notifications.build_notification(summary(titled)).title.endswith(": Short title")
    anonymous = SubmissionResult(SubmissionConfig(OTHER_UUID), error="offline")
    assert notifications.build_notification(summary(anonymous)).message.startswith(OTHER_UUID)


def test_toast_xml_escapes_the_text_and_links_the_report(tmp_path: Path) -> None:
    report = tmp_path / "my reports" / "changes.txt"
    xml = notifications.toast_xml(Notification('R&D <paper> "x"', "a → b\nc", report))
    assert '<text>R&amp;D &lt;paper&gt; "x"</text>' in xml
    assert "<text>a → b\nc</text>" in xml
    assert 'activationType="protocol"' in xml
    assert "my%20reports/changes.txt" in xml
    assert "<actions>" not in xml
    assert "launch=" not in notifications.toast_xml(Notification("t", "m"))


def test_toast_xml_buttons_use_protocol_activation(tmp_path: Path) -> None:
    workbook = tmp_path / "Tau & co.xlsx"
    buttons = (
        NotificationButton("Open workbook", workbook),
        NotificationButton("Tracking page", "https://example.org/?uuid=1&x=2"),
        NotificationButton("Ignored", "javascript:alert(1)"),
        NotificationButton("Fourth", "https://example.org/4"),
        NotificationButton("Fifth", "https://example.org/5"),
    )
    xml = notifications.toast_xml(Notification("t", "m", buttons=buttons))
    actions = xml[xml.index("<actions>") : xml.index("</actions>")]
    assert actions.count("<action ") == 2  # unsupported targets and extra buttons are dropped
    assert '<action content="Open workbook" activationType="protocol" arguments="file:' in xml
    assert "Tau%20%26%20co.xlsx" in xml
    assert 'arguments="https://example.org/?uuid=1&amp;x=2"' in xml
    assert "javascript" not in xml
    assert "Fourth" not in xml
    assert xml.index("</visual>") < xml.index("<actions>") < xml.index("</toast>")


def test_sample_notification() -> None:
    sample = notifications.sample_notification()
    assert sample.title == notifications.APP_NAME
    assert "work" in sample.message


# ------------------------------------------------------------------ showing


@pytest.fixture
def on_platform(monkeypatch: pytest.MonkeyPatch):
    def choose(name: str) -> None:
        monkeypatch.setattr(notifications.sys, "platform", name)

    return choose


def test_windows_toasts_use_powershell(on_platform, monkeypatch: pytest.MonkeyPatch) -> None:
    on_platform("win32")
    calls: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(
        notifications._powershell,
        "run_script",
        lambda script, variables, timeout=None: calls.append((script, dict(variables))) or "",
    )
    notifications.show(Notification("Title", "Message"))
    [(script, variables)] = calls
    assert "ToastNotificationManager" in script
    assert "CreateToastNotifier($env:PSM_TOAST_APP)" in script
    assert variables["PSM_TOAST_APP"] == notifications.WINDOWS_APP_ID
    assert notifications.WINDOWS_APP_ID.endswith(r"\WindowsPowerShell\v1.0\powershell.exe")
    assert "<text>Title</text>" in variables["PSM_TOAST_XML"]


def test_windows_toast_failures_are_reported(on_platform, monkeypatch: pytest.MonkeyPatch) -> None:
    on_platform("win32")

    def fail(*args: object, **kwargs: object) -> str:
        raise _powershell.PowerShellError("Access denied")

    monkeypatch.setattr(notifications._powershell, "run_script", fail)
    with pytest.raises(notifications.NotificationError, match="Access denied"):
        notifications.show(Notification("Title", "Message"))


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record the commands run by the notifications instead of running them."""
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    return calls


def test_macos_uses_osascript(on_platform, commands: list[list[str]]) -> None:
    on_platform("darwin")
    notifications.show(Notification('Say "hi"', "Message"))
    [command] = commands
    assert command[0] == "osascript"
    assert "display notification (item 2 of argv) with title (item 1 of argv)" in command
    assert command[-2:] == ['Say "hi"', "Message"]  # arguments, never interpolated


def test_linux_uses_notify_send(
    on_platform, commands: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    on_platform("linux")
    monkeypatch.setattr(notifications.shutil, "which", lambda name: f"/usr/bin/{name}")
    notifications.show(Notification("Title", "Message"))
    assert commands == [["notify-send", "--app-name", "paper-status-monitor", "Title", "Message"]]


def test_linux_without_notify_send(on_platform, monkeypatch: pytest.MonkeyPatch) -> None:
    on_platform("linux")
    monkeypatch.setattr(notifications.shutil, "which", lambda name: None)
    assert "libnotify" in (notifications.unavailable_reason() or "")
    with pytest.raises(notifications.NotificationError, match="notify-send was not found"):
        notifications.show(Notification("Title", "Message"))


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (subprocess.CompletedProcess([], 1, stdout="", stderr="no display"), "no display"),
        (OSError("not found"), "could not be run"),
        (subprocess.TimeoutExpired("osascript", 60), "could not be run"),
    ],
)
def test_command_failures_are_reported(
    on_platform, monkeypatch: pytest.MonkeyPatch, outcome: object, message: str
) -> None:
    on_platform("darwin")

    def fake_run(command: list[str], **kwargs: object) -> object:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    with pytest.raises(notifications.NotificationError, match=message):
        notifications.show(Notification("Title", "Message"))


@pytest.mark.parametrize(
    ("platform", "program"),
    [("win32", "powershell.exe"), ("darwin", "osascript"), ("linux", "notify-send")],
)
def test_unavailable_reason(
    on_platform, monkeypatch: pytest.MonkeyPatch, platform: str, program: str
) -> None:
    on_platform(platform)
    monkeypatch.setattr(notifications.shutil, "which", lambda name: name)
    assert notifications.unavailable_reason() is None
    monkeypatch.setattr(notifications.shutil, "which", lambda name: None)
    assert program in (notifications.unavailable_reason() or "")


def test_notify_run(snapshot: Snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[Notification] = []
    monkeypatch.setattr(notifications, "show", shown.append)
    assert notifications.notify_run(summary()) is False
    assert notifications.notify_run(summary(changed(snapshot))) is True
    assert len(shown) == 1

    def fail(notification: Notification) -> None:
        raise notifications.NotificationError("no display")

    monkeypatch.setattr(notifications, "show", fail)
    assert notifications.notify_run(summary(changed(snapshot))) is False  # logged, not raised
