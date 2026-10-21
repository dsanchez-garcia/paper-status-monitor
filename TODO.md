# TODO

Prioritised backlog. Pick an item, move it to *In progress* in your pull request, and
to *Done* (with the version) when it is merged. Keep items small and testable.

## Next (high priority)

- [ ] **Publish 0.1.0 on PyPI**: add the pending trusted publisher on PyPI (see
      `docs/development.md` → Releasing) and create the GitHub release `v0.1.0`.
- [ ] **Import the project on Read the Docs** and check that the badge in the README
      turns green.
- [ ] **Scheduled contract test**: a weekly GitHub Actions job that runs
      `pytest -m network` against the demo submission and opens an issue if the API
      format changes.
- [ ] **Periodic checks while the computer stays on**: an option such as
      `autostart enable --daily 09:00` (Task Scheduler) or `run --every 12h`, so
      long uptimes do not skip checks.
- [ ] **Desktop notifications** as an alternative to opening the text report
      (Windows toast notifications; `notify-send` on Linux; `osascript` on macOS),
      selectable with a `notify = "report" | "toast" | "none"` setting.

## Later (medium priority)

- [ ] `remove`, `enable` and `disable` commands that edit the configuration while
      preserving comments (e.g. with `tomlkit`).
- [ ] `summary` command: one table with the latest status of every submission
      (console, Markdown or HTML).
- [ ] Optional e-mail notifications through SMTP. Credentials must come from
      environment variables or the OS keyring, never from files in the repository.
- [ ] Native autostart for Linux (XDG autostart / systemd user timer) and macOS
      (LaunchAgent) in `autostart.py`, with tests for the generated files.
- [ ] Document the meaning of internal status codes (`Status code` column) as they
      are observed, e.g. in `docs/how-it-works.md`.
- [ ] Optional "Summary" sheet in each workbook with the time spent in each status.

## Ideas (low priority)

- [ ] Support other editorial systems (ScholarOne, Editorial Manager, MDPI
      SuSy...) through a pluggable backend interface (`Backend.fetch(uuid) ->
      Snapshot`).
- [ ] Export the history to CSV/JSON for people who do not use Excel.
- [ ] A tiny GUI (system tray icon) showing the last run and the latest statuses.
- [ ] Localised reports (Spanish, ...).

## Done

- [x] 0.1.0 — Rewrite as an installable package: JSON API instead of Selenium, one
      workbook per manuscript and journal (revisions no longer create new files),
      change reports, Windows autostart with readiness wait, `doctor`, strict TOML
      configuration, tests, CI, Read the Docs documentation, PyPI packaging and AI
      agent guidance (`AGENTS.md`).

