# paper-status-monitor

[![CI](https://github.com/dsanchez-garcia/paper-status-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/dsanchez-garcia/paper-status-monitor/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/paper-status-monitor/badge/?version=latest)](https://paper-status-monitor.readthedocs.io/en/latest/)
[![PyPI](https://img.shields.io/pypi/v/paper-status-monitor.svg)](https://pypi.org/project/paper-status-monitor/)
[![Python versions](https://img.shields.io/pypi/pyversions/paper-status-monitor.svg)](https://pypi.org/project/paper-status-monitor/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Monitor the peer-review status of your Elsevier submissions and keep one Excel history per manuscript.**

Elsevier journals send authors a *Track your submission* link
(`https://track.authorhub.elsevier.com/?uuid=...`) that shows the review status of a
manuscript: reviewers invited, reviews completed, last review activity, revision
number... `paper-status-monitor` checks those pages for you — for example every time
you log in — records every change in an Excel workbook and opens a short report when
something changes.

```text
Paper status monitor - report
Run started: 2026-10-21 08:55:12

------------------------------------------------------------------------
CHANGES (1)
------------------------------------------------------------------------

[1st revision] A study of something important
  - Status: 'Under Review' → 'Required Reviews Complete'
  - Reviews completed: '1' → '2'
  Journal: Journal of Examples
  Manuscript number: ABC-D-26-00001R1
  Tracker: https://track.authorhub.elsevier.com/?uuid=...
  Workbook: C:\Users\me\Documents\paper-status-monitor\ABC-D-26-00001 - Journal of Examples - A study of something important.xlsx
```

## Features

- **No browser needed** – reads the same JSON data as the official tracking page
  (no Selenium, ChromeDriver or Chrome).
- **One workbook per manuscript and journal** – every revision (R1, R2, …) is appended
  to the same `.xlsx` file, with a `Detected at` timestamp for every change.
- **Change reports** – a plain-text report is written (and optionally opened) only
  when something changes, a new submission is tracked or a check fails.
- **Runs at login on Windows** – `paper-status-monitor autostart enable` adds a
  windowless launcher to your Startup folder; it waits for the network and for cloud
  drives such as Google Drive or OneDrive to be ready.
- **Robust** – retries on network errors, atomic workbook writes, a lock against
  concurrent runs, a rotating log file and a `doctor` command to diagnose problems.
- **Detects the end of tracking** – when the tracker stops returning data for a
  submission (usually after a final decision) the change is recorded once.

## Quick start

```console
pip install paper-status-monitor

paper-status-monitor init --data-dir "C:\Users\me\Documents\Paper status"
paper-status-monitor add "https://track.authorhub.elsevier.com/?uuid=<your-uuid>" --label "My paper"
paper-status-monitor run
paper-status-monitor autostart enable      # Windows: check at every login
```

Try it first with the public demo submission served by the tracker:

```console
paper-status-monitor check 00000000-0000-0000-0000-000000000000
```

## Commands

| Command | Purpose |
| --- | --- |
| `init` | Create a commented configuration file. |
| `add LINK` | Add a submission (tracking link or UUID). |
| `list` | Show the configured submissions and their last recorded status. |
| `check LINK` | Show the current status of one submission without saving anything. |
| `run` | Check every submission, update the workbooks and write a report. |
| `autostart enable/disable/status` | Run automatically at login (Windows). |
| `doctor` | Diagnose configuration, connectivity and autostart problems. |

See the [documentation](https://paper-status-monitor.readthedocs.io) for the
configuration reference, the workbook format, autostart on Linux and macOS, and
troubleshooting.

## Privacy and responsible use

- Your tracking links are personal: anyone with the link can see the status of your
  manuscript. They are stored only in your local configuration file, and the
  workbooks and reports stay on your computer.
- The tool only reads the status of submissions you configure, at a low frequency
  (typically once per login). Please keep it that way.
- This project is **not affiliated with, endorsed by or supported by Elsevier**. It
  relies on an undocumented endpoint that may change at any time.

## Contributing

Bug reports and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
and, if you use an AI coding agent, [AGENTS.md](AGENTS.md). The roadmap lives in
[TODO.md](TODO.md).

## License

[MIT](LICENSE) © Daniel Sánchez-García

