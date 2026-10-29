# How it works

## Data source

The official page `https://track.authorhub.elsevier.com/?uuid=<uuid>` is a small
JavaScript application. When it loads, it downloads the submission record as JSON
from:

```text
https://tnlkuelk67.execute-api.us-east-1.amazonaws.com/tracker/<uuid>
```

`paper-status-monitor` requests the same JSON document directly (one HTTP `GET` per
submission), which is faster and far more reliable than driving a browser. A
typical record looks like this (public demo submission):

```json
{
  "Uuid": "00000000-0000-0000-0000-000000000000",
  "CorrespondingAuthor": "Maximilian Spillage",
  "DocumentId": 888888,
  "FirstAuthor": "Zachary Mindwarp",
  "JournalAcronym": "SUBTRAK",
  "JournalName": "The International Journal of Submission Trackers",
  "LastUpdated": 1652787284,
  "LatestRevisionNumber": 0,
  "ManuscriptTitle": "Influence of submission trackers, article shredding and ...",
  "PubdNumber": "SUBTRAK-D-22-00128",
  "Status": 3,
  "SubmissionDate": 1583240028,
  "ReviewSummary": {
    "ReviewsCompleted": "1",
    "ReviewInvitationsAccepted": "2",
    "ReviewInvitationsSent": "2+"
  }
}
```

An unknown or expired UUID returns HTTP 404.

## From JSON to what the page shows

The conversion reproduces the logic of the official page:

| Page element | Rule |
| --- | --- |
| Title | `ManuscriptTitle`, prefixed with `[1st revision]`, `[2nd revision]`... when `LatestRevisionNumber > 0`. |
| Manuscript number | `PubdNumber`, plus `R<n>` when `LatestRevisionNumber = n > 0`. |
| Status | `Status` 3 or 23 → *Under Review*; 4 → *Required Reviews Complete*; any other code → *Review Complete*. |
| Last review activity | `LastUpdated` (Unix time) as `dS mmmm yyyy` in local time, e.g. `17th May 2022`; hidden when empty. |
| Date of submission | `SubmissionDate`, same format. |
| Reviewer counts | `ReviewSummary` values, verbatim. |

Because the page collapses many internal codes into *Review Complete*, the raw
`Status code` is also recorded. A change of code without a change of label means
that something happened behind the scenes (for example, the editor started working
on a decision). Add `"Status code"` to `notify_ignore` if you do not want to be
notified about those changes (they are still recorded), or to `record_ignore` if you
do not want them to add rows either. What the codes and labels mean in practice is
described in {ref}`observed-statuses`.

(observed-statuses)=
## Statuses observed in practice

The internal codes are not documented: their meaning can only be learnt by watching
real submissions. This section gathers what has been observed so far, anonymised (no
manuscript numbers, titles, journals, authors or dates). Reviewer counts are written
*completed / accepted / sent*, as in the report.

### Codes

| Code | Label shown | Observed |
| --- | --- | --- |
| 3 | *Under Review* | An original submission with reviewers invited, one of them accepted and no review completed yet (`0 / 1 / 2+`). |
| 4 | *Required Reviews Complete* | Not recorded yet. It is the only code shown with this label, which appeared when the second review was completed (see below). |
| 23 | *Under Review* | Not recorded yet. Whether revisions under review use 3 or 23 is still unknown. |
| Any other | *Review Complete* | Not recorded yet. The label appeared in different situations (see below), which may well correspond to different codes. |

### Two submissions, two rounds each

These two submissions were followed through the original submission and a first
revision before the `Status code` column existed, so only the labels and the counts
are known. Every row is a state seen by the monitor; changes of *Last review
activity* alone are left out, and a state that lasted less than the time between two
checks may be missing.

Submission A:

| Revision | Status | Counts | Notes |
| --- | --- | --- | --- |
| 0 | *Under Review* | `0 / 0 / 2+` | |
| 0 | *Under Review* | `1 / 1 / 2+` | |
| 0 | *Under Review* | `1 / 2 / 2+` | |
| 0 | *Required Reviews Complete* | `2 / 2 / 2+` | When the second review was completed. |
| 0 | *Review Complete* | `2 / 2 / 2+` | The next day, without a new *Last review activity*. |
| 1 | *Review Complete* | `0 / 0 / 0` | First state of the revision: counts back to zero, *Last review activity* still from the previous round. |
| 1 | *Under Review* | `0 / 0 / 2` | Reviewers invited. |
| 1 | *Under Review* | `1 / 1 / 2` | One day after the invitations. |
| 1 | *Required Reviews Complete* | `2 / 2 / 2` | About a week later. |
| 1 | *Review Complete* | `2 / 2 / 2` | Within four days, without a new *Last review activity*. |

Submission B:

| Revision | Status | Counts | Notes |
| --- | --- | --- | --- |
| 0 | *Under Review* | `0 / 0 / 2+` | |
| 0 | *Under Review* | `0 / 1 / 2+` | |
| 0 | *Under Review* | `0 / 2 / 2+` | |
| 0 | *Under Review* | `1 / 2 / 2+` | For months, while *Last review activity* changed every one to four weeks. |
| 0 | *Review Complete* | `1 / 2 / 2+` | Straight from *Under Review*, with one accepted review missing and without a new *Last review activity*. |
| 1 | *Review Complete* | `0 / 0 / 0` | First state of the revision, as in submission A. |
| 1 | *Under Review* | `0 / 0 / 1` | One reviewer invited. |
| 1 | *Under Review* | `0 / 1 / 1` | |
| 1 | *Under Review* | `0 / 0 / 1` | The accepted invitation was no longer counted... |
| 1 | *Under Review* | `0 / 1 / 1` | ...and was counted again later. |
| 1 | *Review Complete* | `1 / 1 / 1` | When the only review was completed. |

### What this tells you

- *Review Complete* does not always mean that the reviews are complete: the page
  shows it for every code other than 3, 4 and 23. It appeared when the editor moved
  on after the reviews, but also as soon as a revision reached the tracker, with all
  the counts at zero, until reviewers were invited.
- *Required Reviews Complete* appeared when the reviews the editor needed (two, in
  submission A) were completed, and *Review Complete* followed within days. The
  editor may also move on before every accepted reviewer has reported: in the first
  round of submission B, *Required Reviews Complete* was not seen.
- *Last review activity* follows the reviewers: the step to *Review Complete* did not
  change it unless a review was completed at the same time, and it often changed
  with no other visible change (perhaps new invitations hidden behind `2+`, or
  reminders).
- The counts start again from zero with every revision, and they can go down.
- `2+` was shown from the start of both first rounds, but exact numbers (`1`, `2`) in
  the revision rounds: `2+` seems to mean *more than two* invitations.
- Both submissions answered HTTP 404 when they were checked again, months after
  their last change.

### Share your observations

The table of codes fills in as codes are recorded. If you see a code that is not
described here, or a different sequence, please
[open an issue](https://github.com/dsanchez-garcia/paper-status-monitor/issues) with
the `Revision`, `Status`, `Status code` and reviewer counts of each row, and roughly
how long each state lasted. Remove the title, manuscript number, journal, authors,
dates and tracking link first.

## A run, step by step

1. Load and validate the configuration; take a lock so that only one run is active.
2. With `--wait`, wait until the data folder exists and the tracker host accepts
   connections (or the timeout expires).
3. For each enabled submission:
   1. fetch the JSON record (with retries and back-off on network errors, HTTP 429
      and 5xx);
   2. convert it to a snapshot of display values;
   3. find the workbook that already holds its history (by manuscript number or
      tracking link), or the workbook named by the `workbook_name` template;
   4. compare the snapshot with the last row of the submission and append a row if
      a *recorded* column changed (`record_fields`, `record_ignore`);
   5. compare the snapshot with the last state seen and keep the changes in
      *notified* columns (`notify_fields`, `notify_ignore`) for the report.
4. Write a report if there is news (or errors), tell you about it as chosen with
   `notify` (open the report, show a desktop notification), and store a summary of
   the run for `doctor` and the last state seen of every submission.

With `run --every`, these steps are repeated at the chosen interval; the lock is held
only during each check.

A failure in one submission never stops the others, and every failure ends up in the
log file and, by default, in the report.

## Responsible use

The tracker is a public service run by Elsevier for authors. This tool:

- only requests the submissions **you** configure, with your own links;
- identifies itself with a descriptive `User-Agent`;
- is designed to run **once per login, or every few hours to once a day** (`--every`
  refuses intervals shorter than one hour), which is a negligible load.

The service's responses carry a TDM reservation (`Tdm-Reservation: 1`): the data is
not meant for text and data mining. Monitoring the status of your own manuscripts is
the use the page was built for; do not use this tool to collect data about other
people's submissions.

