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
    SubmissionConfig,
    add_submission,
    describe_columns,
    describe_notify,
    dump_config,
    find_submission,
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
        (f"[[submissions]]\nuuid = '{DEMO_UUID}'\nfields = 'TMY'", "'fields' must be a table"),
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
fields = {{ paper = "  TMY   paper ", year = 2026 }}

[[submissions]]
uuid = "{OTHER_UUID}"
""",
        )
    )
    assert config.workbook_name == "{paper} - {journal} - {manuscript_number}"
    assert dict(config.submissions[0].fields) == {"paper": "TMY paper", "year": "2026"}
    assert dict(config.submissions[1].fields) == {}
    assert config.custom_field_names == ("paper", "year")


def test_submission_config_is_hashable_with_fields() -> None:
    submission = SubmissionConfig(DEMO_UUID, fields={"paper": "TMY"})
    assert submission == SubmissionConfig(DEMO_UUID, fields={"paper": "TMY"})
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
    assert parse_field_assignment("paper=TMY") == ("paper", "TMY")
    assert parse_field_assignment(" paper = A  b ") == ("paper", "A b")
    assert parse_field_assignment("note=a=b") == ("note", "a=b")
    with pytest.raises(ConfigError, match="NAME=VALUE"):
        parse_field_assignment("paper")
    with pytest.raises(ConfigError, match="Invalid custom field name"):
        parse_field_assignment("my paper=TMY")


# ------------------------------------------------------------------ writing


def full_config(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path / "My data",
        submissions=(
            SubmissionConfig(DEMO_UUID, label="Demo 'quoted'", fields={"paper": "TMY"}),
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
    add_submission(path, DEMO_UUID, label="Demo", fields={"paper": "TMY"})
    assert dict(load_config(path).submissions[0].fields) == {"paper": "TMY"}
    assert "fields = { paper = 'TMY' }" in path.read_text(encoding="utf-8")


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


@pytest.mark.parametrize("value", ["", "email", ["report", "none"], 3, [1]])
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
            SubmissionConfig(DEMO_UUID, label="TMY paper"),
            SubmissionConfig(OTHER_UUID, label="Comfort"),
        ),
    )
    link = f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
    assert find_submission(config, link).label == "TMY paper"
    assert find_submission(config, " tmy PAPER ").uuid == DEMO_UUID
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

# The TMY paper, sent to Energy.
[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"
label = "TMY"   # short name
fields = {{ paper = "TMY" }}

[[submissions]]
  uuid = "{OTHER_UUID}"
  enabled = true  # still under review
  label = "Comfort"
# a note about the comfort paper

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
    assert 'fields = { paper = "TMY" }\nenabled = false\n\n[[submissions]]' in text
    assert "  enabled = false  # still under review\n" in text
    assert f'uuid = "{THIRD_UUID}"\nenabled = false\n[submissions.fields]' in text
    assert text.startswith("# My settings, written by hand.\n")
    assert "# The TMY paper, sent to Energy.\n" in text
    config = load_config(path)
    assert [s.enabled for s in config.submissions] == [False, False, False]
    assert dict(config.submissions[2].fields) == {"paper": "Third"}
    assert (tmp_path / "config.toml.bak").is_file()

    assert set_submission_enabled(path, DEMO_UUID, True)[1] is True
    assert set_submission_enabled(path, DEMO_UUID, True)[1] is False  # nothing to change
    assert 'fields = { paper = "TMY" }\nenabled = true\n' in path.read_text(encoding="utf-8")


def test_remove_keeps_the_rest_of_the_file(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", COMMENTED)

    removed = remove_submission(path, OTHER_UUID)
    assert removed.label == "Comfort"
    text = path.read_text(encoding="utf-8")
    assert "Comfort" not in text
    assert "still under review" not in text
    assert "# a note about the comfort paper" in text  # not attached to the table

    remove_submission(path, DEMO_UUID)
    text = path.read_text(encoding="utf-8")
    assert "# The TMY paper, sent to Energy." not in text  # attached to the table
    assert "# --- Submissions ---\n\n# a note about the comfort paper\n\n[[submissions]]" in text
    assert "\n\n\n" not in text
    assert [s.uuid for s in load_config(path).submissions] == [THIRD_UUID]

    remove_submission(path, THIRD_UUID)
    assert load_config(path).submissions == ()
    assert path.read_text(encoding="utf-8").endswith("# a note about the comfort paper\n")


def test_editing_keeps_windows_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(COMMENTED.replace("\n", "\r\n").encode("utf-8"))
    set_submission_enabled(path, DEMO_UUID, False)
    remove_submission(path, OTHER_UUID)
    data = path.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    assert [s.enabled for s in load_config(path).submissions] == [False, True]


def test_remove_refuses_to_break_the_workbook_names(tmp_path: Path) -> None:
    path = write(
        tmp_path / "config.toml",
        f"""workbook_name = "{{paper}}"

[[submissions]]
uuid = "{DEMO_UUID}"
fields = {{ paper = "TMY" }}

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
    assert path.read_bytes() == before
    assert not (tmp_path / "config.toml.bak").exists()


def test_editing_an_unknown_submission_fails(tmp_path: Path) -> None:
    path = write_config(tmp_path / "config.toml", tmp_path / "data")
    add_submission(path, DEMO_UUID, label="Demo")
    with pytest.raises(ConfigError, match="No submission matches"):
        remove_submission(path, "Nope")
    with pytest.raises(ConfigError, match="is not in"):
        set_submission_enabled(path, THIRD_UUID, False)
