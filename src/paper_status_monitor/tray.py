"""An icon in the notification area while the periodic checks run (Windows).

``paper-status-monitor run --every 12h --tray`` (or ``autostart enable --every 12h
--tray``) shows an icon in the notification area of the taskbar for as long as the
periodic checks run. Its tooltip says when the last check ran and when the next one
is due; its menu lists the latest status of every submission and offers to check
now, to open the window, the last report or the data folder, and to stop the
periodic checks.

The icon uses the Windows API through :mod:`ctypes`, so no extra package is needed
and it is only available on Windows. This module holds the logic that does not
depend on it, so it can be tested everywhere; the window code lives in a private
module that is only imported when the icon is shown. The texts follow the
``language`` setting (see :mod:`~paper_status_monitor.i18n`).
"""

from __future__ import annotations

import dataclasses
import logging
import math
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from paper_status_monitor import i18n
from paper_status_monitor.i18n import _, ngettext
from paper_status_monitor.summary import SummaryRow

log = logging.getLogger(__name__)

#: Name shown at the top of the tooltip.
APP_NAME = "paper-status-monitor"

#: Longest tooltip, in characters (the limit of the Windows API).
MAX_TOOLTIP = 127

#: Most submissions listed in the menu.
MAX_MENU_SUBMISSIONS = 10

#: Commands of the menu.
CHECK_NOW = "check-now"
OPEN_WINDOW = "open-window"
OPEN_REPORT = "open-report"
OPEN_FOLDER = "open-folder"
STOP = "stop"

_MAX_NAME = 40


class TrayError(RuntimeError):
    """The icon could not be shown."""


@dataclass(frozen=True)
class TrayState:
    """What the icon shows.

    Attributes:
        language: Language of the tooltip and the menu.
        checking: ``True`` while a check runs.
        last_check: When the last check started (``None`` before the first one).
        next_check: When the next check is due.
        news: Submissions with news in the last check.
        failed: Submissions that could not be checked in the last check.
        rows: Latest recorded status of every submission (see
            :func:`~paper_status_monitor.summary.summary_rows`).
        report: Report written by the last check that had news.
        data_dir: Data folder.
    """

    language: str = i18n.DEFAULT_LANGUAGE
    checking: bool = False
    last_check: datetime | None = None
    next_check: datetime | None = None
    news: int = 0
    failed: int = 0
    rows: tuple[SummaryRow, ...] = ()
    report: Path | None = None
    data_dir: Path | None = None


@dataclass(frozen=True)
class MenuEntry:
    """One line of the menu.

    Attributes:
        label: Text; an empty label is a separator.
        command: What choosing the line does (``None``: a line of information).
        enabled: ``False`` greys the line out.
    """

    label: str = ""
    command: str | None = None
    enabled: bool = True

    @property
    def separator(self) -> bool:
        """``True`` for a separator line."""
        return not self.label


class TrayBackend(Protocol):
    """The window code that shows the icon (see :class:`TrayIcon`)."""

    def start(self) -> None: ...

    def refresh(self) -> None: ...

    def close(self) -> None: ...


def is_supported() -> bool:
    """Return ``True`` if this system can show the icon (Windows)."""
    return sys.platform == "win32"


def unavailable_reason() -> str | None:
    """Return why the icon cannot be shown on this system, or ``None``."""
    if is_supported():
        return None
    return _("The icon in the notification area is only available on Windows.")


def tooltip_text(state: TrayState, *, now: datetime | None = None) -> str:
    """Return the tooltip of the icon (at most :data:`MAX_TOOLTIP` characters)."""
    with i18n.language(state.language):
        lines = [APP_NAME, _last_check_line(state, now)]
        if state.next_check is not None and not state.checking:
            moment = _moment(state.next_check, now)
            lines.append(_("Next check: {moment}").format(moment=moment))
    text = "\n".join(lines)
    return text if len(text) <= MAX_TOOLTIP else text[: MAX_TOOLTIP - 1] + "…"


def menu_entries(state: TrayState, *, now: datetime | None = None) -> list[MenuEntry]:
    """Return the lines of the menu of the icon.

    Choosing a submission opens the window; the lines about the checks are only
    information.
    """
    with i18n.language(state.language):
        entries = [MenuEntry(line, OPEN_WINDOW) for line in status_lines(state.rows)]
        if entries:
            entries.append(MenuEntry())
        entries.append(MenuEntry(_last_check_line(state, now), enabled=False))
        if state.next_check is not None and not state.checking:
            moment = _moment(state.next_check, now)
            entries.append(
                MenuEntry(_("Next check: {moment}").format(moment=moment), enabled=False)
            )
        entries += [
            MenuEntry(),
            MenuEntry(_("Check now"), CHECK_NOW, enabled=not state.checking),
            MenuEntry(_("Open the window"), OPEN_WINDOW),
            MenuEntry(_("Open the last report"), OPEN_REPORT, enabled=state.report is not None),
            MenuEntry(_("Open the data folder"), OPEN_FOLDER, enabled=state.data_dir is not None),
            MenuEntry(),
            MenuEntry(_("Stop the periodic checks"), STOP),
        ]
    return entries


def status_lines(rows: Sequence[SummaryRow]) -> list[str]:
    """Return one line per submission, e.g. ``"Tau: Under Review (since 2026-09-01)"``."""
    lines = []
    for row in rows[:MAX_MENU_SUBMISSIONS]:
        name = _shorten(row.name, _MAX_NAME)
        if not row.enabled:
            name = _("[paused] {name}").format(name=name)
        line = f"{name}: {row.status if row.recorded else _('not recorded yet')}"
        if row.since is not None:
            line += " (" + _("since {date}").format(date=row.since.isoformat()) + ")"
        lines.append(line)
    hidden = len(rows) - MAX_MENU_SUBMISSIONS
    if hidden > 0:
        more = ngettext("... and {count} more", "... and {count} more", hidden)
        lines.append(more.format(count=hidden))
    return lines


def icon_pixels(size: int) -> list[int]:
    """Draw the icon: a blue disc with a white tick, smoothed by supersampling.

    Returns:
        ``size * size`` pixels as ``0xAARRGGBB`` integers, row by row from the top.
    """
    samples = 4
    disc_colour, tick_colour = (0x15, 0x65, 0xC0), (0xFF, 0xFF, 0xFF)
    centre, radius = size / 2, size / 2 - 0.25
    corner = (0.27 * size, 0.52 * size)  # the tick, in fractions of the size
    bottom = (0.43 * size, 0.69 * size)
    tip = (0.74 * size, 0.34 * size)
    half_width = max(0.9, 0.065 * size)
    pixels = []
    for y in range(size):
        for x in range(size):
            disc = tick = 0
            for sy in range(samples):
                for sx in range(samples):
                    px, py = x + (sx + 0.5) / samples, y + (sy + 0.5) / samples
                    if math.hypot(px - centre, py - centre) > radius:
                        continue
                    disc += 1
                    near = min(
                        _segment_distance((px, py), corner, bottom),
                        _segment_distance((px, py), bottom, tip),
                    )
                    tick += near <= half_width
            if not disc:
                pixels.append(0)
                continue
            share = tick / disc
            red, green, blue = (
                round(base + (top - base) * share)
                for base, top in zip(disc_colour, tick_colour, strict=True)
            )
            alpha = round(255 * disc / samples**2)
            pixels.append((alpha << 24) | (red << 16) | (green << 8) | blue)
    return pixels


def open_window(config_path: Path | None = None) -> None:
    """Open the graphical interface in a new process (without a console window)."""
    from paper_status_monitor import autostart

    command = [str(autostart.gui_interpreter()), "-m", "paper_status_monitor"]
    if config_path is not None:
        command += ["--config", str(config_path)]
    command.append("gui")
    subprocess.Popen(
        command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True
    )


class TrayIcon:
    """The icon of the periodic checks: what it shows and what its menu does.

    Args:
        wake: Event that makes the periodic loop check at once (*Check now*).
        stop: Event that stops the periodic loop (*Stop the periodic checks*).
        config_path: Configuration file, passed to the window it opens.
        backend: Builds the window code from the tooltip, menu and command
            callbacks (by default, the Windows one); injectable for tests.
    """

    def __init__(
        self,
        *,
        wake: threading.Event,
        stop: threading.Event,
        config_path: Path | None = None,
        backend: Callable[..., TrayBackend] | None = None,
    ) -> None:
        self.wake = wake
        self.stop = stop
        self.config_path = config_path
        self._make_backend = backend
        self._backend: TrayBackend | None = None
        self._lock = threading.Lock()
        self._state = TrayState()

    @property
    def state(self) -> TrayState:
        """What the icon shows now."""
        with self._lock:
            return self._state

    @property
    def shown(self) -> bool:
        """``True`` once the icon is in the notification area."""
        return self._backend is not None

    def start(self, **state: object) -> bool:
        """Show the icon with an initial state (see :class:`TrayState`).

        Returns:
            ``True`` if it is shown; otherwise the problem is logged (the periodic
            checks go on without the icon).
        """
        self.update(**state)
        make = self._make_backend
        if make is None:
            reason = unavailable_reason()
            if reason:
                log.warning("No icon in the notification area: %s", reason)
                return False
            from paper_status_monitor import _tray_win32

            make = _tray_win32.Win32Tray
        try:
            backend = make(tooltip=self.tooltip, menu=self.menu, on_command=self.run_command)
            backend.start()
        except (TrayError, OSError) as exc:
            log.warning("The icon could not be shown in the notification area: %s", exc)
            return False
        self._backend = backend
        log.info("Icon shown in the notification area.")
        return True

    def update(self, **changes: object) -> None:
        """Change what the icon shows (any attribute of :class:`TrayState`)."""
        with self._lock:
            self._state = dataclasses.replace(self._state, **changes)  # type: ignore[arg-type]
        if self._backend is not None:
            self._backend.refresh()

    def tooltip(self) -> str:
        """Return the current tooltip."""
        return tooltip_text(self.state)

    def menu(self) -> list[MenuEntry]:
        """Return the current menu."""
        return menu_entries(self.state)

    def run_command(self, command: str) -> None:
        """Carry out a command of the menu."""
        from paper_status_monitor import report

        state = self.state
        if command == CHECK_NOW:
            self.wake.set()
        elif command == STOP:
            log.info("Periodic checks stopped from the icon in the notification area.")
            self.stop.set()
            self.wake.set()
        elif command == OPEN_WINDOW:
            open_window(self.config_path)
        elif command == OPEN_REPORT and state.report is not None:
            report.open_path(state.report)
        elif command == OPEN_FOLDER and state.data_dir is not None:
            report.open_path(state.data_dir)

    def close(self) -> None:
        """Remove the icon."""
        backend, self._backend = self._backend, None
        if backend is not None:
            backend.close()


def _last_check_line(state: TrayState, now: datetime | None) -> str:
    if state.checking:
        return _("Checking now...")
    if state.last_check is None:
        return _("No check yet.")
    details = []
    if state.news:
        news = ngettext("{count} with news", "{count} with news", state.news)
        details.append(news.format(count=state.news))
    if state.failed:
        failed = ngettext("{count} failed", "{count} failed", state.failed)
        details.append(failed.format(count=state.failed))
    return _("Last check: {moment}, {result}").format(
        moment=_moment(state.last_check, now), result=", ".join(details) or _("no news")
    )


def _moment(moment: datetime, now: datetime | None) -> str:
    """``14:30`` today, ``2026-10-30 14:30`` on another day."""
    today = (now or datetime.now()).date()
    return f"{moment:%H:%M}" if moment.date() == today else f"{moment:%Y-%m-%d %H:%M}"


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    (px, py), (ax, ay), (bx, by) = point, start, end
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
