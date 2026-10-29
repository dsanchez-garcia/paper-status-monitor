# Troubleshooting

Start with:

```console
paper-status-monitor doctor
```

and look at the log file it prints (`[INFO] Log file: ...`).

## Nothing happens at login

1. Run `paper-status-monitor autostart status`. If the interpreter is marked
   `(MISSING!)`, Python was reinstalled or upgraded (or the virtual environment was
   deleted): install the package in the current Python and run
   `paper-status-monitor autostart enable` again.
2. Run `paper-status-monitor doctor`. The autostart line also checks that the
   interpreter used at login can import the package.
3. Check the end of the log file: every run at login writes at least one line.
4. Remember that, by design, nothing is shown when nothing changed. The `Last run`
   line of `doctor` tells you when the last run finished.
5. Linux: autostart entries are only started by desktop environments, at a graphical
   login; check that the entry is not turned off in the startup settings of your
   desktop. macOS: check that the agent is allowed in *System Settings → General →
   Login Items*.

```{note}
A typical cause of silent failures is a launcher (shortcut, `.bat` file, scheduled
task) that calls `python` from the `PATH`. When Python is upgraded, `python` may
point to a new interpreter without the required packages and the script crashes
immediately, often in a console window that closes before you can read it. The
launcher created by `autostart enable` uses an absolute path and `doctor` verifies
it.
```

## "The data folder is not available"

The folder in `data_dir` does not exist and its parent is not reachable. This is
normal for a few seconds after login when the folder lives in a cloud drive (Google
Drive for desktop mounts its virtual drive after login). The launcher waits up to
five minutes (`--wait 300`); increase it with
`paper-status-monitor autostart enable --wait 600` if needed. Reports are written to
a local fallback folder meanwhile, so you do not miss errors.

## "Could not reach the tracker"

The computer is offline, a firewall or proxy blocks the connection, or the tracker
is temporarily down. Requests are retried automatically; the next run will try again.
Proxies configured through the `HTTPS_PROXY` environment variable are honoured.

## "The tracker has no data for UUID ... (HTTP 404)"

- If the submission was never recorded: the link is probably wrong. Copy it again
  from the e-mail and check it in a browser.
- If it was being tracked: the tracker usually stops serving a submission after a
  final decision. The change is recorded once in the workbook; pause the submission
  with `paper-status-monitor disable SUBMISSION` or remove it with
  `paper-status-monitor remove SUBMISSION` (both keep the comments of the
  configuration file).

## "Cannot write ...xlsx: the file is in use"

The workbook is open in Excel (which locks it). Close it; the change is detected
again and written on the next run.

## "Another run seems to be in progress"

A run is already active (for example, the autostart one). If you are sure that no
other run is active (for instance after a crash), delete the `run.lock` file whose
path is shown in the message. Stale locks are removed automatically after one hour.
With periodic checks (`--every`), the lock is held only while a check runs; a
periodic check that finds another run in progress is skipped and logged.

## "Periodic checks are already running"

Another process runs `run --every`, usually the one started at login with
`autostart enable --every ...`; the message (and `doctor`) gives its process number.
Its checks continue, so nothing needs to be done. To change the interval, run
`autostart enable --every ...` again and log out and in, or stop that process first
(Task Manager on Windows, `kill` elsewhere). The lock is released automatically when
the process ends, even after a crash.

## Several workbooks for the same manuscript

Sync clients sometimes create conflict copies such as `... (1).xlsx`. The most
recently modified file is used and a warning is logged; merge the rows you want to
keep into one file and delete the others.

## The workbooks keep their old names

The `workbook_name` template only names new workbooks: an existing history is never
split, so changing the template (or a custom field) does not rename anything by
itself. Run `paper-status-monitor organize --dry-run` to see the renames, merges and splits
needed, then `paper-status-monitor organize` to apply them. `doctor` warns when
workbooks do not follow the template.

## "Unknown placeholder(s) {paper}"

The template uses a custom field that no submission has. Add it to at least one
submission (`fields = { paper = "Tau" }`, or `add --field paper=Tau`), or remove it
from `workbook_name`.

## A change was recorded but no report was opened

That is the expected behaviour when the change is only in columns that are not
notified (`notify_fields`, `notify_ignore`): `run` shows it as `[RECORDED]`. A change
that is notified but not recorded is reported only once.

## Desktop notifications do not appear

- Check that `notify` includes `"toast"`: `paper-status-monitor doctor` shows how you
  are told about news. In the graphical interface, *Test* shows one right away.
- Windows: focus assist or *do not disturb* may hide them (they then wait in the
  notification centre), and the notifications of *Windows PowerShell* must not be
  turned off in *Settings → System → Notifications*.
- Linux: install `notify-send` (`sudo apt install libnotify-bin` on Debian and
  Ubuntu); `doctor` warns when it is missing.
- The reason of a failure is written to the log file. The report is written anyway.

## E-mails are not sent

- Run `paper-status-monitor email test`: it sends a test message and explains what
  went wrong.
- *There is no password*: set the `PAPER_STATUS_MONITOR_SMTP_PASSWORD` environment
  variable, or run `paper-status-monitor email set-password` (it needs the `keyring`
  package). The program started at login does not see a variable set only in one
  terminal: set it for your user account (on Windows, *Edit environment variables for
  your account*), or use the keyring.
- *Refused the user name or the password*: many providers (Gmail, Outlook.com...)
  need an *app password* instead of your usual one.
- Check `security` and `smtp_port` with the instructions of your provider:
  `starttls` usually uses port 587 and `ssl` port 465.
- The reason of a failure is written to the log file. The report is written anyway.

## The periodic checks do not run

- They start with the login that follows `autostart enable --every ...`, and stop
  when you log out. `paper-status-monitor autostart status` shows
  `Checks: at login, then every 12h` when they are enabled.
- After every check, the log file has a line `Next check at about ...`.
- If the computer was asleep at the planned time, the check runs shortly after it
  wakes up.

## The icon is not in the notification area

- It is only shown while periodic checks run with `--tray` (`autostart status` shows
  `with an icon in the notification area`), from the login that follows `autostart
  enable --every 12h --tray`, and only on Windows.
- Windows often puts new icons in the hidden part of the notification area: click the
  `^` arrow next to the clock. Drag the icon to the taskbar, or turn it on in
  *Settings → Personalization → Taskbar → Other system tray icons*, to keep it in
  sight.
- *Stop the periodic checks* removes it until your next login.
- If it could not be shown, the reason is in the log file (`The icon could not be
  shown...`); the checks go on without it.

## The window does not open

- `The graphical interface needs tkinter`: your Python was installed without
  tkinter. On Debian or Ubuntu, `sudo apt install python3-tk`; on Windows, rerun the
  Python installer and select *tcl/tk and IDLE*.
- `The window could not be opened`: there is no graphical display (for example, over
  SSH). Use the command line instead.

## "Review Complete" right after submitting a revision

It does not necessarily mean a decision. The official page shows *Review Complete*
for every internal status it has no label for, and a revision that has just reached
the tracker was seen that way, with all the reviewer counts back at zero, until
reviewers were invited; it then became *Under Review*. See {ref}`observed-statuses`.

## Unexpected or missing values

The tracker may change its data format. Compare the output of
`paper-status-monitor check LINK --json` with the columns described in
{doc}`workbooks` and [open an issue](https://github.com/dsanchez-garcia/paper-status-monitor/issues)
— without sharing your tracking link, which is personal.

