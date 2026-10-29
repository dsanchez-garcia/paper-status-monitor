"""Translations of what paper-status-monitor writes for you to read.

The ``language`` setting (see :data:`LANGUAGES`) chooses the language of the change
reports, the desktop notifications, the e-mails, the summary and the graphical
interface. The command line (its messages and help), the error messages that come
from the lower layers (configuration, tracker, SMTP server...) and the data written
to the workbooks and exports stay in English, so that workbooks and scripts work
the same in every language; log messages are never translated.

English is the source language. Messages are written in English in the code and
wrapped in :func:`gettext` (imported as ``_``) or :func:`ngettext`; texts defined
before the language is known, such as module constants, are marked with :func:`N_`
and translated when they are shown. Placeholders use :meth:`str.format` names
(``_("Saved {path}").format(path=...)``), so that translations can reorder them.

Translations live in ``paper_status_monitor/locales/<code>.py``: a ``MESSAGES``
dictionary (English text to translation; plural forms as tuples) and a ``plural``
function that chooses the form for a number. A message without a translation is
shown in English. ``tests/test_i18n.py`` checks that every catalog translates every
message, and only those, with the same placeholders.

The language is chosen at two levels:

* :func:`set_language` sets it for the whole process (the window does it when it
  reads the configuration);
* ``with language(code):`` sets it for the current thread, inside the block. Reports
  and summaries are rendered this way, so a check running in a background thread
  never changes the window, and the command line stays in English.
"""

from __future__ import annotations

import functools
import importlib
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from paper_status_monitor.models import COLUMNS

#: Available languages: code to name (in that language).
LANGUAGES: dict[str, str] = {"en": "English", "es": "Español"}

#: Language used when none is chosen, and the language of the source texts.
DEFAULT_LANGUAGE = "en"

_BUILTIN_COLUMNS = frozenset(COLUMNS)
_process_language = DEFAULT_LANGUAGE
_thread = threading.local()


@dataclass(frozen=True)
class Catalog:
    """The translations of one language.

    Attributes:
        messages: English text to translation; messages with plural forms map their
            singular text to a tuple of forms.
        plural: Index of the plural form to use for a number.
    """

    messages: Mapping[str, str | tuple[str, ...]]
    plural: Callable[[int], int]


def normalize_language(code: str) -> str:
    """Return the code of :data:`LANGUAGES` that *code* stands for.

    Letter case and region suffixes do not matter: ``"ES"``, ``"es-ES"`` and
    ``"es_ES"`` all give ``"es"``.

    Raises:
        ValueError: If the language is not available.
    """
    text = str(code).strip().replace("_", "-").partition("-")[0].casefold()
    if text not in LANGUAGES:
        choices = ", ".join(f'"{key}" ({name})' for key, name in LANGUAGES.items())
        raise ValueError(f"Unknown language {code!r}: use {choices}.")
    return text


def set_language(code: str) -> str:
    """Use *code* for the whole process (every thread without its own language).

    Returns:
        The normalised code.

    Raises:
        ValueError: If the language is not available.
    """
    global _process_language
    _process_language = normalize_language(code)
    return _process_language


def get_language() -> str:
    """Return the language used by the current thread."""
    return getattr(_thread, "code", None) or _process_language


@contextmanager
def language(code: str | None) -> Iterator[str]:
    """Use *code* in the current thread inside a ``with`` block.

    ``None`` keeps the current language. The previous language is restored at the
    end of the block, even if it raises.

    Raises:
        ValueError: If the language is not available.
    """
    previous = getattr(_thread, "code", None)
    _thread.code = normalize_language(code) if code else previous
    try:
        yield get_language()
    finally:
        _thread.code = previous


def language_name(code: str) -> str:
    """Return the name of a language in that language (``"es"`` gives ``"Español"``)."""
    return LANGUAGES[normalize_language(code)]


def gettext(message: str) -> str:
    """Return *message* in the current language (in English if it has no translation)."""
    code = get_language()
    if code == DEFAULT_LANGUAGE:
        return message
    translation = catalog(code).messages.get(message)
    return translation if isinstance(translation, str) else message


#: Short name of :func:`gettext`, as usual: ``from paper_status_monitor.i18n import _``.
_ = gettext


def ngettext(singular: str, plural: str, count: int) -> str:
    """Return the form of a message that suits *count*, in the current language.

    Args:
        singular: English text for one (``"{count} submission"``).
        plural: English text for any other number (``"{count} submissions"``).
        count: The number; it is not inserted, call :meth:`str.format` on the result.
    """
    code = get_language()
    if code != DEFAULT_LANGUAGE:
        translations = catalog(code)
        forms = translations.messages.get(singular)
        if isinstance(forms, tuple) and forms:
            index = min(max(translations.plural(count), 0), len(forms) - 1)
            return forms[index]
    return singular if count == 1 else plural


def N_(message: str) -> str:
    """Mark *message* for translation without translating it now.

    Used for texts defined before the language is known (module constants); they
    are translated with :func:`gettext` when they are shown.
    """
    return message


def column_label(column: str) -> str:
    """Return the name of a workbook column in the current language.

    Only the built-in columns (:data:`~paper_status_monitor.models.COLUMNS`) are
    translated; custom fields keep the names their users gave them. The workbooks
    themselves always use the English names.
    """
    return gettext(column) if column in _BUILTIN_COLUMNS else column


@functools.cache
def catalog(code: str) -> Catalog:
    """Return the translations of a language (empty for English, the source language).

    Raises:
        ValueError: If the language is not available.
        ModuleNotFoundError: If its catalog is missing.
    """
    code = normalize_language(code)
    if code == DEFAULT_LANGUAGE:
        return Catalog(messages={}, plural=lambda count: 0 if count == 1 else 1)
    module = importlib.import_module(f"{__package__}.locales.{code}")
    return Catalog(messages=module.MESSAGES, plural=module.plural)
