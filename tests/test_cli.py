from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from paper_status_monitor import __version__, cli, paths, state
from paper_status_monitor.client import DEMO_UUID, SubmissionNotFoundError
from paper_status_monitor.config import Config, ConfigError, load_config, write_config
from paper_status_monitor.storage import read_records

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    text = path.read_text(encoding="utf-8").replace('notify = "report"', 'notify = "none"')
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
    assert opened == []  # notify = "none" in this configuration

    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    assert "[NO CHANGE]" in capsys.readouterr().out

    text = config_file.read_text(encoding="utf-8")
    config_file.write_text(text.replace('notify = "none"', 'notify = "report"'), encoding="utf-8")
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
    assert created == [{"wait": 60, "config_path": config_file.resolve(), "every": None}]
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


DEFAULT_NAME_LINE = "workbook_name = '{manuscript_number} - {journal} - {title}'"


def set_workbook_name(config_file: Path, template: str) -> None:
    text = config_file.read_text(encoding="utf-8")
    assert DEFAULT_NAME_LINE in text
    config_file.write_text(
        text.replace(DEFAULT_NAME_LINE, f"workbook_name = '{template}'"), encoding="utf-8"
    )


def test_init_mentions_the_window(tmp_path: Path, capsys) -> None:
    args = ["--config", str(tmp_path / "config.toml"), "init", "--data-dir", str(tmp_path)]
    assert cli.main(args) == cli.EXIT_OK
    assert "paper-status-monitor gui" in capsys.readouterr().out


def test_add_with_custom_fields_and_list(config_file: Path, capsys) -> None:
    args = ["-c", str(config_file), "add", DEMO_UUID, "--no-verify"]
    args += ["--field", "paper=TMY", "--field", "project = My thesis"]
    assert cli.main(args) == cli.EXIT_OK
    fields = dict(load_config(config_file).submissions[0].fields)
    assert fields == {"paper": "TMY", "project": "My thesis"}
    assert cli.main(["-c", str(config_file), "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Fields: paper = TMY, project = My thesis" in out
    assert "Workbook names: {manuscript_number} - {journal} - {title}" in out


@pytest.mark.parametrize(
    ("field", "message"), [("paper", "NAME=VALUE"), ("journal=X", "built-in placeholder")]
)
def test_add_rejects_invalid_fields(config_file: Path, capsys, field: str, message: str) -> None:
    args = ["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", field]
    assert cli.main(args) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err
    assert load_config(config_file).submissions == ()


def test_run_can_record_without_notifying(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, make_payload(), make_payload(LastUpdated=1652887284))
    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    capsys.readouterr()

    args = ["-c", str(config_file), "run", "--notify-ignore", "last review activity"]
    assert cli.main(args) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "[RECORDED]" in out
    assert "Report:" not in out
    reports = list((config_file.parent / "data" / "reports").glob("changes_*.txt"))
    assert len(reports) == 1  # written by the first run only (new submission)
    [workbook] = (config_file.parent / "data").glob("*.xlsx")
    assert len(read_records(workbook)) == 2


def test_run_rejects_unknown_columns(config_file: Path, capsys) -> None:
    args = ["-c", str(config_file), "run", "--notify-fields", "Colour"]
    assert cli.main(args) == cli.EXIT_USAGE
    assert "Unknown column 'Colour' in '--notify-fields'" in capsys.readouterr().err


def test_apply_run_overrides(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path, ignore_fields=("Status code",), record_ignore=("Title",))
    parser = cli.build_parser()
    args = parser.parse_args(
        ["run", "--notify-fields", "Status", "--record-ignore", "none", "--notify-ignore", "Title"]
    )
    changed = cli.apply_run_overrides(config, args)
    assert changed.notify_fields == ("Status",)
    assert changed.notify_ignore == ("Title",)
    assert changed.ignore_fields == ()
    assert changed.record_ignore == ()
    assert changed.record_fields is None
    assert cli.apply_run_overrides(config, parser.parse_args(["run"])) is config


def test_organize(config_file: Path, patched_client, make_payload, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=TMY"])
    patched_client.queue(DEMO_UUID, make_payload())
    assert cli.main(["-c", str(config_file), "run", "--no-open"]) == cli.EXIT_OK
    set_workbook_name(config_file, "{paper} - {journal_acronym}")
    data = config_file.parent / "data"
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "organize", "--dry-run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "->  TMY - SUBTRAK.xlsx" in out
    assert "Dry run" in out
    assert not (data / "TMY - SUBTRAK.xlsx").exists()

    assert cli.main(["-c", str(config_file), "organize"]) == cli.EXIT_OK
    assert "Renamed" in capsys.readouterr().out
    assert [path.name for path in data.glob("*.xlsx")] == ["TMY - SUBTRAK.xlsx"]

    assert cli.main(["-c", str(config_file), "organize"]) == cli.EXIT_OK
    assert "Nothing to do" in capsys.readouterr().out


def test_organize_without_workbooks(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    assert cli.main(["-c", str(config_file), "organize"]) == cli.EXIT_OK
    assert "No recorded submissions" in capsys.readouterr().out


def test_organize_refuses_to_run_during_a_run(config_file: Path, capsys) -> None:
    with state.single_instance():
        assert cli.main(["-c", str(config_file), "organize"]) == cli.EXIT_FAILURE
    assert "Another run" in capsys.readouterr().err


def test_gui_command(config_file: Path, monkeypatch) -> None:
    from paper_status_monitor import gui

    opened: list[Path] = []
    monkeypatch.setattr(gui, "run_gui", lambda path: opened.append(path) or 0)
    assert cli.main(["-c", str(config_file), "gui"]) == cli.EXIT_OK
    assert opened == [config_file]


def test_doctor_describes_the_settings_and_the_workbook_names(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=TMY"])
    patched_client.queue(DEMO_UUID, make_payload())
    cli.main(["-c", str(config_file), "run", "--no-open"])
    set_workbook_name(config_file, "{paper}")
    capsys.readouterr()

    cli.main(["-c", str(config_file), "doctor"])

    out = capsys.readouterr().out
    assert "[INFO] Changes recorded: all columns" in out
    assert "[INFO] Changes notified: all columns" in out
    assert "[INFO] Workbook names: {paper}" in out
    assert "[WARN] 1 workbook change(s) needed to follow the naming template" in out


# ------------------------------------------------------------------ remove / enable / disable


def test_disable_enable_and_remove(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo paper"])
    cli.main(["-c", str(config_file), "add", OTHER_UUID, "--no-verify"])
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "disable", "demo paper"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Paused Demo paper" in out
    assert 'paper-status-monitor enable "Demo paper"' in out
    assert [s.enabled for s in load_config(config_file).submissions] == [False, True]
    text = config_file.read_text(encoding="utf-8")
    assert "# Configuration file for paper-status-monitor." in text

    assert cli.main(["-c", str(config_file), "pause", "1"]) == cli.EXIT_OK
    assert "already paused" in capsys.readouterr().out
    assert cli.main(["-c", str(config_file), "list"]) == cli.EXIT_OK
    assert "1. Demo paper  [paused]" in capsys.readouterr().out

    assert cli.main(["-c", str(config_file), "resume", DEMO_UUID]) == cli.EXIT_OK
    assert "Resumed Demo paper" in capsys.readouterr().out
    assert load_config(config_file).submissions[0].enabled

    url = f"https://track.authorhub.elsevier.com/?uuid={OTHER_UUID}"
    assert cli.main(["-c", str(config_file), "remove", url]) == cli.EXIT_OK
    assert "Its workbook was not deleted" in capsys.readouterr().out
    assert [s.uuid for s in load_config(config_file).submissions] == [DEMO_UUID]
    assert (config_file.parent / "config.toml.bak").is_file()


def test_summary_command(
    config_file: Path, patched_client, make_payload, capsys, tmp_path: Path
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    cli.main(["-c", str(config_file), "add", OTHER_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, make_payload())  # the other one fails: not recorded
    cli.main(["-c", str(config_file), "run"])
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "summary"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Paper status summary - ")
    assert "Under Review" in out
    assert "not recorded yet" in out

    target = tmp_path / "out" / "summary.html"
    args = ["-c", str(config_file), "summary", "--format", "html", "-o", str(target)]
    assert cli.main(args) == cli.EXIT_OK
    assert "Summary written to" in capsys.readouterr().out
    assert "<td>Demo</td>" in target.read_text(encoding="utf-8")


def test_unknown_submissions_are_usage_errors(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    assert cli.main(["-c", str(config_file), "remove", "Nope"]) == cli.EXIT_USAGE
    assert "No submission matches 'Nope'" in capsys.readouterr().err
    assert cli.main(["-c", str(config_file), "disable", OTHER_UUID]) == cli.EXIT_USAGE
    assert "is not in" in capsys.readouterr().err


# ------------------------------------------------------------------ periodic checks


def test_run_every_repeats_the_checks(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, make_payload(), make_payload(Status=4))
    intervals: list[timedelta] = []

    def fake_run_every(task, interval, **kwargs) -> int:
        intervals.append(interval)
        task()  # the submission is new
        valid = config_file.read_text(encoding="utf-8")
        config_file.write_text(valid + "\nnot = valid = toml\n", encoding="utf-8")
        task()  # the configuration is broken: the previous settings are used
        return 2

    monkeypatch.setattr(cli.scheduling, "run_every", fake_run_every)
    assert cli.main(["-c", str(config_file), "run", "--every", "12h"]) == cli.EXIT_OK
    assert intervals == [timedelta(hours=12)]
    out = capsys.readouterr().out
    assert "every 12h" in out
    assert "[NEW]" in out
    assert "[CHANGED]" in out
    [workbook] = (config_file.parent / "data").glob("*.xlsx")
    assert len(read_records(workbook)) == 2


def test_periodic_checks_skip_a_check_while_another_run_is_active(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    patched_client.queue(DEMO_UUID, make_payload())

    def fake_run_every(task, interval, **kwargs) -> int:
        with state.single_instance():
            task()  # skipped: another run holds the lock
        task()
        return 2

    monkeypatch.setattr(cli.scheduling, "run_every", fake_run_every)
    assert cli.main(["-c", str(config_file), "run", "--every", "1d"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "Check skipped" in captured.err
    assert captured.out.count("[NEW]") == 1


@pytest.mark.parametrize(("value", "message"), [("soon", "Invalid interval"), ("10m", "too short")])
def test_run_every_rejects_invalid_intervals(
    config_file: Path, capsys, value: str, message: str
) -> None:
    assert cli.main(["-c", str(config_file), "run", "--every", value]) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err


def test_autostart_enable_with_periodic_checks(monkeypatch, config_file: Path, capsys) -> None:
    created: list[dict] = []
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(
        cli.autostart, "enable", lambda **kwargs: created.append(kwargs) or Path("startup.lnk")
    )
    args = ["-c", str(config_file), "autostart", "enable", "--every", "12h"]
    assert cli.main(args) == cli.EXIT_OK
    assert created[0]["every"] == timedelta(hours=12)
    assert "then every 12h" in capsys.readouterr().out
    assert cli.main([*args[:-1], "5m"]) == cli.EXIT_USAGE
    assert "too short" in capsys.readouterr().err


def test_autostart_status_shows_the_schedule(monkeypatch, tmp_path: Path, capsys) -> None:
    info = cli.autostart.ShortcutInfo(
        tmp_path / "paper-status-monitor.lnk",
        sys.executable,
        "-m paper_status_monitor run --wait 300 --every 1d",
        str(tmp_path),
    )
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "status", lambda: info)
    assert cli.main(["autostart", "status"]) == cli.EXIT_OK
    assert "Checks:      at login, then every 1d" in capsys.readouterr().out


# ------------------------------------------------------------------ notifications


def test_run_can_show_a_desktop_notification(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    patched_client.queue(DEMO_UUID, make_payload())
    shown: list = []
    monkeypatch.setattr(cli.report.notifications, "show", shown.append)
    assert cli.main(["-c", str(config_file), "run", "--notify", "toast"]) == cli.EXIT_OK
    assert [notification.title for notification in shown] == ["Now tracking: Demo"]
    assert shown[0].target is not None
    assert shown[0].target.name.startswith("changes_")


def test_apply_run_overrides_for_notifications(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path, notify=("report", "toast"))
    parser = cli.build_parser()

    def notify(*options: str) -> tuple[str, ...]:
        return cli.apply_run_overrides(config, parser.parse_args(["run", *options])).notify

    assert notify("--no-open") == ("toast",)
    assert notify("--notify", "none") == ()
    assert notify("--notify", "Report") == ("report",)
    assert notify("--notify", "report,toast", "--no-open") == ("toast",)
    with pytest.raises(ConfigError, match="--notify"):
        notify("--notify", "email")


def test_doctor_describes_the_notifications(
    config_file: Path, patched_client, demo_payload, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    monkeypatch.setattr(cli.notifications, "unavailable_reason", lambda: "notify-send is missing")
    text = config_file.read_text(encoding="utf-8")
    config_file.write_text(
        text.replace('notify = "none"', 'notify = ["report", "toast"]'), encoding="utf-8"
    )
    patched_client.queue(DEMO_UUID, demo_payload)
    cli.main(["-c", str(config_file), "doctor"])
    out = capsys.readouterr().out
    assert (
        "[INFO] When there is news: the report is opened and a desktop notification is shown" in out
    )
    assert "[WARN] Desktop notifications: notify-send is missing" in out
