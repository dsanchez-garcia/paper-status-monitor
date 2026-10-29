from __future__ import annotations

import ast
import string
import threading
from datetime import date, datetime
from pathlib import Path

import pytest

import paper_status_monitor
from paper_status_monitor import i18n, notifications, report, summary
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import (
    Config,
    ConfigError,
    SubmissionConfig,
    describe_columns,
    dump_config,
    parse_config,
)
from paper_status_monitor.i18n import _, column_label, ngettext
from paper_status_monitor.models import COLUMNS, Change, Snapshot
from paper_status_monitor.monitor import RunSummary, SubmissionResult

SOURCE = Path(paper_status_monitor.__file__).parent
TRANSLATED = [code for code in i18n.LANGUAGES if code != i18n.DEFAULT_LANGUAGE]


def source_messages() -> dict[str, str | None]:
    """Every message marked for translation in the code: text to plural text (or None).

    The built-in column names are messages too (see :func:`i18n.column_label`).
    """
    messages: dict[str, str | None] = dict.fromkeys(COLUMNS)
    for path in sorted(SOURCE.rglob("*.py")):
        if path.parent.name == "locales":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            texts = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
            texts = [text for text in texts if isinstance(text, str)]
            if name in {"_", "gettext", "N_"} and texts:
                messages[texts[0]] = None
            elif name == "ngettext" and len(texts) >= 2:
                messages[texts[0]] = texts[1]
    return messages


def fields(text: str) -> set[str]:
    return {name for _literal, name, _spec, _conv in string.Formatter().parse(text) if name}


def test_messages_are_found_in_the_code() -> None:
    messages = source_messages()
    assert "Open report" in messages
    assert messages["Checked {count} submission at {moment}"] == (
        "Checked {count} submissions at {moment}"
    )
    assert "Manuscript number - Journal - Title (default)" in messages  # marked with N_
    assert "Status" in messages


@pytest.mark.parametrize("code", TRANSLATED)
def test_catalogs_translate_every_message_and_only_those(code: str) -> None:
    catalog = i18n.catalog(code)
    messages = source_messages()
    missing = sorted(set(messages) - set(catalog.messages))
    unused = sorted(set(catalog.messages) - set(messages))
    assert missing == [], f"Messages without a translation in {code}.py"
    assert unused == [], f"Translations of messages that are no longer used in {code}.py"


@pytest.mark.parametrize("code", TRANSLATED)
def test_translations_keep_the_placeholders(code: str) -> None:
    catalog = i18n.catalog(code)
    forms_needed = max(catalog.plural(count) for count in range(1000)) + 1
    for message, plural in source_messages().items():
        translation = catalog.messages[message]
        expected = fields(message) | fields(plural or "")
        if plural is None:
            assert isinstance(translation, str), f"{message!r} is not a plural message"
            assert fields(translation) == expected, message
            assert translation.strip(), message
        else:
            assert isinstance(translation, tuple), f"{message!r} needs its plural forms"
            assert len(translation) == forms_needed, message
            for form in translation:
                assert fields(form) == expected, message
        for form in [translation] if isinstance(translation, str) else translation:
            assert form.count("\n") == message.count("\n"), message


def test_normalize_language() -> None:
    assert i18n.normalize_language("ES") == "es"
    assert i18n.normalize_language(" es-ES ") == "es"
    assert i18n.normalize_language("es_ES") == "es"
    assert i18n.normalize_language("en-GB") == "en"
    with pytest.raises(ValueError, match='"es" \\(Español\\)'):
        i18n.normalize_language("fr")
    assert i18n.language_name("es") == "Español"


def test_english_is_the_default_and_the_fallback() -> None:
    assert i18n.get_language() == "en"
    assert _("Open report") == "Open report"
    assert ngettext("{count} new", "{count} news", 2) == "{count} news"
    with i18n.language("es"):
        assert _("Open report") == "Abrir informe"
        assert _("A message that nobody translated") == "A message that nobody translated"
        assert ngettext("{count} new", "{count} new", 1).format(count=1) == "1 nuevo"
        assert ngettext("{count} new", "{count} new", 0).format(count=0) == "0 nuevos"
        assert ngettext("unknown {count}", "unknowns {count}", 2) == "unknowns {count}"
    assert i18n.catalog("en").messages == {}


def test_the_language_of_a_block_belongs_to_its_thread() -> None:
    seen: list[str] = []

    def worker() -> None:
        with i18n.language("es"):
            started.set()
            release.wait(5)
            seen.append(_("Open report"))

    started, release = threading.Event(), threading.Event()
    thread = threading.Thread(target=worker)
    thread.start()
    started.wait(5)
    assert _("Open report") == "Open report"  # the main thread is not affected
    release.set()
    thread.join(5)
    assert seen == ["Abrir informe"]
    with i18n.language(None):
        assert i18n.get_language() == "en"


def test_set_language_applies_to_every_thread() -> None:
    i18n.set_language("es-ES")
    seen: list[str] = []
    thread = threading.Thread(target=lambda: seen.append(_("Open report")))
    thread.start()
    thread.join(5)
    assert seen == ["Abrir informe"]
    with i18n.language("en"):
        assert _("Open report") == "Open report"
    with pytest.raises(ValueError, match="Unknown language"):
        i18n.set_language("xx")
    assert i18n.get_language() == "es"


def test_only_the_builtin_columns_are_translated() -> None:
    with i18n.language("es"):
        assert column_label("Status") == "Estado"
        assert column_label("Summary") == "Summary"  # a custom field, not the button
        assert describe_columns(["Status"]) == "solo Estado"
        assert describe_columns(COLUMNS) == "todas las columnas"


# ------------------------------------------------------------------ the setting


def test_language_setting(tmp_path: Path) -> None:
    assert parse_config({}).language == "en"
    assert parse_config({"language": "ES"}).language == "es"
    for value in ("fr", 3):
        with pytest.raises(ConfigError, match="'language' must be one of"):
            parse_config({"language": value})
    text = dump_config(Config(data_dir=tmp_path, language="es"))
    assert "language = 'es'" in text
    assert '"es" (Español)' in text


# ------------------------------------------------------------------ documents in Spanish


@pytest.fixture
def snapshot(demo_payload: dict) -> Snapshot:
    return Snapshot.from_api(demo_payload)


def run_summary(snapshot: Snapshot) -> RunSummary:
    changed = SubmissionResult(
        SubmissionConfig(DEMO_UUID, label="Tau", fields={"summary": "x"}),
        snapshot=snapshot,
        changes=[Change("Status", "Under Review", "Required Reviews Complete")],
    )
    failed = SubmissionResult(SubmissionConfig(DEMO_UUID, label="Epsilon"), error="HTTP 503")
    return RunSummary(started_at=datetime(2026, 1, 2, 9, 30), results=[changed, failed])


def test_report_in_spanish(snapshot: Snapshot) -> None:
    with i18n.language("es"):
        text = report.render_report(run_summary(snapshot))
        console = report.render_console(run_summary(snapshot))
    assert text.startswith("Informe del estado de los envíos\nComprobación iniciada: 2026-01-02")
    assert "CAMBIOS (1)" in text
    assert "  - Estado: 'Under Review' → 'Required Reviews Complete'" in text  # values as shown
    assert "  Revista: The International Journal of Submission Trackers" in text
    assert "  Summary: x" in text  # custom fields keep their names
    assert "ERRORES (1)" in text
    assert console.splitlines()[0] == "2 envíos comprobados el 2026-01-02 09:30:00"
    assert "  [CAMBIOS]     Influence of submission trackers" in console  # tags are aligned
    assert "  [ERROR]       Epsilon: HTTP 503" in console


def test_publish_report_uses_the_language_of_the_configuration(
    snapshot: Snapshot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[notifications.Notification] = []
    monkeypatch.setattr(notifications, "show", shown.append)
    config = Config(data_dir=tmp_path, notify=("toast",), language="es")
    path = report.publish_report(run_summary(snapshot), config)
    assert path is not None
    assert "CAMBIOS (1)" in path.read_text(encoding="utf-8")
    [notification] = shown
    assert notification.title == "Estado de los envíos: 1 con cambios, 1 con error"
    assert notification.buttons[0].label == "Abrir informe"
    assert i18n.get_language() == "en"  # only the report was in Spanish


def test_notifications_in_spanish(snapshot: Snapshot) -> None:
    result = SubmissionResult(
        SubmissionConfig(DEMO_UUID, label="Tau"),
        snapshot=snapshot,
        changes=[Change("Status", "a", "b"), Change("Reviews completed", "1", "2")],
    )
    with i18n.language("es"):
        single = notifications.build_notification(RunSummary(datetime.now(), results=[result]))
        sample = notifications.sample_notification()
    assert single is not None
    assert single.title == "Cambio de estado: Tau"
    assert single.message == "Estado: a → b\nRevisiones completadas: 1 → 2"
    assert [button.label for button in single.buttons] == ["Ver seguimiento"]
    assert sample.message.startswith("Las notificaciones de escritorio funcionan")


def test_summary_in_spanish() -> None:
    rows = [
        summary.SummaryRow(
            1, "Tau", recorded=True, status="Under Review", since=date(2026, 1, 1), days=1
        ),
        summary.SummaryRow(2, "Epsilon", enabled=False),
    ]
    with i18n.language("es"):
        text = summary.render_summary(rows, "text")
        page = summary.render_summary(rows, "html")
    assert text.startswith("Resumen del estado de los envíos - ")
    assert "Envío" in text.splitlines()[2]
    assert "2026-01-01 (1 día)" in text
    assert "[en pausa] Epsilon" in text
    assert "aún sin registrar" in text
    assert '<html lang="es">' in page
    assert "<th>Número de manuscrito</th>" in page
    assert summary.render_summary([], "markdown").startswith("# Paper status summary")
