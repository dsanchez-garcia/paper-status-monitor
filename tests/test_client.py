from __future__ import annotations

from datetime import timezone
from typing import Any

import pytest
import requests

from paper_status_monitor.client import (
    API_URL_TEMPLATE,
    DEMO_UUID,
    USER_AGENT,
    InvalidResponseError,
    SubmissionNotFoundError,
    TrackerClient,
    TrackerError,
    TrackerUnavailableError,
    build_session,
    parse_uuid,
    tracker_url,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self) -> Any:
        if self._text is not None:
            raise ValueError(f"Expecting value: {self._text!r}")
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception):
        self.response = response
        self.requested: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.requested.append((url, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self) -> None:
        pass


def make_client(response: FakeResponse | Exception) -> tuple[TrackerClient, FakeSession]:
    session = FakeSession(response)
    return TrackerClient(session=session, timeout=7), session  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}",
        f"https://track.authorhub.elsevier.com/?foo=bar&uuid={DEMO_UUID}#top",
        f"  {DEMO_UUID}  ",
        DEMO_UUID.upper(),
    ],
)
def test_parse_uuid(value: str) -> None:
    assert parse_uuid(value) == DEMO_UUID


@pytest.mark.parametrize("value", ["", "https://track.authorhub.elsevier.com/", "1234-5678"])
def test_parse_uuid_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="No tracking UUID"):
        parse_uuid(value)


def test_tracker_url() -> None:
    assert tracker_url(DEMO_UUID) == f"https://track.authorhub.elsevier.com/?uuid={DEMO_UUID}"


def test_fetch_json_success(demo_payload: dict) -> None:
    client, session = make_client(FakeResponse(200, demo_payload))
    assert client.fetch_json(DEMO_UUID) == demo_payload
    assert session.requested == [(API_URL_TEMPLATE.format(uuid=DEMO_UUID), 7)]


def test_fetch_returns_snapshot(demo_payload: dict) -> None:
    client, _ = make_client(FakeResponse(200, demo_payload))
    snapshot = client.fetch(DEMO_UUID, tz=timezone.utc)
    assert snapshot.manuscript_number == "SUBTRAK-D-22-00128"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (FakeResponse(404), SubmissionNotFoundError),
        (FakeResponse(429), TrackerUnavailableError),
        (FakeResponse(503), TrackerUnavailableError),
        (FakeResponse(400), TrackerError),
        (FakeResponse(200, text="<html>"), InvalidResponseError),
        (FakeResponse(200, ["not", "a", "dict"]), InvalidResponseError),
        (FakeResponse(200, {"message": "Internal error"}), InvalidResponseError),
        (requests.ConnectionError("offline"), TrackerUnavailableError),
        (requests.Timeout("slow"), TrackerUnavailableError),
    ],
)
def test_fetch_json_errors(response: FakeResponse | Exception, error: type[Exception]) -> None:
    client, _ = make_client(response)
    with pytest.raises(error):
        client.fetch_json(DEMO_UUID)


def test_not_found_is_not_reported_as_unavailable() -> None:
    client, _ = make_client(FakeResponse(404))
    with pytest.raises(TrackerError) as info:
        client.fetch_json(DEMO_UUID)
    assert not isinstance(info.value, TrackerUnavailableError)


def test_default_session_identifies_itself() -> None:
    session = build_session(retries=2)
    try:
        assert session.headers["User-Agent"] == USER_AGENT
        assert session.headers["Accept"] == "application/json"
        assert session.get_adapter("https://example.org").max_retries.total == 2
    finally:
        session.close()


def test_context_manager_closes_session(demo_payload: dict) -> None:
    closed = []

    class ClosingSession(FakeSession):
        def close(self) -> None:
            closed.append(True)

    with TrackerClient(session=ClosingSession(FakeResponse(200, demo_payload))) as client:  # type: ignore[arg-type]
        client.fetch_json(DEMO_UUID)
    assert closed == [True]


@pytest.mark.network
def test_live_demo_submission() -> None:
    """Contract test against the real tracker (run with ``pytest -m network``)."""
    with TrackerClient(timeout=30) as client:
        payload = client.fetch_json(DEMO_UUID)
        snapshot = client.fetch(DEMO_UUID)
    for key in ("ManuscriptTitle", "PubdNumber", "Status", "JournalName", "ReviewSummary"):
        assert key in payload, f"the tracker no longer returns {key!r}"
    assert snapshot.title
    assert snapshot.status
    assert snapshot.manuscript_number
