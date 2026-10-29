"""Workbook file names built from a template with placeholders.

The ``workbook_name`` setting is a template such as::

    {paper} - {journal} - {manuscript_number}

Every ``{placeholder}`` is replaced with a value of the submission: the built-in
placeholders listed in :data:`PLACEHOLDERS` come from the tracker, and any other
name refers to a *custom field* declared in the configuration (for instance
``fields = { paper = "Tau" }``). Placeholders accept the usual Python format
specification, so ``{title:.40}`` keeps the first 40 characters of the title.

Submissions whose names coincide share a workbook. A template without
``{manuscript_number}``, such as ``"{paper}"``, therefore keeps every submission of
a paper (one per journal) in a single file. Rows are told apart by their content,
see :class:`paper_status_monitor.storage.WorkbookStore`.

When a placeholder is empty, it is removed together with the separator next to it,
so ``"{paper} - {journal}"`` becomes ``"Journal"`` for a submission without a
``paper`` field.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable, Mapping
from typing import Protocol

from paper_status_monitor.models import (
    COLUMNS,
    Snapshot,
    clean_text,
    parse_tracker_date,
    strip_revision_prefix,
)
from paper_status_monitor.storage import MAX_STEM_LENGTH, sanitize_filename, workbook_name

#: Template that reproduces the names used by previous versions.
DEFAULT_WORKBOOK_NAME = "{manuscript_number} - {journal} - {title}"

#: Built-in placeholders and a short description of their value.
PLACEHOLDERS: dict[str, str] = {
    "manuscript_number": "manuscript number without the revision suffix (ABC-D-26-00001)",
    "journal": "journal name",
    "journal_acronym": "first part of the manuscript number, usually the journal acronym (ABC)",
    "title": "manuscript title",
    "first_author": "first author",
    "corresponding_author": "corresponding author",
    "date_of_submission": "date of the original submission as YYYY-MM-DD (sorts by date)",
    "submission_year": "year of the original submission",
    "label": "label of the submission in the configuration",
}

_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SEPARATORS = " -_.,;+–—"
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_FORMATTER = string.Formatter()


class SubmissionLike(Protocol):
    """What naming needs from a submission.

    :class:`~paper_status_monitor.config.SubmissionConfig` satisfies it.
    """

    @property
    def uuid(self) -> str:
        """Tracking UUID."""

    @property
    def label(self) -> str:
        """Label from the configuration."""

    @property
    def fields(self) -> Mapping[str, str]:
        """Custom fields from the configuration."""


def custom_field_column(name: str) -> str:
    """Return the workbook column of a custom field (``"paper"`` -> ``"Paper"``).

    Underscores become spaces and the first letter is capitalised, so
    ``"funding_agency"`` is written to the column ``"Funding agency"``.
    """
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def custom_field_columns(fields: Mapping[str, str]) -> dict[str, str]:
    """Return the custom fields as a mapping of workbook column to value."""
    return {custom_field_column(name): value for name, value in fields.items()}


def check_custom_field_name(name: str) -> None:
    """Make sure *name* can be used as a custom field (and as a placeholder).

    Raises:
        ValueError: If the name is not an identifier, is a built-in placeholder or
            would be written to a column that already exists.
    """
    if not isinstance(name, str) or not _FIELD_NAME.match(name):
        raise ValueError(
            f"Invalid custom field name {name!r}: use letters, digits and underscores, "
            "starting with a letter (for example 'paper')."
        )
    if name.casefold() in {placeholder.casefold() for placeholder in PLACEHOLDERS}:
        raise ValueError(f"{name!r} is a built-in placeholder and cannot be a custom field.")
    column = custom_field_column(name)
    if column.casefold() in {label.casefold() for label in COLUMNS}:
        raise ValueError(
            f"Custom field {name!r} would be written to the existing column {column!r}; "
            "choose another name."
        )


def template_placeholders(template: str) -> list[str]:
    """Return the placeholder names used in *template*, in order.

    Raises:
        ValueError: If the template is malformed or uses positional (``{}``),
            attribute (``{a.b}``), index (``{a[0]}``) or nested placeholders.
    """
    try:
        parsed = list(_FORMATTER.parse(template))
    except ValueError as exc:
        raise ValueError(
            f"Invalid template {template!r}: {exc}. Write placeholders as {{name}} and "
            "literal braces as {{{{ and }}}}."
        ) from exc
    names = []
    for _literal, name, spec, _conversion in parsed:
        if name is None:
            continue
        if not _FIELD_NAME.match(name):
            raise ValueError(
                f"Invalid placeholder {{{name}}} in {template!r}: use names such as "
                "{journal} or {paper}."
            )
        if spec and "{" in spec:
            raise ValueError(f"Nested placeholders are not supported: {template!r}.")
        names.append(name)
    return names


def validate_template(template: str, custom_fields: Iterable[str] = ()) -> None:
    """Check that *template* is valid and only uses known placeholders.

    Args:
        template: The ``workbook_name`` template.
        custom_fields: Names of the custom fields declared by the submissions.

    Raises:
        ValueError: With a message that lists the valid placeholders.
    """
    if not isinstance(template, str) or not template.strip():
        raise ValueError("The workbook name template is empty.")
    custom = sorted(set(custom_fields))
    known = {*PLACEHOLDERS, *custom}
    unknown = [name for name in template_placeholders(template) if name not in known]
    if unknown:
        listed = ", ".join(f"{{{name}}}" for name in dict.fromkeys(unknown))
        builtin = ", ".join(f"{{{name}}}" for name in PLACEHOLDERS)
        declared = ", ".join(f"{{{name}}}" for name in custom) or "none yet"
        raise ValueError(
            f"Unknown placeholder(s) {listed}. Built-in placeholders: {builtin}. Custom "
            f"fields declared in the submissions: {declared}. To use a custom field, add "
            "it to the 'fields' of a submission, e.g. fields = { paper = \"Tau\" }."
        )
    try:
        render_stem(template, dict.fromkeys(known, "Sample"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid format in the template {template!r}: {exc}") from exc


def placeholder_values(
    snapshot: Snapshot, submission: SubmissionLike | None = None
) -> dict[str, str]:
    """Return the value of every placeholder for a submission.

    Args:
        snapshot: Tracker data (fetched, or rebuilt from the last workbook row).
        submission: Configured submission, for ``{label}`` and the custom fields.
    """
    number = snapshot.base_manuscript_number
    submitted = parse_tracker_date(snapshot.date_of_submission)
    values = {
        "manuscript_number": number or (submission.uuid if submission is not None else ""),
        "journal": snapshot.journal,
        "journal_acronym": number.split("-", 1)[0] if "-" in number else "",
        "title": strip_revision_prefix(snapshot.title),
        "first_author": snapshot.first_author,
        "corresponding_author": snapshot.corresponding_author,
        "date_of_submission": submitted.isoformat() if submitted else "",
        "submission_year": str(submitted.year) if submitted else "",
        "label": submission.label if submission is not None else "",
    }
    if submission is not None:
        for name, value in submission.fields.items():
            values.setdefault(name, clean_text(value))
    return values


def render_stem(template: str, values: Mapping[str, str]) -> str:
    """Render *template* as a file name without extension (possibly empty).

    Values and literal text are cleaned with
    :func:`~paper_status_monitor.storage.sanitize_filename`. Empty placeholders are
    removed together with the separator (``" - "``, ``"_"``...) next to them, and
    leading or trailing separators are dropped.
    """
    parts: list[tuple[str, bool]] = []  # (text, is_literal)
    drop_next_separator = False
    for literal, name, spec, conversion in _FORMATTER.parse(template):
        if literal:
            if not (drop_next_separator and _is_separator(literal)):
                parts.append((literal, True))
            drop_next_separator = False
        if name is None:
            continue
        value: object = values.get(name, "")
        if conversion:
            value = _FORMATTER.convert_field(value, conversion)
        text = sanitize_filename(format(value, spec or ""))
        if text:
            parts.append((text, False))
            drop_next_separator = False
        elif parts and parts[-1][1] and _is_separator(parts[-1][0]):
            parts.pop()
        elif not parts:
            drop_next_separator = True
    stem = _EMPTY_BRACKETS.sub("", "".join(text for text, _ in parts))
    return sanitize_filename(stem).strip(_SEPARATORS)


def truncate_stem(stem: str, limit: int = MAX_STEM_LENGTH) -> str:
    """Shorten *stem* to at most *limit* characters, cutting at a word boundary."""
    if len(stem) <= limit:
        return stem
    cut = stem[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(_SEPARATORS)


def workbook_file_name(
    template: str, snapshot: Snapshot, submission: SubmissionLike | None = None
) -> str:
    """Return the workbook file name (with ``.xlsx``) of a submission.

    If the template renders to an empty name (for example ``"{paper}"`` for a
    submission without that field), the base manuscript number is used instead.

    Raises:
        ValueError: If the name is empty and no manuscript number or UUID is known.
    """
    values = placeholder_values(snapshot, submission)
    stem = truncate_stem(render_stem(template, values))
    if not stem:
        return workbook_name(values["manuscript_number"])
    return f"{stem}.xlsx"


def _is_separator(text: str) -> bool:
    return bool(text) and all(character in _SEPARATORS for character in text)
