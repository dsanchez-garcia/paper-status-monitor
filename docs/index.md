# paper-status-monitor

**Monitor the peer-review status of your Elsevier submissions and keep one Excel
history per manuscript.**

Elsevier journals send authors a *Track your submission* link
(`https://track.authorhub.elsevier.com/?uuid=...`). The page behind it shows the
status of the manuscript, the number of reviewers invited and the number of reviews
completed, the date of the last review activity and the revision number.

`paper-status-monitor` checks those pages for you, typically every time you log in:

- it records every change in **one Excel workbook per manuscript and journal** (all
  revisions go to the same file);
- it writes a **plain-text report** and opens it when something changes;
- it **waits** for the network and for cloud drives (Google Drive, OneDrive...) at
  login, retries on errors and logs everything, so problems do not go unnoticed;
- it needs **no browser**: it reads the same JSON data as the official page.

```{admonition} Not affiliated with Elsevier
:class: note

This is an independent, open-source tool. It uses an undocumented endpoint of the
official tracking page that may change at any time. Use it only for your own
submissions and at a low frequency (see {doc}`how-it-works`).
```

## Where to start

- New users: {doc}`installation` and then {doc}`quickstart`.
- Run it automatically when you log in: {doc}`autostart`.
- Something does not work: {doc}`troubleshooting` and `paper-status-monitor doctor`.
- Developers and AI coding agents: {doc}`development` and the
  [AGENTS.md](https://github.com/dsanchez-garcia/paper-status-monitor/blob/main/AGENTS.md)
  file in the repository.

```{toctree}
:maxdepth: 2
:caption: User guide

installation
quickstart
configuration
cli
gui
autostart
workbooks
troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Reference

how-it-works
api
development
changelog
```

