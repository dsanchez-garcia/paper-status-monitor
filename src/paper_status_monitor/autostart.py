"""Run the monitor automatically when the user logs in (Windows).

A shortcut named ``paper-status-monitor.lnk`` is placed in the user's *Startup*
folder (``shell:startup``). It starts ``pythonw.exe -m paper_status_monitor run
--wait <seconds>`` with the interpreter that is running this code, so no console
window is shown and no administrator rights are needed. With an interval
(``--every 12h``), the program started at login stays in the background and checks
again at that interval while the user stays logged in (see
:mod:`~paper_status_monitor.scheduling`).

On Linux and macOS, use cron, a systemd user timer or a launchd agent instead
(see the documentation).
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from paper_status_monitor import _powershell
from paper_status_monitor.scheduling import format_interval, parse_interval

#: File name of the shortcut created in the Startup folder.
SHORTCUT_NAME = "paper-status-monitor.lnk"

#: Default number of seconds to wait for the network and the data folder at login.
DEFAULT_WAIT = 300

_DESCRIPTION = "Check the status of your manuscripts (paper-status-monitor)"

_CREATE_SCRIPT = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:PSM_LNK)
$shortcut.TargetPath = $env:PSM_TARGET
$shortcut.Arguments = $env:PSM_ARGS
$shortcut.WorkingDirectory = $env:PSM_WORKDIR
$shortcut.Description = $env:PSM_DESCRIPTION
$shortcut.WindowStyle = 7
$shortcut.Save()
"""

_READ_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:PSM_LNK)
Write-Output $shortcut.TargetPath
Write-Output $shortcut.Arguments
Write-Output $shortcut.WorkingDirectory
"""


class AutostartError(RuntimeError):
    """The launcher could not be created, read or removed."""


@dataclass(frozen=True)
class ShortcutInfo:
    """Content of an existing Startup shortcut."""

    path: Path
    target: str
    arguments: str
    working_directory: str

    @property
    def target_exists(self) -> bool:
        """``True`` if the interpreter the shortcut points to still exists."""
        return bool(self.target) and Path(self.target).is_file()

    @property
    def wait(self) -> int | None:
        """Seconds waited for the network at login (``--wait``), if given."""
        return parse_launcher_arguments(self.arguments)[0]

    @property
    def every(self) -> timedelta | None:
        """Interval of the periodic checks (``--every``), or ``None`` (login only)."""
        return parse_launcher_arguments(self.arguments)[1]


def parse_launcher_arguments(arguments: str) -> tuple[int | None, timedelta | None]:
    """Return the ``--wait`` seconds and the ``--every`` interval of a launcher command line.

    Missing or unreadable values are returned as ``None``.
    """
    words = arguments.split()
    wait: int | None = None
    every: timedelta | None = None
    for option, value in itertools.pairwise(words):
        if option == "--wait":
            try:
                wait = int(float(value))
            except ValueError:
                wait = None
        elif option == "--every":
            try:
                every = parse_interval(value, minimum=timedelta(0))
            except ValueError:
                every = None
    return wait, every


def is_supported() -> bool:
    """Return ``True`` on Windows, the only platform with built-in autostart support."""
    return sys.platform == "win32"


def startup_folder() -> Path:
    """Return the current user's Startup folder."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AutostartError("The APPDATA environment variable is not set.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    """Return the path of the shortcut created by :func:`enable`."""
    return startup_folder() / SHORTCUT_NAME


def gui_interpreter(executable: str | Path | None = None) -> Path:
    """Return ``pythonw.exe`` next to *executable* if it exists, else *executable*.

    ``pythonw.exe`` runs Python without opening a console window.
    """
    interpreter = Path(executable or sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    return windowless if windowless.is_file() else interpreter


def console_interpreter(executable: str | Path) -> Path:
    """Return ``python.exe`` next to a ``pythonw.exe`` (used for health checks)."""
    interpreter = Path(executable)
    if interpreter.name.lower() == "pythonw.exe":
        console = interpreter.with_name("python.exe")
        if console.is_file():
            return console
    return interpreter


def launcher_arguments(
    wait: int = DEFAULT_WAIT,
    config_path: Path | None = None,
    every: timedelta | None = None,
) -> list[str]:
    """Return the command-line arguments passed to the interpreter at login.

    Args:
        wait: Seconds to wait for the network and the data folder before a check.
        config_path: Explicit configuration file (``None`` = default location).
        every: Check again at this interval while the user stays logged in
            (``None`` = only at login).
    """
    arguments = ["-m", "paper_status_monitor"]
    if config_path is not None:
        arguments += ["--config", str(config_path)]
    arguments += ["run", "--wait", str(wait)]
    if every is not None:
        arguments += ["--every", format_interval(every)]
    return arguments


def enable(
    *,
    wait: int = DEFAULT_WAIT,
    config_path: Path | None = None,
    executable: str | Path | None = None,
    every: timedelta | None = None,
) -> Path:
    """Create (or replace) the Startup shortcut and return its path.

    Args:
        wait: Seconds to wait for the network and the data folder at login.
        config_path: Explicit configuration file to use (``None`` = default location).
        executable: Interpreter to use (defaults to the current one).
        every: Check again at this interval while the user stays logged in
            (``None`` = only at login).
    """
    _require_windows()
    path = shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_powershell(
        _CREATE_SCRIPT,
        {
            "PSM_LNK": str(path),
            "PSM_TARGET": str(gui_interpreter(executable)),
            "PSM_ARGS": subprocess.list2cmdline(launcher_arguments(wait, config_path, every)),
            "PSM_WORKDIR": str(Path.home()),
            "PSM_DESCRIPTION": _DESCRIPTION,
        },
    )
    return path


def disable() -> bool:
    """Remove the Startup shortcut. Return ``True`` if it existed."""
    _require_windows()
    path = shortcut_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def status() -> ShortcutInfo | None:
    """Return the content of the Startup shortcut, or ``None`` if it does not exist."""
    _require_windows()
    path = shortcut_path()
    if not path.exists():
        return None
    lines = _run_powershell(_READ_SCRIPT, {"PSM_LNK": str(path)}).splitlines()
    lines += [""] * (3 - len(lines))
    return ShortcutInfo(path, lines[0].strip(), lines[1].strip(), lines[2].strip())


def _require_windows() -> None:
    if not is_supported():
        raise AutostartError(
            "Built-in autostart is only available on Windows. On Linux or macOS, use cron, "
            "a systemd user timer or a launchd agent (see the documentation)."
        )


def _run_powershell(script: str, variables: dict[str, str]) -> str:
    """Run a PowerShell script, passing values through environment variables."""
    try:
        return _powershell.run_script(script, variables)
    except _powershell.PowerShellError as exc:
        raise AutostartError(str(exc)) from exc
