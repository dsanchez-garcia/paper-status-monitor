# TODO

Prioritised backlog. Pick an item, move it to *In progress* in your pull request, and
to *Done* (with the version) when it is merged. Keep items small and testable.

## Next (high priority)

- [ ] **Publish 0.1.0 on PyPI**: add the pending trusted publisher on PyPI (see
      `docs/development.md` → Releasing) and create the GitHub release `v0.1.0`.
- [ ] **Import the project on Read the Docs** and check that the badge in the README
      turns green.

## Later (medium priority)

- [ ] Complete the table of status codes in `docs/how-it-works.md` (*Statuses
      observed in practice*) as codes are recorded, always anonymised. Only 3 has
      been recorded so far; still unknown: the codes behind *Review Complete* (after
      the reviews, and when a revision has just reached the tracker) and whether
      revisions under review use 3 or 23.

## Ideas (low priority)

- [ ] Support other editorial systems (ScholarOne, Editorial Manager, MDPI
      SuSy...) through a pluggable backend interface (`Backend.fetch(id) ->
      Snapshot`). Blocked: unlike Elsevier's tracker, these systems have no public
      tracking link; their status pages need the author's login, so a backend would
      have to keep a password (in the system keyring) and scrape HTML, which their
      terms of use may forbid. Start with a system that offers an unauthenticated
      status page or an API, and design the interface around two real backends.
- [ ] More languages for the reports and the window (Spanish is available since the
      unreleased version): copy `src/paper_status_monitor/locales/es.py`.
- [ ] Tray icon on Linux and macOS (the Windows one, `run --every --tray`, exists
      since the unreleased version); it would need a third-party package.

## Done

- [x] Unreleased — icon in the notification area while the periodic checks run
      (`run --every --tray`, `autostart enable --tray`, tick box in the window), with
      the latest statuses and a menu (check now, open the window, the report or the
      data folder, stop); Windows only, through `ctypes`.

- [x] Unreleased — reports, notifications, e-mails, summary and window in Spanish
      (`language` setting, `init --language`, selector in the window), with a test
      that keeps the catalogs complete.
- [x] Unreleased — buttons in the Windows toast notifications (open the report, the
      workbook or its folder, the tracking page), through protocol activation.
- [x] Unreleased — `edit` command (label, custom fields and own settings, in place);
      autostart on Linux (XDG autostart entry) and macOS (launchd agent), with tests
      for the generated files; per-submission `record_*` / `notify_*` settings (CLI,
      GUI, `list`, `doctor`); optional `Time in status` sheet in every workbook
      (`time_in_status`), with live formulas for the current status; e-mail
      notifications through SMTP (`notify = "email"`, `[email]`, `email` command),
      with the password only in the environment or the system keyring; `organize`
      splits a shared workbook whose submissions now map to different names; only
      one loop of periodic checks (`run --every`) at a time; `export` of the
      history to CSV or JSON; the statuses observed on real submissions, anonymised,
      in `docs/how-it-works.md`.
- [x] Unreleased — Weekly contract test against the real tracker that opens an issue
      when the format changes (`contract.yml`); periodic checks while the computer
      stays on (`run --every`, `autostart enable --every`, GUI); desktop
      notifications (`notify = "report" | "toast" | "none"` or a list: Windows
      toasts, `osascript`, `notify-send`); `remove`, `enable` and `disable` commands
      that keep the comments of the configuration, without new dependencies; a
      `summary` command (text, Markdown or HTML), also in the window.
- [x] Unreleased — Independent record/notify choices per column (`record_*`,
      `notify_*`, `run` overrides), workbook name templates with custom fields,
      shared workbooks (e.g. one per paper), `organize`, and an English tkinter GUI.
- [x] 0.1.0 — Rewrite as an installable package: JSON API instead of Selenium, one
      workbook per manuscript and journal (revisions no longer create new files),
      change reports, Windows autostart with readiness wait, `doctor`, strict TOML
      configuration, tests, CI, Read the Docs documentation, PyPI packaging and AI
      agent guidance (`AGENTS.md`).

