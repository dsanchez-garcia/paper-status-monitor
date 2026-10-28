"""Guard rails that keep personal data out of the public repository.

The tool is used with private tracking links. These tests fail if a tracked file
contains a tracking UUID other than the well-known fake ones, or if data files
(workbooks, reports, configuration) are committed by mistake.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: UUIDs that are allowed to appear in the repository (all fictional).
ALLOWED_UUIDS = {
    "00000000-0000-0000-0000-000000000000",  # public demo submission served by the tracker
    "11111111-2222-3333-4444-555555555555",
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
}

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
FORBIDDEN_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".lnk", ".bat"}
FORBIDDEN_NAMES = {
    "config.toml",
    "config.toml.bak",
    "state.json",
    "run.lock",
    ".paper-status-monitor.json",  # last state seen of every submission (contains UUIDs)
}


def tracked_files() -> list[Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [ROOT / name for name in output.split("\0") if name]


def test_no_data_files_are_tracked() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in tracked_files()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES
        or path.name in FORBIDDEN_NAMES
        or path.name.endswith(".local.md")
        or path.name.startswith(("changes_", "monitor_submission_log_"))
    ]
    assert offenders == [], f"personal data files must not be committed: {offenders}"


def test_no_real_tracking_uuids_are_tracked() -> None:
    offenders = []
    for path in tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = {match.lower() for match in UUID_RE.findall(text)} - ALLOWED_UUIDS
        if found:
            offenders.append(f"{path.relative_to(ROOT).as_posix()}: {sorted(found)}")
    assert offenders == [], (
        "tracking UUIDs are personal; use 00000000-0000-0000-0000-000000000000 in examples: "
        f"{offenders}"
    )
