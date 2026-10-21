# Contributing

Thanks for your interest in `paper-status-monitor`!

## Reporting bugs

Open an issue with:

- the output of `paper-status-monitor doctor`;
- the relevant lines of the log file (its path is printed by `doctor`);
- what you expected and what happened.

**Do not paste your tracking links or UUIDs**: anyone with them can see the status
of your manuscript. Replace them with `00000000-0000-0000-0000-000000000000`.

## Proposing changes

1. Fork the repository and create a branch.
2. Set up a development environment:

   ```console
   python -m venv .venv
   .venv\Scripts\activate          # Windows (source .venv/bin/activate elsewhere)
   python -m pip install -e ".[dev,docs]"
   ```

3. Make your change, with tests. Follow the conventions in [AGENTS.md](AGENTS.md)
   (they apply to humans too).
4. Check that everything passes:

   ```console
   python -m pytest
   ruff check .
   ruff format --check .
   sphinx-build -W --keep-going -b html docs docs/_build/html
   ```

5. Add an entry to `CHANGELOG.md` under *Unreleased* and update `TODO.md` if
   relevant.
6. Open a pull request describing the motivation and the change.

All code, comments, documentation and commit messages are written in English.

## Code of conduct

Be kind and constructive. Harassment or discrimination of any kind is not tolerated.

