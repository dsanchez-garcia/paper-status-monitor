# AGENTS.md

Guidance for AI coding agents (GitHub Copilot, Claude, Codex, Cursor...) and human
contributors working on this repository. Read it before changing anything.

## Project in one paragraph

`paper-status-monitor` is a small Python CLI that monitors the peer-review status of
Elsevier manuscripts. It fetches the JSON record behind the official *Track your
submission* page (`https://track.authorhub.elsevier.com/?uuid=<uuid>`), converts it
to the values the page displays, compares them with the last row of an Excel
workbook (one workbook per manuscript and journal), appends a row when something
changed and writes a plain-text report. It is meant to run unattended at login
(Windows Startup shortcut) and must therefore be robust and never fail silently.

## Quick commands

```console
python -m pip install -e ".[dev,docs]"                     # set-up (use a venv)
python -m pytest                                           # tests (no network)
python -m pytest -m network                                # contract test, real API
ruff check . && ruff format --check .                      # lint + format check
sphinx-build -W --keep-going -b html docs docs/_build/html # docs, warnings = errors
python -m build && twine check --strict dist/*             # packaging
```

Every change must keep all four green: tests, ruff check, ruff format, docs build.

## Repository map

| Path | Responsibility |
| --- | --- |
| `src/paper_status_monitor/client.py` | HTTP client (`TrackerClient`), endpoint URL, `parse_uuid`, error classes. |
| `src/paper_status_monitor/models.py` | `Snapshot`, `Change`, `diff_snapshots`, column names, status/date formatting. |
| `src/paper_status_monitor/storage.py` | Workbook naming, lookup, reading and atomic appends (openpyxl). |
| `src/paper_status_monitor/monitor.py` | `Monitor`: fetch → compare → append; `RunSummary`; waiting for readiness. |
| `src/paper_status_monitor/report.py` | Console summary, text report, opening files. |
| `src/paper_status_monitor/config.py` | TOML configuration: load, validate, write, append submissions. |
| `src/paper_status_monitor/state.py` | `state.json` (last run) and the `run.lock` single-instance lock. |
| `src/paper_status_monitor/autostart.py` | Windows Startup shortcut via PowerShell/WScript.Shell. |
| `src/paper_status_monitor/paths.py` | Per-user folders for config, logs, state. |
| `src/paper_status_monitor/cli.py` | argparse CLI and `doctor`. |
| `src/paper_status_monitor/_version.py` | The only place where the version is written. |
| `tests/` | pytest suite; fixtures and the `FakeClient` live in `tests/conftest.py`. |
| `docs/` | Sphinx + MyST documentation published on Read the Docs. |
| `TODO.md` | Prioritised backlog. Pick tasks from here and update it. |
| `CHANGELOG.md` | Keep a Changelog format. Add every user-visible change under *Unreleased*. |

Local, git-ignored folders you may see in the author's working copy (`SS/`,
`Monitoring files/`, `.idea/`) contain personal data and legacy scripts. **Never read
them into commits, tests or docs.** Files named `*.local.md` (for example
`MAINTAINER_TODO.local.md`, the maintainer's private list of manual tasks) are
git-ignored personal notes: you may read them for context, but never commit them or
copy their content into tracked files.

## Domain knowledge (do not break these rules)

- API: `GET https://tnlkuelk67.execute-api.us-east-1.amazonaws.com/tracker/<uuid>`
  returns JSON; unknown or finished submissions return **404**. The UUID
  `00000000-0000-0000-0000-000000000000` is a public, fictional demo record.
- Status label (mirrors the page's JavaScript): code 3 or 23 → `Under Review`,
  4 → `Required Reviews Complete`, anything else → `Review Complete`.
- Revision `n > 0`: title shown as `[<ordinal> revision] <title>`, manuscript number
  `<PubdNumber>R<n>`.
- Dates: Unix seconds formatted as `17th May 2022` in **local** time (like the
  browser). Month names are hard-coded in English; do not use locale-dependent
  `strftime("%B")`.
- Workbook key: **base manuscript number** (without `R<n>`). Lookup matches
  `<key>.xlsx`, `<key> - *.xlsx` and `<key> (*.xlsx` (sync-client duplicates). Never
  derive the key from the title — that was the bug that created one file per
  revision.
- Columns: `models.COLUMNS`. `Detected at` and `Tracker URL` are metadata and are
  never compared. Changes in `ignore_fields` are recorded but not reported.
- Existing workbooks may have older headers: append missing columns, never reorder
  or delete user columns.
- A 404 for a submission that already has a workbook is recorded once as
  `No longer available in the tracker`.

## Conventions

- Python ≥ 3.10, `from __future__ import annotations`, full type hints.
- Ruff, line length 100. Google-style docstrings on public objects (they build the
  API docs).
- **Everything in English**: code, identifiers, comments, messages, docs, commits.
- Minimal dependencies (`requests`, `openpyxl`, `tomli` on 3.10). Do not add
  Selenium, pandas or GUI toolkits.
- Errors shown to users must explain what happened and what to do next.
- Unattended runs must not crash: capture errors per submission and report them.
- Keep the CLI, the docs (`docs/cli.md`, `docs/configuration.md`) and the README in
  sync when you add or change options.

## Testing rules

- Tests must not touch the network or the real user folders. The autouse fixture in
  `tests/conftest.py` redirects `HOME`, `APPDATA`, `LOCALAPPDATA` and XDG folders.
- Use `FakeClient` (fixture `fake_client`) and `make_payload(...)` to simulate the
  tracker; use `Clock` (fixture `clock`) for deterministic timestamps.
- Use `tz=timezone.utc` when asserting formatted dates.
- Tests that need the real API must be marked `@pytest.mark.network`.
- Windows-only behaviour is tested by monkeypatching `sys.platform` and
  `autostart._run_powershell`; real PowerShell tests are skipped elsewhere.

## Privacy and security (hard rules)

- Tracking links are personal. Never commit real UUIDs, workbooks (`*.xlsx`),
  reports (`changes_*.txt`), logs, `config.toml`, `state.json` or private notes
  (`*.local.md`).
- In examples use the demo UUID or obviously fake ones
  (`11111111-2222-3333-4444-555555555555`, `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`).
- `tests/test_repository_hygiene.py` enforces this on tracked files; do not weaken it.
- Never store credentials in code or config files (future e-mail/notification
  features must read secrets from the environment or the OS keyring).

## Definition of done

1. Tests added or updated; `python -m pytest` passes.
2. `ruff check .` and `ruff format --check .` pass.
3. Docs updated and `sphinx-build -W` passes.
4. `CHANGELOG.md` updated under *Unreleased*; `TODO.md` updated if a task was done or
   discovered.
5. No personal data in the diff.

## Releasing

Bump `_version.py`, update `CHANGELOG.md`, commit, then publish a GitHub release
`vX.Y.Z`; `.github/workflows/release.yml` uploads to PyPI via trusted publishing.
Details in `docs/development.md`.

