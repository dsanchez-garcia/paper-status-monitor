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
do not want them to add rows either.

```{note}
The meaning of the internal codes is not documented. Contributions that map codes to
editorial stages, based on your own observations, are welcome.
```

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

