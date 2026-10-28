# Workbooks, reports and logs

## One history per manuscript and journal

Every manuscript submitted to a journal has a manuscript number such as
`ABC-D-26-00001`. Revisions add a suffix: `ABC-D-26-00001R1`, `ABC-D-26-00001R2`...
The history of a submission is identified by the **base number without the
suffix** (and by its tracking link), so the original submission and all its
revisions are recorded together. By default every manuscript has its own workbook:

```text
<data_dir>/
├── ABC-D-26-00001 - Journal of Examples - A study of something important.xlsx
├── XYZ-D-26-01234 - Another Journal - A second manuscript.xlsx
├── .paper-status-monitor.json
└── reports/
    ├── changes_2026-10-21_08-55-12.txt
    └── changes_2026-10-28_09-02-47.txt
```

The name of a new workbook comes from the `workbook_name` template (see
{doc}`configuration`), for example `{paper} - {journal} - {manuscript_number}` to
sort the workbooks by paper, using a custom field `paper` that you give to each
submission. A manuscript sent to a different journal gets a new manuscript number,
and therefore a new history.

## One workbook per paper

Submissions whose names coincide share a workbook. With

```toml
workbook_name = "{paper}"

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
label = "TMY - Energy and Buildings (rejected)"
fields = { paper = "TMY" }

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid=11111111-2222-3333-4444-555555555555"
label = "TMY - Building and Environment"
fields = { paper = "TMY" }
```

both submissions are recorded in `TMY.xlsx`: one row per observed state of either
submission, in chronological order, with the `Journal`, `Manuscript number` and
`Paper` columns telling them apart. The template must not contain
`{manuscript_number}` for this to happen.

## Finding a workbook again

Workbooks are recognised by their **content** (the manuscript number and the
tracking link in their rows), never by their title, so:

- a later change of the title does not create a new file;
- you can rename a workbook by hand: it is still found;
- changing `workbook_name` does not split a history: rows keep being added to the
  workbook that already holds the submission, and the log suggests running
  `organize`.

If several workbooks hold the same submission (for example a `... (1).xlsx` copy
created by a sync client), the most recently modified one is used and a warning is
logged.

## Renaming and merging existing workbooks

After changing `workbook_name` or the custom fields, bring the existing workbooks in
line with:

```console
paper-status-monitor organize --dry-run   # show what would change
paper-status-monitor organize             # do it
```

- A workbook whose submissions now map to a free name is **renamed**.
- Workbooks whose submissions now map to the same name are **merged** into one,
  with the rows in chronological order and every column kept. A copy of every
  workbook involved is first saved in `<data_dir>/backups/organize-<date>/`, and the
  merged workbooks are then removed. Other sheets, charts or formatting of the
  workbook used as the base are kept; those of the others remain in the copies.
- A workbook that also holds rows of submissions that are not in the configuration,
  or whose submissions would now go to different workbooks, is left untouched and
  reported (splitting a workbook is not supported).

Close the workbooks in Excel before organizing them. The graphical interface offers
the same through *Workbooks → Organize workbooks*.

## Columns

The `History` sheet has one row per **observed state**: by default, a row is only
added when at least one tracked column changes (see *What is recorded and what is
notified* in {doc}`configuration` to choose which columns add rows).

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
| *custom fields* | One column per custom field of the submission, e.g. `Paper`. |

`Detected at`, `Tracker URL` and the custom fields are metadata: they are never
compared. All the other columns are compared with the last row of the submission to
decide whether a row is added (`record_fields`, `record_ignore`) and with the last
state seen to decide what is reported (`notify_fields`, `notify_ignore`).

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

## The state file

`<data_dir>/.paper-status-monitor.json` keeps the last state seen of every
submission (keyed by its tracking UUID) and the workbook where it was found. Changes
are reported against it, so a change that is reported but not recorded is reported
only once. It is small and safe to delete: you would at most be told again about the
latest changes. Like the workbooks, it contains your tracking links: do not share
it.

## Reports

A report `reports/changes_<date>_<time>.txt` is written when a run finds:

- **changes** in a tracked submission (`CHANGES` section, one line per changed
  column), limited to the columns that are notified (`notify_fields`,
  `notify_ignore`): changes that are only recorded do not produce a report;
- a submission recorded for the first time (`NOW TRACKING` section);
- errors, unless `notify_on_errors = false` (`ERRORS` section).

The custom fields of each submission are listed with its details. On the console,
`run` also shows the changes that were recorded without being notified, tagged
`[RECORDED]` or `(not notified)`.

If the data folder is not available (for instance, a cloud drive that is not
mounted), the report is written to the local fallback folder
(`%LOCALAPPDATA%\paper-status-monitor\reports` on Windows) so that you still hear
about it. Depending on the `notify` setting, the report is then opened with your
default text editor and/or announced with a desktop notification (see
{doc}`configuration`).

## Logs and run state

Every run is logged to a rotating log file (1 MB, three backups):

| Platform | Log file |
| --- | --- |
| Windows | `%LOCALAPPDATA%\paper-status-monitor\logs\paper-status-monitor.log` |
| macOS | `~/Library/Application Support/paper-status-monitor/logs/paper-status-monitor.log` |
| Linux | `~/.local/state/paper-status-monitor/logs/paper-status-monitor.log` |

The same folder contains `state.json` (summary of the last run, shown by
`doctor`) and `run.lock` while a check is in progress (with `run --every`, only
during each check).

