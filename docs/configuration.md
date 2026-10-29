# Configuration

The configuration is a small [TOML](https://toml.io) file created by
`paper-status-monitor init`. You can also edit every setting in the graphical
interface (`paper-status-monitor gui`, see {doc}`gui`).

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
# Folder where the Excel workbooks and the change reports are stored.
data_dir = 'C:\Users\me\Documents\Paper status'

# One workbook per paper and journal, sorted by paper: "Tau - Journal of Examples - ABC-D-26-00001.xlsx"
workbook_name = "{paper} - {journal} - {manuscript_number}"

# Record every change, but do not open a report when only the date of the last
# review activity changed.
record_fields = "all"
record_ignore = []
notify_fields = "all"
notify_ignore = ["Last review activity"]

# Open the report and also show a desktop notification when there is news.
notify = ["report", "toast"]
notify_on_errors = true
request_timeout = 30

# Reports, notifications, e-mails, summary and window in Spanish.
language = "es"

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
label = "Demo submission"
fields = { paper = "Tau" }

[[submissions]]
uuid = "11111111-2222-3333-4444-555555555555"
label = "Paper under revision"
fields = { paper = "Epsilon" }
enabled = false
```

```{tip}
On Windows, write paths between **single quotes** (`'C:\Users\me'`), which TOML
reads literally, or use forward slashes (`"C:/Users/me"`). In double quotes, a
backslash starts an escape sequence.
```

```{important}
In TOML, every setting written after a `[[submissions]]` line belongs to that
submission. Keep the general settings at the top of the file.
```

## General settings

`data_dir` (string, default `~/Documents/paper-status-monitor`)
: Folder for the workbooks. Reports are written to its `reports` subfolder.
  `~` and environment variables (`%USERPROFILE%`, `$HOME`) are expanded. A relative
  path is relative to the configuration file. The folder is created if needed.

`workbook_name` (string, default `"{manuscript_number} - {journal} - {title}"`)
: Template for the names of the workbooks; see [Workbook names](#workbook-names)
  below.

`time_in_status` (boolean, default `false`)
: Add a *Time in status* sheet to every workbook, with the periods that each
  submission spent in each status and the total days in each one (see
  {doc}`workbooks`). It is added at the next run and rewritten after every change.

`notify` (`"report"`, `"toast"`, `"email"`, `"none"` or a list, default `"report"`)
: How you are told about news (changes, new submissions and, with
  `notify_on_errors`, failed checks). A report is always written to the `reports`
  subfolder of `data_dir`; `"report"` also opens it with the default application
  for `.txt` files, `"toast"` shows a desktop notification (see
  [Desktop notifications](#desktop-notifications)) and `"email"` sends it by e-mail
  (see [E-mail notifications](#e-mail-notifications)). Use a list for several, such
  as `["report", "toast"]`, or `"none"` to only write the report. `open_report`, the
  setting used by version 0.1, is still accepted: `open_report = true` means
  `notify = "report"` and `false` means `notify = "none"`.

`notify_on_errors` (boolean, default `true`)
: Also report (and notify) a submission that cannot be checked, for instance
  because the network is down or the link is wrong. Keep it enabled: it is what
  tells you that something is wrong.

`request_timeout` (number, default `30`)
: Seconds to wait for each answer from the tracker. Failed requests are retried
  three times with an increasing delay.

`language` (`"en"` or `"es"`, default `"en"`)
: Language of the reports, the desktop notifications, the e-mails, the summary and
  the graphical interface: `"en"` (English) or `"es"` (Spanish, *español*). See
  [Language](#language).

(language)=
## Language

With `language = "es"`, everything that paper-status-monitor writes for you to
read is in Spanish: the change reports, the desktop notifications (and their
buttons), the e-mails, the summary (`paper-status-monitor summary` and the
*Summary* button) and the whole graphical interface, where the language can also
be chosen at the bottom of the window. `paper-status-monitor init --language es`
writes the setting for you.

Some things always stay in English, so that they work the same in every language:

- the workbooks: their column names (`Status`, `Last review activity`...) and the
  *Time in status* sheet, which programs and the history rely on;
- the values shown by the tracking page, such as `Under Review` or `17th May 2022`,
  which are written as the page shows them;
- the exports (`export`) and the configuration file;
- the command line: its help and messages, including the summary of a run printed
  by `run` (the report it writes follows the setting);
- the error messages that come from the tracker, the SMTP server or the
  configuration file.

Translations live in `src/paper_status_monitor/locales/`; see {doc}`development` to
add a language.

(record-and-notify)=
## What is recorded and what is notified

Every run compares what the tracker shows with what was recorded before. Two
independent questions are answered for every column that changed:

- **Record**: does the change add a row to the workbook?
- **Notify**: is the change written to the report (which is then opened)?

`record_fields` (`"all"` or a list of columns, default `"all"`)
: Only changes in these columns add a row to the workbook.

`record_ignore` (list of columns, default `[]`)
: Changes in these columns alone never add a row.

`notify_fields` (`"all"` or a list of columns, default `"all"`)
: Only changes in these columns are reported. For example, `["Status"]` reports
  nothing but changes of status.

`notify_ignore` (list of columns, default `[]`)
: Changes in these columns are never reported. `ignore_fields`, the name used by
  version 0.1, is still accepted and means the same.

Column names are the tracked columns listed in {doc}`workbooks` (`Detected at`,
`Tracker URL` and custom fields are never compared); matching is case-insensitive.
Some common choices:

| You want... | Settings |
| --- | --- |
| Everything recorded and reported (default) | nothing to change |
| A new *Last review activity* date recorded, but not reported | `notify_ignore = ["Last review activity"]` |
| Only changes of status reported | `notify_fields = ["Status"]` |
| No new row when only the internal status code changes | `record_ignore = ["Status code"]` |
| Reviewer counts reported, but kept out of the workbook | `record_ignore = ["Reviews completed", "Review invitations accepted", "Review invitations sent"]` |

Rows are snapshots: when a row is added, it contains the current value of *every*
column, including those whose changes alone would not have added it. A change that
is reported but not recorded is reported **once**: the last state seen of every
submission is kept in the data folder (see {doc}`workbooks`). New submissions and,
with `notify_on_errors`, failed checks are always reported.

The same choices can be made for a single run with the `run` options
`--record-fields`, `--record-ignore`, `--notify-fields` and `--notify-ignore` (see
{doc}`cli`); for that run, they also replace the own settings of the submissions
described below.

(own-settings)=
### Different choices for one submission

A submission can have its own `record_fields`, `record_ignore`, `notify_fields` or
`notify_ignore`, written in its `[[submissions]]` table. Each one replaces the general
setting of the same name for that submission only, while the other general settings
still apply to it:

```toml
notify_ignore = ["Last review activity"]   # every submission

[[submissions]]
url = "https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000"
label = "Paper under revision"
notify_fields = ["Status"]                 # this one: only changes of status
record_ignore = []                         # and every change adds a row
```

Write `notify_ignore = []` in a submission to drop the general list for it.
`paper-status-monitor list` shows what is recorded and notified for every submission
that has its own settings. You can set them with `paper-status-monitor edit SUBMISSION
--notify-fields Status` (the same options as `run`; `general` removes one, and
`--use-general-settings` removes them all) or in the graphical interface (*Edit...*,
then *What is recorded and notified*).

(desktop-notifications)=
## Desktop notifications

With `notify = "toast"` (or `["report", "toast"]`), a short notification summarises
the news of every run: the changes of a single submission (`Status: Under Review →
Required Reviews Complete`), or one line per submission when several have news.

| System | How it is shown |
| --- | --- |
| Windows 10 and 11 | A toast notification, shown on behalf of *Windows PowerShell* (no extra software). Clicking it opens the report, and its buttons open the report, the workbook and the tracking page (when several submissions have news: the report and their workbook, or the folder of the workbooks). |
| macOS | *display notification*, through `osascript`. |
| Linux | `notify-send`, from the `libnotify-bin` package (Debian, Ubuntu) or `libnotify`. |

Notifications are best effort: if one cannot be shown, the problem is logged and the
report is still written. Use *Test*, next to the option in the graphical interface,
to check that your system displays them, and `paper-status-monitor doctor` to check
that the required program is installed. Focus assist or *do not disturb* modes may
hide them; they then wait in the notification centre.

(e-mail-notifications)=
## E-mail notifications

With `notify = "email"` (or a list such as `["report", "email"]`), the report of
every run with news is also sent by e-mail, through your SMTP server:

```toml
notify = ["report", "email"]

[email]
smtp_host = "smtp.example.org"
security = "starttls"         # "starttls" (port 587, default), "ssl" (465) or "none" (25)
smtp_port = 587               # optional: only if the server uses another port
username = "me@example.org"   # leave it out if the server needs no login
sender = "me@example.org"     # optional: the From address (default: username)
to = ["me@example.org"]       # one address or a list
```

Write the `[email]` table after the general settings: every setting below an
`[email]` line belongs to it.

**The password is never written to the configuration file**, and a `password`
setting is refused. Give it in one of these ways:

- the `PAPER_STATUS_MONITOR_SMTP_PASSWORD` environment variable, or
- the system keyring (Windows Credential Manager, macOS Keychain, Secret Service on
  Linux), with the optional `keyring` package:

  ```console
  python -m pip install "paper-status-monitor[keyring]"
  paper-status-monitor email set-password
  ```

Then check everything with `paper-status-monitor email test`, which sends a test
message; `doctor` warns when a setting or the password is missing. Many providers
(Gmail, Outlook.com, Yahoo...) do not accept your usual password from programs:
create an *app password* in the security settings of your account and use it
instead.

The message contains the report, including the tracking links of the submissions
with news: send it only to yourself or to people you trust. Like desktop
notifications, e-mails are best effort: when one cannot be sent, the problem is
logged and the report is still written.

## Workbook names

`workbook_name` is a template in which every `{placeholder}` is replaced by a value
of the submission:

| Placeholder | Value |
| --- | --- |
| `{manuscript_number}` | Manuscript number without the revision suffix (`ABC-D-26-00001`). |
| `{journal}` | Journal name. |
| `{journal_acronym}` | First part of the manuscript number, usually the journal acronym (`ABC`). |
| `{title}` | Manuscript title. |
| `{first_author}`, `{corresponding_author}` | Authors, as shown on the tracking page. |
| `{date_of_submission}` | Date of the original submission as `YYYY-MM-DD`, which sorts by date. |
| `{submission_year}` | Year of the original submission. |
| `{label}` | Label of the submission in this file. |
| `{<field>}` | Any custom field of the submission, e.g. `{paper}`. |

Python format specifications are allowed: `{title:.40}` keeps the first 40
characters of the title. Characters that are not allowed in file names are removed,
and a placeholder that is empty for a submission is removed together with the
separator next to it. Some useful templates:

| Template | Example |
| --- | --- |
| `{manuscript_number} - {journal} - {title}` (default) | `ABC-D-26-00001 - Journal of Examples - A study.xlsx` |
| `{paper} - {journal} - {manuscript_number}` | `Tau - Journal of Examples - ABC-D-26-00001.xlsx` |
| `{paper} - {date_of_submission} - {journal_acronym}` | `Tau - 2026-03-03 - ABC.xlsx` |
| `{paper}` | `Tau.xlsx`: **one workbook per paper**, with every journal it was sent to |

Submissions whose names coincide share a workbook. With `"{paper}"`, all the
submissions of a paper (for example, after a rejection, to the next journal) are
recorded in the same workbook, one row per observed state; the `Journal` and
`Manuscript number` columns tell them apart. Leave `{manuscript_number}` out of the
template to group submissions in this way.

The template only decides the name of a workbook when a submission is recorded for
the first time: an existing history is never split. To rename, merge or split
existing workbooks after changing the template, run `paper-status-monitor organize` (see
{doc}`workbooks`).

## Submissions

Each manuscript is a `[[submissions]]` table:

`url` or `uuid` (string, required)
: The *Track your submission* link, or just the UUID it contains. Both are
  normalised to the UUID.

`label` (string, optional)
: A short name shown by `list` and in the reports.

`fields` (table, optional)
: Your own fields, for example `fields = { paper = "Tau", project = "Thesis" }`.
  Each field can be used as a placeholder in `workbook_name` and is written to an
  extra column of the workbook, named after the field (`paper` → `Paper`,
  `funding_agency` → `Funding agency`). Names use letters, digits and underscores
  and cannot be a built-in placeholder or an existing column. Give the same `paper`
  value to the submissions of one paper to several journals to keep them together.

`enabled` (boolean, default `true`)
: Set to `false` to pause monitoring without deleting the entry.

`record_fields`, `record_ignore`, `notify_fields`, `notify_ignore` (optional)
: Own choice of what is recorded and notified for this submission; each one replaces
  the general setting of the same name (see {ref}`own-settings`).

To add submissions, use `paper-status-monitor add LINK [--label TEXT] [--field
NAME=VALUE]` (it validates the link and keeps your comments), the graphical
interface, or edit the file. To change the label or the custom fields of one, use
`paper-status-monitor edit`; to pause, resume or remove one, use
`paper-status-monitor disable`, `enable` or `remove` (they all keep your comments;
see {doc}`cli`), the graphical interface, or edit the file (`enabled = false`
pauses a submission).

## Validation

The file is validated strictly: unknown settings, unknown columns, unknown
placeholders, invalid custom fields, invalid links and duplicated UUIDs are
reported with a clear message instead of being silently ignored. A placeholder such
as `{paper}` is only valid if at least one submission has that field.
`paper-status-monitor list` and `paper-status-monitor doctor` are quick ways to
validate the file.

```{note}
The `add`, `edit`, `remove`, `disable` and `enable` commands edit the file in place
and keep your comments. Saving from the graphical interface rewrites the file with
explanatory comments, so comments you added by hand are lost. `edit`, `remove`,
`disable`, `enable` and the window keep the previous file as `config.toml.bak`.
```
