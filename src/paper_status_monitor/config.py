"""Configuration file handling.

The configuration is a small TOML file. Example::

    data_dir = 'C:/Users/me/Documents/paper-status-monitor'
    open_report = true

    [[submissions]]
    url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
    label = "Demo submission"
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from paper_status_monitor import paths
from paper_status_monitor.client import parse_uuid, tracker_url
from paper_status_monitor.models import TRACKED_COLUMNS

#: Documentation page describing every setting.
DOCS_URL = "https://paper-status-monitor.readthedocs.io/en/latest/configuration.html"

_TOP_LEVEL_KEYS = frozenset(
    {
        "data_dir",
        "open_report",
        "notify_on_errors",
        "ignore_fields",
        "request_timeout",
        "submissions",
    }
)
_SUBMISSION_KEYS = frozenset({"url", "uuid", "label", "enabled"})

_TEMPLATE = """\
# Configuration file for paper-status-monitor.
# Documentation: {docs_url}

# Folder where one Excel workbook per manuscript and the change reports are stored.
data_dir = {data_dir}

# Open the change report with your default text editor when something changes.
open_report = true

# Also write (and open) a report when a submission cannot be checked.
notify_on_errors = true

# Columns whose changes are recorded in the workbook but do not trigger a report.
# Example: ignore_fields = ["Status code"]
ignore_fields = []

# Seconds to wait for each answer from the tracker.
request_timeout = 30

# Add one [[submissions]] block per manuscript: paste the "Track your submission"
# link you received by e-mail (or just the UUID it contains). For example:
#
# [[submissions]]
# url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
# label = "Demo submission"   # optional: short name shown in the reports
# enabled = true              # optional: set to false to pause monitoring
"""


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class SubmissionConfig:
    """One monitored submission.

    Attributes:
        uuid: Tracking UUID taken from the "Track your submission" link.
        label: Optional short name shown in reports and listings.
        enabled: ``False`` pauses monitoring without removing the entry.
    """

    uuid: str
    label: str = ""
    enabled: bool = True

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
        open_report: Open the report with the default application after a run.
        notify_on_errors: Write a report when a submission cannot be checked.
        ignore_fields: Columns whose changes do not trigger a report.
        request_timeout: Seconds to wait for each tracker answer.
        path: File the configuration was loaded from, if any.
    """

    data_dir: Path
    submissions: tuple[SubmissionConfig, ...] = ()
    open_report: bool = True
    notify_on_errors: bool = True
    ignore_fields: tuple[str, ...] = ()
    request_timeout: float = 30.0
    path: Path | None = None

    @property
    def reports_dir(self) -> Path:
        """Folder where change reports are written."""
        return self.data_dir / "reports"

    @property
    def enabled_submissions(self) -> tuple[SubmissionConfig, ...]:
        """Submissions with ``enabled = true``."""
        return tuple(s for s in self.submissions if s.enabled)


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

    return Config(
        data_dir=data_dir,
        submissions=_parse_submissions(data.get("submissions", []), where),
        open_report=_parse_bool(data, "open_report", True, where),
        notify_on_errors=_parse_bool(data, "notify_on_errors", True, where),
        ignore_fields=_parse_ignore_fields(data.get("ignore_fields", []), where),
        request_timeout=float(timeout),
        path=path,
    )


def _parse_bool(data: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}'{where} must be true or false.")
    return value


def _parse_ignore_fields(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'ignore_fields'{where} must be a list of column names.")
    canonical = {label.casefold(): label for label in TRACKED_COLUMNS}
    result = []
    for item in value:
        label = canonical.get(item.strip().casefold())
        if label is None:
            raise ConfigError(
                f"Unknown column {item!r} in 'ignore_fields'{where}. "
                f"Valid columns: {', '.join(TRACKED_COLUMNS)}."
            )
        result.append(label)
    return tuple(result)


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
        submissions.append(SubmissionConfig(uuid=uuid, label=label.strip(), enabled=enabled))
    return tuple(submissions)


def toml_string(value: str) -> str:
    """Quote *value* as a TOML string, preferring literal strings for Windows paths."""
    if "'" not in value and all(ch == "\t" or ord(ch) >= 0x20 for ch in value):
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def render_config(data_dir: Path | str) -> str:
    """Return the text of a new, commented configuration file."""
    return _TEMPLATE.format(docs_url=DOCS_URL, data_dir=toml_string(str(data_dir)))


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


def submission_block(uuid: str, label: str = "") -> str:
    """Return the TOML block that declares one submission."""
    lines = ["[[submissions]]", f"url = {toml_string(tracker_url(uuid))}"]
    if label:
        lines.append(f"label = {toml_string(label)}")
    return "\n".join(lines) + "\n"


def add_submission(path: Path, uuid: str, label: str = "") -> None:
    """Append a submission to the configuration file, preserving its comments.

    Raises:
        ConfigError: If the file is invalid or already contains *uuid*.
    """
    config = load_config(path)
    if any(submission.uuid == uuid for submission in config.submissions):
        raise ConfigError(f"Submission {uuid} is already in {path}")
    text = path.read_text(encoding="utf-8")
    if not text or text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(separator + submission_block(uuid, label))
    load_config(path)
