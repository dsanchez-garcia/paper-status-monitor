"""Rename and merge existing workbooks so that they follow the naming template.

The ``workbook_name`` setting decides the name of the workbook of a submission
when it is first recorded. A history is never split afterwards: if the template
changes, the rows of a submission keep being appended to the workbook that already
holds them. ``paper-status-monitor organize`` brings existing workbooks in line
with the current template:

* a workbook whose submissions now map to a free name is **renamed**;
* workbooks whose submissions now map to the same name (for example, with
  ``workbook_name = "{paper}"``, the submissions of one paper to several journals)
  are **merged** into one, with the rows in chronological order. A copy of every
  workbook involved is first saved in ``<data_dir>/backups/organize-<date>/``.

A workbook is left untouched (and the reason reported) when it also holds rows of
submissions that are not in the configuration, or when its submissions would go
to different workbooks (splitting a workbook is not supported).
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from paper_status_monitor import naming, storage
from paper_status_monitor.config import Config, SubmissionConfig
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
    """A planned rename or merge.

    Attributes:
        kind: ``"rename"`` or ``"merge"``.
        target: Workbook that results from the action.
        sources: Workbooks renamed or merged into *target*.
        submissions: Names of the submissions whose history moves.
    """

    kind: str
    target: Path
    sources: tuple[Path, ...]
    submissions: tuple[str, ...] = ()

    def describe(self) -> str:
        """Return a human-readable, multi-line description of the action."""
        if self.kind == "rename":
            return f"Rename  {self.sources[0].name}\n    ->  {self.target.name}"
        existing = " (existing workbook)" if self.target.exists() else ""
        lines = [f"Merge into  {self.target.name}{existing}"]
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
    for source, names in by_source.items():
        expected = {str(name.expected) for name in names}
        if len({value.casefold() for value in expected}) > 1:
            plan.skipped.append(
                f"{source.name}: its submissions ({_names(names)}) would now go to different "
                "workbooks; splitting a workbook is not supported, move the rows by hand."
            )
            continue
        owned = {
            id(record)
            for name in names
            for record in store.submission_records(source, name.key, name.submission.uuid)
        }
        foreign = sum(1 for record in store.records(source) if id(record) not in owned)
        target_name = expected.pop()
        if foreign and source.name != target_name:
            plan.skipped.append(
                f"{source.name}: it also holds {foreign} row(s) of submissions that are not in "
                "the configuration; rename or merge it by hand."
            )
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
                f"{action.target.name}: it is renamed or merged itself; run 'organize' again "
                "afterwards to finish."
            )
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
                done, problems = _merge(action, outcome.backup_dir)
                outcome.done.append(done)
                outcome.errors += problems
        except PermissionError as exc:
            outcome.errors.append(
                f"{_first_line(action)}: {exc}. Close the workbooks in Excel and try again."
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
        raise FileExistsError(f"{target.name} already exists")
    os.replace(source, target)
    return f"Renamed {source.name} -> {target.name}"


def _merge(action: Action, backup_dir: Path) -> tuple[str, list[str]]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in (action.target, *action.sources):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)
    rows = storage.merge_workbooks(action.target, action.sources)
    problems = []
    for source in action.sources:
        try:
            source.unlink()
        except OSError as exc:
            problems.append(
                f"{source.name} was merged into {action.target.name} but could not be "
                f"removed ({exc}); delete it by hand (a copy is in {backup_dir})."
            )
    merged = ", ".join(source.name for source in action.sources)
    return f"Merged {merged} into {action.target.name} ({rows} rows)", problems


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _first_line(action: Action) -> str:
    return action.describe().splitlines()[0].replace("  ", " ")


def _names(names: list[WorkbookName]) -> str:
    return ", ".join(name.submission.display_name for name in names)
