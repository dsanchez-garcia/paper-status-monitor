# Quick start

This page takes you from installation to automatic monitoring in five minutes.

## 1. Try the demo submission

The tracker serves a public, fictional submission with the UUID
`00000000-0000-0000-0000-000000000000`. Use it to check that everything works:

```console
$ paper-status-monitor check 00000000-0000-0000-0000-000000000000
Title:                       Influence of submission trackers, article shredding and ...
Revision:                    0
Status:                      Under Review
Status code:                 3
Last review activity:        17th May 2022
Reviews completed:           1
Review invitations accepted: 2
Review invitations sent:     2+
Journal:                     The International Journal of Submission Trackers
Corresponding author:        Maximilian Spillage
First author:                Zachary Mindwarp
Date of submission:          3rd March 2020
Manuscript number:           SUBTRAK-D-22-00128
Tracker URL:                 https://track.authorhub.elsevier.com/?uuid=00000000-0000-0000-0000-000000000000
```

`check` never writes anything.

## 2. Create the configuration file

Choose the folder where the workbooks and reports will be stored. A cloud-synced
folder (Google Drive, OneDrive, Dropbox...) is fine.

```console
paper-status-monitor init --data-dir "C:\Users\me\Documents\Paper status"
```

The file is created in the default location (on Windows,
`%APPDATA%\paper-status-monitor\config.toml`). See {doc}`configuration` for all the
settings.

## 3. Add your submissions

Find the *Track your submission* link in the e-mail the journal sent you after
submission, and add it:

```console
paper-status-monitor add "https://track.authorhub.elsevier.com/?uuid=<your-uuid>" --label "My paper"
```

The tool contacts the tracker, shows the title it found and appends a
`[[submissions]]` block to the configuration file. Repeat for each manuscript.

```{note}
The same link keeps working for all the revisions of a manuscript, so you only need
to add it once.
```

## 4. Run a check

```console
$ paper-status-monitor run
Checked 1 submission(s) at 2026-10-21 08:55:12
  [NEW]       My paper title (Under Review)
Report: C:\Users\me\Documents\Paper status\reports\changes_2026-10-21_08-55-12.txt
```

The first run creates the workbook and a report listing the newly tracked
submission. Later runs only write a row (and a report) when something changes.

## 5. Check automatically at every login (Windows)

```console
paper-status-monitor autostart enable
```

From now on, the monitor runs in the background (without a console window) every
time you log in, and the report opens in your text editor when there is news. See
{doc}`autostart` for details and for Linux/macOS.

## 6. Make sure everything is fine

```console
paper-status-monitor doctor
```

`doctor` checks the configuration, the data folder, the connection to the tracker,
the autostart shortcut and the result of the last run.

