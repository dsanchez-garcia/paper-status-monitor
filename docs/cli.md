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

The command line is in English. The reports, notifications, e-mails and summaries
it produces follow the `language` setting (see {ref}`language`).

## `init`

Create a commented configuration file.

```console
paper-status-monitor init [--data-dir PATH] [--language CODE] [--force]
```

`--data-dir PATH`
: Folder for the workbooks and reports (default `~/Documents/paper-status-monitor`).

`--language CODE`
: Language of the reports, notifications, e-mails, summary and window: `en`
  (English, the default) or `es` (Spanish). It is written as the `language`
  setting.

`--force`
: Overwrite an existing configuration file.

## `add`

Add a submission to the configuration file.

```console
paper-status-monitor add LINK_OR_UUID [--label TEXT] [--field NAME=VALUE ...] [--no-verify]
```

The tracker is contacted first to make sure the link works; the title and journal
found are printed. Use `--no-verify` to skip that step (for instance, when offline).

`--label TEXT`
: Short name shown by `list` and in the reports.

`--field NAME=VALUE`
: Custom field of the submission, repeatable: `--field paper=Tau --field
  project=Thesis`. Custom fields can be used in the workbook names (`{paper}`) and are
  written to extra columns (see {doc}`configuration`).

## `edit`

Change the label, the custom fields or the own record and notify settings of a
submission.

```console
paper-status-monitor edit SUBMISSION [--label TEXT] [--field NAME=VALUE ...]
                                     [--remove-field NAME ...] [--clear-fields]
                                     [--record-fields COLUMNS] [--record-ignore COLUMNS]
                                     [--notify-fields COLUMNS] [--notify-ignore COLUMNS]
                                     [--use-general-settings]
```

`SUBMISSION` is the tracking link, the UUID, the label (case-insensitive) or the
number shown by `list`. The configuration file is edited in place, so your comments
are kept: only the lines of the settings you change are written (they are added after
the link of the submission if they are missing). The previous file is kept as
`config.toml.bak`.

`--label TEXT`
: New label; `--label ""` removes it.

`--field NAME=VALUE`
: Add a custom field or change its value. Repeat it for several fields.

`--remove-field NAME`
: Remove a custom field. Repeat it for several fields.

`--clear-fields`
: Remove every custom field; the fields given with `--field` are then the only ones.

`--record-fields COLUMNS`, `--record-ignore COLUMNS`, `--notify-fields COLUMNS`, `--notify-ignore COLUMNS`
: Give the submission its own setting, which replaces the general setting of the
  same name for it (see {ref}`own-settings`). `COLUMNS` is written as in `run`, and
  `general` removes the own setting, so that the general one applies again.

`--use-general-settings`
: Remove every own setting of the submission; the ones given in the same command are
  then the only ones.

```console
paper-status-monitor edit "Tau paper" --label "Tau" --field paper=Tau --field project=Thesis
paper-status-monitor edit 2 --remove-field project
paper-status-monitor edit 2 --notify-fields Status    # only report changes of status
paper-status-monitor edit 2 --use-general-settings
```

Changes that would make the configuration invalid are refused, for example removing
the only `paper` field while `workbook_name` uses `{paper}`. Existing workbooks keep
their names: when the template uses the label or a field that changed, `edit` reminds
you to run [`organize`](#organize).

## `remove`, `disable` and `enable`

Remove a submission from the configuration, or pause and resume its monitoring.

```console
paper-status-monitor remove SUBMISSION
paper-status-monitor disable SUBMISSION     # also: pause
paper-status-monitor enable SUBMISSION      # also: resume
```

`SUBMISSION` is the tracking link, the UUID, the label (case-insensitive) or the
number shown by `list`. The configuration file is edited in place, so your comments
are kept: `remove` deletes the `[[submissions]]` table (with the comment lines
written right above it), `disable` and `enable` change or add its `enabled` line.
The previous file is kept as `config.toml.bak`, and workbooks are never deleted.

```console
paper-status-monitor disable "Tau paper"
paper-status-monitor list                   # 1. Tau paper  [paused]
paper-status-monitor enable 1
```

## `list`

Show the naming template and the configured submissions with their custom fields,
their last recorded status and their workbook.

## `summary`

Show one table with the latest recorded status of every submission: journal,
manuscript number, status and since when, reviews (completed / accepted / invited)
and the last review activity. It is read from the workbooks; nothing is downloaded.

```console
paper-status-monitor summary [--format text|markdown|html] [--output FILE]
```

`--format FORMAT`
: `text` (default, an aligned table), `markdown` or `html` (a standalone page).

`-o FILE`, `--output FILE`
: Write the table to `FILE` instead of showing it.

```text
#  Submission        Journal              Manuscript number  Status                     Since                 Reviews     Last review activity
1  Tau paper         Journal of Examples  ABC-D-26-00001R1   Required Reviews Complete  2026-02-01 (30 days)  2 / 2 / 2+  2nd February 2026
2  [paused] Epsilon  -                    -                  not recorded yet           -                     -           -
```

*Since* is the date on which the current status was first recorded. The table does
not contain the tracking links, so it can be shared. Its headings follow the
`language` setting; the values are written as the tracking page shows them.

## `export`

Write the recorded history of every submission, read from the workbooks, for other
tools than Excel: CSV (one row per observed state, with the name of the submission
in the first column) or JSON (the rows grouped by submission, with its custom
fields). Nothing is downloaded.

```console
paper-status-monitor export [--format csv|json] [--output FILE] [--include-links]
```

`--format FORMAT`
: `csv` (default) or `json`.

`-o FILE`, `--output FILE`
: Write the history to `FILE` instead of showing it.

`--include-links`
: Also export the tracking links. They are left out by default, so that an export
  can be shared; submissions without a label are then called *Submission 1*,
  *Submission 2*... (their number in `list`).

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
paper-status-monitor run [--wait SECONDS] [--every INTERVAL [--tray]] [--notify CHANNELS]
                         [--no-open] [--dry-run]
                         [--record-fields COLUMNS] [--record-ignore COLUMNS]
                         [--notify-fields COLUMNS] [--notify-ignore COLUMNS]
```

`--wait SECONDS`
: Before each check, wait up to `SECONDS` for the data folder to be available and
  for the tracker to be reachable. Useful right after logging in or after the
  computer wakes up, when the network or a cloud drive is not ready yet. The
  autostart launcher uses `--wait 300`.

`--every INTERVAL`
: Keep running: check now and then once every `INTERVAL` (`12h`, `1d`, `1h30m`...;
  the minimum is `1h`), until the process is stopped (`Ctrl+C`, or logging out).
  The configuration file is read again before every check, and a computer that was
  asleep or hibernated catches up with one check shortly after it wakes up. See
  *Periodic checks* in {doc}`autostart`.

`--tray`
: With `--every`, show an icon in the notification area while the checks run
  (Windows): its tooltip and menu show the latest statuses, and its menu can check
  now, open the window or stop the checks. See {ref}`tray-icon`.

`--notify CHANNELS`
: How to tell you about news in this run, instead of the `notify` setting: `report`
  (open the report), `toast` (desktop notification), `email` (send the report by
  e-mail), a list such as `report,toast`, or `none`.

`--no-open`
: Do not open the report (it is still written). A desktop notification is still
  shown if `notify` includes `toast`.

`--dry-run`
: Fetch and compare, print the changes, but write nothing.

`--record-fields COLUMNS`, `--record-ignore COLUMNS`, `--notify-fields COLUMNS`, `--notify-ignore COLUMNS`
: Override the settings of the same name (see *What is recorded and what is
  notified* in {doc}`configuration`) for this run only, also for the submissions that
  have their own settings. `COLUMNS` is a comma-separated list of column names,
  case-insensitive; `all` selects every column and `none` empties a list. For example:

  ```console
  paper-status-monitor run --notify-fields Status
  paper-status-monitor run --notify-ignore "Last review activity,Status code"
  ```

The console summary tags every submission: `[NEW]`, `[CHANGED]` (reportable
changes; changes that are only recorded are marked `(not notified)`), `[RECORDED]`
(a row was added, but nothing is reported), `[NO CHANGE]` or `[ERROR]`.

Only one run can be active at a time; a second one exits with an error. With
`--every`, the lock is only held during each check: a periodic check that finds
another run in progress is skipped and logged. Only one loop of periodic checks can
run at a time, though: a second `run --every` (for example, typed in a terminal while
the one started at login runs) exits with an error that names the process running
them, and `doctor` shows it too.

## `organize`

Rename, merge or split existing workbooks so that their names follow the
`workbook_name` template (see {doc}`workbooks`).

```console
paper-status-monitor organize [--dry-run]
```

`--dry-run`
: Only print the renames, merges and splits that would be done.

Workbooks are merged in chronological order, and a shared workbook whose
submissions now go to different workbooks is split, after a copy of every workbook
involved is saved in the `backups` subfolder of the data folder. Workbooks that also
hold rows of submissions that are not in the configuration are left untouched.

## `gui`

Open the graphical interface (see {doc}`gui`). It is also installed as a separate
command, `paper-status-monitor-gui`, that does not open a console window on Windows.

```console
paper-status-monitor gui
```

## `autostart`

Manage the launcher that runs the monitor at every login (see {doc}`autostart`): a
shortcut in the Startup folder on Windows, an XDG autostart entry on Linux or a
launchd agent on macOS.

```console
paper-status-monitor autostart enable [--wait SECONDS] [--every INTERVAL [--tray]]
paper-status-monitor autostart disable
paper-status-monitor autostart status
```

When `--config` is given to `autostart enable`, the launcher uses that file. With
`--every 12h`, the program started at login keeps checking every 12 hours while you
stay logged in (see *Periodic checks* in {doc}`autostart`), and with `--tray` too it
shows an icon in the notification area while it does (Windows). `status` shows the
launcher, its interpreter, its arguments and when the checks run. On Linux, `enable`
warns you when no graphical session is found, because autostart entries are started
by desktop environments.

## `email`

Check the e-mail notifications and keep the password of the SMTP server in the
system keyring (see *E-mail notifications* in {doc}`configuration`).

```console
paper-status-monitor email test
paper-status-monitor email set-password
paper-status-monitor email delete-password
```

`test` sends a test message with the settings of the `[email]` table and explains
what went wrong if it cannot (for example, a refused password). `set-password` asks
for the password without showing it and keeps it in the system keyring, for the
`username` of the `[email]` table; it needs the `keyring` package
(`python -m pip install "paper-status-monitor[keyring]"`). `delete-password` removes
it. When the `PAPER_STATUS_MONITOR_SMTP_PASSWORD` environment variable is set, it is
used instead of the keyring.

## `doctor`

Diagnose the installation and print one line per check:

```text
[INFO] paper-status-monitor 0.2.0, Python 3.13.1
[ OK ] Configuration: C:\Users\me\AppData\Roaming\paper-status-monitor\config.toml (2 enabled submission(s))
[INFO] Changes recorded: all columns
[INFO] Changes notified: all columns except Last review activity
[INFO] When there is news: the report is opened and a desktop notification is shown
[INFO] Language of the reports, notifications, e-mails, summary and window: English (en)
[INFO] Workbook names: {paper} - {journal} - {manuscript_number}
[ OK ] Data folder: C:\Users\me\Documents\Paper status (2 workbook(s))
[ OK ] Tracker reachable (demo submission status: Under Review)
[ OK ] Autostart enabled: paper-status-monitor.lnk -> C:\Python313\pythonw.exe -m paper_status_monitor run --wait 300 --every 12h
[ OK ] Last run: 2026-10-21 08:55:14 (2 checked, 0 changed, 0 failed)
```

The autostart check also verifies that the interpreter used at login can import the
package — the most common reason for silent failures after reinstalling Python.
`doctor` also warns when existing workbooks do not follow the naming template, and
when desktop notifications are chosen but cannot be shown (for example, when
`notify-send` is missing on Linux).

## Running as a module

Every command is also available as `python -m paper_status_monitor COMMAND`.

