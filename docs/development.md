# Development

Contributions are welcome. This page explains how the project is organised and how
to work on it. AI coding agents should also read
[AGENTS.md](https://github.com/dsanchez-garcia/paper-status-monitor/blob/main/AGENTS.md),
and the backlog lives in
[TODO.md](https://github.com/dsanchez-garcia/paper-status-monitor/blob/main/TODO.md).

## Set-up

```console
git clone https://github.com/dsanchez-garcia/paper-status-monitor.git
cd paper-status-monitor
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Linux / macOS
python -m pip install -e ".[dev,docs]"
```

```{tip}
If the repository lives in a cloud-synced folder (Google Drive, OneDrive...), create
the virtual environment **outside** of it to avoid syncing thousands of files, e.g.
`python -m venv ~/.venvs/paper-status-monitor`.
```

## Everyday commands

| Task | Command |
| --- | --- |
| Run the tests | `python -m pytest` |
| Tests with coverage | `python -m pytest --cov` |
| Contract test against the real tracker | `python -m pytest -m network` |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| Build the documentation | `sphinx-build -W --keep-going -b html docs docs/_build/html` |
| Build the distribution | `python -m build` then `twine check --strict dist/*` |

The default test run never touches the network or your real configuration: every
test runs with `HOME`, `APPDATA`, `LOCALAPPDATA` and the XDG variables redirected to
a temporary folder, and the tracker is replaced by a fake client.

## Project layout

```text
src/paper_status_monitor/
├── __init__.py     public API (re-exports)
├── __main__.py     python -m paper_status_monitor
├── _version.py     single source of the version number
├── cli.py          argparse CLI: init, add, list, check, run, autostart, doctor
├── client.py       HTTP client for the tracker JSON endpoint, UUID parsing, errors
├── models.py       Snapshot (display values), Change, diff, status/date formatting
├── storage.py      Excel workbooks: naming, lookup, reading, atomic appends
├── monitor.py      orchestration: fetch -> compare -> append, wait for readiness
├── report.py       console summary, text report, opening files
├── config.py       TOML configuration: loading, validation, writing, adding
├── state.py        last-run summary (state.json) and single-instance lock
├── autostart.py    Windows Startup shortcut (created through PowerShell/WScript)
└── paths.py        per-user folders for configuration, logs and state
tests/              pytest suite (one file per module) + fixtures in conftest.py
docs/               this documentation (Sphinx + MyST Markdown)
```

## Architecture

```text
config.toml ──> Config ──> Monitor.run()
                              │
                              ├── TrackerClient.fetch(uuid) ──> JSON ──> Snapshot.from_api()
                              ├── storage.find_workbook(base manuscript number)
                              ├── diff_snapshots(last row, snapshot) ──> [Change]
                              └── storage.append_record(...)      (only if something changed)
                           RunSummary ──> report.write_report() / open_path()
                                      └─> state.save_last_run()
```

Key design decisions:

- **Display values everywhere.** A `Snapshot` stores strings exactly as the official
  page shows them. Comparisons are plain string comparisons and survive a round trip
  through Excel (numbers are written as numbers but normalised back to strings).
- **Workbook key = base manuscript number.** Revisions (`R1`, `R2`...) share the
  workbook. The file name contains journal and title for readability only.
- **Metadata columns** (`Detected at`, `Tracker URL`) are never compared.
- **Schema evolution.** New columns are appended to the header of existing
  workbooks, so files written by older versions keep working.
- **Fail soft.** Errors are captured per submission and reported; a run never stops
  half-way because of one submission.

## Coding conventions

- Python 3.10+, `from __future__ import annotations`, type hints everywhere.
- Formatting and linting with Ruff (line length 100); configuration in
  `pyproject.toml`.
- Google-style docstrings for public functions and classes (they feed the API page).
- Everything in English: code, comments, messages, documentation.
- Keep runtime dependencies minimal (`requests`, `openpyxl`, `tomli` on 3.10).
- User-facing messages must say what happened **and** what to do next.

## Privacy rules

Tracking links give access to the status of a manuscript, so they are personal.

- Never commit tracking UUIDs, workbooks, reports, logs or configuration files. Use
  the public demo UUID `00000000-0000-0000-0000-000000000000` or obviously fake UUIDs
  (`11111111-2222-3333-4444-555555555555`) in tests and documentation.
- `tests/test_repository_hygiene.py` fails if a tracked file contains another UUID
  or a data file.

## Documentation

The documentation is written in MyST Markdown and built with Sphinx and the Read the
Docs theme. The API page is generated from the docstrings. Read the Docs builds it
from `.readthedocs.yaml`; to publish it, import the GitHub repository at
<https://readthedocs.org/dashboard/import/>.

## Releasing

1. Update the version in `src/paper_status_monitor/_version.py` and move the
   *Unreleased* entries of `CHANGELOG.md` to a new section.
2. Commit, then create a tag and a GitHub release named `vX.Y.Z`.
3. The `release` workflow builds the distribution and publishes it to PyPI with
   [trusted publishing](https://docs.pypi.org/trusted-publishers/).

One-time PyPI set-up: on <https://pypi.org/manage/account/publishing/>, add a
*pending publisher* with project name `paper-status-monitor`, owner
`dsanchez-garcia`, repository `paper-status-monitor`, workflow `release.yml` and
environment `pypi`.

