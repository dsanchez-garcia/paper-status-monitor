# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Choose independently which changes are **recorded** (add a row to the workbook)
  and which are **notified** (written to the report): new settings `record_fields`,
  `record_ignore`, `notify_fields` and `notify_ignore`, and the matching `run`
  options `--record-fields`, `--record-ignore`, `--notify-fields` and
  `--notify-ignore`. For example, `notify_ignore = ["Last review activity"]` keeps a
  new review activity date in the workbook without opening a report, and
  `notify_fields = ["Status"]` reports only changes of status.
- The last state seen of every submission is kept in
  `<data_dir>/.paper-status-monitor.json`, so a change that is reported but not
  recorded is reported only once.
- `workbook_name` setting: a template with placeholders (`{manuscript_number}`,
  `{journal}`, `{journal_acronym}`, `{title}`, `{first_author}`,
  `{corresponding_author}`, `{date_of_submission}`, `{submission_year}`, `{label}`)
  and format specifications (`{title:.40}`) for the names of new workbooks.
- Custom fields per submission (`fields = { paper = "TMY" }` or
  `add --field paper=TMY`), usable as placeholders and written to extra columns.
- Submissions whose workbook names coincide share a workbook: with
  `workbook_name = "{paper}"`, all the submissions of a paper to different journals
  are recorded in one file.
- `organize` command: rename or merge existing workbooks to follow the template,
  with a dry run and backups of the merged workbooks.
- Graphical interface in English (`paper-status-monitor gui`, also installed as the
  windowless `paper-status-monitor-gui` command) to manage submissions and custom
  fields, tick what is recorded and notified for every column, choose and preview
  workbook names, organize workbooks, run checks and manage the Windows autostart.
  It uses the standard-library `tkinter` (no new dependency).
- `list` shows the naming template and the custom fields; `doctor` describes what is
  recorded and notified and warns when workbooks do not follow the template; `run`
  tags changes that were recorded without being notified (`[RECORDED]`).
- **Desktop notifications**: the new `notify` setting chooses how you are told about
  news: `"report"` (open the report, as before), `"toast"` (a desktop notification:
  a toast on Windows 10 and 11, `osascript` on macOS, `notify-send` on Linux), both
  (`["report", "toast"]`) or `"none"`. The report is always written. `run --notify`
  overrides it for one run; the window has a *Show a desktop notification* option
  with a *Test* button, and `doctor` warns when notifications cannot be shown.
- **Periodic checks while the computer stays on**: `run --every 12h` keeps running
  and checks again at that interval (minimum one hour), reading the configuration
  again before each check and catching up once after sleep or hibernation.
  `autostart enable --every 12h` makes the program started at login do so, the
  window offers the same, and `autostart status` shows when the checks run.
- `remove`, `disable` (alias `pause`) and `enable` (alias `resume`) commands. They
  edit the configuration in place, keeping its comments, and accept the tracking
  link, the UUID, the label or the number shown by `list`.
- A weekly contract test against the real tracker
  (`.github/workflows/contract.yml`, `tests/test_contract.py`) opens an issue when
  the data format changes.
- `summary` command: one table with the latest status of every submission (since
  when, reviews, last review activity) as text, Markdown or HTML (`--format`,
  `--output`), read from the workbooks. The window has a *Summary* button that can
  also save it. The table does not include the tracking links.

### Changed

- Workbooks are found by their content (manuscript number or tracking link) instead
  of their file name, so renaming a workbook or changing the template never splits a
  history.
- Changes are compared with the last row **of the submission**, so a workbook can
  hold several submissions.
- `ignore_fields` is now called `notify_ignore`; the old name is still accepted.
- The commented configuration written by `init` documents the new settings.
- `open_report` is now called `notify`: `open_report = true` means `notify = "report"`
  and `false` means `notify = "none"`. The old name is still accepted. `run --no-open`
  no longer prevents a desktop notification.
- `run --wait` applies before every check (with `--every`, also after the computer
  wakes up).
- `list` marks paused submissions `[paused]` instead of `[disabled]`.

## [0.1.0] - 2026-10-21

First public release: a complete rewrite of the author's personal monitoring script
as an installable, documented and tested package.

### Added

- `paper-status-monitor` command with the `init`, `add`, `list`, `check`, `run`,
  `autostart` and `doctor` sub-commands (also available as
  `python -m paper_status_monitor`).
- Data is read from the JSON endpoint used by the official *Track your submission*
  page, reproducing the page's rules for status labels, revision prefixes,
  manuscript numbers and dates.
- One Excel workbook per manuscript and journal, keyed by the base manuscript
  number, so every revision is appended to the same file.
- New columns `Detected at`, `Revision`, `Status code` and `Tracker URL`.
- Plain-text change reports (opened automatically), with a local fallback folder
  when the data folder is unavailable.
- Detection of submissions that disappear from the tracker (HTTP 404), recorded once.
- `run --wait` to wait for the network and cloud drives at login; retries with
  back-off; atomic workbook writes; single-instance lock; rotating log file;
  last-run summary.
- Windows autostart through a Startup-folder shortcut that runs `pythonw.exe`
  without a console window, and a `doctor` command that verifies it.
- TOML configuration file with strict validation.
- Documentation for Read the Docs, a pytest suite, GitHub Actions workflows for CI
  and PyPI trusted publishing, and guidance files for AI coding agents.

### Changed

- The status is no longer scraped from the rendered page with Selenium and Chrome.
- Settings and tracking links moved from the source code to a configuration file.

### Removed

- Dependencies on Selenium, webdriver-manager, pandas and Tkinter.

[Unreleased]: https://github.com/dsanchez-garcia/paper-status-monitor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dsanchez-garcia/paper-status-monitor/releases/tag/v0.1.0

