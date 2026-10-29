from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

import pytest

from paper_status_monitor import __version__, cli, paths, state
from paper_status_monitor.client import DEMO_UUID, SubmissionNotFoundError
from paper_status_monitor.config import (
    SMTP_PASSWORD_ENV_VAR,
    Config,
    ConfigError,
    SubmissionConfig,
    load_config,
    write_config,
)
from paper_status_monitor.models import TRACKED_COLUMNS
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
    assert "not available on this system" in capsys.readouterr().err


def test_autostart_enable_warns_without_a_desktop(monkeypatch, config_file: Path, capsys) -> None:
    monkeypatch.setattr(cli.autostart.sys, "platform", "linux")
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["-c", str(config_file), "autostart", "enable"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "paper-status-monitor.desktop" in out
    assert "Warning: No graphical session was found" in out
    assert cli.main(["autostart", "status"]) == cli.EXIT_OK
    assert "Checks:      at login" in capsys.readouterr().out


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
    assert created == [
        {"wait": 60, "config_path": config_file.resolve(), "every": None, "tray": False}
    ]
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
    args += ["--field", "paper=Tau", "--field", "project = My thesis"]
    assert cli.main(args) == cli.EXIT_OK
    fields = dict(load_config(config_file).submissions[0].fields)
    assert fields == {"paper": "Tau", "project": "My thesis"}
    assert cli.main(["-c", str(config_file), "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Fields: paper = Tau, project = My thesis" in out
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
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=Tau"])
    patched_client.queue(DEMO_UUID, make_payload())
    assert cli.main(["-c", str(config_file), "run", "--no-open"]) == cli.EXIT_OK
    set_workbook_name(config_file, "{paper} - {journal_acronym}")
    data = config_file.parent / "data"
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "organize", "--dry-run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "->  Tau - SUBTRAK.xlsx" in out
    assert "Dry run" in out
    assert not (data / "Tau - SUBTRAK.xlsx").exists()

    assert cli.main(["-c", str(config_file), "organize"]) == cli.EXIT_OK
    assert "Renamed" in capsys.readouterr().out
    assert [path.name for path in data.glob("*.xlsx")] == ["Tau - SUBTRAK.xlsx"]

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
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=Tau"])
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


def test_export_command(
    config_file: Path, patched_client, make_payload, capsys, tmp_path: Path
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    patched_client.queue(DEMO_UUID, make_payload())
    cli.main(["-c", str(config_file), "run"])
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "export"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Submission,Detected at,Title,")
    assert "\nDemo," in out
    assert DEMO_UUID not in out

    target = tmp_path / "out" / "history.json"
    args = ["-c", str(config_file), "export", "--format", "json", "--include-links"]
    assert cli.main([*args, "-o", str(target)]) == cli.EXIT_OK
    assert "1 row(s) of 1 submission(s) written to" in capsys.readouterr().out
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["submissions"][0]["tracker_url"].endswith(DEMO_UUID)


def test_unknown_submissions_are_usage_errors(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    assert cli.main(["-c", str(config_file), "remove", "Nope"]) == cli.EXIT_USAGE
    assert "No submission matches 'Nope'" in capsys.readouterr().err
    assert cli.main(["-c", str(config_file), "disable", OTHER_UUID]) == cli.EXIT_USAGE
    assert "is not in" in capsys.readouterr().err
    assert cli.main(["-c", str(config_file), "edit", "2", "--label", "x"]) == cli.EXIT_USAGE
    assert "No submission matches '2'" in capsys.readouterr().err


# ------------------------------------------------------------------ edit


def test_edit_label_and_fields(config_file: Path, capsys) -> None:
    args = ["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"]
    cli.main([*args, "--field", "paper=Tau", "--field", "year=2026"])
    capsys.readouterr()

    options = ["--label", "Tau paper", "--field", "paper=Epsilon", "--field", "project=Thesis"]
    options += ["--remove-field", "year"]
    assert cli.main(["-c", str(config_file), "edit", "demo", *options]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Updated Tau paper in" in out
    assert "Label:  Tau paper  (was: Demo)" in out
    assert "Fields: paper = Epsilon, project = Thesis  (was: paper = Tau, year = 2026)" in out
    assert "Previous configuration: config.toml.bak" in out
    assert "organize" not in out  # the default names do not use the label or the fields
    [submission] = load_config(config_file).submissions
    assert submission.label == "Tau paper"
    assert dict(submission.fields) == {"paper": "Epsilon", "project": "Thesis"}
    assert "# Configuration file for paper-status-monitor." in config_file.read_text("utf-8")

    assert cli.main(["-c", str(config_file), "edit", "1", "--label", "Tau paper"]) == cli.EXIT_OK
    assert "Nothing to change: Tau paper already has these values." in capsys.readouterr().out

    args = ["-c", str(config_file), "edit", DEMO_UUID, "--label", "", "--clear-fields"]
    assert cli.main([*args, "--field", "paper=Tau"]) == cli.EXIT_OK
    assert "Label:  (none)  (was: Tau paper)" in capsys.readouterr().out
    [submission] = load_config(config_file).submissions
    assert (submission.label, dict(submission.fields)) == ("", {"paper": "Tau"})


def test_edit_suggests_organize_when_the_workbook_names_change(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=Tau"])
    set_workbook_name(config_file, "{paper} - {label} - {journal}")
    capsys.readouterr()
    args = ["-c", str(config_file), "edit", "1", "--field", "paper=Epsilon", "--label", "x"]
    assert cli.main(args) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "The workbook names use {paper}, {label}: an existing workbook keeps its name" in out
    assert "paper-status-monitor organize" in out


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ([], "Nothing to change: use --label, --field"),
        (["--remove-field", "year"], "has no custom field 'year' (its custom fields: paper)"),
        (["--field", "paper=X", "--remove-field", "paper"], "both name the custom field 'paper'"),
        (["--field", "journal=X"], "built-in placeholder"),
        (["--field", "paper"], "NAME=VALUE"),
        (["--clear-fields"], "would make the configuration invalid"),
        (["--record-ignore", "all"], "--record-ignore expects a comma-separated list"),
        (["--notify-fields", "Colour"], "Unknown column 'Colour' in '--notify-fields'"),
    ],
)
def test_edit_errors_leave_the_file_unchanged(
    config_file: Path, capsys, options: list[str], message: str
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--field", "paper=Tau"])
    set_workbook_name(config_file, "{paper}")
    capsys.readouterr()
    before = config_file.read_bytes()
    assert cli.main(["-c", str(config_file), "edit", "1", *options]) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err
    assert config_file.read_bytes() == before


# ------------------------------------------------------------------ own settings of a submission


def test_edit_own_settings_and_list_them(config_file: Path, capsys) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    capsys.readouterr()

    options = ["--notify-fields", "Status", "--record-ignore", "status code"]
    assert cli.main(["-c", str(config_file), "edit", "demo", *options]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Records:  all columns except Status code  (was: all columns)" in out
    assert "Notifies: only Status  (was: all columns)" in out
    assert "It now follows its own settings." in out
    [submission] = load_config(config_file).submissions
    assert dict(submission.overrides) == {
        "record_ignore": ("Status code",),
        "notify_fields": ("Status",),
    }

    assert cli.main(["-c", str(config_file), "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Own settings: records all columns except Status code; notifies only Status" in out

    assert cli.main(["-c", str(config_file), "edit", "1", "--notify-fields", "general"]) == 0
    assert dict(load_config(config_file).submissions[0].overrides) == {
        "record_ignore": ("Status code",)
    }
    capsys.readouterr()
    assert cli.main(["-c", str(config_file), "edit", "1", "--use-general-settings"]) == 0
    assert "It now follows the general settings." in capsys.readouterr().out
    assert load_config(config_file).submissions[0].overrides == {}


def test_run_uses_the_own_settings_of_each_submission(
    config_file: Path, patched_client, make_payload, capsys
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    cli.main(["-c", str(config_file), "edit", "1", "--notify-ignore", "Last review activity"])
    patched_client.queue(DEMO_UUID, make_payload(), make_payload(LastUpdated=1652887284))
    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    assert "[RECORDED]" in capsys.readouterr().out  # recorded, but not notified
    [workbook] = (config_file.parent / "data").glob("*.xlsx")
    assert len(read_records(workbook)) == 2


def test_run_options_win_over_the_own_settings(tmp_path: Path) -> None:
    own = {"notify_fields": ("Status",), "record_ignore": ("Title",)}
    config = Config(data_dir=tmp_path, submissions=(SubmissionConfig(DEMO_UUID, overrides=own),))
    parser = cli.build_parser()

    changed = cli.apply_run_overrides(config, parser.parse_args(["run", "--notify-fields", "all"]))
    [submission] = changed.submissions
    assert dict(submission.overrides) == {"record_ignore": ("Title",)}
    assert changed.notified_columns_for(submission) == TRACKED_COLUMNS
    unchanged = cli.apply_run_overrides(config, parser.parse_args(["run", "--no-open"]))
    assert unchanged.submissions == config.submissions


def test_doctor_lists_the_submissions_with_their_own_settings(
    config_file: Path, patched_client, demo_payload, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    cli.main(["-c", str(config_file), "edit", "1", "--notify-fields", "Status"])
    patched_client.queue(DEMO_UUID, demo_payload)
    capsys.readouterr()
    cli.main(["-c", str(config_file), "doctor"])
    assert "[INFO] With their own record/notify settings: Demo" in capsys.readouterr().out


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


def test_run_every_refuses_a_second_loop(
    config_file: Path, patched_client, demo_payload, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    patched_client.queue(DEMO_UUID, demo_payload)  # for doctor
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify"])
    intervals: list[timedelta] = []
    monkeypatch.setattr(
        cli.scheduling, "run_every", lambda task, interval, **kwargs: intervals.append(interval)
    )
    capsys.readouterr()
    with state.periodic_checks_lock():
        assert cli.main(["-c", str(config_file), "run", "--every", "12h"]) == cli.EXIT_FAILURE
        assert "Periodic checks are already running in process" in capsys.readouterr().err
        cli.main(["-c", str(config_file), "doctor"])
        assert "[INFO] Periodic checks are running in process" in capsys.readouterr().out
    assert intervals == []
    assert cli.main(["-c", str(config_file), "run", "--every", "12h"]) == cli.EXIT_OK
    assert intervals == [timedelta(hours=12)]


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
    info = cli.autostart.LauncherInfo(
        tmp_path / "paper-status-monitor.lnk",
        sys.executable,
        "-m paper_status_monitor run --wait 300 --every 1d",
        str(tmp_path),
    )
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "status", lambda: info)
    assert cli.main(["autostart", "status"]) == cli.EXIT_OK
    assert "Checks:      at login, then every 1d" in capsys.readouterr().out


# ------------------------------------------------------------------ icon in the notification area


class FakeTrayBackend:
    """The window code of the tray icon, replaced: it records what it is asked."""

    instances: ClassVar[list[FakeTrayBackend]] = []

    def __init__(self, *, tooltip, menu, on_command) -> None:
        self.tooltip, self.menu, self.on_command = tooltip, menu, on_command
        self.closed = False
        FakeTrayBackend.instances.append(self)

    def start(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_run_tray_needs_periodic_checks_on_windows(config_file: Path, monkeypatch, capsys) -> None:
    assert cli.main(["-c", str(config_file), "run", "--tray"]) == cli.EXIT_USAGE
    assert "--tray shows an icon while the periodic checks run" in capsys.readouterr().err
    monkeypatch.setattr(cli.tray.sys, "platform", "linux")
    args = ["-c", str(config_file), "run", "--every", "12h", "--tray"]
    assert cli.main(args) == cli.EXIT_USAGE
    assert "only available on Windows" in capsys.readouterr().err


def test_run_every_with_a_tray_icon(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    import functools

    monkeypatch.setattr(cli.tray.sys, "platform", "win32")
    FakeTrayBackend.instances = []
    monkeypatch.setattr(
        cli.tray, "TrayIcon", functools.partial(cli.tray.TrayIcon, backend=FakeTrayBackend)
    )
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Tau"])
    patched_client.queue(DEMO_UUID, make_payload())
    loops: list[dict] = []

    def fake_run_every(task, interval, **kwargs) -> int:
        loops.append(kwargs)
        task()
        [backend] = FakeTrayBackend.instances
        assert "Last check: " in backend.tooltip()
        assert "Next check: " in backend.tooltip()
        labels = [entry.label for entry in backend.menu()]
        assert labels[0].startswith("Tau: Under Review (since ")
        backend.on_command(cli.tray.STOP)
        return 1

    monkeypatch.setattr(cli.scheduling, "run_every", fake_run_every)
    args = ["-c", str(config_file), "run", "--every", "12h", "--tray"]
    assert cli.main(args) == cli.EXIT_OK
    [options] = loops
    assert options["stop"].is_set()  # stopped from the menu of the icon
    assert FakeTrayBackend.instances[0].closed


def test_autostart_enable_with_a_tray_icon(monkeypatch, config_file: Path, capsys) -> None:
    created: list[dict] = []
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(cli.tray.sys, "platform", "win32")
    monkeypatch.setattr(
        cli.autostart, "enable", lambda **kwargs: created.append(kwargs) or Path("startup.lnk")
    )
    base = ["-c", str(config_file), "autostart", "enable"]
    assert cli.main([*base, "--tray"]) == cli.EXIT_USAGE
    assert "add --every" in capsys.readouterr().err
    assert cli.main([*base, "--every", "12h", "--tray"]) == cli.EXIT_OK
    assert created[-1]["tray"] is True
    assert "An icon in the notification area" in capsys.readouterr().out

    info = cli.autostart.LauncherInfo(
        Path("paper-status-monitor.lnk"),
        sys.executable,
        "-m paper_status_monitor run --wait 300 --every 12h --tray",
        "",
    )
    monkeypatch.setattr(cli.autostart, "status", lambda: info)
    assert cli.main(["autostart", "status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "then every 12h, with an icon in the notification area" in out


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
        notify("--notify", "sms")
    with pytest.raises(ConfigError, match=r"'--notify' includes \"email\", but the \[email\]"):
        notify("--notify", "report,email")


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


# ------------------------------------------------------------------ language


def in_spanish(config_file: Path) -> None:
    text = config_file.read_text(encoding="utf-8")
    assert "language = 'en'" in text
    config_file.write_text(text.replace("language = 'en'", "language = 'es'"), encoding="utf-8")


def test_init_with_a_language(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.toml"
    assert cli.main(["-c", str(path), "init", "--language", "es-ES"]) == cli.EXIT_OK
    assert load_config(path).language == "es"
    assert "Language of the reports and the window: Español" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["-c", str(path), "init", "--force", "--language", "xx"])
    assert "Unknown language 'xx'" in capsys.readouterr().err


def test_documents_follow_the_language_but_the_command_line_stays_in_english(
    config_file: Path, patched_client, make_payload, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    in_spanish(config_file)
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Tau"])
    patched_client.queue(DEMO_UUID, make_payload())
    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Checked 1 submission at" in out
    assert "[NEW]" in out
    [path] = (config_file.parent / "data" / "reports").glob("changes_*.txt")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("Informe del estado de los envíos")
    assert "NUEVOS EN SEGUIMIENTO (1)" in text

    assert cli.main(["-c", str(config_file), "summary", "--format", "markdown"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("# Resumen del estado de los envíos")
    assert "| # | Envío | Revista |" in out

    cli.main(["-c", str(config_file), "doctor"])
    assert "summary and window: Español (es)" in capsys.readouterr().out


def test_test_email_in_the_configured_language(config_file: Path, smtp, monkeypatch) -> None:
    with_email(config_file)
    in_spanish(config_file)
    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    assert cli.main(["-c", str(config_file), "email", "test"]) == cli.EXIT_OK
    [message] = smtp.sent()
    assert message["Subject"] == "[paper-status-monitor] Mensaje de prueba"
    assert "no lo reenvíes" in message.get_content()


# ------------------------------------------------------------------ e-mail

EMAIL_TABLE = """
[email]
smtp_host = "smtp.example.org"
username = "me@example.org"
to = ["me@example.org"]
"""


def with_email(config_file: Path, notify: str = '"none"') -> None:
    text = config_file.read_text(encoding="utf-8").replace('notify = "none"', f"notify = {notify}")
    config_file.write_text(text + EMAIL_TABLE, encoding="utf-8")


def test_email_test_command(config_file: Path, smtp, monkeypatch, capsys) -> None:
    with_email(config_file)
    assert cli.main(["-c", str(config_file), "email", "test"]) == cli.EXIT_FAILURE
    assert "There is no password for me@example.org" in capsys.readouterr().err

    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    assert cli.main(["-c", str(config_file), "email", "test"]) == cli.EXIT_OK
    assert "Test e-mail sent to me@example.org through smtp.example.org." in capsys.readouterr().out
    [message] = smtp.sent()
    assert message["Subject"] == "[paper-status-monitor] Test message"


def test_email_test_needs_the_settings(config_file: Path, capsys) -> None:
    assert cli.main(["-c", str(config_file), "email", "test"]) == cli.EXIT_USAGE
    assert "lacks smtp_host, to, sender" in capsys.readouterr().err


def test_email_password_in_the_system_keyring(
    config_file: Path, fake_keyring, monkeypatch, capsys
) -> None:
    with_email(config_file)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "secret")
    assert cli.main(["-c", str(config_file), "email", "set-password"]) == cli.EXIT_OK
    assert "now kept in the system keyring" in capsys.readouterr().out
    assert fake_keyring.passwords == {("paper-status-monitor", "me@example.org"): "secret"}
    assert "secret" not in config_file.read_text(encoding="utf-8")

    assert cli.main(["-c", str(config_file), "email", "delete-password"]) == cli.EXIT_OK
    assert "Password removed from the system keyring." in capsys.readouterr().out
    assert cli.main(["-c", str(config_file), "email", "delete-password"]) == cli.EXIT_OK
    assert "No password was stored." in capsys.readouterr().out

    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "")
    assert cli.main(["-c", str(config_file), "email", "set-password"]) == cli.EXIT_USAGE
    assert "nothing was stored" in capsys.readouterr().err


def test_email_set_password_without_the_keyring_package(
    config_file: Path, monkeypatch, capsys
) -> None:
    with_email(config_file)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "secret")
    assert cli.main(["-c", str(config_file), "email", "set-password"]) == cli.EXIT_FAILURE
    assert "pip install keyring" in capsys.readouterr().err


def test_run_sends_the_report_by_email(
    config_file: Path, patched_client, make_payload, smtp, monkeypatch
) -> None:
    cli.main(["-c", str(config_file), "add", DEMO_UUID, "--no-verify", "--label", "Demo"])
    with_email(config_file, notify='"email"')
    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    patched_client.queue(DEMO_UUID, make_payload())

    assert cli.main(["-c", str(config_file), "run"]) == cli.EXIT_OK

    [message] = smtp.sent()
    assert message["Subject"] == "[paper-status-monitor] Now tracking: Demo"
    assert "NOW TRACKING (1)" in message.get_content()
    assert list((config_file.parent / "data" / "reports").glob("changes_*.txt"))


def test_doctor_checks_the_email_settings(
    config_file: Path, patched_client, demo_payload, fake_keyring, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli.autostart, "is_supported", lambda: False)
    with_email(config_file, notify='["report", "email"]')
    patched_client.queue(DEMO_UUID, demo_payload)
    cli.main(["-c", str(config_file), "doctor"])
    assert "[WARN] E-mails: there is no password for me@example.org" in capsys.readouterr().out

    fake_keyring.set_password("paper-status-monitor", "me@example.org", "secret")
    cli.main(["-c", str(config_file), "doctor"])
    out = capsys.readouterr().out
    assert "[INFO] E-mails are sent to me@example.org through smtp.example.org" in out
    assert "the report is sent by e-mail" in out
