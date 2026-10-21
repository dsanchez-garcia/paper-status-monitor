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
  final decision. The change is recorded once in the workbook; remove the submission
  from the configuration or set `enabled = false`.

## "Cannot write ...xlsx: the file is in use"

The workbook is open in Excel (which locks it). Close it; the change is detected
again and written on the next run.

## "Another run seems to be in progress"

A run is already active (for example, the autostart one). If you are sure that no
other run is active (for instance after a crash), delete the `run.lock` file whose
path is shown in the message. Stale locks are removed automatically after one hour.

## Several workbooks for the same manuscript

Sync clients sometimes create conflict copies such as `... (1).xlsx`. The most
recently modified file is used and a warning is logged; merge the rows you want to
keep into one file and delete the others.

## Unexpected or missing values

The tracker may change its data format. Compare the output of
`paper-status-monitor check LINK --json` with the columns described in
{doc}`workbooks` and [open an issue](https://github.com/dsanchez-garcia/paper-status-monitor/issues)
— without sharing your tracking link, which is personal.

