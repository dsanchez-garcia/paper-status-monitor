from __future__ import annotations

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
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    assert not autostart.is_supported()
    with pytest.raises(autostart.AutostartError, match="only available on Windows"):
        autostart.enable()


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
    info = autostart.ShortcutInfo(Path("x.lnk"), "", variables["PSM_ARGS"], "")
    assert (info.wait, info.every) == (30, timedelta(hours=6))


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
