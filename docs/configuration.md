# Configuration

The configuration is a small [TOML](https://toml.io) file created by
`paper-status-monitor init`.

## Location

| Platform | Default path |
| --- | --- |
| Windows | `%APPDATA%\paper-status-monitor\config.toml` |
| macOS | `~/Library/Application Support/paper-status-monitor/config.toml` |
| Linux | `$XDG_CONFIG_HOME/paper-status-monitor/config.toml` (default `~/.config/...`) |

You can use another file with the global `--config PATH` option
(`paper-status-monitor --config my.toml run`) or with the
`PAPER_STATUS_MONITOR_CONFIG` environment variable.

## Example

```toml
# Folder where one Excel workbook per manuscript and the change reports are stored.
data_dir = 'C:\Users\me\Documents\Paper status'

open_report = true
notify_on_errors = true
ignore_fields = []
request_timeout = 30

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
label = "Demo submission"

[[submissions]]
uuid = "11111111-2222-3333-4444-555555555555"
label = "Paper under revision"
enabled = false
```

```{tip}
On Windows, write paths between **single quotes** (`'C:\Users\me'`), which TOML
reads literally, or use forward slashes (`"C:/Users/me"`). In double quotes, a
backslash starts an escape sequence.
```

## Settings

`data_dir` (string, default `~/Documents/paper-status-monitor`)
: Folder for the workbooks. Reports are written to its `reports` subfolder.
  `~` and environment variables (`%USERPROFILE%`, `$HOME`) are expanded. A relative
  path is relative to the configuration file. The folder is created if needed.

`open_report` (boolean, default `true`)
: Open the report with the default application for `.txt` files after a run that
  produced one.

`notify_on_errors` (boolean, default `true`)
: Also write (and open) a report when a submission cannot be checked, for instance
  because the network is down or the link is wrong. Keep it enabled: it is what
  tells you that something is wrong.

`ignore_fields` (list of column names, default `[]`)
: Columns whose changes are still recorded in the workbook but do not trigger a
  report. For example, `["Status code"]` ignores changes in the internal status code
  that do not change the visible status. Valid names are the tracked columns listed
  in {doc}`workbooks`; matching is case-insensitive.

`request_timeout` (number, default `30`)
: Seconds to wait for each answer from the tracker. Failed requests are retried
  three times with an increasing delay.

## Submissions

Each manuscript is a `[[submissions]]` table:

`url` or `uuid` (string, required)
: The *Track your submission* link, or just the UUID it contains. Both are
  normalised to the UUID.

`label` (string, optional)
: A short name shown by `list` and in the reports.

`enabled` (boolean, default `true`)
: Set to `false` to pause monitoring without deleting the entry.

To add submissions, use `paper-status-monitor add LINK` (it validates the link and
keeps your comments) or edit the file. To remove one, delete its block or set
`enabled = false`.

## Validation

The file is validated strictly: unknown settings, unknown columns in
`ignore_fields`, invalid links and duplicated UUIDs are reported with a clear
message instead of being silently ignored. `paper-status-monitor list` and
`paper-status-monitor doctor` are quick ways to validate it.

