"""Default per-user locations for the configuration file, logs and run state.

Only the standard library is used so that the package keeps a small footprint.

* **Windows** - configuration in ``%APPDATA%/paper-status-monitor``; logs, run state
  and lock file in ``%LOCALAPPDATA%/paper-status-monitor``.
* **macOS** - everything in ``~/Library/Application Support/paper-status-monitor``.
* **Linux** - configuration in ``$XDG_CONFIG_HOME/paper-status-monitor`` (default
  ``~/.config``); logs and state in ``$XDG_STATE_HOME/paper-status-monitor`` (default
  ``~/.local/state``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "paper-status-monitor"

#: Environment variable that overrides the location of the configuration file.
CONFIG_ENV_VAR = "PAPER_STATUS_MONITOR_CONFIG"


def user_config_dir() -> Path:
    """Return the per-user directory that holds ``config.toml``."""
    if sys.platform == "win32":
        return _windows_dir("APPDATA", "AppData/Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return _xdg_dir("XDG_CONFIG_HOME", ".config")


def user_state_dir() -> Path:
    """Return the per-user, machine-local directory for logs and run state."""
    if sys.platform == "win32":
        return _windows_dir("LOCALAPPDATA", "AppData/Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return _xdg_dir("XDG_STATE_HOME", ".local/state")


def default_config_path() -> Path:
    """Return the configuration file path, honouring :data:`CONFIG_ENV_VAR`."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return user_config_dir() / "config.toml"


def default_data_dir() -> Path:
    """Return the default folder for the Excel workbooks and change reports."""
    return Path.home() / "Documents" / APP_NAME


def log_file_path() -> Path:
    """Return the path of the rotating log file."""
    return user_state_dir() / "logs" / f"{APP_NAME}.log"


def state_file_path() -> Path:
    """Return the path of the JSON file that stores the result of the last run."""
    return user_state_dir() / "state.json"


def lock_file_path() -> Path:
    """Return the path of the lock file that prevents concurrent runs."""
    return user_state_dir() / "run.lock"


def fallback_reports_dir() -> Path:
    """Return the folder used for reports when the data folder is not available."""
    return user_state_dir() / "reports"


def _windows_dir(env_var: str, fallback: str) -> Path:
    base = os.environ.get(env_var)
    root = Path(base) if base else Path.home() / fallback
    return root / APP_NAME


def _xdg_dir(env_var: str, fallback: str) -> Path:
    base = os.environ.get(env_var)
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / fallback
    return root / APP_NAME
