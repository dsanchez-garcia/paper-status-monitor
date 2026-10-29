"""Translations, one module per language (see :mod:`paper_status_monitor.i18n`).

To add a language:

1. Copy ``es.py`` to ``<code>.py`` (an ISO 639-1 code such as ``fr``), translate
   every value of ``MESSAGES`` and adapt ``plural``.
2. Add the code and the name of the language, written in that language, to
   :data:`paper_status_monitor.i18n.LANGUAGES`.
3. Run ``python -m pytest tests/test_i18n.py``: it reports missing, unused and
   inconsistent translations.

Keys are the English texts exactly as written in the code. Keep the ``{name}``
placeholders (their order may change), the line breaks and the ``...`` of buttons
that open a window.
"""
