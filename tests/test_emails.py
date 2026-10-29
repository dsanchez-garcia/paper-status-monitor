from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage

import pytest

from conftest import FakeKeyring, FakeSMTP
from paper_status_monitor import emails
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import SMTP_PASSWORD_ENV_VAR, EmailConfig, SubmissionConfig
from paper_status_monitor.models import Change, Snapshot
from paper_status_monitor.monitor import RunSummary, SubmissionResult

SETTINGS = EmailConfig(
    smtp_host="smtp.example.org",
    username="me@example.org",
    to=("me@example.org", "Co Author <co@example.org>"),
)


def changed_run() -> RunSummary:
    result = SubmissionResult(
        SubmissionConfig(DEMO_UUID, label="Demo"),
        snapshot=Snapshot(title="A study", status="Review Complete"),
        changes=[Change("Status", "Under Review", "Review Complete")],
    )
    return RunSummary(started_at=datetime(2026, 1, 2, 9, 30), results=[result])


def test_send_with_starttls_and_login(smtp: type[FakeSMTP], monkeypatch) -> None:
    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    message = emails.sample_message(SETTINGS)
    emails.send(message, SETTINGS, password=emails.smtp_password(SETTINGS))

    [server] = smtp.servers
    assert (server.host, server.port, server.encrypted) == ("smtp.example.org", 587, False)
    assert server.calls == [
        "starttls",
        ("login", "me@example.org", "secret"),
        ("send", message),
        "quit",
    ]
    assert message["Subject"] == "[paper-status-monitor] Test message"
    assert message["From"] == "me@example.org"
    assert message["To"] == "me@example.org, Co Author <co@example.org>"
    assert message["Message-ID"].endswith("@example.org>")
    assert "E-mail notifications work" in message.get_content()


def test_send_through_ssl_without_login(smtp: type[FakeSMTP]) -> None:
    settings = EmailConfig(
        smtp_host="mail.example.org", security="ssl", sender="me@example.org", to=("me@x.org",)
    )
    emails.send(emails.sample_message(settings), settings)
    [server] = smtp.servers
    assert (server.port, server.encrypted) == (465, True)
    assert [call[0] if isinstance(call, tuple) else call for call in server.calls] == [
        "send",
        "quit",
    ]


def test_send_refuses_incomplete_settings(smtp: type[FakeSMTP]) -> None:
    with pytest.raises(emails.EmailError, match="lacks smtp_host, to, sender"):
        emails.send(EmailMessage(), EmailConfig())
    no_password = rf"no password for me@example\.org.*{SMTP_PASSWORD_ENV_VAR}"
    with pytest.raises(emails.EmailError, match=no_password):
        emails.send(emails.sample_message(SETTINGS), SETTINGS, password=None)
    assert smtp.servers == []


def test_refused_passwords_are_explained(smtp: type[FakeSMTP]) -> None:
    smtp.fail_login = True
    refused = r"refused the user name or the password \(535 5\.7\.8"
    with pytest.raises(emails.EmailError, match=refused):
        emails.send(emails.sample_message(SETTINGS), SETTINGS, password="wrong")


def test_network_errors_are_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(emails.smtplib, "SMTP", unreachable)
    with pytest.raises(emails.EmailError, match=r"smtp\.example\.org:587: connection refused"):
        emails.send(emails.sample_message(SETTINGS), SETTINGS, password="secret")


def test_email_run_sends_the_report(smtp: type[FakeSMTP], monkeypatch) -> None:
    assert emails.email_run(changed_run(), SETTINGS, text="REPORT") is False  # no password
    assert smtp.servers == []

    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    assert emails.email_run(changed_run(), SETTINGS, text="REPORT\n") is True
    [server] = smtp.servers
    message = server.calls[2][1]
    assert message["Subject"] == "[paper-status-monitor] Status changed: Demo"
    body = message.get_content()
    assert body.startswith("REPORT\n\n-- \n")
    assert "do not forward" in body

    quiet = RunSummary(started_at=datetime(2026, 1, 2))
    assert emails.email_run(quiet, SETTINGS, text="nothing") is False
    assert len(smtp.servers) == 1


def test_passwords_in_the_system_keyring(
    fake_keyring: FakeKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyring = fake_keyring
    assert emails.keyring_available()
    assert emails.smtp_password(SETTINGS) is None
    assert emails.password_source(SETTINGS) == ""

    emails.store_password(SETTINGS, "from the keyring")
    assert keyring.passwords == {(emails.KEYRING_SERVICE, "me@example.org"): "from the keyring"}
    assert emails.smtp_password(SETTINGS) == "from the keyring"
    assert emails.password_source(SETTINGS) == "the system keyring"
    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "from the environment")
    assert emails.smtp_password(SETTINGS) == "from the environment"  # the variable wins
    assert SMTP_PASSWORD_ENV_VAR in emails.password_source(SETTINGS)

    assert emails.delete_password(SETTINGS) is True
    assert emails.delete_password(SETTINGS) is False
    with pytest.raises(emails.EmailError, match="Set 'username'"):
        emails.store_password(EmailConfig(smtp_host="x"), "secret")


def test_without_the_keyring_package() -> None:
    assert not emails.keyring_available()  # the tests never use the real keyring
    assert emails.smtp_password(SETTINGS) is None
    with pytest.raises(emails.EmailError, match="pip install keyring"):
        emails.store_password(SETTINGS, "secret")


def test_keyring_errors_do_not_break_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenKeyring(FakeKeyring):
        def get_password(self, service: str, user: str) -> str | None:
            raise RuntimeError("locked")

    monkeypatch.setattr(emails, "_keyring", BrokenKeyring)
    assert emails.smtp_password(SETTINGS) is None
    with pytest.raises(emails.EmailError, match="could not be removed"):
        emails.delete_password(SETTINGS)


def test_unavailable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = "the [email] table lacks smtp_host, to, sender"
    assert emails.unavailable_reason(EmailConfig()) == missing
    assert "there is no password for me@example.org" in (emails.unavailable_reason(SETTINGS) or "")
    monkeypatch.setenv(SMTP_PASSWORD_ENV_VAR, "secret")
    assert emails.unavailable_reason(SETTINGS) is None
