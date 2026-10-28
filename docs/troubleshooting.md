# Troubleshooting

Start with:

```console
paper-status-monitor doctor
```

and look at the log file it prints (`[INFO] Log file: ...`).

## Nothing happens at login

1. Run `paper-status-monitor autostart status`. If the interpreter is marked
   `(MISSING!)`, Python was reinstalled or upgraded: install the package in the
   current Python and run `paper-status-monitor autostart enable` again.
2. Run `paper-status-monitor doctor`. The autostart line also checks that the
   interpreter used at login can import the package.
3. Check the end of the log file: every run at login writes at least one line.
4. Remember that, by design, nothing is shown when nothing changed. The `Last run`
   line of `doctor` tells you when the last run finished.

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

## Several workbooks for the same manuscript

Sync clients sometimes create conflict copies such as `... (1).xlsx`. The most
recently modified file is used and a warning is logged; merge the rows you want to
keep into one file and delete the others.

## The workbooks keep their old names

The `workbook_name` template only names new workbooks: an existing history is never
split, so changing the template (or a custom field) does not rename anything by
itself. Run `paper-status-monitor organize --dry-run` to see the renames and merges
needed, then `paper-status-monitor organize` to apply them. `doctor` warns when
workbooks do not follow the template.

## "Unknown placeholder(s) {paper}"

The template uses a custom field that no submission has. Add it to at least one
submission (`fields = { paper = "TMY" }`, or `add --field paper=TMY`), or remove it
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

## The periodic checks do not run

- They start with the login that follows `autostart enable --every ...`, and stop
  when you log out. `paper-status-monitor autostart status` shows
  `Checks: at login, then every 12h` when they are enabled.
- After every check, the log file has a line `Next check at about ...`.
- If the computer was asleep at the planned time, the check runs shortly after it
  wakes up.

## The window does not open

- `The graphical interface needs tkinter`: your Python was installed without
  tkinter. On Debian or Ubuntu, `sudo apt install python3-tk`; on Windows, rerun the
  Python installer and select *tcl/tk and IDLE*.
- `The window could not be opened`: there is no graphical display (for example, over
  SSH). Use the command line instead.

## Unexpected or missing values

The tracker may change its data format. Compare the output of
`paper-status-monitor check LINK --json` with the columns described in
{doc}`workbooks` and [open an issue](https://github.com/dsanchez-garcia/paper-status-monitor/issues)
— without sharing your tracking link, which is personal.

