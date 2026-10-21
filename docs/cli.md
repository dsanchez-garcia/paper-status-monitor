# Command-line reference

```text
paper-status-monitor [--version] [-c PATH] [-v] COMMAND ...
```

Global options (before the command):

`--version`
: Print the version and exit.

`-c PATH`, `--config PATH`
: Use this configuration file instead of the default one (see {doc}`configuration`).

`-v`, `--verbose`
: Show debug messages on the console and write them to the log file.

Exit codes: `0` success, `1` at least one submission (or check) failed, `2` usage or
configuration error.

## `init`

Create a commented configuration file.

```console
paper-status-monitor init [--data-dir PATH] [--force]
```

`--data-dir PATH`
: Folder for the workbooks and reports (default `~/Documents/paper-status-monitor`).

`--force`
: Overwrite an existing configuration file.

## `add`

Add a submission to the configuration file.

```console
paper-status-monitor add LINK_OR_UUID [--label TEXT] [--no-verify]
```

The tracker is contacted first to make sure the link works; the title and journal
found are printed. Use `--no-verify` to skip that step (for instance, when offline).

## `list`

Show the configured submissions with their last recorded status and workbook.

## `check`

Show the current status of one submission. Nothing is written.

```console
paper-status-monitor check LINK_OR_UUID [--json]
```

`--json`
: Print the raw JSON record returned by the tracker.

## `run`

Check every enabled submission, append changes to the workbooks, write a report if
there is news and save a summary of the run.

```console
paper-status-monitor run [--wait SECONDS] [--no-open] [--dry-run]
```

`--wait SECONDS`
: Before checking, wait up to `SECONDS` for the data folder to be available and for
  the tracker to be reachable. Useful right after logging in, when the network or a
  cloud drive is not ready yet. The autostart launcher uses `--wait 300`.

`--no-open`
: Do not open the report, even if `open_report = true`.

`--dry-run`
: Fetch and compare, print the changes, but write nothing.

Only one run can be active at a time; a second one exits with an error.

## `autostart`

Manage the Windows Startup shortcut (see {doc}`autostart`).

```console
paper-status-monitor autostart enable [--wait SECONDS]
paper-status-monitor autostart disable
paper-status-monitor autostart status
```

When `--config` is given to `autostart enable`, the shortcut uses that file.

## `doctor`

Diagnose the installation and print one line per check:

```text
[INFO] paper-status-monitor 0.1.0, Python 3.13.1
[ OK ] Configuration: C:\Users\me\AppData\Roaming\paper-status-monitor\config.toml (2 enabled submission(s))
[ OK ] Data folder: C:\Users\me\Documents\Paper status (2 workbook(s))
[ OK ] Tracker reachable (demo submission status: Under Review)
[ OK ] Autostart enabled: paper-status-monitor.lnk -> C:\Python313\pythonw.exe -m paper_status_monitor run --wait 300
[ OK ] Last run: 2026-10-21 08:55:14 (2 checked, 0 changed, 0 failed)
```

The autostart check also verifies that the interpreter used at login can import the
package — the most common reason for silent failures after reinstalling Python.

## Running as a module

Every command is also available as `python -m paper_status_monitor COMMAND`.

