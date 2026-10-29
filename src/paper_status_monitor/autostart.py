"""Run the monitor automatically when the user logs in.

The launcher depends on the system; none of them needs administrator rights:

* **Windows** - a shortcut named ``paper-status-monitor.lnk`` in the user's *Startup*
  folder (``shell:startup``), created through PowerShell. It starts ``pythonw.exe -m
  paper_status_monitor run --wait <seconds>``, so no console window is shown.
* **Linux** (and other systems with a freedesktop.org desktop) - an XDG autostart
  entry, ``$XDG_CONFIG_HOME/autostart/paper-status-monitor.desktop`` (by default in
  ``~/.config/autostart``), started by the desktop environment when you log in.
* **macOS** - a launchd agent,
  ``~/Library/LaunchAgents/io.github.paper-status-monitor.plist``, that launchd starts
  when you log in (``RunAtLoad``).

The launcher runs the interpreter that is running this code. With an interval
(``--every 12h``), the program started at login stays in the background and checks
again at that interval while the user stays logged in (see
:mod:`~paper_status_monitor.scheduling`). A launcher takes effect at the next login.
"""

from __future__ import annotations

import itertools
import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from paper_status_monitor import _powershell
from paper_status_monitor.i18n import N_, _
from paper_status_monitor.scheduling import format_interval, parse_interval

#: File name of the shortcut created in the Startup folder (Windows).
SHORTCUT_NAME = "paper-status-monitor.lnk"

#: File name of the XDG autostart entry (Linux).
DESKTOP_ENTRY_NAME = "paper-status-monitor.desktop"

#: Label of the launchd agent (macOS); its file is ``<label>.plist``.
LAUNCH_AGENT_LABEL = "io.github.paper-status-monitor"

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

# Characters that force an argument of the Exec key to be quoted (Desktop Entry spec).
_EXEC_RESERVED = frozenset(" \t\n\"'\\><~|&;$*?#()`")
# Escape sequences of desktop entry strings.
_DESKTOP_ESCAPES = {"\\": "\\", "s": " ", "n": "\n", "t": "\t", "r": "\r"}
# Field codes that a desktop environment replaces with file names, URLs...
_FIELD_CODES = frozenset(f"%{code}" for code in "fFuUdDnNickvm")


class AutostartError(RuntimeError):
    """The launcher could not be created, read or removed."""


@dataclass(frozen=True)
class LauncherInfo:
    """Content of an existing launcher (shortcut, autostart entry or launchd agent).

    Attributes:
        path: File of the launcher.
        target: Interpreter it runs.
        arguments: Command-line arguments given to the interpreter, as one text.
        working_directory: Folder it starts in (may be empty).
    """

    path: Path
    target: str
    arguments: str
    working_directory: str

    @property
    def target_exists(self) -> bool:
        """``True`` if the interpreter the launcher points to still exists."""
        return bool(self.target) and Path(self.target).is_file()

    @property
    def wait(self) -> int | None:
        """Seconds waited for the network at login (``--wait``), if given."""
        return parse_launcher_arguments(self.arguments)[0]

    @property
    def every(self) -> timedelta | None:
        """Interval of the periodic checks (``--every``), or ``None`` (login only)."""
        return parse_launcher_arguments(self.arguments)[1]

    @property
    def tray(self) -> bool:
        """``True`` if the periodic checks show an icon in the notification area (``--tray``)."""
        return "--tray" in self.arguments.split()


#: Former name of :class:`LauncherInfo`, from the time when only Windows was supported.
ShortcutInfo = LauncherInfo


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


def platform_kind() -> str | None:
    """Return the kind of launcher used on this system.

    Returns:
        ``"windows"`` (Startup shortcut), ``"macos"`` (launchd agent), ``"xdg"`` (XDG
        autostart entry, on Linux and the BSDs) or ``None`` if there is none.
    """
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith(("linux", "freebsd", "openbsd", "netbsd", "dragonfly")):
        return "xdg"
    return None


def is_supported() -> bool:
    """Return ``True`` if this system has a built-in launcher (Windows, Linux, macOS)."""
    return platform_kind() is not None


def describe_launcher() -> str:
    """Describe the launcher of this system, e.g. ``"a shortcut in the Startup folder"``.

    The text is in the current language (see :mod:`~paper_status_monitor.i18n`).
    """
    descriptions = {
        "windows": N_("a shortcut in the Startup folder"),
        "xdg": N_("an XDG autostart entry"),
        "macos": N_("a launchd agent"),
    }
    return _(descriptions.get(platform_kind() or "", N_("no launcher")))


def startup_folder() -> Path:
    """Return the current user's Startup folder (Windows)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AutostartError("The APPDATA environment variable is not set.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    """Return the path of the Startup shortcut created by :func:`enable` (Windows)."""
    return startup_folder() / SHORTCUT_NAME


def xdg_autostart_folder() -> Path:
    """Return the folder of the XDG autostart entries (``$XDG_CONFIG_HOME/autostart``)."""
    base = os.environ.get("XDG_CONFIG_HOME", "")
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return root / "autostart"


def launch_agents_folder() -> Path:
    """Return the folder of the user's launchd agents (``~/Library/LaunchAgents``)."""
    return Path.home() / "Library" / "LaunchAgents"


def launcher_path() -> Path:
    """Return the file of the launcher created by :func:`enable` on this system.

    Raises:
        AutostartError: If this system has no built-in launcher.
    """
    kind = _require_supported()
    if kind == "windows":
        return shortcut_path()
    if kind == "macos":
        return launch_agents_folder() / f"{LAUNCH_AGENT_LABEL}.plist"
    return xdg_autostart_folder() / DESKTOP_ENTRY_NAME


def gui_interpreter(executable: str | Path | None = None) -> Path:
    """Return ``pythonw.exe`` next to *executable* if it exists, else *executable*.

    ``pythonw.exe`` runs Python on Windows without opening a console window.
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
    tray: bool = False,
) -> list[str]:
    """Return the command-line arguments passed to the interpreter at login.

    Args:
        wait: Seconds to wait for the network and the data folder before a check.
        config_path: Explicit configuration file (``None`` = default location).
        every: Check again at this interval while the user stays logged in
            (``None`` = only at login).
        tray: Show an icon in the notification area during the periodic checks
            (only with *every*; see :mod:`~paper_status_monitor.tray`).
    """
    arguments = ["-m", "paper_status_monitor"]
    if config_path is not None:
        arguments += ["--config", str(config_path)]
    arguments += ["run", "--wait", str(wait)]
    if every is not None:
        arguments += ["--every", format_interval(every)]
        if tray:
            arguments.append("--tray")
    return arguments


def enable(
    *,
    wait: int = DEFAULT_WAIT,
    config_path: Path | None = None,
    executable: str | Path | None = None,
    every: timedelta | None = None,
    tray: bool = False,
) -> Path:
    """Create (or replace) the launcher and return its path.

    Args:
        wait: Seconds to wait for the network and the data folder at login.
        config_path: Explicit configuration file to use (``None`` = default location).
        executable: Interpreter to use (defaults to the current one).
        every: Check again at this interval while the user stays logged in
            (``None`` = only at login).
        tray: Show an icon in the notification area during the periodic checks
            (Windows, only with *every*).

    Raises:
        AutostartError: If this system has no built-in launcher, or the launcher
            cannot be written.
    """
    path = launcher_path()
    interpreter = str(gui_interpreter(executable))
    arguments = launcher_arguments(wait, config_path, every, tray)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AutostartError(f"Cannot create {path.parent}: {exc}") from exc
    kind = platform_kind()
    if kind == "windows":
        _run_powershell(
            _CREATE_SCRIPT,
            {
                "PSM_LNK": str(path),
                "PSM_TARGET": interpreter,
                "PSM_ARGS": subprocess.list2cmdline(arguments),
                "PSM_WORKDIR": str(Path.home()),
                "PSM_DESCRIPTION": _DESCRIPTION,
            },
        )
    elif kind == "macos":
        _write_atomic(path, launch_agent([interpreter, *arguments], str(Path.home())))
    else:
        entry = desktop_entry([interpreter, *arguments], str(Path.home()))
        _write_atomic(path, entry.encode("utf-8"))
    return path


def disable() -> bool:
    """Remove the launcher. Return ``True`` if it existed.

    A program already started by the launcher (for example, one that checks every 12
    hours) keeps running until you log out.
    """
    path = launcher_path()
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError as exc:
        raise AutostartError(f"Cannot remove {path}: {exc}") from exc
    return True


def status() -> LauncherInfo | None:
    """Return the content of the launcher, or ``None`` if it does not exist.

    Raises:
        AutostartError: If this system has no built-in launcher, or the launcher
            cannot be read.
    """
    path = launcher_path()
    if not path.exists():
        return None
    kind = platform_kind()
    if kind == "windows":
        lines = _run_powershell(_READ_SCRIPT, {"PSM_LNK": str(path)}).splitlines()
        lines += [""] * (3 - len(lines))
        return LauncherInfo(path, lines[0].strip(), lines[1].strip(), lines[2].strip())
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AutostartError(f"Cannot read {path}: {exc}") from exc
    if kind == "macos":
        command, folder = read_launch_agent(data)
    else:
        command, folder = read_desktop_entry(data.decode("utf-8", errors="replace"))
    if not command:
        raise AutostartError(f"{path} does not say which program to run.")
    return LauncherInfo(path, command[0], shlex.join(command[1:]), folder)


def session_warning() -> str | None:
    """Return a warning if the launcher of this system will probably never run.

    XDG autostart entries are started by desktop environments: on a computer without
    a graphical session (for example, a server used through SSH), use cron or a
    systemd timer instead.
    """
    if platform_kind() != "xdg":
        return None
    if any(os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP")):
        return None
    return (
        "No graphical session was found: autostart entries are started by the desktop "
        "environment when you log in to the desktop. On a computer without one, use cron "
        "or a systemd timer instead (see the documentation)."
    )


# --------------------------------------------------------------------------- XDG (Linux)


def desktop_entry(command: Sequence[str], working_directory: str = "") -> str:
    """Return the text of an XDG autostart entry that runs *command* at login.

    Args:
        command: Program and arguments.
        working_directory: Folder the program starts in (``Path`` key), if any.
    """
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=paper-status-monitor",
        f"Comment={_escape_desktop_value(_DESCRIPTION)}",
        f"Exec={desktop_exec(command)}",
    ]
    if working_directory:
        lines.append(f"Path={_escape_desktop_value(working_directory)}")
    lines += ["Terminal=false", "X-GNOME-Autostart-enabled=true"]
    return "\n".join(lines) + "\n"


def read_desktop_entry(text: str) -> tuple[list[str], str]:
    """Return the command (``Exec`` key) and the folder (``Path`` key) of a desktop entry."""
    values: dict[str, str] = {}
    group = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        key, separator, value = line.partition("=")
        if separator and group == "Desktop Entry":
            values.setdefault(key.strip(), value.strip())
    command = parse_desktop_exec(values.get("Exec", ""))
    return command, _unescape_desktop_value(values.get("Path", ""))


def desktop_exec(command: Sequence[str]) -> str:
    """Return the value of the ``Exec`` key of a desktop entry that runs *command*.

    Arguments with reserved characters are quoted as the Desktop Entry Specification
    requires, ``%`` is doubled and backslashes are escaped.
    """
    words = []
    for argument in command:
        if argument and not _EXEC_RESERVED.intersection(argument):
            word = argument
        else:
            inner = "".join(f"\\{char}" if char in '"`$\\' else char for char in argument)
            word = f'"{inner}"'
        words.append(word.replace("%", "%%"))
    return _escape_desktop_value(" ".join(words))


def parse_desktop_exec(value: str) -> list[str]:
    """Split the value of an ``Exec`` key into the program and its arguments.

    This is the inverse of :func:`desktop_exec`. Field codes such as ``%f`` are
    dropped and ``%%`` gives ``%``.
    """
    text = _unescape_desktop_value(value)
    words: list[str] = []
    current: list[str] = []
    in_word = quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == "\\" and index + 1 < len(text) and text[index + 1] in '"`$\\':
                current.append(text[index + 1])
                index += 1
            elif char == '"':
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted = in_word = True
        elif char in " \t":
            if in_word:
                words.append("".join(current))
                current, in_word = [], False
        else:
            current.append(char)
            in_word = True
        index += 1
    if in_word:
        words.append("".join(current))
    return [word.replace("%%", "%") for word in words if word not in _FIELD_CODES]


def _escape_desktop_value(text: str) -> str:
    """Apply the escape rules of desktop entry strings (backslash, newline, tab...)."""
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")


def _unescape_desktop_value(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] in _DESKTOP_ESCAPES:
            result.append(_DESKTOP_ESCAPES[text[index + 1]])
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


# --------------------------------------------------------------------------- launchd (macOS)


def launch_agent(command: Sequence[str], working_directory: str = "") -> bytes:
    """Return the property list of a launchd agent that runs *command* at login."""
    agent: dict[str, object] = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": list(command),
        "RunAtLoad": True,
    }
    if working_directory:
        agent["WorkingDirectory"] = working_directory
    return plistlib.dumps(agent)


def read_launch_agent(data: bytes) -> tuple[list[str], str]:
    """Return the command (``ProgramArguments``) and the folder of a launchd agent.

    Raises:
        AutostartError: If *data* is not a property list.
    """
    try:
        agent = plistlib.loads(data)
    except Exception as exc:  # plistlib raises several unrelated exception types
        raise AutostartError(f"The launchd agent cannot be read: {exc}") from exc
    if not isinstance(agent, dict):
        raise AutostartError("The launchd agent cannot be read: it is not a dictionary.")
    arguments = agent.get("ProgramArguments")
    command = [str(item) for item in arguments] if isinstance(arguments, list) else []
    if not command and isinstance(agent.get("Program"), str):
        command = [agent["Program"]]
    return command, str(agent.get("WorkingDirectory", ""))


# --------------------------------------------------------------------------- helpers


def _require_supported() -> str:
    kind = platform_kind()
    if kind is None:
        raise AutostartError(
            "Built-in autostart is not available on this system. Use cron, a systemd user "
            "timer or your system's scheduler instead (see the documentation)."
        )
    return kind


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise AutostartError(f"Cannot write {path}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _run_powershell(script: str, variables: dict[str, str]) -> str:
    """Run a PowerShell script, passing values through environment variables."""
    try:
        return _powershell.run_script(script, variables)
    except _powershell.PowerShellError as exc:
        raise AutostartError(str(exc)) from exc
