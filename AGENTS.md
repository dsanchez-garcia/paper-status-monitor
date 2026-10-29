# AGENTS.md

Guidance for AI coding agents (GitHub Copilot, Claude, Codex, Cursor...) and human
contributors working on this repository. Read it before changing anything.

## Project in one paragraph

`paper-status-monitor` is a small Python CLI (with an optional tkinter window) that
monitors the peer-review status of Elsevier manuscripts. It fetches the JSON record
behind the official *Track your submission* page
(`https://track.authorhub.elsevier.com/?uuid=<uuid>`), converts it to the values the
page displays, compares them with the last row recorded for the submission in an
Excel workbook, appends a row when a *recorded* column changed and writes a
plain-text report (opened, or announced with a desktop notification) when a
*notified* column changed. It is meant to run unattended at login (a Startup
shortcut on Windows, an XDG autostart entry on Linux or a launchd agent on macOS,
optionally checking again every few hours) and must therefore be robust and never
fail silently.

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
| `src/paper_status_monitor/naming.py` | `workbook_name` templates: placeholders, custom fields, file names. |
| `src/paper_status_monitor/storage.py` | `WorkbookStore` (lookup by content, cache), reading, atomic appends, merging, the optional `Time in status` sheet. |
| `src/paper_status_monitor/timeline.py` | `status_periods`, `total_days`: periods of time in each status, for the `Time in status` sheet. |
| `src/paper_status_monitor/monitor.py` | `Monitor`: fetch → compare → record/notify; `RunSummary`; readiness wait. |
| `src/paper_status_monitor/organize.py` | Plan and apply renames, merges and splits of existing workbooks (`organize`). |
| `src/paper_status_monitor/report.py` | Console summary, text report, `publish_report` (opens it and/or shows a notification), opening files. |
| `src/paper_status_monitor/notifications.py` | Desktop notifications: Windows toasts (through PowerShell), `osascript`, `notify-send`. |
| `src/paper_status_monitor/emails.py` | E-mail notifications through SMTP (`[email]` table); the password comes only from the environment or the system keyring. |
| `src/paper_status_monitor/scheduling.py` | `run --every`: interval parsing and the wall-clock loop. |
| `src/paper_status_monitor/tray.py` | `run --every --tray`: icon in the notification area (Windows) — tooltip, menu, icon pixels and commands, without Windows code. |
| `src/paper_status_monitor/_tray_win32.py` | ctypes window code of that icon (hidden window, message loop thread, `Shell_NotifyIconW`); imported only when shown. |
| `src/paper_status_monitor/summary.py` | `summary`: one table with the latest status of every submission (text, Markdown, HTML). |
| `src/paper_status_monitor/export.py` | `export`: the recorded history as CSV or JSON, without the tracking links unless asked for. |
| `src/paper_status_monitor/config.py` | TOML configuration: load, validate, write (`save_config`), edit in place keeping comments (`add_submission`, `edit_submission`, `remove_submission`, `set_submission_enabled`). |
| `src/paper_status_monitor/state.py` | `state.json`, the `run.lock` lock, `SeenSnapshots` (last state seen, in `data_dir`). |
| `src/paper_status_monitor/i18n.py` | Translations: `_` / `ngettext` / `N_`, `column_label`, `set_language` (process) and `language()` (thread). |
| `src/paper_status_monitor/locales/` | One catalog per language (`es.py`): `MESSAGES` (English text to translation) and `plural`. |
| `src/paper_status_monitor/gui.py` | GUI entry points and widget-free logic (testable without a display). |
| `src/paper_status_monitor/_gui_app.py` | tkinter widgets of the GUI; imported only when the window opens. |
| `src/paper_status_monitor/autostart.py` | Launchers at login (optionally with `--every`): Windows Startup shortcut via PowerShell/WScript.Shell, XDG autostart entry (Linux), launchd agent (macOS). |
| `src/paper_status_monitor/_powershell.py` | Runs PowerShell scripts without a console window (autostart, toasts). |
| `src/paper_status_monitor/paths.py` | Per-user folders for config, logs, state. |
| `src/paper_status_monitor/cli.py` | argparse CLI and `doctor`. |
| `src/paper_status_monitor/_version.py` | The only place where the version is written. |
| `tests/` | pytest suite; fixtures and the `FakeClient` live in `tests/conftest.py`; `test_contract.py` checks the real tracker (`-m network`). |
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
  4 → `Required Reviews Complete`, anything else → `Review Complete`. What the codes
  mean in practice is only known from observations, listed in `docs/how-it-works.md`
  (*Statuses observed in practice*).
- Revision `n > 0`: title shown as `[<ordinal> revision] <title>`, manuscript number
  `<PubdNumber>R<n>`.
- Dates: Unix seconds formatted as `17th May 2022` in **local** time (like the
  browser). Month names are hard-coded in English; do not use locale-dependent
  `strftime("%B")`.
- History key: **base manuscript number** (without `R<n>`), plus the tracking UUID.
  Rows of a submission are recognised by their content (`Manuscript number` base or
  `Tracker URL`), never by the title — deriving the key from the title was the bug
  that created one file per revision. Rows without any identifier belong to the
  workbook named after the key (`<key>.xlsx`, `<key> - *.xlsx`, `<key> (*.xlsx`).
- Workbook names come from the `workbook_name` template (`naming.py`); the default
  `{manuscript_number} - {journal} - {title}` reproduces the 0.1 names. Several
  submissions may share a workbook (e.g. `"{paper}"`): always use the last row **of
  the submission**, not of the workbook. A history is never split: the template only
  names new workbooks; `organize` renames, merges or splits existing workbooks
  (backups first, workbooks in use or with unknown rows left alone), always moving
  whole histories.
- Columns: `models.COLUMNS`, plus one column per custom field (`paper` → `Paper`).
  `Detected at`, `Tracker URL` and custom fields are metadata and are never compared.
- Record vs notify are independent: rows are added when a column in
  `Config.recorded_columns_for(submission)` differs from the last row of the
  submission; changes are reported when a column in
  `Config.notified_columns_for(submission)` differs from the last state seen
  (`SeenSnapshots`, `<data_dir>/.paper-status-monitor.json`), which falls back to the
  last row. Update the state only after a successful check, never in dry runs.
  `ignore_fields` is the old name of `notify_ignore`. A submission's own
  `record_*`/`notify_*` keys (`SubmissionConfig.overrides`) each replace the general
  setting of the same name; the `run` options replace both.
- How news is announced is the `notify` setting: `"report"` (open the report),
  `"toast"` (desktop notification), `"email"` (send the report through SMTP), a list
  or `"none"`; the report is always written.
  `open_report = true/false` is its former name (`"report"` / `"none"`); using both
  names is an error. Notifications are best effort: failures are logged, never raised.
- `run --every` repeats complete runs: it takes the run lock only during each check,
  re-reads the configuration every time (keeping the previous one if it became
  invalid), waits against the wall clock (sleep, hibernation, clock changes) and
  refuses intervals below `scheduling.MIN_INTERVAL` (one hour), to keep the load on
  the tracker negligible. Only one loop runs per user: `state.periodic_checks_lock`
  holds an operating-system lock on `periodic.lock` (released when the process ends,
  so it never goes stale; never use `os.kill(pid, 0)`, which kills on Windows).
- `run --every --tray` (and `autostart enable --every --tray`) shows an icon in the
  notification area on Windows. Its window runs its own message loop in a separate
  thread; the menu only sets the `wake` / `stop` events of `scheduling.run_every`,
  opens files or starts the GUI in a new process. The icon is optional: if it
  cannot be shown, the problem is logged and the checks go on.
- The CLI edits the configuration in place (`add`, `edit`, `remove`, `disable`,
  `enable`): only the lines of one `[[submissions]]` table change, and the result is
  written only if parsing it gives exactly the expected configuration (unusual
  layouts are refused, never guessed). The GUI rewrites the whole file with
  `save_config` (keeping a `.bak`).
- Existing workbooks may have older headers: append missing columns, never reorder
  or delete user columns.
- The optional `Time in status` sheet (`time_in_status`) is derived data, rebuilt from
  the history at every append and merge (and then kept up to date even if the setting
  is off). It is recognised by the `Written by paper-status-monitor` note in `A2`: a
  user sheet with the same name is never touched, and `_history_sheet` never returns
  it. Ongoing periods use Excel formulas (`NOW()`, `SUMIFS`): never rewrite a
  workbook just to refresh them.
- A 404 for a submission that already has a workbook is recorded once as
  `No longer available in the tracker`.
- Language (`language`, `i18n.LANGUAGES`): reports, notifications, e-mails, the
  summary and the GUI are translated; the workbooks (column names, the `Time in
  status` sheet), tracker values, exports, the configuration file, the CLI and error
  messages of the lower layers stay in English, and log messages are never wrapped
  in `_()`. Documents are rendered inside
  `with i18n.language(config.language):` (thread-local: `publish_report`, the CLI
  `summary` and `email test`); the GUI calls `i18n.set_language` (whole process).
  Never compare or store translated texts: compare the English column names.

## Conventions

- Python ≥ 3.10, `from __future__ import annotations`, full type hints.
- Ruff, line length 100. Google-style docstrings on public objects (they build the
  API docs).
- **Everything in English**: code, identifiers, comments, messages, docs, commits.
  The only exception are the translation catalogs in `locales/`.
- Texts of reports, notifications, e-mails, the summary and the GUI are wrapped for
  translation: `_("Saved {path}").format(path=...)` (literal message, named
  placeholders, never an f-string inside `_()`), `ngettext(...)` for counts, `N_()`
  for module constants translated when shown, `column_label()` for column names.
  Update `locales/es.py` in the same change: `tests/test_i18n.py` fails on missing,
  unused or inconsistent translations. Do not use `_` as a throwaway variable in
  modules that import it.
- Minimal dependencies (`requests`, `openpyxl`, `tomli` on 3.10). Do not add
  Selenium, pandas or third-party GUI toolkits: the GUI uses the standard-library
  `tkinter` only, imported lazily so that the CLI never needs it.
- Keep GUI logic that does not need widgets in `gui.py` (tested everywhere) and the
  widgets in `_gui_app.py`; the GUI must call the same functions as the CLI.
- Errors shown to users must explain what happened and what to do next.
- Unattended runs must not crash: capture errors per submission and report them.
- Keep the CLI, the GUI, the docs (`docs/cli.md`, `docs/configuration.md`,
  `docs/gui.md`) and the README in sync when you add or change options.

## Testing rules

- Tests must not touch the network or the real user folders. The autouse fixture in
  `tests/conftest.py` redirects `HOME`, `APPDATA`, `LOCALAPPDATA` and XDG folders.
- Use `FakeClient` (fixture `fake_client`) and `make_payload(...)` to simulate the
  tracker; use `Clock` (fixture `clock`) for deterministic timestamps.
- Use `tz=timezone.utc` when asserting formatted dates.
- Tests that need the real API must be marked `@pytest.mark.network`; they live in
  `tests/test_contract.py`, and the weekly `contract.yml` workflow runs them and opens
  an issue when they fail.
- Never show real desktop notifications in tests: monkeypatch `notifications.show`,
  `subprocess.run` or `_powershell.run_script` (and `sys.platform`). Never show a
  real tray icon either: give `tray.TrayIcon` a fake `backend`, or monkeypatch
  `_tray_win32._notify` and `_tray_win32._choose_from_menu`.
- Never send real e-mails or touch the developer's keyring: the autouse fixture
  blocks `smtplib` and the keyring; use the `smtp` and `fake_keyring` fixtures.
- Platform-specific behaviour is tested on every system by monkeypatching
  `sys.platform` (and `autostart._run_powershell` for Windows): XDG entries and
  launchd agents are written to the temporary home folder; real PowerShell tests are
  skipped elsewhere.
- GUI tests build the real window hidden, with `synchronous=True` and stubbed message
  boxes (see `tests/test_gui.py`); they are skipped where Tk cannot open a window.
  Output capturing is suspended while a Tk window exists, because pytest's
  file-descriptor capture makes Tcl fail randomly on Windows.

## Privacy and security (hard rules)

- Tracking links are personal. Never commit real UUIDs, workbooks (`*.xlsx`),
  reports (`changes_*.txt`), logs, `config.toml` (or its `.bak` copy), `state.json`,
  `.paper-status-monitor.json` or private notes (`*.local.md`).
- In examples use the demo UUID or obviously fake ones
  (`11111111-2222-3333-4444-555555555555`, `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`).
- Observations of real submissions (for example the statuses observed in
  `docs/how-it-works.md`) must be anonymised: no manuscript numbers, titles,
  journals, authors, dates or tracking links.
- Examples in docs, messages and tests must be fictional: never take labels, custom
  fields, topics, titles, journals, acronyms or dates from the maintainer's real
  submissions (workbooks, reports, `config.toml`). Use the demo record, the
  `Journal of Examples` (`ABC-D-26-00001`) and papers called `Tau` or `Epsilon`.
- `tests/test_repository_hygiene.py` enforces this on tracked files; do not weaken it.
  Windows GUIDs look like UUIDs too: build them from parts in the code, as
  `notifications._FOLDERID_SYSTEM` does, instead of allowing them in the test.
- Never store credentials in code or config files. The SMTP password is read only
  from `PAPER_STATUS_MONITOR_SMTP_PASSWORD` or the system keyring (`emails.py`), and
  a `password` key in the `[email]` table is refused: keep it that way.

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

