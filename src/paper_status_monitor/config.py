"""Configuration file handling.

The configuration is a small TOML file. Example::

    data_dir = 'C:/Users/me/Documents/paper-status-monitor'
    workbook_name = "{paper} - {journal} - {manuscript_number}"
    notify_ignore = ["Last review activity"]
    notify = ["report", "toast"]

    [[submissions]]
    url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
    label = "Demo submission"
    fields = { paper = "Demo" }

Which changes are *recorded* (add a row to the workbook) and which are *notified*
(written to the report) are chosen independently with ``record_fields`` /
``record_ignore`` and ``notify_fields`` / ``notify_ignore``; ``notify`` chooses how
you are told about the news (open the report, a desktop notification, or nothing).

:func:`add_submission`, :func:`remove_submission` and :func:`set_submission_enabled`
edit the file in place and keep its comments; :func:`save_config` rewrites it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from paper_status_monitor import naming, paths
from paper_status_monitor.client import DEMO_UUID, parse_uuid, tracker_url
from paper_status_monitor.models import TRACKED_COLUMNS, clean_text

#: Documentation page describing every setting.
DOCS_URL = "https://paper-status-monitor.readthedocs.io/en/latest/configuration.html"

#: Template used when ``workbook_name`` is not set (the names used by version 0.1).
DEFAULT_WORKBOOK_NAME = naming.DEFAULT_WORKBOOK_NAME

#: Ways of telling the user about news (values of the ``notify`` setting):
#: ``"report"`` opens the text report, ``"toast"`` shows a desktop notification.
NOTIFY_CHANNELS: tuple[str, ...] = ("report", "toast")

_TOP_LEVEL_KEYS = frozenset(
    {
        "data_dir",
        "workbook_name",
        "record_fields",
        "record_ignore",
        "notify_fields",
        "notify_ignore",
        "ignore_fields",
        "notify",
        "open_report",
        "notify_on_errors",
        "request_timeout",
        "submissions",
    }
)
_SUBMISSION_KEYS = frozenset({"url", "uuid", "label", "enabled", "fields"})
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class SubmissionConfig:
    """One monitored submission.

    Attributes:
        uuid: Tracking UUID taken from the "Track your submission" link.
        label: Optional short name shown in reports and listings.
        enabled: ``False`` pauses monitoring without removing the entry.
        fields: Custom fields (name to text), e.g. ``{"paper": "TMY"}``. They can be
            used as placeholders in ``workbook_name`` and are written to extra
            columns of the workbook.
    """

    uuid: str
    label: str = ""
    enabled: bool = True
    fields: Mapping[str, str] = field(default_factory=dict, hash=False)

    @property
    def tracker_url(self) -> str:
        """Link to the official tracking page."""
        return tracker_url(self.uuid)

    @property
    def display_name(self) -> str:
        """The label if there is one, otherwise the UUID."""
        return self.label or self.uuid


@dataclass(frozen=True)
class Config:
    """Validated configuration.

    Attributes:
        data_dir: Folder for the workbooks; reports go to its ``reports`` subfolder.
        submissions: Monitored submissions, in file order.
        notify_on_errors: Write a report when a submission cannot be checked.
        ignore_fields: Former name of :attr:`notify_ignore` (both are honoured).
        request_timeout: Seconds to wait for each tracker answer.
        path: File the configuration was loaded from, if any.
        workbook_name: Template of the workbook names (see :mod:`~paper_status_monitor.naming`).
        notify_fields: Columns whose changes are reported (``None`` = all columns).
        notify_ignore: Columns whose changes are never reported.
        record_fields: Columns whose changes add a row (``None`` = all columns).
        record_ignore: Columns whose changes alone never add a row.
        notify: How the user is told about news, a subset of :data:`NOTIFY_CHANNELS`:
            ``"report"`` opens the report, ``"toast"`` shows a desktop notification.
            The report is written in every case.
    """

    data_dir: Path
    submissions: tuple[SubmissionConfig, ...] = ()
    notify_on_errors: bool = True
    ignore_fields: tuple[str, ...] = ()
    request_timeout: float = 30.0
    path: Path | None = None
    workbook_name: str = DEFAULT_WORKBOOK_NAME
    notify_fields: tuple[str, ...] | None = None
    notify_ignore: tuple[str, ...] = ()
    record_fields: tuple[str, ...] | None = None
    record_ignore: tuple[str, ...] = ()
    notify: tuple[str, ...] = ("report",)

    @property
    def open_report(self) -> bool:
        """``True`` if the report is opened when there is news (``"report"`` in :attr:`notify`)."""
        return "report" in self.notify

    @property
    def reports_dir(self) -> Path:
        """Folder where change reports are written."""
        return self.data_dir / "reports"

    @property
    def enabled_submissions(self) -> tuple[SubmissionConfig, ...]:
        """Submissions with ``enabled = true``."""
        return tuple(s for s in self.submissions if s.enabled)

    @property
    def notified_columns(self) -> tuple[str, ...]:
        """Columns whose changes are reported, in workbook order."""
        return select_columns(self.notify_fields, (*self.notify_ignore, *self.ignore_fields))

    @property
    def recorded_columns(self) -> tuple[str, ...]:
        """Columns whose changes add a row to the workbook, in workbook order."""
        return select_columns(self.record_fields, self.record_ignore)

    @property
    def custom_field_names(self) -> tuple[str, ...]:
        """Names of the custom fields used by the submissions, sorted."""
        return tuple(sorted({name for s in self.submissions for name in s.fields}))


def select_columns(fields: Iterable[str] | None, ignore: Iterable[str] = ()) -> tuple[str, ...]:
    """Return the tracked columns chosen by a ``*_fields`` / ``*_ignore`` pair.

    Args:
        fields: Chosen columns, or ``None`` for all of them.
        ignore: Columns removed from the choice.
    """
    chosen = None if fields is None else {name.casefold() for name in fields}
    ignored = {name.casefold() for name in ignore}
    return tuple(
        label
        for label in TRACKED_COLUMNS
        if (chosen is None or label.casefold() in chosen) and label.casefold() not in ignored
    )


def split_columns(selected: Iterable[str]) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    """Express a choice of columns as a ``(fields, ignore)`` pair, the inverse of
    :func:`select_columns`.

    When most columns are chosen, the result is "all except ..." (so columns added
    by future versions are chosen too); otherwise it is "only ...".
    """
    chosen = {name.casefold() for name in selected}
    inside = tuple(label for label in TRACKED_COLUMNS if label.casefold() in chosen)
    outside = tuple(label for label in TRACKED_COLUMNS if label.casefold() not in chosen)
    if not outside:
        return None, ()
    if len(inside) > len(outside):
        return None, outside
    return inside, ()


def describe_columns(selected: Iterable[str]) -> str:
    """Describe a choice of columns, e.g. ``"all columns except Status code"``."""
    fields, ignore = split_columns(selected)
    if fields is None:
        return "all columns except " + ", ".join(ignore) if ignore else "all columns"
    return "only " + ", ".join(fields) if fields else "no columns"


def canonical_columns(
    names: Iterable[str], *, setting: str = "columns", where: str = ""
) -> tuple[str, ...]:
    """Return the canonical spelling of tracked column names (case-insensitive).

    Raises:
        ConfigError: If a name is not a tracked column.
    """
    canonical = {label.casefold(): label for label in TRACKED_COLUMNS}
    result: list[str] = []
    for item in names:
        label = canonical.get(item.strip().casefold())
        if label is None:
            raise ConfigError(
                f"Unknown column {item!r} in '{setting}'{where}. "
                f"Valid columns: {', '.join(TRACKED_COLUMNS)}."
            )
        if label not in result:
            result.append(label)
    return tuple(result)


def parse_columns_option(
    text: str, *, option: str, allow_all: bool = True
) -> tuple[str, ...] | None:
    """Parse a comma-separated list of columns given on the command line.

    ``"all"`` gives ``None`` (every column) when *allow_all* is true, and ``"none"``
    or an empty text gives an empty tuple.

    Raises:
        ConfigError: If a column is unknown.
    """
    items = [item.strip() for item in text.split(",") if item.strip()]
    keyword = items[0].casefold() if len(items) == 1 else ""
    if keyword == "all":
        if allow_all:
            return None
        raise ConfigError(f"{option} expects a comma-separated list of columns, or 'none'.")
    if keyword == "none" or not items:
        return ()
    return canonical_columns(items, setting=option)


def parse_notify(value: Any, *, setting: str = "notify", where: str = "") -> tuple[str, ...]:
    """Parse the ways of telling the user about news.

    Accepted values are a channel name (``"report"`` or ``"toast"``), a
    comma-separated text or a list of names, and ``"none"`` (or an empty list) for
    nothing. Names are case-insensitive.

    Returns:
        The channels, in the order of :data:`NOTIFY_CHANNELS`.

    Raises:
        ConfigError: If the value is not valid.
    """
    problem = (
        f'\'{setting}\'{where} must be "report" (open the report), "toast" (desktop '
        'notification), "none", or a list such as ["report", "toast"].'
    )
    if isinstance(value, str):
        items = [item.strip().casefold() for item in value.split(",") if item.strip()]
        if not items:
            raise ConfigError(problem)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = [item.strip().casefold() for item in value]
    else:
        raise ConfigError(problem)
    if items == ["none"]:
        return ()
    unknown = [item for item in items if item not in NOTIFY_CHANNELS]
    if unknown:
        raise ConfigError(f"Unknown value {unknown[0]!r}: {problem}")
    return tuple(channel for channel in NOTIFY_CHANNELS if channel in items)


def describe_notify(channels: Iterable[str]) -> str:
    """Describe how the user is told about news, e.g. ``"the report is opened"``."""
    chosen = set(channels)
    parts = []
    if "report" in chosen:
        parts.append("the report is opened")
    if "toast" in chosen:
        parts.append("a desktop notification is shown")
    return " and ".join(parts) if parts else "the report is written but not opened"


def find_submission(config: Config, text: str) -> SubmissionConfig:
    """Return the submission named by *text*.

    *text* may be a tracking link, a UUID, a label (case-insensitive) or the number
    shown by ``paper-status-monitor list``.

    Raises:
        ConfigError: If no submission, or more than one, matches.
    """
    value = text.strip()
    where = f" in {config.path}" if config.path else ""
    try:
        uuid: str | None = parse_uuid(value)
    except ValueError:
        uuid = None
    if uuid is not None:
        for submission in config.submissions:
            if submission.uuid == uuid:
                return submission
        raise ConfigError(f"Submission {uuid} is not{where}.")
    matches = [s for s in config.submissions if s.label and s.label.casefold() == value.casefold()]
    if len(matches) > 1:
        raise ConfigError(
            f"Several submissions are labelled {value!r}; use the tracking link or the UUID."
        )
    if matches:
        return matches[0]
    if value.isdigit() and 1 <= int(value) <= len(config.submissions):
        return config.submissions[int(value) - 1]
    raise ConfigError(
        f"No submission matches {value!r}{where}. Use the tracking link, the UUID, the label "
        "or the number shown by: paper-status-monitor list"
    )


def parse_field_assignment(text: str) -> tuple[str, str]:
    """Parse a ``NAME=VALUE`` custom field given on the command line.

    Raises:
        ConfigError: If the text has no ``=`` or the name is not valid.
    """
    name, separator, value = text.partition("=")
    if not separator:
        raise ConfigError(f"Invalid field {text!r}: write NAME=VALUE, for example paper=TMY.")
    try:
        naming.check_custom_field_name(name.strip())
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return name.strip(), clean_text(value)


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the configuration file.

    Args:
        path: File to read. Defaults to :func:`paper_status_monitor.paths.default_config_path`.

    Raises:
        ConfigError: If the file does not exist or contains invalid settings.
    """
    config_path = Path(path).expanduser() if path else paths.default_config_path()
    if not config_path.is_file():
        raise ConfigError(
            f"Configuration file not found: {config_path}\n"
            "Create one with: paper-status-monitor init"
        )
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc
    return parse_config(data, base_dir=config_path.parent, path=config_path)


def parse_config(
    data: Mapping[str, Any], *, base_dir: Path | None = None, path: Path | None = None
) -> Config:
    """Validate an already parsed configuration mapping.

    Args:
        data: Parsed TOML document.
        base_dir: Directory used to resolve a relative ``data_dir``.
        path: Origin of the data, stored in :attr:`Config.path`.

    Raises:
        ConfigError: If a setting is unknown or has an invalid value.
    """
    where = f" in {path}" if path else ""
    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(
            f"Unknown setting(s){where}: {', '.join(unknown)}. "
            f"Valid settings: {', '.join(sorted(_TOP_LEVEL_KEYS))}. See {DOCS_URL}"
        )

    raw_dir = data.get("data_dir")
    if raw_dir is None:
        data_dir = paths.default_data_dir()
    elif isinstance(raw_dir, str) and raw_dir.strip():
        data_dir = Path(os.path.expandvars(raw_dir.strip())).expanduser()
        if not data_dir.is_absolute() and base_dir is not None:
            data_dir = base_dir / data_dir
    else:
        raise ConfigError(f"'data_dir'{where} must be a non-empty string.")

    timeout = data.get("request_timeout", 30.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError(f"'request_timeout'{where} must be a positive number of seconds.")

    submissions = _parse_submissions(data.get("submissions", []), where)
    template = data.get("workbook_name", DEFAULT_WORKBOOK_NAME)
    if not isinstance(template, str) or not template.strip():
        raise ConfigError(
            f"'workbook_name'{where} must be a non-empty text such as {DEFAULT_WORKBOOK_NAME!r}."
        )
    custom_fields = {name for submission in submissions for name in submission.fields}
    try:
        naming.validate_template(template, custom_fields)
    except ValueError as exc:
        raise ConfigError(f"'workbook_name'{where}: {exc}") from exc

    return Config(
        data_dir=data_dir,
        submissions=submissions,
        notify_on_errors=_parse_bool(data, "notify_on_errors", True, where),
        ignore_fields=_parse_column_list(data, "ignore_fields", where),
        request_timeout=float(timeout),
        path=path,
        workbook_name=template,
        notify_fields=_parse_column_choice(data, "notify_fields", where),
        notify_ignore=_parse_column_list(data, "notify_ignore", where),
        record_fields=_parse_column_choice(data, "record_fields", where),
        record_ignore=_parse_column_list(data, "record_ignore", where),
        notify=_parse_notify_setting(data, where),
    )


def _parse_notify_setting(data: Mapping[str, Any], where: str) -> tuple[str, ...]:
    """Read ``notify``, or its former form ``open_report = true/false``."""
    if "notify" not in data:
        return ("report",) if _parse_bool(data, "open_report", True, where) else ()
    if "open_report" in data:
        raise ConfigError(
            f"'open_report'{where} is the former name of 'notify'; remove it "
            '(open_report = true is now notify = "report", and false is notify = "none").'
        )
    return parse_notify(data["notify"], where=where)


def _parse_bool(data: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}'{where} must be true or false.")
    return value


def _parse_column_list(data: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{key}'{where} must be a list of column names.")
    return canonical_columns(value, setting=key, where=where)


def _parse_column_choice(data: Mapping[str, Any], key: str, where: str) -> tuple[str, ...] | None:
    value = data.get(key, "all")
    if isinstance(value, str) and value.strip().casefold() == "all":
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{key}'{where} must be \"all\" or a list of column names.")
    return canonical_columns(value, setting=key, where=where)


def _parse_fields(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name}: 'fields' must be a table, e.g. fields = {{ paper = \"TMY\" }}.")
    result: dict[str, str] = {}
    for key, item in value.items():
        try:
            naming.check_custom_field_name(key)
        except ValueError as exc:
            raise ConfigError(f"{name}: {exc}") from exc
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise ConfigError(
                f'{name}: the custom field {key!r} must be a text, e.g. {key} = "TMY".'
            )
        result[key] = clean_text(item)
    return result


def _parse_submissions(value: Any, where: str) -> tuple[SubmissionConfig, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"'submissions'{where} must be a list of [[submissions]] tables.")
    submissions: list[SubmissionConfig] = []
    seen: set[str] = set()
    for index, entry in enumerate(value, start=1):
        name = f"Submission #{index}{where}"
        if not isinstance(entry, Mapping):
            raise ConfigError(f"{name} must be a [[submissions]] table.")
        unknown = sorted(set(entry) - _SUBMISSION_KEYS)
        if unknown:
            raise ConfigError(
                f"{name} has unknown key(s): {', '.join(unknown)}. "
                f"Valid keys: {', '.join(sorted(_SUBMISSION_KEYS))}."
            )
        source = entry.get("url", entry.get("uuid"))
        if not isinstance(source, str) or not source.strip():
            raise ConfigError(f"{name} needs a 'url' (tracking link) or a 'uuid'.")
        try:
            uuid = parse_uuid(source)
        except ValueError as exc:
            raise ConfigError(f"{name}: {exc}") from exc
        if uuid in seen:
            raise ConfigError(f"{name} duplicates UUID {uuid}.")
        seen.add(uuid)
        label = entry.get("label", "")
        if not isinstance(label, str):
            raise ConfigError(f"{name}: 'label' must be a string.")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{name}: 'enabled' must be true or false.")
        fields = _parse_fields(entry.get("fields", {}), name)
        submissions.append(
            SubmissionConfig(uuid=uuid, label=label.strip(), enabled=enabled, fields=fields)
        )
    return tuple(submissions)


# --------------------------------------------------------------------------- writing


def toml_string(value: str) -> str:
    """Quote *value* as a TOML string, preferring literal strings for Windows paths."""
    if "'" not in value and all(ch == "\t" or ord(ch) >= 0x20 for ch in value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def toml_key(name: str) -> str:
    """Return *name* as a TOML key (bare when possible, quoted otherwise)."""
    return name if _BARE_KEY.match(name) else json.dumps(name, ensure_ascii=False)


def _toml_list(items: Iterable[str]) -> str:
    return "[" + ", ".join(toml_string(item) for item in items) + "]"


def _toml_choice(fields: tuple[str, ...] | None) -> str:
    return '"all"' if fields is None else _toml_list(fields)


def _toml_table(mapping: Mapping[str, str]) -> str:
    items = ", ".join(f"{toml_key(key)} = {toml_string(value)}" for key, value in mapping.items())
    return "{ " + items + " }" if items else "{}"


def _toml_number(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_notify(channels: tuple[str, ...]) -> str:
    if not channels:
        return '"none"'
    if len(channels) == 1:
        return f'"{channels[0]}"'
    return "[" + ", ".join(f'"{channel}"' for channel in channels) + "]"


def dump_config(config: Config) -> str:
    """Return the text of a commented configuration file holding *config*.

    The former ``ignore_fields`` setting is written as ``notify_ignore``, and the
    former ``open_report`` as ``notify``.
    """
    notify_ignore = tuple(dict.fromkeys((*config.notify_ignore, *config.ignore_fields)))
    lines = [
        "# Configuration file for paper-status-monitor.",
        f"# Documentation: {DOCS_URL}",
        "",
        "# Folder where the Excel workbooks and the change reports are stored.",
        f"data_dir = {toml_string(str(config.data_dir))}",
        "",
        "# Name of the workbooks. Placeholders: {manuscript_number}, {journal},",
        "# {journal_acronym}, {title}, {first_author}, {corresponding_author},",
        "# {date_of_submission} (YYYY-MM-DD), {submission_year}, {label} and the custom",
        "# fields of the submissions, e.g. {paper}. Submissions whose names coincide",
        '# share a workbook: "{paper}" keeps all the submissions of a paper in one file.',
        f"workbook_name = {toml_string(config.workbook_name)}",
        "",
        '# Changes that add a row to the workbook: "all" or a list of columns such as',
        '# ["Status"], and columns whose changes alone never add a row.',
        f"record_fields = {_toml_choice(config.record_fields)}",
        f"record_ignore = {_toml_list(config.record_ignore)}",
        "",
        '# Changes that are reported: "all" or a list of columns such as ["Status"], and',
        '# columns whose changes are never reported, e.g. ["Last review activity"].',
        f"notify_fields = {_toml_choice(config.notify_fields)}",
        f"notify_ignore = {_toml_list(notify_ignore)}",
        "",
        "# How you are told about news (changes, new submissions and failed checks). A",
        "# report is always written to the 'reports' subfolder of data_dir; \"report\" also",
        '# opens it with your text editor and "toast" shows a desktop notification. Use a',
        '# list for both, e.g. ["report", "toast"], or "none" to only write the report.',
        f"notify = {_toml_notify(config.notify)}",
        "",
        "# Also report (and notify) the submissions that cannot be checked.",
        f"notify_on_errors = {_toml_bool(config.notify_on_errors)}",
        "",
        "# Seconds to wait for each answer from the tracker.",
        f"request_timeout = {_toml_number(config.request_timeout)}",
        "",
        '# Add one [[submissions]] block per manuscript: paste the "Track your submission"',
        "# link you received by e-mail (or just the UUID it contains). For example:",
        "#",
        "# [[submissions]]",
        f'# url = "{tracker_url(DEMO_UUID)}"',
        '# label = "Demo submission"    # optional: short name shown in the reports',
        '# fields = { paper = "Demo" }  # optional: custom fields (names and columns)',
        "# enabled = true               # optional: set to false to pause monitoring",
    ]
    for submission in config.submissions:
        block = submission_block(
            submission.uuid, submission.label, fields=submission.fields, enabled=submission.enabled
        )
        lines += ["", block.rstrip("\n")]
    return "\n".join(lines) + "\n"


def render_config(data_dir: Path | str) -> str:
    """Return the text of a new, commented configuration file."""
    return dump_config(Config(data_dir=Path(data_dir)))


def write_config(path: Path, data_dir: Path | str, *, overwrite: bool = False) -> Path:
    """Create a configuration file at *path*.

    Raises:
        ConfigError: If the file exists and *overwrite* is ``False``.
    """
    if path.exists() and not overwrite:
        raise ConfigError(f"A configuration file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_config(data_dir))
    return path


def save_config(config: Config, path: Path | None = None, *, backup: bool = True) -> Path:
    """Write *config* to a file, replacing it atomically.

    The file is rewritten from scratch (with explanatory comments), so comments
    added by hand are not kept; the previous file is copied to ``<name>.bak``.

    Args:
        config: Configuration to write.
        path: Destination; defaults to :attr:`Config.path`, then to the default location.
        backup: Keep a copy of the previous file.

    Raises:
        ConfigError: If the configuration is not valid (nothing is written).
    """
    target = path or config.path or paths.default_config_path()
    text = dump_config(config)
    parse_config(tomllib.loads(text), base_dir=target.parent, path=target)
    _write_atomic(target, text, backup=backup)
    return target


def _write_atomic(target: Path, text: str, *, backup: bool) -> None:
    """Replace *target* with *text* (UTF-8), keeping the previous file as ``<name>.bak``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.is_file():
        shutil.copy2(target, target.with_name(f"{target.name}.bak"))
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def submission_block(
    uuid: str,
    label: str = "",
    *,
    fields: Mapping[str, str] | None = None,
    enabled: bool = True,
) -> str:
    """Return the TOML block that declares one submission."""
    lines = ["[[submissions]]", f"url = {toml_string(tracker_url(uuid))}"]
    if label:
        lines.append(f"label = {toml_string(label)}")
    if fields:
        lines.append(f"fields = {_toml_table(fields)}")
    if not enabled:
        lines.append("enabled = false")
    return "\n".join(lines) + "\n"


def add_submission(
    path: Path, uuid: str, label: str = "", fields: Mapping[str, str] | None = None
) -> None:
    """Append a submission to the configuration file, preserving its comments.

    Raises:
        ConfigError: If the file is invalid, already contains *uuid* or the result
            would be invalid (the file is then left unchanged).
    """
    config = load_config(path)
    if any(submission.uuid == uuid for submission in config.submissions):
        raise ConfigError(f"Submission {uuid} is already in {path}")
    _parse_fields(dict(fields or {}), f"Submission {uuid}")
    original = path.read_bytes()
    text = original.decode("utf-8").replace("\r\n", "\n")
    if not text or text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(separator + submission_block(uuid, label, fields=fields))
    try:
        load_config(path)
    except ConfigError:
        path.write_bytes(original)
        raise


# --------------------------------------------------------------------------- editing in place

_TABLE_HEADER = re.compile(r"\s*(\[\[?)([^\[\]#]+)\]\]?\s*(?:#.*)?")
_ENABLED_LINE = re.compile(r"(\s*)enabled(\s*)=(\s*)(?:true|false)(\s*(?:#.*)?)")
_CANNOT_EDIT = (
    "The configuration file could not be edited safely, because its layout is unusual. "
    "Edit it in a text editor, or use: paper-status-monitor gui"
)


@dataclass(frozen=True)
class _Block:
    """Lines of one ``[[submissions]]`` table (indices into the lines of the file).

    Attributes:
        lead: First comment line written right above the header (or the header).
        header: The ``[[submissions]]`` line.
        end: Line after the last key of the table (blank lines and comments that
            follow belong to the gap before the next table).
    """

    lead: int
    header: int
    end: int


def remove_submission(path: Path, uuid: str) -> SubmissionConfig:
    """Remove a submission from the configuration file, keeping the rest of the text.

    The comment lines written right above its ``[[submissions]]`` line go with it.
    The previous file is kept as ``<name>.bak``; workbooks are never touched.

    Args:
        path: Configuration file.
        uuid: Tracking UUID of the submission (see :func:`find_submission`).

    Returns:
        The submission removed.

    Raises:
        ConfigError: If the submission is not in the file, if the configuration would
            become invalid (for example, ``workbook_name`` uses a custom field that only
            this submission has) or if the file is too unusual to be edited safely.
            The file is then left unchanged.
    """
    config = load_config(path)
    submission = find_submission(config, uuid)
    remaining = tuple(s for s in config.submissions if s is not submission)

    def edit(lines: list[str], block: _Block) -> list[str]:
        return _delete_lines(lines, block.lead, block.end)

    _edit_submission(config, submission, edit, replace(config, submissions=remaining))
    return submission


def set_submission_enabled(path: Path, uuid: str, enabled: bool) -> tuple[SubmissionConfig, bool]:
    """Pause (``enabled = false``) or resume a submission, keeping the rest of the text.

    The ``enabled`` line of the submission is changed, or added after its last key.

    Args:
        path: Configuration file.
        uuid: Tracking UUID of the submission (see :func:`find_submission`).
        enabled: ``False`` to pause monitoring, ``True`` to resume it.

    Returns:
        The submission as it was, and ``True`` if the file was changed (``False`` if
        the submission was already in that state).

    Raises:
        ConfigError: If the submission is not in the file or the file is too unusual
            to be edited safely (it is then left unchanged).
    """
    config = load_config(path)
    submission = find_submission(config, uuid)
    if submission.enabled == enabled:
        return submission, False
    changed = replace(submission, enabled=enabled)
    expected = replace(
        config,
        submissions=tuple(changed if s is submission else s for s in config.submissions),
    )

    def edit(lines: list[str], block: _Block) -> list[str]:
        return _set_enabled_line(lines, block, enabled)

    _edit_submission(config, submission, edit, expected)
    return submission, True


def _edit_submission(
    config: Config,
    submission: SubmissionConfig,
    edit: Callable[[list[str], _Block], list[str]],
    expected: Config,
) -> None:
    """Apply *edit* to the block of *submission* in the file *config* was loaded from,
    and write the file only if the result is exactly *expected*."""
    path = config.path
    if path is None:  # pragma: no cover - load_config always sets it
        raise ConfigError(_CANNOT_EDIT)
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and not lines[-1]:
        lines.pop()
    blocks = _submission_blocks(lines)
    if len(blocks) != len(config.submissions):
        raise ConfigError(_CANNOT_EDIT)
    block = blocks[config.submissions.index(submission)]
    new_text = newline.join(edit(list(lines), block)) + newline
    try:
        data = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(_CANNOT_EDIT) from exc
    try:
        result = parse_config(data, base_dir=path.parent, path=path)
    except ConfigError as exc:
        raise ConfigError(
            f"The change would make the configuration invalid: {exc} "
            "Adjust the other settings first."
        ) from exc
    if result != expected:
        raise ConfigError(_CANNOT_EDIT)
    _write_atomic(path, new_text, backup=True)


def _table_header(line: str) -> tuple[bool, str] | None:
    """Return ``(is_array_of_tables, name)`` if *line* is a table header."""
    match = _TABLE_HEADER.fullmatch(line)
    if match is None:
        return None
    brackets, name = match.groups()
    return brackets == "[[", "".join(name.split())


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _is_blank_or_comment(line: str) -> bool:
    return not line.strip() or _is_comment(line)


def _submission_blocks(lines: list[str]) -> list[_Block]:
    """Find the ``[[submissions]]`` tables of a configuration file, in order.

    A table goes on until the next header that is not one of its sub-tables
    (``[submissions.fields]``).
    """
    headers = [
        (index, *header)
        for index, line in enumerate(lines)
        if (header := _table_header(line)) is not None
    ]
    blocks = []
    for position, (index, is_array, name) in enumerate(headers):
        if not (is_array and name == "submissions"):
            continue
        limit = next(
            (
                other
                for other, other_array, other_name in headers[position + 1 :]
                if other_array or not other_name.startswith("submissions.")
            ),
            len(lines),
        )
        end = limit
        while end > index + 1 and _is_blank_or_comment(lines[end - 1]):
            end -= 1
        lead = index
        while lead > 0 and _is_comment(lines[lead - 1]):
            lead -= 1
        blocks.append(_Block(lead, index, end))
    return blocks


def _delete_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Delete ``lines[start:end]`` without leaving two blank lines in a row."""
    result = lines[:start] + lines[end:]
    while start < len(result) and not result[start].strip():
        if start > 0 and result[start - 1].strip():
            break
        del result[start]
    while result and not result[-1].strip():
        result.pop()
    return result


def _set_enabled_line(lines: list[str], block: _Block, enabled: bool) -> list[str]:
    """Write ``enabled = <value>`` in the main table of a ``[[submissions]]`` block."""
    main_end = next(
        (i for i in range(block.header + 1, block.end) if _table_header(lines[i]) is not None),
        block.end,
    )
    for index in range(block.header + 1, main_end):
        match = _ENABLED_LINE.fullmatch(lines[index])
        if match is not None:
            indent, before, after, tail = match.groups()
            lines[index] = f"{indent}enabled{before}={after}{_toml_bool(enabled)}{tail}"
            return lines
    if enabled:
        return lines  # true is the default: nothing to write
    position = main_end
    while position > block.header + 1 and _is_blank_or_comment(lines[position - 1]):
        position -= 1
    keys = [line for line in lines[block.header + 1 : position] if not _is_blank_or_comment(line)]
    indent = keys[0][: len(keys[0]) - len(keys[0].lstrip())] if keys else ""
    lines.insert(position, f"{indent}enabled = false")
    return lines
