# Workbooks, reports and logs

## One workbook per manuscript and journal

Every manuscript submitted to a journal has a manuscript number such as
`ABC-D-26-00001`. Revisions add a suffix: `ABC-D-26-00001R1`, `ABC-D-26-00001R2`...
The workbook is identified by the **base number without the suffix**, so the
original submission and all its revisions are recorded in the same file:

```text
<data_dir>/
├── ABC-D-26-00001 - Journal of Examples - A study of something important.xlsx
├── XYZ-D-26-01234 - Another Journal - A second manuscript.xlsx
└── reports/
    ├── changes_2026-10-21_08-55-12.txt
    └── changes_2026-10-28_09-02-47.txt
```

The journal and the title are added to the file name only to make it readable; only
the `ABC-D-26-00001 - ` prefix is used to find the file again. You can therefore
rename the rest of the file name, and a later change of title does not create a new
file. A manuscript sent to a different journal gets a new manuscript number and
therefore a new workbook.

If several files share the same prefix (for example a `... (1).xlsx` copy created
by a sync client), the most recently modified one is used and a warning is logged.

## Columns

The `History` sheet has one row per **observed state**: a row is only added when at
least one tracked column changes.

| Column | Content |
| --- | --- |
| `Detected at` | Local date and time at which the state was first seen. |
| `Title` | Manuscript title, without the `[1st revision]` prefix shown on the page. |
| `Revision` | `0` for the original submission, `1` for R1, and so on. |
| `Status` | Status as shown on the page: `Under Review`, `Required Reviews Complete` or `Review Complete`. |
| `Status code` | Internal numeric status behind the label (see {doc}`how-it-works`). |
| `Last review activity` | Last time a reviewer was invited, accepted or completed a review. |
| `Reviews completed` | Number of completed reviews. |
| `Review invitations accepted` | Number of reviewers who accepted. |
| `Review invitations sent` | Number of invitations sent (`2+` means two or more). |
| `Journal` | Journal name. |
| `Corresponding author` | As shown on the page. |
| `First author` | As shown on the page. |
| `Date of submission` | Date of the original submission. |
| `Manuscript number` | Including the revision suffix (`ABC-D-26-00001R1`). |
| `Tracker URL` | Link to the official page (clickable). |

`Detected at` and `Tracker URL` are metadata: they are never compared. All the other
columns are compared with the last row of the workbook to detect changes. Columns
listed in `ignore_fields` are compared and recorded, but their changes alone do not
trigger a report.

Dates are written exactly as the official page shows them (`25th January 2025`),
converted to your local time zone like your browser does.

```{note}
You can add your own columns, notes, colours or charts to the workbook: new rows are
written under the matching column headers, and unknown columns are left untouched.
Close the workbook in Excel before a run, otherwise it cannot be updated (the error
is reported and the change is recorded on the next run).
```

When the tracker stops returning data for a submission that already has a workbook
(it answers *404 Not Found*, which usually happens once a final decision has been
made), a last row with the status `No longer available in the tracker` is added
once. You can then remove the submission from the configuration.

## Reports

A report `reports/changes_<date>_<time>.txt` is written when a run finds:

- **changes** in a tracked submission (`CHANGES` section, one line per changed column);
- a submission recorded for the first time (`NOW TRACKING` section);
- errors, unless `notify_on_errors = false` (`ERRORS` section).

If the data folder is not available (for instance, a cloud drive that is not
mounted), the report is written to the local fallback folder
(`%LOCALAPPDATA%\paper-status-monitor\reports` on Windows) so that you still hear
about it. With `open_report = true` the report is opened with your default text
editor.

## Logs and run state

Every run is logged to a rotating log file (1 MB, three backups):

| Platform | Log file |
| --- | --- |
| Windows | `%LOCALAPPDATA%\paper-status-monitor\logs\paper-status-monitor.log` |
| macOS | `~/Library/Application Support/paper-status-monitor/logs/paper-status-monitor.log` |
| Linux | `~/.local/state/paper-status-monitor/logs/paper-status-monitor.log` |

The same folder contains `state.json` (summary of the last run, shown by
`doctor`) and `run.lock` while a run is in progress.

