from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from paper_status_monitor import i18n, tray
from paper_status_monitor.summary import SummaryRow
from paper_status_monitor.tray import MenuEntry, TrayIcon, TrayState

NOW = datetime(2026, 10, 29, 9, 30)


def rows(count: int = 2) -> tuple[SummaryRow, ...]:
    tau = SummaryRow(
        1, "Tau", recorded=True, status="Under Review", since=date(2026, 9, 1), days=58
    )
    epsilon = SummaryRow(2, "Epsilon", enabled=False)
    extra = tuple(
        SummaryRow(number, f"Paper {number}", recorded=True, status="Review Complete")
        for number in range(3, count + 1)
    )
    return (tau, epsilon, *extra)[:count]


def checked(**changes: Any) -> TrayState:
    values: dict[str, Any] = {
        "last_check": datetime(2026, 10, 29, 9, 0),
        "next_check": datetime(2026, 10, 29, 21, 0),
        "rows": rows(),
        "data_dir": Path("data"),
    }
    values.update(changes)
    return TrayState(**values)


# ------------------------------------------------------------------ texts


def test_tooltip() -> None:
    assert tray.tooltip_text(TrayState(), now=NOW) == "paper-status-monitor\nNo check yet."
    assert tray.tooltip_text(checked(checking=True), now=NOW).endswith("\nChecking now...")
    assert tray.tooltip_text(checked(), now=NOW) == (
        "paper-status-monitor\nLast check: 09:00, no news\nNext check: 21:00"
    )
    busy = checked(news=1, failed=2, next_check=datetime(2026, 10, 30, 9, 0))
    assert tray.tooltip_text(busy, now=NOW) == (
        "paper-status-monitor\nLast check: 09:00, 1 with news, 2 failed\n"
        "Next check: 2026-10-30 09:00"
    )
    spanish = tray.tooltip_text(checked(language="es", news=2), now=NOW)
    assert spanish == (
        "paper-status-monitor\nÚltima comprobación: 09:00, 2 con novedades\n"
        "Próxima comprobación: 21:00"
    )
    assert i18n.get_language() == "en"


def test_tooltips_are_cut_to_the_limit_of_windows() -> None:
    long_state = checked(language="es", news=123456789012345, failed=123456789012345)
    text = tray.tooltip_text(long_state, now=NOW)
    assert len(text) == tray.MAX_TOOLTIP
    assert text.endswith("…")


def test_status_lines() -> None:
    assert tray.status_lines(rows()) == [
        "Tau: Under Review (since 2026-09-01)",
        "[paused] Epsilon: not recorded yet",
    ]
    many = tray.status_lines(rows(13))
    assert len(many) == tray.MAX_MENU_SUBMISSIONS + 1
    assert many[-1] == "... and 3 more"
    long_name = SummaryRow(1, "A" * 60, recorded=True, status="Under Review")
    assert tray.status_lines([long_name])[0].startswith("A" * 39 + "…: ")


def test_menu() -> None:
    entries = tray.menu_entries(checked(), now=NOW)
    labels = [entry.label for entry in entries]
    assert labels == [
        "Tau: Under Review (since 2026-09-01)",
        "[paused] Epsilon: not recorded yet",
        "",
        "Last check: 09:00, no news",
        "Next check: 21:00",
        "",
        "Check now",
        "Open the window",
        "Open the last report",
        "Open the data folder",
        "",
        "Stop the periodic checks",
    ]
    by_label = {entry.label: entry for entry in entries}
    assert by_label["Tau: Under Review (since 2026-09-01)"].command == tray.OPEN_WINDOW
    assert by_label["Last check: 09:00, no news"] == MenuEntry(
        "Last check: 09:00, no news", enabled=False
    )
    assert not by_label["Open the last report"].enabled  # no report yet
    assert by_label["Stop the periodic checks"].command == tray.STOP
    assert entries[2].separator

    busy = tray.menu_entries(checked(checking=True, report=Path("r.txt")), now=NOW)
    commands = {entry.command: entry for entry in busy if entry.command}
    assert not commands[tray.CHECK_NOW].enabled
    assert commands[tray.OPEN_REPORT].enabled
    assert "Next check: 21:00" not in [entry.label for entry in busy]

    spanish = [entry.label for entry in tray.menu_entries(checked(language="es"), now=NOW)]
    assert "[en pausa] Epsilon: aún sin registrar" in spanish
    assert "Comprobar ahora" in spanish
    assert "Detener las comprobaciones periódicas" in spanish


def test_icon_pixels() -> None:
    for size in (16, 24, 32):
        pixels = tray.icon_pixels(size)
        assert len(pixels) == size * size
        assert pixels[0] == 0  # transparent corner
        assert pixels[(size // 2) * size + size // 2] >> 24 == 255  # opaque centre
        colours = {pixel & 0xFFFFFF for pixel in pixels if pixel >> 24 == 255}
        assert 0xFFFFFF in colours  # the tick
        assert 0x1565C0 in colours  # the disc


def test_unavailable_outside_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray.sys, "platform", "linux")
    assert not tray.is_supported()
    assert "only available on Windows" in (tray.unavailable_reason() or "")
    monkeypatch.setattr(tray.sys, "platform", "win32")
    assert tray.unavailable_reason() is None


# ------------------------------------------------------------------ the icon object


class FakeBackend:
    """Stands for the window code: records what the icon asks of it."""

    instances: ClassVar[list[FakeBackend]] = []

    def __init__(self, *, tooltip: Any, menu: Any, on_command: Any) -> None:
        self.tooltip, self.menu, self.on_command = tooltip, menu, on_command
        self.started = self.closed = False
        self.refreshed = 0
        FakeBackend.instances.append(self)

    def start(self) -> None:
        self.started = True

    def refresh(self) -> None:
        self.refreshed += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def icon(tmp_path: Path) -> TrayIcon:
    FakeBackend.instances = []
    return TrayIcon(
        wake=threading.Event(),
        stop=threading.Event(),
        config_path=tmp_path / "config.toml",
        backend=FakeBackend,
    )


def test_tray_icon_shows_the_state(icon: TrayIcon) -> None:
    assert icon.start(language="es", data_dir=Path("data")) is True
    [backend] = FakeBackend.instances
    assert backend.started
    assert icon.shown
    assert "Aún no se ha hecho ninguna comprobación." in backend.tooltip()
    icon.update(last_check=NOW, rows=rows())
    assert backend.refreshed == 1
    assert "Tau: Under Review" in backend.menu()[0].label
    icon.close()
    assert backend.closed
    assert not icon.shown
    icon.close()  # twice is harmless


def test_tray_icon_commands(
    icon: TrayIcon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_status_monitor import report

    opened: list[Path] = []
    started: list[list[str]] = []
    monkeypatch.setattr(report, "open_path", opened.append)
    monkeypatch.setattr(tray.subprocess, "Popen", lambda command, **kwargs: started.append(command))
    icon.start(data_dir=tmp_path)

    icon.run_command(tray.OPEN_REPORT)  # no report yet: nothing happens
    icon.update(report=tmp_path / "changes.txt")
    icon.run_command(tray.OPEN_REPORT)
    icon.run_command(tray.OPEN_FOLDER)
    assert opened == [tmp_path / "changes.txt", tmp_path]

    icon.run_command(tray.OPEN_WINDOW)
    [command] = started
    assert command[1:] == [
        "-m",
        "paper_status_monitor",
        "--config",
        str(tmp_path / "config.toml"),
        "gui",
    ]

    icon.run_command(tray.CHECK_NOW)
    assert icon.wake.is_set()
    assert not icon.stop.is_set()
    icon.wake.clear()
    icon.run_command(tray.STOP)
    assert icon.stop.is_set()
    assert icon.wake.is_set()


def test_tray_icon_failures_are_only_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken(FakeBackend):
        def start(self) -> None:
            raise tray.TrayError("no taskbar")

    events = {"wake": threading.Event(), "stop": threading.Event()}
    assert TrayIcon(**events, backend=Broken).start() is False
    assert "no taskbar" in caplog.text
    monkeypatch.setattr(tray.sys, "platform", "linux")
    assert TrayIcon(**events).start() is False
    assert "only available on Windows" in caplog.text


# ------------------------------------------------------------------ the Windows window code


@pytest.mark.skipif(sys.platform != "win32", reason="the window code needs Windows")
def test_windows_tray_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_status_monitor import _tray_win32

    calls: list[tuple[int, str]] = []

    def fake_notify(message: int, data: Any) -> bool:  # no real icon in the taskbar
        calls.append((message, data.szTip))
        return True

    monkeypatch.setattr(_tray_win32, "_notify", fake_notify)
    texts = {"tip": "first"}
    commands: list[str] = []
    entries = [
        MenuEntry("Information"),
        MenuEntry(),
        MenuEntry("Check & go", tray.CHECK_NOW),
        MenuEntry("Disabled", tray.STOP, enabled=False),
    ]
    icon = _tray_win32.Win32Tray(
        tooltip=lambda: texts["tip"], menu=lambda: entries, on_command=commands.append
    )
    icon.start()
    try:
        assert calls == [(0, "first")]  # NIM_ADD
        texts["tip"] = "second"
        icon.refresh()
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert calls[1] == (1, "second")  # NIM_MODIFY

        for chosen, expected in ((3, ["check-now"]), (4, []), (1, []), (0, [])):
            commands.clear()
            monkeypatch.setattr(
                _tray_win32, "_choose_from_menu", lambda menu, window, item=chosen: item
            )
            icon.show_menu()
            assert commands == expected
    finally:
        icon.close()
    assert not icon._thread.is_alive()
    assert calls[-1][0] == 2  # NIM_DELETE
    assert _tray_win32.create_icon(16)


class FakeTaskbar:
    """Stands for ``Shell_NotifyIconW``: keeps the icons, and can be unready or flaky.

    Attributes:
        ready: ``False`` refuses everything, like a taskbar that has not started.
        lies: Number of next calls that report a failure but are applied anyway, like
            a taskbar that times out while Explorer is busy.
    """

    def __init__(self) -> None:
        self.ready = True
        self.lies = 0
        self.icons: dict[tuple[Any, int], str] = {}
        self.calls: list[int] = []

    def __call__(self, message: int, data: Any) -> bool:
        self.calls.append(message)
        if not self.ready:
            return False
        key = (data.hWnd, data.uID)
        if message == 0:  # NIM_ADD
            done = key not in self.icons
            self.icons.setdefault(key, data.szTip)
        elif message == 1:  # NIM_MODIFY
            done = key in self.icons
            if done:
                self.icons[key] = data.szTip
        else:  # NIM_DELETE
            done = self.icons.pop(key, None) is not None
        if self.lies:
            self.lies -= 1
            return False
        return done


def wait_until(condition: Any, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


@pytest.mark.skipif(sys.platform != "win32", reason="the window code needs Windows")
def test_windows_tray_icon_waits_for_the_taskbar(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_status_monitor import _tray_win32

    taskbar = FakeTaskbar()
    taskbar.ready = False  # at login, the taskbar may not have started yet
    monkeypatch.setattr(_tray_win32, "_notify", taskbar)
    tips = {"tip": "first"}
    icon = _tray_win32.Win32Tray(tooltip=lambda: tips["tip"], menu=list, on_command=print)
    icon.start()
    try:
        assert not icon._added
        taskbar.ready = True
        tips["tip"] = "second"
        icon.refresh()  # added on the next refresh (or when the taskbar starts)
        wait_until(lambda: icon._added)
        assert list(taskbar.icons.values()) == ["second"]
    finally:
        icon.close()
    assert taskbar.icons == {}


@pytest.mark.skipif(sys.platform != "win32", reason="the window code needs Windows")
def test_windows_tray_icon_survives_a_taskbar_that_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from paper_status_monitor import _tray_win32

    taskbar = FakeTaskbar()
    taskbar.lies = 1  # NIM_ADD times out, but the icon is added
    monkeypatch.setattr(_tray_win32, "_notify", taskbar)
    tips = {"tip": "first"}
    icon = _tray_win32.Win32Tray(tooltip=lambda: tips["tip"], menu=list, on_command=print)
    icon.start()
    try:
        assert icon._added  # found with NIM_MODIFY
        taskbar.lies = 1  # a NIM_MODIFY times out, but the tooltip changes
        tips["tip"] = "second"
        icon.refresh()
        wait_until(lambda: len(taskbar.calls) >= 5)
        assert icon._added
        tips["tip"] = "third"
        icon.refresh()
        wait_until(lambda: list(taskbar.icons.values()) == ["third"])
        assert list(taskbar.icons.values()) == ["third"]  # the tooltip is not frozen
        taskbar.lies = 1  # even when the last answer was a failure...
    finally:
        icon.close()
    assert taskbar.icons == {}  # ...no ghost icon is left behind


def test_open_window_runs_the_gui_without_a_console(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        tray.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs))
    )
    tray.open_window()
    [(command, options)] = calls
    assert command[-3:] == ["-m", "paper_status_monitor", "gui"]
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
