"""Shared fixtures.

Every test runs with HOME, APPDATA, LOCALAPPDATA and the XDG variables pointing to a
temporary folder, so the real configuration, logs and Startup folder of the
developer are never touched. No test reaches the network unless it is marked
with ``@pytest.mark.network``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from paper_status_monitor.client import DEMO_UUID, TrackerUnavailableError
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.models import Snapshot

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every per-user folder to a temporary directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.delenv("PAPER_STATUS_MONITOR_CONFIG", raising=False)
    return home


@pytest.fixture
def demo_payload() -> dict[str, Any]:
    """The public demo record returned by the tracker (fictional data)."""
    return json.loads((DATA_DIR / "demo_submission.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_payload(demo_payload: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    """Build a tracker record from the demo record with some values replaced.

    Keyword arguments ending in ``_summary`` are applied to ``ReviewSummary``,
    e.g. ``make_payload(Status=4, ReviewsCompleted_summary="2")``.
    """

    def factory(**changes: Any) -> dict[str, Any]:
        payload = copy.deepcopy(demo_payload)
        for key, value in changes.items():
            if key.endswith("_summary"):
                payload["ReviewSummary"][key.removesuffix("_summary")] = value
            else:
                payload[key] = value
        return payload

    return factory


class FakeClient:
    """Stand-in for :class:`~paper_status_monitor.client.TrackerClient`.

    ``responses`` maps a UUID to a list of payloads or exceptions that are
    returned (or raised) in order; the last item is repeated when the list is
    exhausted.
    """

    def __init__(self, responses: dict[str, list[Any]] | None = None, reachable: bool = True):
        self.responses = responses or {}
        self.reachable = reachable
        self.calls: list[str] = []

    def queue(self, uuid: str, *items: Any) -> None:
        self.responses.setdefault(uuid, []).extend(items)

    def fetch_json(self, uuid: str) -> dict[str, Any]:
        self.calls.append(uuid)
        items = self.responses.get(uuid)
        if not items:
            raise TrackerUnavailableError("no fake response queued")
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, Exception):
            raise item
        return item

    def fetch(self, uuid: str, tz: Any = None) -> Snapshot:
        return Snapshot.from_api(self.fetch_json(uuid), tz=tz or timezone.utc)

    def is_reachable(self, timeout: float = 5.0) -> bool:
        return self.reachable

    def close(self) -> None:
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A configuration with the demo submission and a temporary data folder."""
    return Config(
        data_dir=tmp_path / "data",
        submissions=(SubmissionConfig(uuid=DEMO_UUID, label="Demo"),),
        open_report=False,
    )


class Clock:
    """Deterministic replacement for ``datetime.now``."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 1, 2, 9, 30, 0)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()
