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

## Contract test

The tracker endpoint is undocumented, so `tests/test_contract.py` checks, against
the real service, that the demo record still has the fields and types this package
reads, that it still converts like the official page, that the stored copy used by
the offline tests (`tests/data/demo_submission.json`) is up to date, and that an
unknown submission still answers HTTP 404. These tests are marked `network` and
deselected by default; run them with `python -m pytest -m network`.

The `contract.yml` workflow runs them every Monday, and on demand from the *Actions*
tab. If they fail twice, 15 minutes apart, it opens an issue labelled
`contract-test`, or comments on the open one. GitHub disables scheduled workflows in
repositories without activity for 60 days; re-enable it from the *Actions* tab.

## Project layout

```text
src/paper_status_monitor/
├── __init__.py     public API (re-exports)
├── __main__.py     python -m paper_status_monitor
├── _version.py     single source of the version number
├── cli.py          argparse CLI: init, add, remove, enable, disable, list, summary,
│                   check, run, organize, gui, autostart, doctor
├── client.py       HTTP client for the tracker JSON endpoint, UUID parsing, errors
├── models.py       Snapshot (display values), Change, diff, status/date formatting
├── naming.py       workbook_name templates: placeholders, custom fields, file names
├── storage.py      Excel workbooks: lookup by content, reading, atomic appends, merging
├── monitor.py      orchestration: fetch -> compare -> record / notify, wait for readiness
├── organize.py     rename and merge existing workbooks to follow the template
├── report.py       console summary, text report, publishing (open it, notify)
├── notifications.py desktop notifications: Windows toasts, osascript, notify-send
├── scheduling.py   periodic checks (run --every): intervals and the wall-clock loop
├── summary.py      one table with the latest status of every submission
├── config.py       TOML configuration: loading, validation, writing, adding
├── state.py        last-run summary, single-instance lock, last state seen per submission
├── gui.py          graphical interface: entry points and widget-free logic
├── _gui_app.py     tkinter widgets of the graphical interface (imported lazily)
├── autostart.py    Windows Startup shortcut (created through PowerShell/WScript)
├── _powershell.py  runs Windows PowerShell scripts without a console window
└── paths.py        per-user folders for configuration, logs and state
tests/              pytest suite (one file per module) + fixtures in conftest.py
docs/               this documentation (Sphinx + MyST Markdown)
```

## Architecture

```text
config.toml ──> Config ──> Monitor.run()
                              │
                              ├── TrackerClient.fetch(uuid) ──> JSON ──> Snapshot.from_api()
                              ├── naming.workbook_file_name(template, snapshot, submission)
                              ├── WorkbookStore.locate(key, uuid, name) ──> last row of the submission
                              ├── diff(last row, snapshot)  ∩ recorded columns ──> append a row?
                              ├── diff(last seen, snapshot) ∩ notified columns ──> report?
                              └── storage.append_record(...) and SeenSnapshots.update(...)
                           RunSummary ──> report.publish_report() ──> open_path()
                                      │                           └─> notifications
                                      └─> state.save_last_run()
```

Key design decisions:

- **Display values everywhere.** A `Snapshot` stores strings exactly as the official
  page shows them. Comparisons are plain string comparisons and survive a round trip
  through Excel (numbers are written as numbers but normalised back to strings).
- **History key = base manuscript number.** Revisions (`R1`, `R2`...) share the
  history; rows are matched by base manuscript number or tracking link, never by
  title. The `workbook_name` template only names *new* workbooks, and several
  submissions may share one; existing histories are found by content and never
  split (`organize` renames and merges them on request).
- **Record and notify are independent.** Rows are added from the comparison with the
  last row of the submission; reports come from the comparison with the last state
  seen (`.paper-status-monitor.json` in the data folder), so a change that is
  reported but not recorded is reported once.
- **Metadata columns** (`Detected at`, `Tracker URL`, custom fields) are never compared.
- **Schema evolution.** New columns are appended to the header of existing
  workbooks, so files written by older versions keep working.
- **Fail soft.** Errors are captured per submission and reported; a run never stops
  half-way because of one submission.
- **Periodic checks are a loop around one run.** `run --every` re-reads the
  configuration and takes the lock for each check only, and waits against the wall
  clock, so that sleep, hibernation and clock changes are handled.
- **The CLI edits the configuration in place.** `add`, `remove`, `disable` and
  `enable` change only the lines of one submission, then parse the result and refuse
  to write it unless it is exactly the expected configuration, so comments are kept
  without a TOML library that preserves them. The GUI rewrites the file instead.
- **The GUI is a thin layer.** `gui.py` holds the logic that does not need a display
  (and is tested everywhere); `_gui_app.py` only builds tkinter widgets and calls the
  same functions as the CLI. Tk tests are skipped where no display is available.

## Coding conventions

- Python 3.10+, `from __future__ import annotations`, type hints everywhere.
- Formatting and linting with Ruff (line length 100); configuration in
  `pyproject.toml`.
- Google-style docstrings for public functions and classes (they feed the API page).
- Everything in English: code, comments, messages, documentation.
- Keep runtime dependencies minimal (`requests`, `openpyxl`, `tomli` on 3.10). The
  graphical interface uses `tkinter` from the standard library only.
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

