from __future__ import annotations

from pathlib import Path

import pytest

from paper_status_monitor import config as config_module
from paper_status_monitor import paths
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import (
    ConfigError,
    add_submission,
    load_config,
    parse_config,
    render_config,
    toml_string,
    write_config,
)

OTHER_UUID = "11111111-2222-3333-4444-555555555555"


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
