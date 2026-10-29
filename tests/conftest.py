"""Shared fixtures.

Every test runs with HOME, APPDATA, LOCALAPPDATA and the XDG variables pointing to a
temporary folder, so the real configuration, logs and Startup folder of the
developer are never touched. No test reaches the network unless it is marked
with ``@pytest.mark.network``. No test can send an e-mail or use the system keyring:
use the ``smtp`` and ``fake_keyring`` fixtures. Every test starts in English, and
the language chosen by a test (for instance, by opening a window whose configuration
says ``language = "es"``) never leaks into the next one.
"""

from __future__ import annotations

import copy
import json
import smtplib
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from paper_status_monitor import emails, i18n
from paper_status_monitor.client import DEMO_UUID, TrackerUnavailableError
from paper_status_monitor.config import SMTP_PASSWORD_ENV_VAR, Config, SubmissionConfig
from paper_status_monitor.models import Snapshot

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def english_by_default() -> Iterator[None]:
    """Start every test in English and restore English afterwards."""
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


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
    monkeypatch.delenv(SMTP_PASSWORD_ENV_VAR, raising=False)
    monkeypatch.setattr(emails, "_keyring", lambda: None)
    monkeypatch.setattr(emails.smtplib, "SMTP", _NoSMTP)
    monkeypatch.setattr(emails.smtplib, "SMTP_SSL", _NoSMTP)
    return home


class _NoSMTP:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("Tests must not contact a real SMTP server: use the smtp fixture.")


class FakeSMTP:
    """Stand-in for :class:`smtplib.SMTP` that records the conversation."""

    servers: ClassVar[list[FakeSMTP]] = []
    fail_login: ClassVar[bool] = False

    def __init__(
        self, host: str, port: int, timeout: float | None = None, context: Any = None
    ) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.encrypted = context is not None  # SMTP_SSL receives an SSL context
        self.calls: list[Any] = []
        FakeSMTP.servers.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        self.calls.append(("login", user, password))

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(("send", message))

    @classmethod
    def sent(cls) -> list[EmailMessage]:
        """The messages sent through every fake server."""
        return [
            call[1]
            for server in cls.servers
            for call in server.calls
            if isinstance(call, tuple) and call[0] == "send"
        ]


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    """Send e-mails to :class:`FakeSMTP` instead of a real server."""
    FakeSMTP.servers = []
    FakeSMTP.fail_login = False
    monkeypatch.setattr(emails.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(emails.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


class FakeKeyring:
    """A system keyring kept in memory (the interface of the ``keyring`` package)."""

    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.passwords.get((service, user))

    def set_password(self, service: str, user: str, password: str) -> None:
        self.passwords[(service, user)] = password

    def delete_password(self, service: str, user: str) -> None:
        del self.passwords[(service, user)]


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """Make the e-mail module use an in-memory keyring."""
    keyring = FakeKeyring()
    monkeypatch.setattr(emails, "_keyring", lambda: keyring)
    return keyring


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
        notify=(),
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
