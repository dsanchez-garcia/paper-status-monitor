"""HTTP client for the public *Track your submission* service used by Elsevier journals.

The official page (https://track.authorhub.elsevier.com/?uuid=...) is a small
JavaScript application that downloads the submission record from a JSON endpoint.
This module talks to that endpoint directly, so no browser is needed.
"""

from __future__ import annotations

import logging
import re
import socket
from datetime import tzinfo
from types import TracebackType
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from paper_status_monitor._version import __version__
from paper_status_monitor.models import Snapshot

log = logging.getLogger(__name__)

#: JSON endpoint used by the official tracking page.
API_URL_TEMPLATE = "https://tnlkuelk67.execute-api.us-east-1.amazonaws.com/tracker/{uuid}"

#: Human-facing tracking page.
TRACKER_URL_TEMPLATE = "https://track.authorhub.elsevier.com/?uuid={uuid}"

#: Public demo submission served by the tracker (fictional data, handy for testing).
DEMO_UUID = "00000000-0000-0000-0000-000000000000"

#: User agent sent with every request, so that the service owner can identify the tool.
USER_AGENT = (
    f"paper-status-monitor/{__version__} (+https://github.com/dsanchez-garcia/paper-status-monitor)"
)

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


class TrackerError(Exception):
    """Base class for errors raised while querying the tracker."""


class SubmissionNotFoundError(TrackerError):
    """The tracker has no data for the UUID (wrong link, or tracking has finished)."""


class TrackerUnavailableError(TrackerError):
    """The tracker could not be reached (network problem, timeout or server error)."""


class InvalidResponseError(TrackerError):
    """The tracker answered with something that is not a submission record."""


def parse_uuid(value: str) -> str:
    """Extract the tracking UUID from a tracking link or a bare UUID.

    Args:
        value: Either a link such as
            ``https://track.authorhub.elsevier.com/?uuid=<uuid>`` or the UUID itself.

    Returns:
        The UUID in lower case.

    Raises:
        ValueError: If no UUID can be found in *value*.
    """
    text = value.strip()
    candidates = parse_qs(urlparse(text).query).get("uuid", [])
    for candidate in [*candidates, text]:
        match = _UUID_RE.search(candidate)
        if match:
            return match.group(0).lower()
    example = TRACKER_URL_TEMPLATE.format(uuid=DEMO_UUID)
    raise ValueError(
        f"No tracking UUID found in {value!r}. Expected a link such as {example} or a bare UUID."
    )


def tracker_url(uuid: str) -> str:
    """Return the link to the official tracking page for *uuid*."""
    return TRACKER_URL_TEMPLATE.format(uuid=uuid)


def build_session(retries: int = 3) -> requests.Session:
    """Create a :class:`requests.Session` with retries and identifying headers.

    Connection errors, timeouts and HTTP 429/5xx answers are retried with an
    exponential back-off (1 s, 2 s, 4 s, ...).
    """
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


class TrackerClient:
    """Fetch submission records from the tracker.

    Args:
        timeout: Seconds to wait for each answer.
        retries: Number of automatic retries for transient errors.
        session: Optional pre-configured session (mainly for tests).
        api_url_template: Endpoint template with a ``{uuid}`` placeholder.

    Example:
        >>> with TrackerClient() as client:  # doctest: +SKIP
        ...     snapshot = client.fetch("00000000-0000-0000-0000-000000000000")
        ...     print(snapshot.status)
        Under Review
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 3,
        session: requests.Session | None = None,
        api_url_template: str = API_URL_TEMPLATE,
    ) -> None:
        self.timeout = timeout
        self.api_url_template = api_url_template
        self.session = session if session is not None else build_session(retries)

    def __enter__(self) -> TrackerClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def fetch_json(self, uuid: str) -> dict[str, Any]:
        """Return the raw JSON record of a submission.

        Raises:
            SubmissionNotFoundError: The tracker answered HTTP 404.
            TrackerUnavailableError: Network error, timeout, HTTP 429 or 5xx.
            InvalidResponseError: The answer is not a JSON submission record.
            TrackerError: Any other unexpected HTTP status.
        """
        url = self.api_url_template.format(uuid=uuid)
        log.debug("GET %s", url)
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TrackerUnavailableError(f"Could not reach the tracker: {exc}") from exc

        status = response.status_code
        if status == 404:
            raise SubmissionNotFoundError(
                f"The tracker has no data for UUID {uuid} (HTTP 404). Either the link is wrong "
                "or the submission is no longer tracked, which usually happens after a final "
                "decision."
            )
        if status == 429 or status >= 500:
            raise TrackerUnavailableError(f"The tracker answered HTTP {status}; try again later.")
        if not 200 <= status < 300:
            raise TrackerError(f"Unexpected answer from the tracker: HTTP {status}.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidResponseError("The tracker did not return valid JSON.") from exc
        if not isinstance(payload, dict) or not {"ManuscriptTitle", "PubdNumber"} & payload.keys():
            raise InvalidResponseError("The tracker answer does not look like a submission record.")
        return payload

    def fetch(self, uuid: str, tz: tzinfo | None = None) -> Snapshot:
        """Return the current :class:`~paper_status_monitor.models.Snapshot` of a submission."""
        return Snapshot.from_api(self.fetch_json(uuid), tz=tz)

    def is_reachable(self, timeout: float = 5.0) -> bool:
        """Return ``True`` if a TCP connection to the tracker host can be opened."""
        parsed = urlparse(self.api_url_template.format(uuid=DEMO_UUID))
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
