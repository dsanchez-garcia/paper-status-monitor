from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from paper_status_monitor import config as config_module
from paper_status_monitor import paths
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import (
    DEFAULT_WORKBOOK_NAME,
    Config,
    ConfigError,
    EmailConfig,
    SubmissionConfig,
    add_submission,
    describe_columns,
    describe_notify,
    dump_config,
    edit_submission,
    find_submission,
    is_email_address,
    load_config,
    parse_columns_option,
    parse_config,
    parse_field_assignment,
    parse_notify,
    remove_submission,
    render_config,
    save_config,
    select_columns,
    set_submission_enabled,
    split_columns,
    toml_string,
    write_config,
)
from paper_status_monitor.models import TRACKED_COLUMNS

OTHER_UUID = "11111111-2222-3333-4444-555555555555"
THIRD_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_full_config(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        f"""
data_dir = 'C:\\Users\\me\\My papers'
open_report = false
notify_on_errors = false
ignore_fields = ["status code"]
request_timeout = 12

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
label = "Demo"

[[submissions]]
uuid = "{OTHER_UUID.upper()}"
enabled = false
""",
    )
    config = load_config(path)
    assert config.path == path
    assert config.open_report is False
    assert config.notify_on_errors is False
    assert config.ignore_fields == ("Status code",)
    assert config.request_timeout == 12.0
    assert [s.uuid for s in config.submissions] == [DEMO_UUID, OTHER_UUID]
    assert config.submissions[0].label == "Demo"
    assert config.submissions[0].display_name == "Demo"
    assert config.submissions[1].display_name == OTHER_UUID
    assert config.enabled_submissions == config.submissions[:1]
    assert config.reports_dir == config.data_dir / "reports"


def test_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path / "config.toml", ""))
    assert config.data_dir == paths.default_data_dir()
    assert config.submissions == ()
    assert config.open_report is True
    assert config.notify_on_errors is True
    assert config.ignore_fields == ()
    assert config.time_in_status is False


def test_relative_data_dir_is_relative_to_the_config_file(tmp_path: Path) -> None:
    config = load_config(write(tmp_path / "cfg" / "config.toml", "data_dir = 'workbooks'"))
    assert config.data_dir == tmp_path / "cfg" / "workbooks"


def test_home_in_data_dir_is_expanded(tmp_path: Path, isolated_user_dirs: Path) -> None:
    config = load_config(write(tmp_path / "config.toml", "data_dir = '~/papers'"))
    assert config.data_dir == isolated_user_dirs / "papers"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="paper-status-monitor init"):
        load_config(tmp_path / "nope.toml")


def test_default_location_honours_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path / "elsewhere.toml", "")
    monkeypatch.setenv(paths.CONFIG_ENV_VAR, str(path))
    assert load_config().path == path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("data_dir = ", "Invalid TOML"),
        ("open_reprot = true", "Unknown setting"),
        ("data_dir = 3", "data_dir"),
        ("open_report = 'yes'", "open_report"),
        ("request_timeout = -1", "request_timeout"),
        ("ignore_fields = ['Colour']", "Unknown column"),
        ("ignore_fields = 'Status'", "ignore_fields"),
        ("submissions = 3", "submissions"),
        ("[[submissions]]\nlabel = 'x'", "needs a 'url'"),
        ("[[submissions]]\nurl = 'https://example.org'", "No tracking UUID"),
        (
            "[[submissions]]\nurl = '00000000-0000-0000-0000-000000000000'\ncolour = 1",
            "unknown key",
        ),
        (
            f"[[submissions]]\nuuid = '{DEMO_UUID}'\n[[submissions]]\nuuid = '{DEMO_UUID}'",
            "duplicates",
        ),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nenabled = 'no'", "enabled"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nlabel = 3", "label"),
    ],
)
def test_invalid_configs(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path / "config.toml", text))


@pytest.mark.parametrize(
    "data_dir",
    [r"H:\My Drive\Paper status", "/home/me/papers", "C:/Users/O'Brien/papers"],
)
def test_written_config_round_trips(tmp_path: Path, data_dir: str) -> None:
    path = write_config(tmp_path / "sub" / "config.toml", data_dir)
    config = load_config(path)
    expected = Path(data_dir)
    if not expected.is_absolute():  # e.g. a Windows path read on Linux
        expected = path.parent / expected
    assert config.data_dir == expected
    assert config.submissions == ()


def test_write_config_refuses_to_overwrite(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path)
    with pytest.raises(ConfigError, match="already exists"):
        write_config(path, tmp_path)
    write_config(path, tmp_path / "other", overwrite=True)
    assert load_config(path).data_dir == tmp_path / "other"


def test_add_submission_preserves_comments(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    add_submission(path, DEMO_UUID, label="Demo 'quoted'")
    add_submission(path, OTHER_UUID)

    text = path.read_text(encoding="utf-8")
    assert "# Configuration file for paper-status-monitor." in text
    config = load_config(path)
    assert [s.uuid for s in config.submissions] == [DEMO_UUID, OTHER_UUID]
    assert config.submissions[0].label == "Demo 'quoted'"

    with pytest.raises(ConfigError, match="already"):
        add_submission(path, DEMO_UUID)


def test_add_submission_to_a_file_without_trailing_newline(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", "open_report = false")
    add_submission(path, DEMO_UUID)
    assert load_config(path).submissions[0].uuid == DEMO_UUID


def test_toml_string() -> None:
    assert toml_string(r"C:\Users\me") == r"'C:\Users\me'"
    assert toml_string("O'Brien") == '"O\'Brien"'
    assert toml_string("line\nbreak") == '"line\\nbreak"'


def test_parse_config_without_file() -> None:
    config = parse_config({"data_dir": "relative"})
    assert config.data_dir == Path("relative")
    assert config.path is None


def test_rendered_template_is_valid() -> None:
    config = parse_config(config_module.tomllib.loads(render_config("/tmp/x")))
    assert config.open_report is True


def test_example_config_is_valid() -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "config.example.toml"
    config = load_config(example)
    assert [s.uuid for s in config.submissions] == [DEMO_UUID]


# ------------------------------------------------------------------ record / notify


def test_record_and_notify_settings(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "config.toml",
            """
record_fields = "all"
record_ignore = ["status code"]
notify_fields = ["Status", "REVIEWS COMPLETED"]
notify_ignore = []
""",
        )
    )
    assert config.record_fields is None
    assert config.record_ignore == ("Status code",)
    assert config.notify_fields == ("Status", "Reviews completed")
    assert config.recorded_columns == tuple(c for c in TRACKED_COLUMNS if c != "Status code")
    assert config.notified_columns == ("Status", "Reviews completed")


def test_defaults_record_and_notify_everything(tmp_path: Path) -> None:
    config = load_config(write(tmp_path / "config.toml", ""))
    assert config.recorded_columns == TRACKED_COLUMNS
    assert config.notified_columns == TRACKED_COLUMNS
    assert config.workbook_name == DEFAULT_WORKBOOK_NAME


def test_legacy_ignore_fields_is_merged_into_notify_ignore(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "config.toml",
            'ignore_fields = ["Status code"]\nnotify_ignore = ["Last review activity"]',
        )
    )
    assert "Status code" not in config.notified_columns
    assert "Last review activity" not in config.notified_columns
    assert config.recorded_columns == TRACKED_COLUMNS


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("notify_fields = 3", '"all" or a list'),
        ("notify_fields = 'some'", '"all" or a list'),
        ("notify_fields = ['Colour']", "Unknown column 'Colour' in 'notify_fields'"),
        ("record_fields = [1]", '"all" or a list'),
        ("record_ignore = 'Status'", "'record_ignore'.*list of column names"),
        ("notify_ignore = ['Detected at']", "Unknown column"),
        ("workbook_name = ''", "workbook_name"),
        ("workbook_name = 3", "workbook_name"),
        ("workbook_name = '{paper}'", r"Unknown placeholder\(s\) \{paper\}"),
        ("workbook_name = '{journal'", "Invalid template"),
        ("time_in_status = 'yes'", "'time_in_status'.*true or false"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = 'Tau'", "'fields' must be a table"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = {{ 2x = 'a' }}", "Invalid custom"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = {{ title = 'a' }}", "built-in"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = {{ paper = true }}", "must be a text"),
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = {{ paper = [] }}", "must be a text"),
    ],
)
def test_invalid_new_settings(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path / "config.toml", text))


def test_custom_fields_and_template(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "config.toml",
            f"""
workbook_name = "{{paper}} - {{journal}} - {{manuscript_number}}"

[[submissions]]
uuid = "{DEMO_UUID}"
fields = {{ paper = "  Tau   paper ", year = 2026 }}

[[submissions]]
uuid = "{OTHER_UUID}"
""",
        )
    )
    assert config.workbook_name == "{paper} - {journal} - {manuscript_number}"
    assert dict(config.submissions[0].fields) == {"paper": "Tau paper", "year": "2026"}
    assert dict(config.submissions[1].fields) == {}
    assert config.custom_field_names == ("paper", "year")


def test_submission_config_is_hashable_with_fields() -> None:
    submission = SubmissionConfig(DEMO_UUID, fields={"paper": "Tau"})
    assert submission == SubmissionConfig(DEMO_UUID, fields={"paper": "Tau"})
    assert submission != SubmissionConfig(DEMO_UUID, fields={"paper": "Other"})
    assert len({submission}) == 1


def test_select_split_and_describe_columns() -> None:
    assert select_columns(None) == TRACKED_COLUMNS
    assert select_columns(["status", "Title"]) == ("Title", "Status")
    assert select_columns(None, ["Status code"]) == tuple(
        c for c in TRACKED_COLUMNS if c != "Status code"
    )
    everything_but = [c for c in TRACKED_COLUMNS if c != "Last review activity"]
    assert split_columns(TRACKED_COLUMNS) == (None, ())
    assert split_columns(everything_but) == (None, ("Last review activity",))
    assert split_columns(["Status"]) == (("Status",), ())
    assert split_columns([]) == ((), ())
    assert describe_columns(TRACKED_COLUMNS) == "all columns"
    assert describe_columns(everything_but) == "all columns except Last review activity"
    assert describe_columns(["Status", "Revision"]) == "only Revision, Status"
    assert describe_columns([]) == "no columns"


@pytest.mark.parametrize(
    ("text", "allow_all", "expected"),
    [
        ("all", True, None),
        ("ALL", True, None),
        ("none", True, ()),
        ("", False, ()),
        ("status, last review activity", True, ("Status", "Last review activity")),
        ("Status,Status", False, ("Status",)),
    ],
)
def test_parse_columns_option(text: str, allow_all: bool, expected: object) -> None:
    assert parse_columns_option(text, option="--x", allow_all=allow_all) == expected


def test_parse_columns_option_errors() -> None:
    with pytest.raises(ConfigError, match="Unknown column 'Colour' in '--notify-fields'"):
        parse_columns_option("Status,Colour", option="--notify-fields")
    with pytest.raises(ConfigError, match="'none'"):
        parse_columns_option("all", option="--notify-ignore", allow_all=False)


def test_parse_field_assignment() -> None:
    assert parse_field_assignment("paper=Tau") == ("paper", "Tau")
    assert parse_field_assignment(" paper = A  b ") == ("paper", "A b")
    assert parse_field_assignment("note=a=b") == ("note", "a=b")
    with pytest.raises(ConfigError, match="NAME=VALUE"):
        parse_field_assignment("paper")
    with pytest.raises(ConfigError, match="Invalid custom field name"):
        parse_field_assignment("my paper=Tau")


# ------------------------------------------------------------------ writing


def full_config(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path / "My data",
        submissions=(
            SubmissionConfig(
                DEMO_UUID,
                label="Demo 'quoted'",
                fields={"paper": "Tau"},
                overrides={"notify_fields": ("Status",), "record_fields": None},
            ),
            SubmissionConfig(OTHER_UUID, enabled=False, fields={"paper": 'A "b"', "x_2": "1"}),
        ),
        notify=(),
        notify_on_errors=False,
        request_timeout=12.5,
        workbook_name="{paper} - {journal}",
        notify_fields=("Status",),
        notify_ignore=("Title",),
        ignore_fields=("Status code",),
        record_fields=None,
        record_ignore=("Last review activity",),
        time_in_status=True,
    )


def test_dump_config_round_trips(tmp_path: Path) -> None:
    config = full_config(tmp_path)
    text = dump_config(config)
    loaded = parse_config(config_module.tomllib.loads(text))
    assert loaded.data_dir == config.data_dir
    assert loaded.submissions == config.submissions
    assert loaded.workbook_name == config.workbook_name
    assert loaded.notify_fields == ("Status",)
    assert loaded.notify_ignore == ("Title", "Status code")  # the old name is merged
    assert loaded.ignore_fields == ()
    assert loaded.notified_columns == config.notified_columns
    assert loaded.recorded_columns == config.recorded_columns
    assert loaded.request_timeout == 12.5
    assert (loaded.open_report, loaded.notify_on_errors) == (False, False)
    assert loaded.notify == ()
    assert 'notify = "none"' in text
    assert "open_report" not in text
    assert "enabled = false" in text
    assert "# Name of the workbooks." in text
    assert (
        "fields = { paper = 'Tau' }\nrecord_fields = \"all\"\nnotify_fields = ['Status']\n" in text
    )
    assert "\ntime_in_status = true\n" in text
    assert loaded.time_in_status is True


def test_save_config_keeps_a_backup(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    original = path.read_text(encoding="utf-8")
    config = load_config(path)
    save_config(replace(config, notify_ignore=("Last review activity",)))
    assert load_config(path).notify_ignore == ("Last review activity",)
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".config.toml.tmp-*"))


def test_save_config_refuses_invalid_settings(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="Unknown placeholder"):
        save_config(replace(load_config(path), workbook_name="{nope}"))
    assert path.read_text(encoding="utf-8") == before


def test_save_config_creates_the_file(tmp_path: Path) -> None:
    path = tmp_path / "new" / "config.toml"
    save_config(Config(data_dir=tmp_path / "data"), path)
    assert load_config(path).data_dir == tmp_path / "data"
    assert not (path.parent / "config.toml.bak").exists()


def test_add_submission_with_fields(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    add_submission(path, DEMO_UUID, label="Demo", fields={"paper": "Tau"})
    assert dict(load_config(path).submissions[0].fields) == {"paper": "Tau"}
    assert "fields = { paper = 'Tau' }" in path.read_text(encoding="utf-8")


def test_add_submission_with_invalid_fields_leaves_the_file_unchanged(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    before = path.read_bytes()
    with pytest.raises(ConfigError, match="built-in placeholder"):
        add_submission(path, DEMO_UUID, fields={"journal": "x"})
    assert path.read_bytes() == before


# ------------------------------------------------------------------ notifications


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("report", ("report",)),
        ("TOAST", ("toast",)),
        ("none", ()),
        ([], ()),
        (["toast", "report"], ("report", "toast")),
        ("toast, report", ("report", "toast")),
    ],
)
def test_parse_notify(value: object, expected: tuple[str, ...]) -> None:
    assert parse_notify(value) == expected


@pytest.mark.parametrize("value", ["", "sms", ["report", "none"], 3, [1]])
def test_parse_notify_errors(value: object) -> None:
    with pytest.raises(ConfigError, match="'notify' must be"):
        parse_notify(value)


def test_notify_setting_and_its_former_name(tmp_path: Path) -> None:
    both = load_config(write(tmp_path / "a.toml", 'notify = ["report", "toast"]'))
    assert both.notify == ("report", "toast")
    assert both.open_report is True
    assert load_config(write(tmp_path / "b.toml", "open_report = false")).notify == ()
    assert load_config(write(tmp_path / "c.toml", "open_report = true")).notify == ("report",)
    assert load_config(write(tmp_path / "d.toml", "")).notify == ("report",)
    with pytest.raises(ConfigError, match="former name of 'notify'"):
        load_config(write(tmp_path / "e.toml", 'open_report = true\nnotify = "toast"'))


@pytest.mark.parametrize(
    ("channels", "line"),
    [
        (("report",), 'notify = "report"'),
        (("report", "toast"), 'notify = ["report", "toast"]'),
        ((), 'notify = "none"'),
    ],
)
def test_dump_config_writes_the_notification_channels(
    tmp_path: Path, channels: tuple[str, ...], line: str
) -> None:
    text = dump_config(Config(data_dir=tmp_path, notify=channels))
    assert line in text
    assert parse_config(config_module.tomllib.loads(text)).notify == channels


def test_describe_notify() -> None:
    assert describe_notify(["report"]) == "the report is opened"
    assert describe_notify(["toast", "report"]) == (
        "the report is opened and a desktop notification is shown"
    )
    assert describe_notify([]) == "the report is written but not opened"


# ------------------------------------------------------------------ finding and editing submissions


def test_find_submission(tmp_path: Path) -> None:
    config = Config(
        data_dir=tmp_path,
        submissions=(
            SubmissionConfig(DEMO_UUID, label="Tau paper"),
            SubmissionConfig(OTHER_UUID, label="Epsilon"),
        ),
    )
    link = f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
    assert find_submission(config, link).label == "Tau paper"
    assert find_submission(config, " tau PAPER ").uuid == DEMO_UUID
    assert find_submission(config, "2").uuid == OTHER_UUID
    with pytest.raises(ConfigError, match="No submission matches '3'"):
        find_submission(config, "3")
    with pytest.raises(ConfigError, match="is not"):
        find_submission(config, THIRD_UUID)
    twins = replace(
        config,
        submissions=(
            SubmissionConfig(DEMO_UUID, label="Twin"),
            SubmissionConfig(OTHER_UUID, "twin"),
        ),
    )
    with pytest.raises(ConfigError, match="Several submissions"):
        find_submission(twins, "Twin")


COMMENTED = f"""\
# My settings, written by hand.
data_dir = 'data'  # next to this file

# --- Submissions ---

# The Tau paper, sent to the Journal of Examples.
[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
label = "Tau"   # short name
fields = {{ paper = "Tau" }}

[[submissions]]
  uuid = "{OTHER_UUID}"
  enabled = true  # still under review
  label = "Epsilon"
# a note about the epsilon paper

[[submissions]]
uuid = "{THIRD_UUID}"
[submissions.fields]
paper = "Third"
"""


def test_disable_adds_or_changes_the_enabled_line(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    assert set_submission_enabled(path, DEMO_UUID, False)[1] is True
    assert set_submission_enabled(path, OTHER_UUID, False)[1] is True
    assert set_submission_enabled(path, THIRD_UUID, False)[1] is True

    text = path.read_text(encoding="utf-8")
    assert 'fields = { paper = "Tau" }\nenabled = false\n\n[[submissions]]' in text
    assert "  enabled = false  # still under review\n" in text
    assert f'uuid = "{THIRD_UUID}"\nenabled = false\n[submissions.fields]' in text
    assert text.startswith("# My settings, written by hand.\n")
    assert "# The Tau paper, sent to the Journal of Examples.\n" in text
    config = load_config(path)
    assert [s.enabled for s in config.submissions] == [False, False, False]
    assert dict(config.submissions[2].fields) == {"paper": "Third"}
    assert (tmp_path / "config.toml.bak").is_file()

    assert set_submission_enabled(path, DEMO_UUID, True)[1] is True
    assert set_submission_enabled(path, DEMO_UUID, True)[1] is False  # nothing to change
    assert 'fields = { paper = "Tau" }\nenabled = true\n' in path.read_text(encoding="utf-8")


def test_remove_keeps_the_rest_of_the_file(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    removed = remove_submission(path, OTHER_UUID)
    assert removed.label == "Epsilon"
    text = path.read_text(encoding="utf-8")
    assert "Epsilon" not in text
    assert "still under review" not in text
    assert "# a note about the epsilon paper" in text  # not attached to the table

    remove_submission(path, DEMO_UUID)
    text = path.read_text(encoding="utf-8")
    assert "# The Tau paper, sent to the Journal of Examples." not in text  # attached to the table
    assert "# --- Submissions ---\n\n# a note about the epsilon paper\n\n[[submissions]]" in text
    assert "\n\n\n" not in text
    assert [s.uuid for s in load_config(path).submissions] == [THIRD_UUID]

    remove_submission(path, THIRD_UUID)
    assert load_config(path).submissions == ()
    assert path.read_text(encoding="utf-8").endswith("# a note about the epsilon paper\n")


def test_editing_keeps_windows_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(COMMENTED.replace("\n", "\r\n").encode("utf-8"))
    set_submission_enabled(path, DEMO_UUID, False)
    remove_submission(path, OTHER_UUID)
    edit_submission(path, THIRD_UUID, label="Third", fields={"paper": "3rd", "year": "2026"})
    data = path.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    config = load_config(path)
    assert [s.enabled for s in config.submissions] == [False, True]
    assert config.submissions[1].label == "Third"
    assert dict(config.submissions[1].fields) == {"paper": "3rd", "year": "2026"}


def test_remove_refuses_to_break_the_workbook_names(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        f"""workbook_name = "{{paper}}"

[[submissions]]
uuid = "{DEMO_UUID}"
fields = {{ paper = "Tau" }}

[[submissions]]
uuid = "{OTHER_UUID}"
""",
    )
    before = path.read_bytes()
    with pytest.raises(ConfigError, match=r"would make the configuration invalid.*placeholder"):
        remove_submission(path, DEMO_UUID)
    assert path.read_bytes() == before


def test_unusual_layouts_are_not_edited(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", f'submissions = [{{ uuid = "{DEMO_UUID}" }}]\n')
    before = path.read_bytes()
    with pytest.raises(ConfigError, match="could not be edited safely"):
        set_submission_enabled(path, DEMO_UUID, False)
    with pytest.raises(ConfigError, match="could not be edited safely"):
        remove_submission(path, DEMO_UUID)
    with pytest.raises(ConfigError, match="could not be edited safely"):
        edit_submission(path, DEMO_UUID, label="Demo")
    assert path.read_bytes() == before
    assert not (tmp_path / "config.toml.bak").exists()


@pytest.mark.parametrize(
    "block",
    [
        'fields.paper = "Tau"',  # dotted keys
        'label = """Tau\npaper"""',  # a label written on two lines
    ],
)
def test_unusual_keys_are_not_edited(tmp_path: Path, block: str) -> None:
    path = write(tmp_path / "config.toml", f'[[submissions]]\nuuid = "{DEMO_UUID}"\n{block}\n')
    before = path.read_bytes()
    with pytest.raises(ConfigError, match="could not be edited safely"):
        edit_submission(path, DEMO_UUID, label="Other", fields={"paper": "Other"})
    assert path.read_bytes() == before


def test_edit_changes_adds_and_removes_labels(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    before, after = edit_submission(path, DEMO_UUID, label="  Tau paper ")
    assert (before.label, after.label) == ("Tau", "Tau paper")
    edit_submission(path, THIRD_UUID, label="Third paper")
    edit_submission(path, "epsilon", label="")

    text = path.read_text(encoding="utf-8")
    assert "label = 'Tau paper'   # short name\n" in text
    assert f"uuid = \"{THIRD_UUID}\"\nlabel = 'Third paper'\n[submissions.fields]" in text
    assert "Epsilon" not in text
    assert "  enabled = true  # still under review\n# a note about the epsilon paper" in text
    assert text.startswith("# My settings, written by hand.\n")
    labels = [s.label for s in load_config(path).submissions]
    assert labels == ["Tau paper", "", "Third paper"]
    assert (tmp_path / "config.toml.bak").is_file()


def test_edit_custom_fields_in_every_layout(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    edit_submission(path, DEMO_UUID, fields={"paper": "Tau", "year": "2026"})
    edit_submission(path, OTHER_UUID, fields={"paper": "Epsilon"})
    edit_submission(path, THIRD_UUID, fields={"paper": "Third", "project": "My thesis"})
    text = path.read_text(encoding="utf-8")
    assert "fields = { paper = 'Tau', year = '2026' }\n" in text
    assert "  label = \"Epsilon\"\n  fields = { paper = 'Epsilon' }\n" in text
    assert "[submissions.fields]\npaper = \"Third\"\nproject = 'My thesis'\n" in text
    config = load_config(path)
    assert [dict(s.fields) for s in config.submissions] == [
        {"paper": "Tau", "year": "2026"},
        {"paper": "Epsilon"},
        {"paper": "Third", "project": "My thesis"},
    ]

    edit_submission(path, THIRD_UUID, fields={"project": "Thesis"})
    assert "[submissions.fields]\nproject = 'Thesis'\n" in path.read_text(encoding="utf-8")
    edit_submission(path, THIRD_UUID, fields={})
    edit_submission(path, DEMO_UUID, fields={})
    text = path.read_text(encoding="utf-8")
    assert "[submissions.fields]" not in text
    assert "year" not in text
    assert text.endswith(f'[[submissions]]\nuuid = "{THIRD_UUID}"\n')
    assert [dict(s.fields) for s in load_config(path).submissions] == [{}, {"paper": "Epsilon"}, {}]


def test_edit_without_changes_does_not_write(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)
    before, after = edit_submission(path, DEMO_UUID, label="Tau", fields={"paper": " Tau "})
    assert before == after
    assert path.read_text(encoding="utf-8") == COMMENTED
    assert not (tmp_path / "config.toml.bak").exists()


def test_edit_refuses_invalid_changes(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", 'workbook_name = "{paper}"\n\n' + COMMENTED)
    before = path.read_bytes()
    with pytest.raises(ConfigError, match="built-in placeholder"):
        edit_submission(path, DEMO_UUID, fields={"journal": "x"})
    edit_submission(path, DEMO_UUID, fields={})  # the third submission still has {paper}
    with pytest.raises(ConfigError, match=r"would make the configuration invalid.*placeholder"):
        edit_submission(path, THIRD_UUID, fields={})
    assert [dict(s.fields) for s in load_config(path).submissions][2] == {"paper": "Third"}
    assert path.read_bytes() != before


def test_editing_an_unknown_submission_fails(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    add_submission(path, DEMO_UUID, label="Demo")
    with pytest.raises(ConfigError, match="No submission matches"):
        remove_submission(path, "Nope")
    with pytest.raises(ConfigError, match="is not in"):
        set_submission_enabled(path, THIRD_UUID, False)


# ------------------------------------------------------------------ own settings of a submission


def test_own_settings_replace_the_general_settings_of_the_same_name(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "config.toml",
            f"""
notify_ignore = ["Last review activity"]
ignore_fields = ["Title"]
record_ignore = ["Status code"]

[[submissions]]
uuid = "{DEMO_UUID}"
notify_fields = ["status", "Last review activity"]

[[submissions]]
uuid = "{OTHER_UUID}"
notify_ignore = []
record_fields = "all"
record_ignore = []

[[submissions]]
uuid = "{THIRD_UUID}"
""",
        )
    )
    demo, other, third = config.submissions
    assert dict(demo.overrides) == {"notify_fields": ("Status", "Last review activity")}
    assert config.notified_columns_for(demo) == ("Status",)  # the general ignore still applies
    assert config.recorded_columns_for(demo) == config.recorded_columns
    assert dict(other.overrides) == {
        "notify_ignore": (),
        "record_fields": None,
        "record_ignore": (),
    }
    assert config.notified_columns_for(other) == TRACKED_COLUMNS  # replaces ignore_fields too
    assert config.recorded_columns_for(other) == TRACKED_COLUMNS
    assert third.overrides == {}
    assert config.notified_columns_for(third) == config.notified_columns
    assert config.recorded_columns_for(third) == config.recorded_columns


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("notify_fields = 'Status'", "'notify_fields' of submission #1"),
        (
            "record_ignore = ['Colour']",
            "Unknown column 'Colour' in 'record_ignore' of submission #1",
        ),
        ("record_ignore = 'all'", "'record_ignore' of submission #1"),
        ("ignore_fields = ['Title']", "unknown key"),
    ],
)
def test_invalid_own_settings(tmp_path: Path, text: str, message: str) -> None:
    content = f"[[submissions]]\nuuid = '{DEMO_UUID}'\n{text}\n"
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path / "config.toml", content))


def test_edit_own_settings_in_place(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    edit_submission(path, DEMO_UUID, overrides={"notify_fields": ("Status",), "record_ignore": ()})
    edit_submission(path, THIRD_UUID, overrides={"notify_ignore": ("last review activity",)})
    text = path.read_text(encoding="utf-8")
    assert "fields = { paper = \"Tau\" }\nrecord_ignore = []\nnotify_fields = ['Status']\n" in text
    assert (
        f"uuid = \"{THIRD_UUID}\"\nnotify_ignore = ['Last review activity']\n[submissions.fields]"
    ) in text
    demo, _, third = load_config(path).submissions
    assert dict(demo.overrides) == {"notify_fields": ("Status",), "record_ignore": ()}
    assert dict(third.overrides) == {"notify_ignore": ("Last review activity",)}

    edit_submission(path, DEMO_UUID, overrides={"notify_fields": None})
    text = path.read_text(encoding="utf-8")
    assert 'fields = { paper = "Tau" }\nnotify_fields = "all"\n' in text
    assert "record_ignore" not in text

    edit_submission(path, DEMO_UUID, overrides={})
    edit_submission(path, THIRD_UUID, overrides={})
    assert all(not s.overrides for s in load_config(path).submissions)
    assert "notify_" not in path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown setting"):
        edit_submission(path, DEMO_UUID, overrides={"notify": ("Status",)})
    with pytest.raises(ConfigError, match="Unknown column 'Colour'"):
        edit_submission(path, DEMO_UUID, overrides={"notify_fields": ("Colour",)})
    with pytest.raises(ConfigError, match="list of column names"):
        edit_submission(path, DEMO_UUID, overrides={"notify_ignore": None})


# ------------------------------------------------------------------ e-mail


def test_email_settings(tmp_path: Path) -> None:
    text = """
notify = ["report", "email"]

[email]
smtp_host = " smtp.example.org "
security = "SSL"
username = "me@example.org"
to = "me@example.org, Co Author <co@example.org>"
"""
    config = load_config(write(tmp_path / "config.toml", text))
    assert config.notify == ("report", "email")
    assert config.email == EmailConfig(
        smtp_host="smtp.example.org",
        security="ssl",
        username="me@example.org",
        to=("me@example.org", "Co Author <co@example.org>"),
    )
    assert (config.email.port, config.email.from_address) == (465, "me@example.org")
    assert config.email.missing == ()
    assert describe_notify(config.notify) == (
        "the report is opened and the report is sent by e-mail"
    )
    assert EmailConfig(security="none", smtp_port=2525).port == 2525
    assert EmailConfig().missing == ("smtp_host", "to", "sender")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('notify = "email"', r"includes \"email\", but the \[email\] table lacks smtp_host"),
        ("[email]\npassword = 'x'", "passwords are never read from the configuration file"),
        ("[email]\nsmtp_password = 'x'", "passwords are never read"),
        ("[email]\nserver = 'x'", r"Unknown setting\(s\) in \[email\]"),
        ("[email]\nsmtp_port = 'x'", "must be a port number"),
        ("[email]\nsmtp_port = 70000", "must be a port number"),
        ("[email]\nsecurity = 'tls'", '"starttls", "ssl" or "none"'),
        ("[email]\nto = 3", "must be an address or a list"),
        ("[email]\nto = ['not an address']", r"'not an address' in \[email\]"),
        ("[email]\nsender = 'me'", r"'me' in \[email\]"),
        ("[email]\nsmtp_host = 3", r"'smtp_host' in \[email\]"),
        ("email = 3", "'email'.*must be a table"),
        (
            'notify = "email"\n[email]\nsmtp_host = "h"\nusername = "jdoe"\nto = ["a@b.org"]',
            "lacks sender",
        ),
    ],
)
def test_invalid_email_settings(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path / "config.toml", text))


def test_email_settings_are_written_and_read_back(tmp_path: Path) -> None:
    settings = EmailConfig(
        smtp_host="smtp.example.org",
        smtp_port=2525,
        security="none",
        username="jdoe",
        sender="Me <me@example.org>",
        to=("me@example.org",),
    )
    text = dump_config(Config(data_dir=tmp_path, notify=("email",), email=settings))
    assert "\n[email]\nsmtp_host = 'smtp.example.org'\nsmtp_port = 2525\n" in text
    loaded = parse_config(config_module.tomllib.loads(text))
    assert (loaded.notify, loaded.email) == (("email",), settings)

    empty = dump_config(Config(data_dir=tmp_path))
    assert "\n# [email]\n" in empty
    assert parse_config(config_module.tomllib.loads(empty)).email == EmailConfig()


@pytest.mark.parametrize(
    ("text", "valid"),
    [
        ("me@example.org", True),
        ("Me <me@example.org>", True),
        ("me", False),
        ("me@", False),
        ("@example.org", False),
        ("a@b@c.org", False),
    ],
)
def test_is_email_address(text: str, valid: bool) -> None:
    assert is_email_address(text) is valid
