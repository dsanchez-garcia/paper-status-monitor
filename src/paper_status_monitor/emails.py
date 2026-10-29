"""E-mail notifications: the report of a run, sent through an SMTP server.

They are enabled with ``notify = "email"`` (or a list that includes it) and an
``[email]`` table in the configuration (see
:class:`~paper_status_monitor.config.EmailConfig`). The password of the server is
**never** stored in the configuration: it is read from the
``PAPER_STATUS_MONITOR_SMTP_PASSWORD`` environment variable or, if the optional
`keyring <https://pypi.org/project/keyring/>`_ package is installed, from the system
keyring (Windows Credential Manager, macOS Keychain, Secret Service on Linux), where
``paper-status-monitor email set-password`` stores it.

Like desktop notifications, e-mails are best effort: when one cannot be sent, the
problem is logged and the report is still written.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import TYPE_CHECKING, Any

from paper_status_monitor import notifications
from paper_status_monitor.config import SMTP_PASSWORD_ENV_VAR, EmailConfig
from paper_status_monitor.i18n import _

if TYPE_CHECKING:
    from paper_status_monitor.monitor import RunSummary

log = logging.getLogger(__name__)

#: Service name under which the password is kept in the system keyring (the account
#: is the SMTP user name).
KEYRING_SERVICE = "paper-status-monitor"

#: Start of every subject, to filter the messages.
SUBJECT_PREFIX = "[paper-status-monitor]"

_TIMEOUT = 30


def _footer() -> str:
    """The signature of every message, in the current language."""
    note = _(
        "Sent by paper-status-monitor. The tracking links in this message are personal: "
        "do not forward it."
    )
    return f"-- \n{note}\n"


class EmailError(RuntimeError):
    """An e-mail could not be sent, or the password could not be stored."""


def smtp_password(settings: EmailConfig) -> str | None:
    """Return the password of the SMTP server, or ``None`` if there is none.

    The ``PAPER_STATUS_MONITOR_SMTP_PASSWORD`` environment variable wins; otherwise
    the system keyring is asked (service :data:`KEYRING_SERVICE`, account
    ``settings.username``) when the ``keyring`` package is installed.
    """
    password = os.environ.get(SMTP_PASSWORD_ENV_VAR)
    if password:
        return password
    if not settings.username:
        return None
    backend = _keyring()
    if backend is None:
        return None
    try:
        return backend.get_password(KEYRING_SERVICE, settings.username)
    except Exception as exc:  # keyring backends raise many different errors
        log.warning("The system keyring could not be read: %s", exc)
        return None


def password_source(settings: EmailConfig) -> str:
    """Say where the password comes from: ``"the environment variable"``,
    ``"the system keyring"`` or ``""`` (none)."""
    if os.environ.get(SMTP_PASSWORD_ENV_VAR):
        return f"the {SMTP_PASSWORD_ENV_VAR} environment variable"
    return "the system keyring" if smtp_password(settings) else ""


def keyring_available() -> bool:
    """Return ``True`` if the optional ``keyring`` package is installed."""
    return _keyring() is not None


def store_password(settings: EmailConfig, password: str) -> None:
    """Save the password of the SMTP server in the system keyring.

    Raises:
        EmailError: If there is no user name, the ``keyring`` package is missing or
            the keyring refuses the password.
    """
    if not settings.username:
        raise EmailError(
            "Set 'username' in the [email] table first: the password is kept for that user."
        )
    backend = _require_keyring()
    try:
        backend.set_password(KEYRING_SERVICE, settings.username, password)
    except Exception as exc:  # keyring backends raise many different errors
        raise EmailError(f"The system keyring refused the password: {exc}") from exc


def delete_password(settings: EmailConfig) -> bool:
    """Remove the password of the SMTP server from the system keyring.

    Returns:
        ``True`` if a password was removed, ``False`` if there was none.

    Raises:
        EmailError: If the ``keyring`` package is missing or the keyring fails.
    """
    if not settings.username:
        return False
    backend = _require_keyring()
    try:
        if backend.get_password(KEYRING_SERVICE, settings.username) is None:
            return False
        backend.delete_password(KEYRING_SERVICE, settings.username)
    except Exception as exc:  # keyring backends raise many different errors
        raise EmailError(f"The password could not be removed from the keyring: {exc}") from exc
    return True


def build_message(settings: EmailConfig, subject: str, body: str) -> EmailMessage:
    """Return a plain-text message from :attr:`EmailConfig.from_address` to its recipients."""
    message = EmailMessage()
    message["Subject"] = f"{SUBJECT_PREFIX} {subject}"
    message["From"] = settings.from_address
    message["To"] = ", ".join(settings.to)
    message["Date"] = formatdate(localtime=True)
    domain = parseaddr(settings.from_address)[1].rpartition("@")[2] or "paper-status-monitor"
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(body)
    return message


def send(
    message: EmailMessage,
    settings: EmailConfig,
    *,
    password: str | None = None,
    timeout: float = _TIMEOUT,
) -> None:
    """Send *message* through the SMTP server of *settings*.

    Raises:
        EmailError: If it could not be sent; the message says why.
    """
    if settings.missing:
        raise EmailError(f"The [email] table lacks {', '.join(settings.missing)}.")
    if settings.username and not password:
        raise EmailError(
            f"There is no password for {settings.username}: set the {SMTP_PASSWORD_ENV_VAR} "
            "environment variable, or run: paper-status-monitor email set-password"
        )
    context = ssl.create_default_context()
    server = f"{settings.smtp_host}:{settings.port}"
    try:
        client: smtplib.SMTP
        if settings.security == "ssl":
            client = smtplib.SMTP_SSL(
                settings.smtp_host, settings.port, timeout=timeout, context=context
            )
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.port, timeout=timeout)
        with client:
            if settings.security == "starttls":
                client.starttls(context=context)
            if settings.username:
                client.login(settings.username, password or "")
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(
            f"{server} refused the user name or the password ({_reply(exc)}). Some providers "
            "(Gmail, Outlook...) need an app password instead of your usual one."
        ) from exc
    except smtplib.SMTPResponseException as exc:
        raise EmailError(f"{server} refused the message ({_reply(exc)}).") from exc
    except (smtplib.SMTPException, OSError) as exc:  # ssl.SSLError is an OSError
        raise EmailError(f"The e-mail could not be sent through {server}: {exc}") from exc


def email_run(
    summary: RunSummary, settings: EmailConfig, *, text: str, include_errors: bool = True
) -> bool:
    """Send the report of a run by e-mail, if the run has news.

    Failures are logged, never raised.

    Args:
        summary: The run.
        settings: How e-mails are sent.
        text: The report (the body of the message).
        include_errors: Whether the submissions that could not be checked are news.

    Returns:
        ``True`` if the e-mail was sent.
    """
    notification = notifications.build_notification(summary, include_errors=include_errors)
    if notification is None:
        return False
    message = build_message(settings, notification.title, f"{text.rstrip()}\n\n{_footer()}")
    try:
        send(message, settings, password=smtp_password(settings))
    except EmailError as exc:
        log.warning("The e-mail could not be sent: %s", exc)
        return False
    log.info("E-mail sent to %s: %s", ", ".join(settings.to), notification.title)
    return True


def sample_message(settings: EmailConfig) -> EmailMessage:
    """Return the message used to check that e-mails work (in the current language)."""
    body = _(
        "E-mail notifications work: you will receive a message like this one, with the "
        "report, when there is news about your submissions."
    )
    return build_message(settings, _("Test message"), f"{body}\n\n{_footer()}")


def unavailable_reason(settings: EmailConfig) -> str | None:
    """Return why e-mails cannot be sent, or ``None`` (the server is not contacted)."""
    if settings.missing:
        return f"the [email] table lacks {', '.join(settings.missing)}"
    if settings.username and not smtp_password(settings):
        return (
            f"there is no password for {settings.username}: set the {SMTP_PASSWORD_ENV_VAR} "
            "environment variable, or run: paper-status-monitor email set-password"
        )
    return None


def _keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _require_keyring() -> Any:
    backend = _keyring()
    if backend is None:
        raise EmailError(
            "The keyring package is not installed. Install it with: python -m pip install "
            f"keyring (or set the {SMTP_PASSWORD_ENV_VAR} environment variable instead)."
        )
    return backend


def _reply(exc: smtplib.SMTPResponseException) -> str:
    detail = exc.smtp_error
    text = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
    return f"{exc.smtp_code} {' '.join(text.split())}".strip()
