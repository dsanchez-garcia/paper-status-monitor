from __future__ import annotations

import plistlib
import shlex
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from paper_status_monitor import _powershell, autostart


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    """Pretend to run on Windows and record the PowerShell scripts instead of running them."""
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_powershell(script: str, variables: dict[str, str]) -> str:
        calls.append((script, variables))
        if "CreateShortcut" in script and "Save()" in script:
            Path(variables["PSM_LNK"]).write_bytes(b"fake shortcut")
            return ""
        return "C:\\Python\\pythonw.exe\n-m paper_status_monitor run --wait 300\nC:\\Users\\me\n"

    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(autostart, "_run_powershell", fake_powershell)
    return calls


def test_launcher_arguments() -> None:
    assert autostart.launcher_arguments() == [
        "-m",
        "paper_status_monitor",
        "run",
        "--wait",
        str(autostart.DEFAULT_WAIT),
    ]
    assert autostart.launcher_arguments(60, Path("cfg.toml")) == [
        "-m",
        "paper_status_monitor",
        "--config",
        "cfg.toml",
        "run",
        "--wait",
        "60",
    ]


def test_gui_interpreter_prefers_pythonw(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.touch()
    assert autostart.gui_interpreter(python) == python
    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    assert autostart.gui_interpreter(python) == pythonw
    assert autostart.console_interpreter(pythonw) == python


def test_startup_folder_uses_appdata(isolated_user_dirs: Path) -> None:
    assert autostart.startup_folder() == (
        isolated_user_dirs
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def test_enable_status_disable(windows: list, tmp_path: Path) -> None:
    path = autostart.enable(wait=120, config_path=tmp_path / "my config.toml")
    assert path.name == autostart.SHORTCUT_NAME
    assert path.exists()
    script, variables = windows[0]
    assert "WindowStyle = 7" in script
    assert variables["PSM_TARGET"] == str(autostart.gui_interpreter())
    assert "--wait 120" in variables["PSM_ARGS"]
    assert f'"{tmp_path / "my config.toml"}"' in variables["PSM_ARGS"]

    info = autostart.status()
    assert info is not None
    assert info.target == "C:\\Python\\pythonw.exe"
    assert info.arguments == "-m paper_status_monitor run --wait 300"

    assert autostart.disable() is True
    assert autostart.disable() is False
    assert autostart.status() is None


def test_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart.sys, "platform", "cygwin")
    assert not autostart.is_supported()
    assert autostart.describe_launcher() == "no launcher"
    with pytest.raises(autostart.AutostartError, match="not available on this system"):
        autostart.enable()
    with pytest.raises(autostart.AutostartError, match="not available on this system"):
        autostart.status()


@pytest.mark.parametrize(
    ("platform", "kind", "launcher"),
    [
        ("win32", "windows", "a shortcut in the Startup folder"),
        ("darwin", "macos", "a launchd agent"),
        ("linux", "xdg", "an XDG autostart entry"),
        ("freebsd14", "xdg", "an XDG autostart entry"),
    ],
)
def test_platform_kind(
    monkeypatch: pytest.MonkeyPatch, platform: str, kind: str, launcher: str
) -> None:
    monkeypatch.setattr(autostart.sys, "platform", platform)
    assert autostart.platform_kind() == kind
    assert autostart.is_supported()
    assert autostart.describe_launcher() == launcher


def test_run_powershell_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Access denied")

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    with pytest.raises(autostart.AutostartError, match="Access denied"):
        autostart._run_powershell("exit 1", {})


def test_powershell_timeouts_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("powershell.exe", 5)

    monkeypatch.setattr(_powershell.subprocess, "run", fake_run)
    with pytest.raises(_powershell.PowerShellError, match="did not finish within 5 seconds"):
        _powershell.run_script("Start-Sleep 10", timeout=5)


def test_launcher_arguments_with_periodic_checks() -> None:
    arguments = autostart.launcher_arguments(60, every=timedelta(hours=12))
    assert arguments[-4:] == ["--wait", "60", "--every", "12h"]
    with_icon = autostart.launcher_arguments(60, every=timedelta(hours=12), tray=True)
    assert with_icon[-5:] == ["--wait", "60", "--every", "12h", "--tray"]
    assert "--tray" not in autostart.launcher_arguments(60, tray=True)  # only with --every


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ("-m paper_status_monitor run --wait 300", (300, None)),
        ("-m paper_status_monitor run --wait 120 --every 1d12h", (120, timedelta(hours=36))),
        (
            '-m paper_status_monitor --config "C:\\my config.toml" run --every 2h',
            (None, timedelta(hours=2)),
        ),
        ("-m paper_status_monitor run --wait soon --every never", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_launcher_arguments(arguments: str, expected: tuple) -> None:
    assert autostart.parse_launcher_arguments(arguments) == expected


def test_enable_with_periodic_checks(windows: list, tmp_path: Path) -> None:
    autostart.enable(wait=30, every=timedelta(hours=6))
    _, variables = windows[0]
    assert variables["PSM_ARGS"].endswith("run --wait 30 --every 6h")
    info = autostart.LauncherInfo(Path("x.lnk"), "", variables["PSM_ARGS"], "")
    assert (info.wait, info.every, info.tray) == (30, timedelta(hours=6), False)
    autostart.enable(wait=30, every=timedelta(hours=6), tray=True)
    _, variables = windows[-1]
    assert variables["PSM_ARGS"].endswith("run --wait 30 --every 6h --tray")
    assert autostart.LauncherInfo(Path("x.lnk"), "", variables["PSM_ARGS"], "").tray


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_real_shortcut_round_trip(isolated_user_dirs: Path) -> None:
    """Create a real .lnk in the (temporary) Startup folder and read it back."""
    path = autostart.enable(wait=42)
    try:
        info = autostart.status()
        assert info is not None
        assert info.target_exists
        assert info.arguments.endswith("run --wait 42")
    finally:
        assert autostart.disable()
    assert not path.exists()


def test_shortcut_info_is_the_former_name_of_launcher_info() -> None:
    assert autostart.ShortcutInfo is autostart.LauncherInfo


# ------------------------------------------------------------------ Linux (XDG autostart)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            ["/usr/bin/python3", "-m", "paper_status_monitor", "run", "--wait", "300"],
            "/usr/bin/python3 -m paper_status_monitor run --wait 300",
        ),
        (
            ["/opt/my python/bin/python3", "--config", "/home/me/a$b.toml", "100%"],
            '"/opt/my python/bin/python3" --config "/home/me/a\\\\$b.toml" 100%%',
        ),
        (['C:\\x "y"', ""], '"C:\\\\\\\\x \\\\"y\\\\"" ""'),
    ],
)
def test_desktop_exec_quotes_like_the_specification(command: list[str], expected: str) -> None:
    assert autostart.desktop_exec(command) == expected
    assert autostart.parse_desktop_exec(expected) == command


@pytest.mark.parametrize(
    "command",
    [
        ["/home/me/venv/bin/python", "--config", "/home/me/it's `odd` $HOME\\x;y.toml"],
        ["python", "tab\there", "new\nline", "~", "a&b|c", "#hash", "(x)", "<in>", "*?"],
    ],
)
def test_desktop_exec_round_trips(command: list[str]) -> None:
    value = autostart.desktop_exec(command)
    assert "\n" not in value
    assert autostart.parse_desktop_exec(value) == command


def test_parse_desktop_exec_drops_field_codes() -> None:
    assert autostart.parse_desktop_exec("/usr/bin/app --open %U 50%% \\s") == [
        "/usr/bin/app",
        "--open",
        "50%",
    ]


def test_read_desktop_entry_uses_the_main_group_only() -> None:
    text = (
        "# written by hand\n"
        "[Desktop Entry]\n"
        "Name=paper-status-monitor\n"
        "Exec = /usr/bin/python3 -m paper_status_monitor run --wait 60\n"
        "Path=/home/me\n"
        "\n"
        "[Desktop Action other]\n"
        "Exec=/bin/false\n"
    )
    command, folder = autostart.read_desktop_entry(text)
    assert command == ["/usr/bin/python3", "-m", "paper_status_monitor", "run", "--wait", "60"]
    assert folder == "/home/me"


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart.sys, "platform", "linux")


@pytest.mark.usefixtures("linux")
def test_xdg_autostart_entry_round_trip(isolated_user_dirs: Path, tmp_path: Path) -> None:
    config = tmp_path / "my config $1.toml"
    path = autostart.enable(wait=60, config_path=config, every=timedelta(hours=12))
    assert path == isolated_user_dirs / ".config" / "autostart" / autostart.DESKTOP_ENTRY_NAME
    text = path.read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]\nType=Application\n")
    assert "\nTerminal=false\n" in text
    assert "\nExec=" in text
    assert text.count("\n") == len(text.splitlines())  # one key per line

    info = autostart.status()
    assert info is not None
    assert info.path == path
    assert info.target == str(autostart.gui_interpreter())
    assert info.target_exists
    assert shlex.split(info.arguments) == autostart.launcher_arguments(
        60, config, timedelta(hours=12)
    )
    assert (info.wait, info.every) == (60, timedelta(hours=12))
    assert info.working_directory == str(Path.home())

    assert autostart.disable() is True
    assert autostart.status() is None
    assert autostart.disable() is False


@pytest.mark.usefixtures("linux")
def test_xdg_autostart_folder_ignores_relative_xdg_config_home(
    isolated_user_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/folder")
    assert autostart.launcher_path() == (
        isolated_user_dirs / ".config" / "autostart" / autostart.DESKTOP_ENTRY_NAME
    )


@pytest.mark.usefixtures("linux")
def test_unreadable_autostart_entry(isolated_user_dirs: Path) -> None:
    path = autostart.launcher_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=paper-status-monitor\n", encoding="utf-8")
    with pytest.raises(autostart.AutostartError, match="does not say which program to run"):
        autostart.status()


@pytest.mark.usefixtures("linux")
def test_session_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"):
        monkeypatch.delenv(name, raising=False)
    warning = autostart.session_warning()
    assert warning is not None
    assert "No graphical session" in warning
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert autostart.session_warning() is None
    monkeypatch.delenv("WAYLAND_DISPLAY")
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    assert autostart.session_warning() is None


# ------------------------------------------------------------------ macOS (launchd agent)


def test_launchd_agent_round_trip(
    monkeypatch: pytest.MonkeyPatch, isolated_user_dirs: Path
) -> None:
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    path = autostart.enable(wait=30, every=timedelta(days=1))
    assert path == (
        isolated_user_dirs / "Library" / "LaunchAgents" / "io.github.paper-status-monitor.plist"
    )
    agent = plistlib.loads(path.read_bytes())
    interpreter = str(autostart.gui_interpreter())
    assert agent == {
        "Label": autostart.LAUNCH_AGENT_LABEL,
        "ProgramArguments": [interpreter, *autostart.launcher_arguments(30, None, timedelta(1))],
        "RunAtLoad": True,
        "WorkingDirectory": str(Path.home()),
    }

    info = autostart.status()
    assert info is not None
    assert (info.target, info.wait, info.every) == (interpreter, 30, timedelta(days=1))
    assert info.arguments.endswith("run --wait 30 --every 1d")

    assert autostart.disable() is True
    assert not path.exists()


def test_read_launch_agent() -> None:
    data = plistlib.dumps({"Label": "x", "Program": "/usr/local/bin/paper-status-monitor"})
    assert autostart.read_launch_agent(data) == (["/usr/local/bin/paper-status-monitor"], "")
    with pytest.raises(autostart.AutostartError, match="cannot be read"):
        autostart.read_launch_agent(b"not a property list")
    with pytest.raises(autostart.AutostartError, match="not a dictionary"):
        autostart.read_launch_agent(plistlib.dumps(["a", "b"]))
