# TODO

Prioritised backlog. Pick an item, move it to *In progress* in your pull request, and
to *Done* (with the version) when it is merged. Keep items small and testable.

## Next (high priority)

- [ ] **Publish 0.1.0 on PyPI**: add the pending trusted publisher on PyPI (see
      `docs/development.md` → Releasing) and create the GitHub release `v0.1.0`.
- [ ] **Import the project on Read the Docs** and check that the badge in the README
      turns green.

## Later (medium priority)

- [ ] `edit` command to change the label or the custom fields of a submission in
      place, keeping the comments (like `remove`, `enable` and `disable`).
- [ ] Optional e-mail notifications through SMTP. Credentials must come from
      environment variables or the OS keyring, never from files in the repository.
- [ ] Native autostart for Linux (XDG autostart / systemd user timer) and macOS
      (LaunchAgent) in `autostart.py`, with tests for the generated files. They can
      start `run --wait 300 --every 12h` at login, like the Windows shortcut.
- [ ] Document the meaning of internal status codes (`Status code` column) as they
      are observed, e.g. in `docs/how-it-works.md`.
- [ ] Optional "Summary" sheet in each workbook with the time spent in each status.
- [ ] Per-submission `record_*` / `notify_*` overrides (today they apply to every
      submission).
- [ ] `organize`: split a workbook whose submissions now map to different names
      (today it is reported and left untouched).

## Ideas (low priority)

- [ ] Support other editorial systems (ScholarOne, Editorial Manager, MDPI
      SuSy...) through a pluggable backend interface (`Backend.fetch(uuid) ->
      Snapshot`).
- [ ] Export the history to CSV/JSON for people who do not use Excel.
- [ ] A system tray icon showing the last run and the latest statuses (the GUI
      window exists since the unreleased version).
- [ ] Localised reports and GUI (Spanish, ...).
- [ ] Buttons in the Windows toast notification (open the workbook, open the
      tracking page), through protocol activation.
- [ ] Refuse a second `run --every` loop in the same session (today it only adds
      requests: the run lock keeps checks from overlapping).

## Done

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

