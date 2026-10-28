from __future__ import annotations

import contextlib
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from paper_status_monitor import gui, naming
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import (
    ConfigError,
    SubmissionConfig,
    add_submission,
    load_config,
    write_config,
)
from paper_status_monitor.models import TRACKED_COLUMNS, TRACKER_URL_COLUMN
from paper_status_monitor.storage import append_record

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


def test_parse_fields_text() -> None:
    text = """
    # one field per line
    paper = TMY
    project: "My thesis"
    note = a = b

    """
    assert gui.parse_fields_text(text) == {
        "paper": "TMY",
        "project": "My thesis",
        "note": "a = b",
    }
    assert gui.parse_fields_text("") == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("paper TMY", "must look like"),
        ("2paper = x", "Invalid custom field name"),
        ("journal = x", "built-in placeholder"),
        ("paper = a\npaper = b", "twice"),
    ],
)
def test_parse_fields_text_errors(text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        gui.parse_fields_text(text)


def test_format_fields() -> None:
    fields = {"paper": "TMY", "project": "My thesis"}
    assert gui.parse_fields_text(gui.format_fields_text(fields)) == fields
    assert gui.format_fields_inline(fields) == "paper=TMY, project=My thesis"


def config_values(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "data_dir": str(tmp_path / "data"),
        "workbook_name": "{journal}",
        "recorded": TRACKED_COLUMNS,
        "notified": TRACKED_COLUMNS,
        "notify": ["report"],
        "notify_on_errors": True,
        "request_timeout": "30",
        "submissions": [],
        "path": tmp_path / "config.toml",
    }
    values.update(changes)
    return values


def test_build_config(tmp_path: Path) -> None:
    submissions = [SubmissionConfig(DEMO_UUID, label="Demo", fields={"paper": "TMY"})]
    notified = [column for column in TRACKED_COLUMNS if column != "Last review activity"]
    config = gui.build_config(
        **config_values(
            tmp_path,
            workbook_name="{paper}",
            notified=notified,
            notify=[],
            request_timeout="12,5",
            submissions=submissions,
        )
    )
    assert config.notify_fields is None
    assert config.notify_ignore == ("Last review activity",)
    assert (config.record_fields, config.record_ignore) == (None, ())
    assert config.request_timeout == 12.5
    assert config.open_report is False
    assert config.notify == ()
    assert config.submissions == tuple(submissions)
    assert config.workbook_name == "{paper}"
    assert config.data_dir == tmp_path / "data"
    only_status = gui.build_config(**config_values(tmp_path, notified=["Status"]))
    assert only_status.notify_fields == ("Status",)
    assert only_status.notified_columns == ("Status",)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request_timeout": "soon"}, "timeout"),
        ({"request_timeout": "0"}, "request_timeout"),
        ({"workbook_name": "{nope}"}, "Unknown placeholder"),
        ({"data_dir": "  "}, "data_dir"),
    ],
)
def test_build_config_errors(tmp_path: Path, changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        gui.build_config(**config_values(tmp_path, **changes))


def test_preview_rows(tmp_path: Path) -> None:
    data = tmp_path / "data"
    append_record(
        data / "Old name.xlsx",
        {
            "Manuscript number": "ABC-D-26-00001",
            "Journal": "Journal of Examples",
            TRACKER_URL_COLUMN: f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}",
        },
    )
    submissions = [
        SubmissionConfig(DEMO_UUID, label="Demo", fields={"paper": "TMY"}),
        SubmissionConfig(OTHER_UUID, fields={"paper": "Next"}),
    ]
    config = gui.build_config(
        **config_values(
            tmp_path, workbook_name="{paper} - {journal_acronym}", submissions=submissions
        )
    )
    assert gui.preview_rows(config) == [
        ("Demo", "Old name.xlsx", "TMY - ABC.xlsx"),
        (OTHER_UUID, "(not recorded yet)", "Next - ABC.xlsx (example)"),
    ]


def test_placeholders_help() -> None:
    text = gui.placeholders_help(["paper"])
    assert "{manuscript_number}" in text
    assert "Custom fields: {paper}" in text
    assert "none yet" in gui.placeholders_help()


def test_presets_are_valid_templates() -> None:
    for template in gui.NAME_PRESETS.values():
        naming.validate_template(template, ["paper"])


def test_run_gui_without_tkinter(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert gui.run_gui(Path("config.toml")) == 1
    assert "tkinter" in capsys.readouterr().err


def test_main_passes_the_configuration_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[Path | None] = []
    monkeypatch.setattr(gui, "run_gui", lambda path: received.append(path) or 0)
    assert gui.main(["--config", str(tmp_path / "my.toml")]) == 0
    assert gui.main([]) == 0
    assert received == [tmp_path / "my.toml", None]


# ------------------------------------------------------------------ the window (needs Tk)


@pytest.fixture
def tk_root(capsys: pytest.CaptureFixture[str]):
    """A hidden Tk root window, or a skip when Tk cannot open windows (e.g. Linux CI).

    Output capturing is suspended while the window exists: on Windows, pytest's
    file-descriptor capture makes Tcl fail randomly while reading its own library.
    """
    tkinter = pytest.importorskip("tkinter")
    with capsys.disabled():
        try:
            root = tkinter.Tk()
        except tkinter.TclError as exc:  # no display
            pytest.skip(f"Tk cannot open a window here: {exc}")
        root.withdraw()
        yield root
        with contextlib.suppress(tkinter.TclError):
            root.destroy()


@pytest.fixture
def make_app(tk_root, monkeypatch: pytest.MonkeyPatch):
    """Create the main window without message boxes, extra windows or background threads."""
    from paper_status_monitor import _gui_app

    monkeypatch.setattr(_gui_app.report, "open_path", lambda path: True)

    class QuietApp(_gui_app.App):
        def __init__(self, config_path: Path) -> None:
            self.messages: list[tuple[str, str, str]] = []
            self.answers: list[bool | None] = []
            self.windows: list[tuple[str, str, Any]] = []
            super().__init__(tk_root, config_path, synchronous=True)

        def show_error(self, title: str, message: str, *, parent: object = None) -> None:
            self.messages.append(("error", title, message))

        def show_info(self, title: str, message: str, *, parent: object = None) -> None:
            self.messages.append(("info", title, message))

        def ask_yes_no(self, title: str, message: str, *, parent: object = None) -> bool:
            return bool(self.answers.pop(0)) if self.answers else True

        def ask_yes_no_cancel(self, title: str, message: str) -> bool | None:
            return self.answers.pop(0) if self.answers else False

        def text_window(self, title: str, text: str, *, action: Any = None, **options: Any) -> Any:
            self.windows.append((title, text, action))
            return None

    return QuietApp


def configured(tmp_path: Path, **fields: str) -> Path:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    add_submission(path, DEMO_UUID, label="Demo", fields=fields or None)
    return path


def test_window_shows_and_saves_the_configuration(make_app, tmp_path: Path) -> None:
    path = configured(tmp_path, paper="TMY")
    app = make_app(path)
    assert app.messages == []
    assert not app.dirty
    assert app.tree.get_children() == (DEMO_UUID,)
    assert tuple(app.tree.item(DEMO_UUID, "values"))[:3] == ("Demo", "paper=TMY", "yes")
    assert app.statuses[DEMO_UUID] == "not recorded yet"
    assert "{paper}" in app.placeholders_var.get()
    assert app.autostart_var.get()

    app.notify_vars["Last review activity"].set(False)
    app.template_var.set("{paper} - {journal_acronym}")
    assert app.dirty
    assert "all columns except Last review activity" in app.selection_var.get()
    assert app.save()

    config = load_config(path)
    assert config.notify_ignore == ("Last review activity",)
    assert config.workbook_name == "{paper} - {journal_acronym}"
    assert (tmp_path / "config.toml.bak").is_file()
    assert not app.dirty


def test_window_manages_submissions(make_app, tmp_path: Path) -> None:
    path = tmp_path / "config.toml"  # created by Save
    app = make_app(path)
    assert app.dirty

    dialog = app.add_submission()
    dialog.window.withdraw()
    dialog.link_var.set(f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}")
    dialog.label_var.set("Demo")
    dialog.set_fields_text("paper = TMY")
    dialog.verify_var.set(False)
    assert dialog.submit() is not None
    assert [s.uuid for s in app.submissions] == [DEMO_UUID]

    duplicate = app.add_submission()
    duplicate.window.withdraw()
    duplicate.link_var.set(DEMO_UUID)
    duplicate.verify_var.set(False)
    assert duplicate.submit() is None
    assert app.messages[-1][1] == "Duplicate submission"
    duplicate.close()

    app.tree.selection_set(DEMO_UUID)
    app.toggle_submission()
    assert app.submissions[0].enabled is False
    edit = app.edit_submission()
    assert edit is not None
    edit.window.withdraw()
    edit.set_fields_text("paper = TMY\nproject = Thesis")
    edit.submit()
    assert dict(app.submissions[0].fields) == {"paper": "TMY", "project": "Thesis"}
    assert app.save()
    saved = load_config(path).submissions[0]
    assert (saved.enabled, saved.label, dict(saved.fields)) == (
        False,
        "Demo",
        {"paper": "TMY", "project": "Thesis"},
    )

    app.tree.selection_set(DEMO_UUID)
    app.remove_submission()
    assert app.submissions == []
    assert app.tree.get_children() == ()


def test_window_checks_new_links_with_the_tracker(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client, demo_payload
) -> None:
    from paper_status_monitor import _gui_app

    monkeypatch.setattr(_gui_app, "TrackerClient", lambda **kwargs: fake_client)
    fake_client.queue(DEMO_UUID, demo_payload)
    app = make_app(tmp_path / "config.toml")
    dialog = app.add_submission()
    dialog.window.withdraw()
    dialog.link_var.set(DEMO_UUID)
    dialog.submit()
    assert [s.uuid for s in app.submissions] == [DEMO_UUID]
    assert "Found: Influence of submission trackers" in app.messages[-1][2]

    app.tree.selection_set(DEMO_UUID)
    app.check_submission()
    title, text, _ = app.windows[-1]
    assert title == f"Current status - {DEMO_UUID}"
    assert "SUBTRAK-D-22-00128" in text


def test_window_runs_checks(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client, make_payload
) -> None:
    monkeypatch.setattr("paper_status_monitor.monitor.TrackerClient", lambda **kw: fake_client)
    fake_client.queue(DEMO_UUID, make_payload())
    app = make_app(configured(tmp_path))
    app.open_report_var.set(False)

    app.run_check(dry_run=True)
    assert "[NEW]" in app.output.get("1.0", "end")
    assert "dry run" in app.output.get("1.0", "end")
    assert not (tmp_path / "data").exists()

    app.run_check()
    assert "Report:" in app.output.get("1.0", "end")
    assert app.statuses[DEMO_UUID].startswith("Under Review")
    assert app.last_run_var.get().startswith("Last run:")


def test_window_previews_and_organizes_workbook_names(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client, make_payload
) -> None:
    monkeypatch.setattr("paper_status_monitor.monitor.TrackerClient", lambda **kw: fake_client)
    fake_client.queue(DEMO_UUID, make_payload())
    app = make_app(configured(tmp_path, paper="TMY"))
    app.run_check()

    app.template_var.set("{paper}")
    app.update_preview()
    rows = [tuple(app.preview.item(item, "values")) for item in app.preview.get_children()]
    assert [(row[0], row[2]) for row in rows] == [("Demo", "TMY.xlsx")]

    app.organize_workbooks()  # saves first (the answer is yes), then shows the plan
    title, text, action = app.windows[-1]
    assert title == "Organize workbooks"
    assert "->  TMY.xlsx" in text
    action[1]()  # Apply
    assert [p.name for p in (tmp_path / "data").glob("*.xlsx")] == ["TMY.xlsx"]
    assert "Renamed" in app.messages[-1][2]

    app.template_var.set("{nope}")
    app.update_preview()
    assert "Unknown placeholder" in app.preview_message_var.get()
    assert app.preview.get_children() == ()


def test_window_reports_an_invalid_configuration(make_app, tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("open_reprot = true", encoding="utf-8")
    app = make_app(path)
    kind, title, message = app.messages[0]
    assert (kind, title) == ("error", "Invalid configuration")
    assert "Unknown setting" in message
    assert app.dirty


def test_closing_asks_about_unsaved_changes(make_app, tmp_path: Path, tk_root) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    app = make_app(path)
    app.timeout_var.set("45")
    app.answers = [None]  # cancel
    app.close()
    assert tk_root.winfo_exists()
    app.answers = [True]  # save, then close
    app.close()
    assert load_config(path).request_timeout == 45


def test_parse_and_format_hours() -> None:
    assert gui.parse_hours("0") is None
    assert gui.parse_hours("") is None
    assert gui.parse_hours("12") == timedelta(hours=12)
    assert gui.parse_hours("1,5") == timedelta(minutes=90)
    for text in ("soon", "-2", "nan"):
        with pytest.raises(ConfigError, match="number of hours"):
            gui.parse_hours(text)
    with pytest.raises(ConfigError, match="too often"):
        gui.parse_hours("0.5")
    assert gui.format_hours(None) == "0"
    assert gui.format_hours(timedelta(hours=12)) == "12"
    assert gui.format_hours(timedelta(minutes=90)) == "1.5"


def test_window_saves_the_notification_channels(make_app, tmp_path: Path) -> None:
    path = configured(tmp_path)
    app = make_app(path)
    assert app.open_report_var.get() is True
    assert app.toast_var.get() is False

    app.toast_var.set(True)
    assert app.dirty
    assert app.save()
    assert load_config(path).notify == ("report", "toast")

    app.open_report_var.set(False)
    app.toast_var.set(False)
    assert app.save()
    assert load_config(path).notify == ()


def test_window_sends_a_test_notification(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_status_monitor import _gui_app

    shown: list[Any] = []
    monkeypatch.setattr(_gui_app.notifications, "show", shown.append)
    app = make_app(configured(tmp_path))
    app.send_test_notification()
    assert [notification.title for notification in shown] == ["paper-status-monitor"]
    assert app.messages[-1][:2] == ("info", "Test notification")

    def fail(notification: Any) -> None:
        raise _gui_app.notifications.NotificationError("no display")

    monkeypatch.setattr(_gui_app.notifications, "show", fail)
    app.send_test_notification()
    kind, title, message = app.messages[-1]
    assert (kind, title) == ("error", "No desktop notification")
    assert "no display" in message


def test_window_shows_and_saves_the_summary(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client, make_payload
) -> None:
    from paper_status_monitor import _gui_app

    monkeypatch.setattr("paper_status_monitor.monitor.TrackerClient", lambda **kw: fake_client)
    fake_client.queue(DEMO_UUID, make_payload())
    app = make_app(configured(tmp_path))
    app.run_check()

    app.show_summary()
    title, text, action = app.windows[-1]
    assert title == "Summary"
    assert "1  Demo" in text
    assert "Under Review" in text

    target = tmp_path / "summary.md"
    monkeypatch.setattr(_gui_app.filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    action[1]()  # Save...
    assert target.read_text(encoding="utf-8").startswith("# Paper status summary")
    assert "summary.md" in app.status_var.get()


def test_window_enables_periodic_checks(
    make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_status_monitor import _gui_app

    calls: list[dict[str, Any]] = []
    shortcut = tmp_path / "paper-status-monitor.lnk"
    info = _gui_app.autostart.ShortcutInfo(
        shortcut, sys.executable, "-m paper_status_monitor run --wait 120 --every 12h", ""
    )
    monkeypatch.setattr(_gui_app.autostart, "is_supported", lambda: True)
    monkeypatch.setattr(_gui_app.autostart, "status", lambda: info)
    monkeypatch.setattr(
        _gui_app.autostart, "enable", lambda **kwargs: calls.append(kwargs) or shortcut
    )
    app = make_app(configured(tmp_path))
    assert (app.wait_var.get(), app.every_var.get()) == ("120", "12")  # read from the shortcut
    assert "and then every 12 hours" in app.autostart_var.get()

    app.every_var.set("6")
    app.enable_autostart()
    assert calls[-1]["every"] == timedelta(hours=6)
    assert calls[-1]["wait"] == 120
    assert "every 6 hours while you stay logged in" in app.messages[-1][2]

    app.every_var.set("0.5")
    app.enable_autostart()
    assert app.messages[-1][:2] == ("error", "Invalid value")
    assert len(calls) == 1
