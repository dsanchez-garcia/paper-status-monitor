from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_status_monitor import __version__, cli, paths, state
from paper_status_monitor.client import DEMO_UUID, SubmissionNotFoundError
from paper_status_monitor.config import load_config, write_config
from paper_status_monitor.storage import read_records


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    text = path.read_text(encoding="utf-8").replace("open_report = true", "open_report = false")
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch, fake_client):
    """Make every TrackerClient created by the CLI or the monitor return fake data."""

    def factory(*args: object, **kwargs: object):
        return fake_client

    monkeypatch.setattr(cli, "TrackerClient", factory)
    monkeypatch.setattr("paper_status_monitor.monitor.TrackerClient", factory)
    return fake_client


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == cli.EXIT_USAGE
    assert "COMMAND" in capsys.readouterr().out


def test_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.toml"
    args = ["--config", str(path), "init", "--data-dir", str(tmp_path / "data")]
    assert cli.main(args) == cli.EXIT_OK
    assert load_config(path).data_dir == tmp_path / "data"
    assert "Next steps" in capsys.readouterr().out
    assert cli.main(args) == cli.EXIT_USAGE
    assert "already exists" in capsys.readouterr().err
    assert cli.main([*args, "--force"]) == cli.EXIT_OK


def test_init_uses_the_default_location() -> None:
    assert cli.main(["init"]) == cli.EXIT_OK
    assert paths.default_config_path().is_file()


def test_add_and_list(config_file: Path, patched_client, demo_payload, capsys) -> None:
    patched_client.queue(DEMO_UUID, demo_payload)
    url = f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
    assert cli.main(["-c", str(config_file), "add", url, "--label", "Demo"]) == cli.EXIT_OK
    assert "Found: Influence of submission trackers" in capsys.readouterr().out
    assert load_config(config_file).submissions[0].label == "Demo"

    assert cli.main(["-c", str(config_file), "add", DEMO_UUID]) == cli.EXIT_USAGE
    assert "already" in capsys.readouterr().err

    assert cli.main(["-c", str(config_file), "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "1. Demo" in out
    assert "Last recorded status: none yet" in out


def test_add_rejects_unknown_submissions(config_file: Path, patched_client, capsys) -> None:
    patched_client.queue(DEMO_UUID, SubmissionNotFoundError("HTTP 404"))
    assert cli.main(["-c", str(config_file), "add", DEMO_UUID]) == cli.EXIT_FAILURE
    assert "--no-verify" in capsys.readouterr().err
    assert cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"]) == cli.EXIT_OK


def test_add_rejects_invalid_links(config_file: Path, capsys) -> None:
    assert cli.main(["-c", str(config_file), "add", "https://example.org"]) == cli.EXIT_USAGE
    assert "No tracking UUID" in capsys.readouterr().err


def test_missing_config_is_a_usage_error(tmp_path: Path, capsys) -> None:
    assert cli.main(["-c", str(tmp_path / "missing.toml"), "list"]) == cli.EXIT_USAGE
    assert "paper-status-monitor init" in capsys.readouterr().err


def test_check(patched_client, demo_payload, capsys) -> None:
    patched_client.queue(DEMO_UUID, demo_payload)
    assert cli.main(["check", DEMO_UUID]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Manuscript number:" in out
    assert "SUBTRAK-D-22-00128" in out
    assert "Tracker URL:" in out


def test_check_json(patched_client, demo_payload, capsys) -> None:
    patched_client.queue(DEMO_UUID, demo_payload)
    assert cli.main(["check", "--json", DEMO_UUID]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == demo_payload


def test_check_errors(patched_client, capsys) -> None:
    patched_client.queue(DEMO_UUID, SubmissionNotFoundError("HTTP 404"))
    assert cli.main(["check", DEMO_UUID]) == cli.EXIT_FAILURE
    assert "HTTP 404" in capsys.readouterr().err


def test_run_end_to_end(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, make_payload(), make_payload(), make_payload(Status=4))
    opened: list[Path] = []
    monkeypatch.setattr(cli.report, "open_path", opened.append)

    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "[NEW]" in out
    reports = sorted((config_file.parent / "data" / "reports").glob("changes_*.txt"))
    assert len(reports) == 1
    assert "NOW TRACKING (1)" in reports[0].read_text(encoding="utf-8")
    assert opened == []  # open_report = false in this configuration

    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    assert "[NO CHANGE]" in capsys.readouterr().out

    text = config_file.read_text(encoding="utf-8")
    config_file.write_text(
        text.replace("open_report = false", "open_report = true"), encoding="utf-8"
    )
    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    assert "[CHANGED]" in capsys.readouterr().out
    assert len(opened) == 1

    [workbook] = (config_file.parent / "data").glob("*.xlsx")
    assert len(read_records(workbook)) == 2
    last_run = state.load_last_run()
    assert last_run is not None
    assert last_run["changed"] == 1


def test_run_returns_failure_when_a_submission_fails(
    config_file: Path, patched_client, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, SubmissionNotFoundError("HTTP 404"))
    assert cli.main(["-c", str(config_file), "run", "--no-open"]) == cli.EXIT_FAILURE
    assert "[ERROR]" in capsys.readouterr().out
    reports = list((config_file.parent / "data" / "reports").glob("*.txt"))
    assert len(reports) == 1


def test_run_dry_run(config_file: Path, patched_client, demo_payload) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, demo_payload)
    assert cli.main(["-c", str(config_file), "run", "--dry-run"]) == cli.EXIT_OK
    assert not (config_file.parent / "data").exists()
    assert state.load_last_run() is None


def test_run_without_submissions(config_file: Path, capsys) -> None:
    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    assert "No enabled submissions" in capsys.readouterr().out


def test_run_refuses_to_run_twice(config_file: Path, patched_client, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    with state.single_instance():
        assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_FAILURE
    assert "Another run" in capsys.readouterr().err


def test_autostart_on_unsupported_platform(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    assert cli.main(["autostart", "status"]) == cli.EXIT_USAGE
    assert "only available on Windows" in capsys.readouterr().err


def test_autostart_commands(monkeypatch, config_file: Path, capsys) -> None:
    created: list[dict] = []
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(
        cli.autostart,
        "enable",
        lambda **kwargs: created.append(kwargs) or Path("startup.lnk"),
    )
    monkeypatch.setattr(cli.autostart, "disable", lambda: True)
    monkeypatch.setattr(cli.autostart, "status", lambda: None)

    assert cli.main(["-c", str(config_file), "autostart", "enable", "--wait", "60"]) == 0
    assert created == [{"wait": 60, "config_path": config_file.resolve()}]
    assert cli.main(["autostart", "disable"]) == cli.EXIT_OK
    assert cli.main(["autostart", "status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Autostart enabled" in out
    assert "Autostart disabled." in out
    assert "not enabled" in out


def test_autostart_enable_requires_a_valid_config(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    missing = tmp_path / "missing.toml"
    assert cli.main(["-c", str(missing), "autostart", "enable"]) == cli.EXIT_USAGE


def test_doctor(config_file: Path, patched_client, demo_payload, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, demo_payload)
    (config_file.parent / "data").mkdir()
    assert cli.main(["-c", str(config_file), "doctor"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "[ OK ] Configuration" in out
    assert "[ OK ] Data folder" in out
    assert "[ OK ] Tracker reachable" in out
    assert "[WARN] No completed run recorded yet" in out


def test_doctor_reports_failures(tmp_path: Path, patched_client, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    patched_client.queue(DEMO_UUID, SubmissionNotFoundError("HTTP 404"))
    assert cli.main(["-c", str(tmp_path / "missing.toml"), "doctor"]) == cli.EXIT_FAILURE
    out = capsys.readouterr().out
    assert "[FAIL] Configuration file not found" in out
    assert "[FAIL] Tracker not reachable" in out
    assert "2 problem(s) found." in out
