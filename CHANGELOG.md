# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

