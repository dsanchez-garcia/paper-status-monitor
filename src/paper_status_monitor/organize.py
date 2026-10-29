"""Rename and merge existing workbooks so that they follow the naming template.

The ``workbook_name`` setting decides the name of the workbook of a submission
when it is first recorded. A history is never split afterwards: if the template
changes, the rows of a submission keep being appended to the workbook that already
holds them. ``paper-status-monitor organize`` brings existing workbooks in line
with the current template:

* a workbook whose submissions now map to a free name is **renamed**;
* workbooks whose submissions now map to the same name (for example, with
  ``workbook_name = "{paper}"``, the submissions of one paper to several journals)
  are **merged** into one, with the rows in chronological order;
* a workbook whose submissions now map to different names is **split**: the rows of
  each submission go to its workbook (a copy of the original, or an existing
  workbook they are merged into), and the original keeps only its own rows or is
  removed.

A copy of every workbook that is merged or split is first saved in
``<data_dir>/backups/organize-<date>/``. A workbook is left untouched (and the reason
reported) when it also holds rows of submissions that are not in the configuration.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from paper_status_monitor import naming, storage
from paper_status_monitor.config import Config, SubmissionConfig
from paper_status_monitor.i18n import _, ngettext
from paper_status_monitor.models import Snapshot
from paper_status_monitor.state import SEEN_FILE_NAME, SeenSnapshots

log = logging.getLogger(__name__)

#: Subfolder of the data folder where ``organize`` keeps copies of the workbooks.
BACKUP_DIR_NAME = "backups"


@dataclass(frozen=True)
class WorkbookName:
    """Current and expected workbook of a configured submission.

    Attributes:
        submission: The configured submission.
        current: Workbook that holds its history (``None`` if not recorded yet).
        expected: File name given by the naming template for the last recorded state
            (``None`` if the submission has not been recorded yet).
        key: Base manuscript number of the submission (empty if not recorded yet).
    """

    submission: SubmissionConfig
    current: Path | None = None
    expected: str | None = None
    key: str = ""

    @property
    def needs_change(self) -> bool:
        """``True`` if the workbook name does not follow the template."""
        return self.current is not None and self.expected not in (None, self.current.name)


@dataclass(frozen=True)
class Action:
    """A planned rename, merge or split.

    Attributes:
        kind: ``"rename"``, ``"merge"`` or ``"split"``.
        target: Workbook that results from the action (for a split, the workbook
            that is split).
        sources: Workbooks renamed or merged into *target* (for a split, the workbook
            that is split).
        submissions: Names of the submissions whose history moves.
        parts: For a split, the workbook of every group of submissions, with the
            base manuscript number, the tracking UUID and the name of each one.
    """

    kind: str
    target: Path
    sources: tuple[Path, ...]
    submissions: tuple[str, ...] = ()
    parts: tuple[tuple[Path, tuple[tuple[str, str, str], ...]], ...] = ()

    def describe(self) -> str:
        """Return a human-readable, multi-line description of the action.

        The text is in the current language (see :mod:`~paper_status_monitor.i18n`).
        """
        if self.kind == "rename":
            return _("Rename  {source}\n    ->  {target}").format(
                source=self.sources[0].name, target=self.target.name
            )
        if self.kind == "split":
            lines = [_("Split   {workbook}").format(workbook=self.target.name)]
            for target, members in self.parts:
                if target == self.target:
                    note = " " + _("(kept here)")
                else:
                    note = " " + _("(existing workbook)") if target.exists() else ""
                who = ", ".join(name for _key, _uuid, name in members)
                lines.append(f"    ->  {target.name}{note}: {who}")
            return "\n".join(lines)
        existing = " " + _("(existing workbook)") if self.target.exists() else ""
        lines = [_("Merge into  {workbook}").format(workbook=self.target.name) + existing]
        lines += [f"    +  {source.name}" for source in self.sources]
        return "\n".join(lines)


@dataclass
class OrganizePlan:
    """What ``organize`` would do.

    Attributes:
        actions: Renames and merges, in order.
        skipped: Workbooks left untouched, with the reason.
        names: Current and expected workbook of every configured submission.
    """

    actions: list[Action] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    names: list[WorkbookName] = field(default_factory=list)


@dataclass
class OrganizeOutcome:
    """What ``organize`` did.

    Attributes:
        done: One line per completed action.
        errors: Problems (the corresponding workbooks were left as they were).
        backup_dir: Folder with the copies made before merging, if any.
    """

    done: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    backup_dir: Path | None = None


def workbook_names(
    config: Config, store: storage.WorkbookStore | None = None
) -> list[WorkbookName]:
    """Return the current and expected workbook of every configured submission.

    The expected name is computed from the last row recorded for the submission
    and its configuration (label and custom fields); nothing is downloaded.
    """
    store = store or storage.WorkbookStore(config.data_dir)
    seen = SeenSnapshots.load(config.data_dir / SEEN_FILE_NAME)
    names = []
    for submission in config.submissions:
        location = store.locate_uuid(submission.uuid, hint=seen.workbook(submission.uuid))
        if location is None or location.last_record is None:
            names.append(WorkbookName(submission))
            continue
        snapshot = Snapshot.from_record(location.last_record)
        expected = naming.workbook_file_name(config.workbook_name, snapshot, submission)
        names.append(WorkbookName(submission, location.path, expected, location.key))
    return names


def plan_organize(config: Config, store: storage.WorkbookStore | None = None) -> OrganizePlan:
    """Work out the renames and merges needed to follow the naming template."""
    store = store or storage.WorkbookStore(config.data_dir)
    plan = OrganizePlan(names=workbook_names(config, store))
    by_source: dict[Path, list[WorkbookName]] = {}
    for name in plan.names:
        if name.current is not None:
            by_source.setdefault(name.current, []).append(name)

    groups: dict[str, dict[Path, list[WorkbookName]]] = {}
    splits: list[Action] = []
    for source, names in by_source.items():
        expected = {str(name.expected) for name in names}
        if len({value.casefold() for value in expected}) > 1:
            split = _plan_split(source, names, store, config.data_dir)
            if isinstance(split, str):
                plan.skipped.append(split)
            else:
                splits.append(split)
            continue
        owned = {
            id(record)
            for name in names
            for record in store.submission_records(source, name.key, name.submission.uuid)
        }
        foreign = sum(1 for record in store.records(source) if id(record) not in owned)
        target_name = expected.pop()
        if foreign and source.name != target_name:
            reason = ngettext(
                "{workbook}: it also holds {count} row of submissions that are not in the "
                "configuration; rename or merge it by hand.",
                "{workbook}: it also holds {count} rows of submissions that are not in the "
                "configuration; rename or merge it by hand.",
                foreign,
            )
            plan.skipped.append(reason.format(workbook=source.name, count=foreign))
            continue
        groups.setdefault(target_name.casefold(), {})[source] = names

    for sources in groups.values():
        target_name = str(next(iter(sources.values()))[0].expected)
        target = config.data_dir / target_name
        moving = [source for source in sources if source.name != target_name]
        if not moving:
            continue
        submissions = tuple(name.submission.display_name for s in moving for name in sources[s])
        in_place = len(moving) < len(sources)
        if (
            len(moving) == 1
            and not in_place
            and (not target.exists() or _same_file(moving[0], target))
        ):
            plan.actions.append(Action("rename", target, (moving[0],), submissions))
        else:
            plan.actions.append(Action("merge", target, tuple(moving), submissions))

    moving_sources = {source for action in plan.actions for source in action.sources}
    for action in list(plan.actions):
        if action.target in moving_sources and action.target not in action.sources:
            plan.actions.remove(action)
            plan.skipped.append(
                _(
                    "{workbook}: it is renamed or merged itself; run 'organize' again "
                    "afterwards to finish."
                ).format(workbook=action.target.name)
            )
    busy = {path for action in plan.actions for path in (action.target, *action.sources)}
    split_sources = {action.target for action in splits}
    for action in splits:
        parts = {target for target, _members in action.parts} - {action.target}
        if action.target in busy or parts & (busy | split_sources):
            plan.skipped.append(
                _(
                    "{workbook}: it takes part in another change; run 'organize' again "
                    "afterwards to split it."
                ).format(workbook=action.target.name)
            )
        else:
            plan.actions.append(action)
    return plan


def apply_organize(
    plan: OrganizePlan, config: Config, *, now: Callable[[], datetime] = datetime.now
) -> OrganizeOutcome:
    """Carry out a plan made by :func:`plan_organize`.

    Every action is independent: if one fails (typically because a workbook is
    open in Excel), it is reported and the others still run.
    """
    outcome = OrganizeOutcome()
    for action in plan.actions:
        try:
            if action.kind == "rename":
                outcome.done.append(_rename(action))
            else:
                if outcome.backup_dir is None:
                    stamp = f"organize-{now():%Y-%m-%d_%H-%M-%S}"
                    outcome.backup_dir = config.data_dir / BACKUP_DIR_NAME / stamp
                change = _split if action.kind == "split" else _merge
                done, problems = change(
                    action, outcome.backup_dir, time_in_status=config.time_in_status
                )
                outcome.done.append(done)
                outcome.errors += problems
        except storage.WorkbookLockedError as exc:
            outcome.errors.append(f"{_first_line(action)}: {exc}")
        except PermissionError as exc:
            outcome.errors.append(
                _("{action}: {error}. Close the workbooks in Excel and try again.").format(
                    action=_first_line(action), error=exc
                )
            )
        except Exception as exc:  # report and keep going with the other actions
            log.exception("Could not organize %s", action.target.name)
            outcome.errors.append(f"{_first_line(action)}: {type(exc).__name__}: {exc}")
    for line in outcome.done:
        log.info("organize: %s", line)
    for line in outcome.errors:
        log.error("organize: %s", line)
    return outcome


def _rename(action: Action) -> str:
    source, target = action.sources[0], action.target
    if target.exists() and not _same_file(source, target):
        raise FileExistsError(_("{workbook} already exists").format(workbook=target.name))
    os.replace(source, target)
    return _("Renamed {source} -> {target}").format(source=source.name, target=target.name)


def _merge(
    action: Action, backup_dir: Path, *, time_in_status: bool = False
) -> tuple[str, list[str]]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in (action.target, *action.sources):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)
    rows = storage.merge_workbooks(action.target, action.sources, time_in_status=time_in_status)
    problems = []
    for source in action.sources:
        try:
            source.unlink()
        except OSError as exc:
            problems.append(
                _(
                    "{source} was merged into {target} but could not be removed ({error}); "
                    "delete it by hand (a copy is in {folder})."
                ).format(
                    source=source.name, target=action.target.name, error=exc, folder=backup_dir
                )
            )
    merged = ", ".join(source.name for source in action.sources)
    done = ngettext(
        "Merged {sources} into {target} ({count} row)",
        "Merged {sources} into {target} ({count} rows)",
        rows,
    )
    return done.format(sources=merged, target=action.target.name, count=rows), problems


def _plan_split(
    source: Path, names: list[WorkbookName], store: storage.WorkbookStore, data_dir: Path
) -> Action | str:
    """Plan how to split a workbook whose submissions now go to different workbooks.

    Returns:
        The action, or the reason why the workbook is left as it is.
    """
    groups: dict[str, list[WorkbookName]] = {}
    for name in names:
        groups.setdefault(str(name.expected).casefold(), []).append(name)
    unattributed = 0
    for record in store.records(source):
        owners = [
            group
            for group in groups.values()
            if any(storage.belongs_to(record, name.key, name.submission.uuid) for name in group)
        ]
        unattributed += len(owners) != 1
    if unattributed:
        reason = ngettext(
            "{workbook}: its submissions ({names}) now go to different workbooks, but "
            "{count} of its rows belongs to none of them (or to several); split it by hand.",
            "{workbook}: its submissions ({names}) now go to different workbooks, but "
            "{count} of its rows belong to none of them (or to several); split it by hand.",
            unattributed,
        )
        return reason.format(workbook=source.name, names=_names(names), count=unattributed)
    parts = tuple(
        (
            data_dir / str(group[0].expected),
            tuple((name.key, name.submission.uuid, name.submission.display_name) for name in group),
        )
        for group in groups.values()
    )
    names_moved = tuple(name.submission.display_name for name in names)
    return Action("split", source, (source,), names_moved, parts)


def _split(
    action: Action, backup_dir: Path, *, time_in_status: bool = False
) -> tuple[str, list[str]]:
    """Move the rows of every submission of a workbook to its own workbook."""
    source = action.target
    involved = [source, *(target for target, _members in action.parts if target != source)]
    storage.ensure_writable(involved)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in involved:
        copy = backup_dir / path.name
        if path.exists() and not copy.exists():  # keep the oldest copy of this run
            shutil.copy2(path, copy)
    moved: list[str] = []
    kept: Callable[[Mapping[str, str]], bool] | None = None
    for target, members in action.parts:
        if target == source or _same_file(target, source):
            kept = _rows_of(members)
            continue
        rows = storage.copy_rows(source, target, _rows_of(members), time_in_status=time_in_status)
        part = ngettext("{workbook} ({count} row)", "{workbook} ({count} rows)", rows)
        moved.append(part.format(workbook=target.name, count=rows))
    targets = ", ".join(moved)
    if kept is not None:
        rows = storage.copy_rows(source, source, kept, time_in_status=time_in_status)
        done = ngettext(
            "Split {workbook}: kept {count} row, moved the others to {targets}",
            "Split {workbook}: kept {count} rows, moved the others to {targets}",
            rows,
        )
        return done.format(workbook=source.name, count=rows, targets=targets), []
    done = _("Split {workbook} into {targets}").format(workbook=source.name, targets=targets)
    try:
        source.unlink()
    except OSError as exc:
        problem = _(
            "{workbook} was split but could not be removed ({error}); delete it by hand "
            "(a copy is in {folder})."
        ).format(workbook=source.name, error=exc, folder=backup_dir)
        return done, [problem]
    return done, []


def _rows_of(members: tuple[tuple[str, str, str], ...]) -> Callable[[Mapping[str, str]], bool]:
    """Return a test for the rows of a group of submissions."""

    def keep(record: Mapping[str, str]) -> bool:
        return any(storage.belongs_to(record, key, uuid) for key, uuid, _name in members)

    return keep


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _first_line(action: Action) -> str:
    return " ".join(action.describe().splitlines()[0].split())


def _names(names: list[WorkbookName]) -> str:
    return ", ".join(name.submission.display_name for name in names)
