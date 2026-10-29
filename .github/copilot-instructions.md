# Copilot instructions

Follow [AGENTS.md](../AGENTS.md) at the repository root: it describes the
architecture, the domain rules, the commands to run and the privacy rules.

Most important points:

- Everything in English (except the translation catalogs in `locales/`). Python ≥ 3.10,
  type hints, Ruff (line length 100), Google-style docstrings.
- Texts of reports, notifications, e-mails, the summary and the GUI go through
  `i18n._()` / `ngettext()` with named placeholders; add their Spanish translation to
  `locales/es.py` (`tests/test_i18n.py` checks it). Workbooks, exports and the CLI stay
  in English.
- Before finishing: `python -m pytest`, `ruff check .`, `ruff format --check .` and
  `sphinx-build -W --keep-going -b html docs docs/_build/html` must pass.
- Tests never use the network (use the `fake_client` and `make_payload` fixtures).
- Never commit tracking UUIDs, workbooks, reports, logs or configuration files. Use
  the demo UUID `00000000-0000-0000-0000-000000000000` in examples.
- The workbook key is the base manuscript number (without `R1`, `R2`...), never the
  title. Several submissions may share a workbook (`workbook_name` template): compare
  with the last row of the submission, not of the workbook.
- Recording and notifying are independent (`record_*` / `notify_*` settings); how news
  is announced is `notify` (`report`, `toast`, `none`), and the report is always written.
- Update `CHANGELOG.md` (*Unreleased*) and `TODO.md` when relevant.

