# Graphical interface

Everything can be done from a window instead of the command line:

```console
paper-status-monitor gui
```

On Windows, the separate command `paper-status-monitor-gui` opens the same window
without a console; you can pin it to the Start menu or create a desktop shortcut to
it (it is installed next to `paper-status-monitor`, in the `Scripts` folder of your
Python installation). Use `--config PATH` with either command to open another
configuration file.

The window shows the configuration file; nothing is written until you click
**Save** (or press `Ctrl+S`). Saving rewrites the file with explanatory comments and
keeps the previous version as `config.toml.bak`. If the file does not exist yet, the
window starts with the default settings and creates it when you save.

The window opens in the language of the configuration (`language`, see
{ref}`language`). Change it with **Language (window and
reports)** at the bottom: the window is shown again in that language right away,
keeping what you typed, and the reports, notifications and e-mails use it once you
save.

## Submissions

The list shows every submission with its label, custom fields, whether it is
monitored and its last recorded status. A `*` after *yes* or *no* means that the
submission has its own choice of what is recorded and notified.

- **Add...** opens a form for the tracking link (or UUID), an optional label and
  the custom fields, one per line (`paper = Tau`). The link is checked with the
  tracker unless you untick the option. Its *What is recorded and notified* box
  gives the submission its own choice, instead of the one of the *Notifications*
  tab (see {ref}`own-settings`).
- **Edit...** (or a double-click) changes a submission; **Remove** stops monitoring
  it (its workbook is kept); **Pause / resume** sets `enabled`.
- **Check now** shows what the tracker says at this moment, without saving anything.
- **Open workbook** opens the workbook of the selected submission in Excel.
- **Summary** shows the latest status of every submission in one table (like
  `paper-status-monitor summary`); *Save...* writes it as an HTML page, a Markdown
  table or text.
- **Export...** saves the recorded history of every submission as CSV or JSON,
  without the tracking links (like `paper-status-monitor export`).

Give the same custom field (for example `paper = Tau`) to the submissions of one
paper to several journals, and use it in the workbook name (see below).

## Notifications

One row per column, with two independent tick boxes:

- **Record**: a change in this column adds a row to the workbook;
- **Notify**: a change in this column is written to the report, which is opened.

For example, to keep the history of *Last review activity* without being told about
it, tick *Record* and untick *Notify*; to hear only about changes of status, use
*Notify only status changes*. A summary below the buttons describes the choice in
words. See *What is recorded and what is notified* in {doc}`configuration` for the
details.

Under *When there is news*, choose how you are told: **Open the report with your
text editor**, **Show a desktop notification**, or both (the report is written in
every case). **Test** shows a notification right away, to check that your system
displays them (see *Desktop notifications* in {doc}`configuration`). **Send the
report by e-mail** needs the server and the recipients, set with **Settings...**
(the password can be saved there in the system keyring; it is never written to the
configuration file), and **Test** sends a test message (see *E-mail notifications*
in {doc}`configuration`). The last option decides whether failed checks are
reported.

## Workbooks

- **Data folder**: where the workbooks and the reports are stored.
- **Workbook name**: the naming template, with presets such as *Paper - Journal -
  Manuscript number* or *One workbook per paper (all journals)*. The available
  placeholders, including your custom fields, are listed below it.
- The **preview** shows, for every submission, its current workbook and the name it
  gets with the template (submissions not recorded yet are previewed with example
  data). Errors in the template are shown in red.
- **Organize workbooks...** shows the renames, merges and splits needed to follow the
  template and applies them on request (see {doc}`workbooks`).
- **Add a 'Time in status' sheet to every workbook** sets `time_in_status`: a second
  sheet with how long each submission spent in each status (see {doc}`workbooks`).

## Run

- **Run now** checks every monitored submission, exactly like
  `paper-status-monitor run`, and shows the summary; **Dry run** checks without
  writing anything. Runs use the settings shown in the window, even before they are
  saved, which is handy to try a choice of notifications with a dry run.
- **Open last report** and **Open reports folder**.
- The timeout of each request to the tracker.
- **Run automatically at login**: enable, disable or check the launcher (a shortcut
  in the Startup folder on Windows, an XDG autostart entry on Linux, a launchd agent
  on macOS; see {doc}`autostart`). *Then check again every ... hours* keeps
  checking periodically while you stay logged in (`0` = only at login); *Show an icon
  in the notification area* adds an icon with the latest statuses and a menu while
  it does (Windows; see {ref}`tray-icon`);
  *Refresh* shows the settings of the existing launcher. The program started at
  login reads the saved configuration, so the window offers to save first.

The *File* menu opens the configuration and log files in your text editor; *Help*
links to this documentation.

```{note}
The window uses tkinter, which is part of the standard Python installation on
Windows and macOS. On some Linux distributions it is a separate package, for example
`sudo apt install python3-tk` on Debian and Ubuntu.
```
