# Copilot instructions

Follow [AGENTS.md](../AGENTS.md) at the repository root: it describes the
architecture, the domain rules, the commands to run and the privacy rules.

Most important points:

- Everything in English. Python ≥ 3.10, type hints, Ruff (line length 100),
  Google-style docstrings.
- Before finishing: `python -m pytest`, `ruff check .`, `ruff format --check .` and
  `sphinx-build -W --keep-going -b html docs docs/_build/html` must pass.
- Tests never use the network (use the `fake_client` and `make_payload` fixtures).
- Never commit tracking UUIDs, workbooks, reports, logs or configuration files. Use
  the demo UUID `00000000-0000-0000-0000-000000000000` in examples.
- The workbook key is the base manuscript number (without `R1`, `R2`...), never the
  title.
- Update `CHANGELOG.md` (*Unreleased*) and `TODO.md` when relevant.

