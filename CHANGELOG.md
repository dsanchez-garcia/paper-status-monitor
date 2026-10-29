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
- Custom fields per submission (`fields = { paper = "Tau" }` or
  `add --field paper=Tau`), usable as placeholders and written to extra columns.
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
- `edit` command: change the label (`--label`) or the custom fields (`--field`,
  `--remove-field`, `--clear-fields`) of a submission. Like `remove`, it edits the
  configuration in place, keeping its comments, and refuses changes that would make
  it invalid; it reminds you to run `organize` when the workbook names depend on what
  changed.
- **Autostart on Linux and macOS**: `autostart enable` now also works on Linux, with
  an XDG autostart entry (`~/.config/autostart/paper-status-monitor.desktop`) started
  by the desktop environment at login, and on macOS, with a launchd agent
  (`~/Library/LaunchAgents/io.github.paper-status-monitor.plist`). The options
  (`--wait`, `--every`), `autostart status`, `doctor` and the window work as on
  Windows. On Linux, `enable` warns when no graphical session is found.
- **Own record and notify settings for a submission**: a `[[submissions]]` table can
  have its own `record_fields`, `record_ignore`, `notify_fields` or `notify_ignore`,
  each replacing the general setting of the same name for that submission (for
  example, report only the changes of status of one of them). Set them with
  `edit --notify-fields Status` (`general` or `--use-general-settings` remove them) or
  in the window (*What is recorded and notified* in the submission form; a `*` marks
  them in the list). `list` and `doctor` show them, and the options of `run` replace
  them for one run.
- **Time in each status**: with `time_in_status = true` (or a tick box in the
  *Workbooks* tab of the window), every workbook gets a `Time in status` sheet with
  the periods that each submission spent in each status (from, to, days) and the
  total days in each one. The days of the current status are Excel formulas, so they
  stay up to date without rewriting the workbook; the sheet is rebuilt after every
  change and by `organize`, and a user sheet with the same name is never touched.
- `organize` splits a workbook whose submissions now go to different workbooks (for
  example, after changing `workbook_name` from `"{paper}"` to `"{paper} - {journal}"`):
  the rows of every submission move to its workbook, a copy of the original or an
  existing workbook (in chronological order), after a backup. Workbooks that are open
  in Excel, or that hold rows of submissions that are not configured, are left alone.
- `export` command: the recorded history of every submission as CSV (one row per
  observed state) or JSON (grouped by submission), read from the workbooks, without
  the tracking links unless `--include-links` is given. The window has an *Export...*
  button.
- A second loop of periodic checks is refused while another one runs (for example,
  a `run --every` typed in a terminal while the one started at login runs), with a
  message that names the process; `doctor` shows it. The lock is held by the
  operating system, so it is released even if the process crashes.
- **E-mail notifications**: `notify = "email"` (alone or in a list) sends the report
  of every run with news through your SMTP server, set in a new `[email]` table
  (`smtp_host`, `security`, `smtp_port`, `username`, `sender`, `to`). The password is
  never stored in the configuration (a `password` setting is refused): it comes from
  the `PAPER_STATUS_MONITOR_SMTP_PASSWORD` environment variable or from the system
  keyring, through the optional `keyring` extra and `email set-password`. The new
  `email test` command sends a test message, `doctor` checks the settings, `run
  --notify email` works for one run, and the window has a *Send the report by
  e-mail* option with *Settings...* and *Test*.
- Documentation: *Statuses observed in practice* (in *How it works*) gathers the
  status codes and sequences of statuses seen on real submissions, anonymised. For
  example, *Review Complete* is also shown as soon as a revision reaches the
  tracker, before reviewers are invited.
- **Buttons in the Windows notifications**: *Open report*, *Open workbook* and
  *Tracking page* when one submission has news; *Open report* and *Open workbook*
  (or *Open folder*) when several have news. They use protocol activation, so
  nothing is registered and no program keeps running.
- **Reports and window in Spanish**: the new `language` setting (`"en"`, the default,
  or `"es"`) translates the change reports, the desktop notifications, the e-mails,
  the summary and the whole graphical interface, where it can also be changed at
  the bottom of the window (the window is rebuilt at once, keeping what you typed).
  `init --language es` writes it, and `doctor` shows it. The workbooks (their column
  names), the values shown by the tracker, the exports and the command
  line stay in English. Translations live in `paper_status_monitor/locales/`, and a
  test checks that they are complete.
- **An icon in the notification area** (Windows) while the periodic checks run:
  `run --every 12h --tray`, `autostart enable --every 12h --tray`, or the new tick
  box in the window. Its tooltip says when the last check ran and when the next one
  is due; its menu lists the latest status of every submission and can check now,
  open the window, the last report or the data folder, and stop the checks. It needs
  no extra package (the Windows API is used through `ctypes`).

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
- `autostart status` shows `Launcher:` instead of `Shortcut:`, and the Python class
  `autostart.ShortcutInfo` is now `autostart.LauncherInfo` (the old name still works).
- Messages with a number use the singular or the plural as needed ("Checked 1
  submission", "(1 row)") instead of "submission(s)" or "row(s)".

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

[Unreleased]: https://github.com/dsanchez-garcia/paper-status-monitor/compare/b3549f1ab4f7a05d41457277c829f113c67e163d...HEAD
[0.1.0]: https://github.com/dsanchez-garcia/paper-status-monitor/tree/b3549f1ab4f7a05d41457277c829f113c67e163d

