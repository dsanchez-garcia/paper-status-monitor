from __future__ import annotations

from datetime import timezone

import pytest

from paper_status_monitor import naming
from paper_status_monitor.client import DEMO_UUID
from paper_status_monitor.config import SubmissionConfig
from paper_status_monitor.models import Snapshot
from paper_status_monitor.storage import MAX_STEM_LENGTH, workbook_name

JOURNAL = "The International Journal of Submission Trackers"


@pytest.fixture
def snapshot(demo_payload: dict) -> Snapshot:
    return Snapshot.from_api(demo_payload, tz=timezone.utc)


def submission(**fields: str) -> SubmissionConfig:
    return SubmissionConfig(DEMO_UUID, label="Demo", fields=fields)


def test_placeholder_values(snapshot: Snapshot) -> None:
    revised = snapshot.replace(manuscript_number="SUBTRAK-D-22-00128R2", revision="2")
    values = naming.placeholder_values(revised, submission(paper="Tau"))
    assert values["manuscript_number"] == "SUBTRAK-D-22-00128"
    assert values["journal"] == JOURNAL
    assert values["journal_acronym"] == "SUBTRAK"
    assert values["title"].startswith("Influence of submission trackers")
    assert values["first_author"] == "Zachary Mindwarp"
    assert values["corresponding_author"] == "Maximilian Spillage"
    assert values["date_of_submission"] == "2020-03-03"
    assert values["submission_year"] == "2020"
    assert values["label"] == "Demo"
    assert values["paper"] == "Tau"


def test_placeholder_values_without_tracker_data() -> None:
    values = naming.placeholder_values(Snapshot(), submission())
    assert values["manuscript_number"] == DEMO_UUID  # the UUID identifies the submission
    assert values["journal_acronym"] == ""
    assert values["date_of_submission"] == ""


def test_default_template_gives_the_names_of_previous_versions(snapshot: Snapshot) -> None:
    expected = workbook_name(snapshot.base_manuscript_number, snapshot.journal, snapshot.title)
    assert naming.workbook_file_name(naming.DEFAULT_WORKBOOK_NAME, snapshot) == expected
    no_title = snapshot.replace(title="")
    assert naming.workbook_file_name(naming.DEFAULT_WORKBOOK_NAME, no_title) == (
        f"SUBTRAK-D-22-00128 - {JOURNAL}.xlsx"
    )


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "{paper} - {journal} - {manuscript_number}",
            f"Tau - {JOURNAL} - SUBTRAK-D-22-00128.xlsx",
        ),
        ("{paper}", "Tau.xlsx"),
        ("{paper}_{journal_acronym}_{submission_year}", "Tau_SUBTRAK_2020.xlsx"),
        ("{date_of_submission} {paper} ({journal_acronym})", "2020-03-03 Tau (SUBTRAK).xlsx"),
        ("{title:.10}", "Influence.xlsx"),
        ("All my submissions", "All my submissions.xlsx"),
        ("{{{paper}}}", "{Tau}.xlsx"),
    ],
)
def test_templates(snapshot: Snapshot, template: str, expected: str) -> None:
    assert naming.workbook_file_name(template, snapshot, submission(paper="Tau")) == expected


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{paper} - {journal_acronym} - {manuscript_number}", "SUBTRAK - SUBTRAK-D-22-00128"),
        ("{journal_acronym} - {paper} - {manuscript_number}", "SUBTRAK - SUBTRAK-D-22-00128"),
        ("{journal_acronym} - {manuscript_number} - {paper}", "SUBTRAK - SUBTRAK-D-22-00128"),
        ("{paper}_{project}_{journal_acronym}", "SUBTRAK"),
        ("{manuscript_number} ({paper})", "SUBTRAK-D-22-00128"),
        ("{paper}", "SUBTRAK-D-22-00128"),  # nothing left: the manuscript number is used
    ],
)
def test_empty_placeholders_are_removed_with_their_separator(
    snapshot: Snapshot, template: str, expected: str
) -> None:
    assert naming.workbook_file_name(template, snapshot, submission()) == f"{expected}.xlsx"


def test_values_are_cleaned_for_file_names(snapshot: Snapshot) -> None:
    odd = snapshot.replace(journal="Examples: Policy/Practice?")
    name = naming.workbook_file_name("{paper} - {journal}", odd, submission(paper='A "big" one'))
    assert name == "A big one - Examples PolicyPractice.xlsx"


def test_long_names_are_cut_at_a_word_boundary(snapshot: Snapshot) -> None:
    stem = naming.workbook_file_name("{title} {title}", snapshot).removesuffix(".xlsx")
    assert len(stem) <= MAX_STEM_LENGTH
    assert snapshot.title.startswith(stem[:40])
    assert not stem.endswith((" ", "-", "."))
    assert (stem + " ") in (snapshot.title + " " + snapshot.title + " ")


def test_validate_template_accepts_declared_custom_fields() -> None:
    naming.validate_template("{paper} - {journal} - {title:.40}", ["paper"])
    naming.validate_template(naming.DEFAULT_WORKBOOK_NAME)


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (
            "{papr} - {journal}",
            r"Unknown placeholder\(s\) \{papr\}.*declared in the submissions: \{paper\}",
        ),
        ("{journal", "Invalid template"),
        ("{}", "Invalid placeholder"),
        ("{0}", "Invalid placeholder"),
        ("{journal.upper}", "Invalid placeholder"),
        ("{journal[0]}", "Invalid placeholder"),
        ("{title:{paper}}", "Nested"),
        ("{title:d}", "Invalid format"),
    ],
)
def test_invalid_templates(template: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        naming.validate_template(template, ["paper"])


def test_unknown_placeholder_message_without_custom_fields() -> None:
    with pytest.raises(ValueError, match="none yet"):
        naming.validate_template("{paper}")


def test_template_placeholders() -> None:
    assert naming.template_placeholders("{paper} - {journal} {{literal}} {title:.5}") == [
        "paper",
        "journal",
        "title",
    ]


@pytest.mark.parametrize("name", ["paper", "Paper_2", "_draft", "funding_agency"])
def test_valid_custom_field_names(name: str) -> None:
    naming.check_custom_field_name(name)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("2paper", "Invalid custom field name"),
        ("my paper", "Invalid custom field name"),
        ("", "Invalid custom field name"),
        ("journal", "built-in placeholder"),
        ("Label", "built-in placeholder"),
        ("status", "existing column"),
        ("tracker_url", "existing column"),
        ("detected_at", "existing column"),
    ],
)
def test_invalid_custom_field_names(name: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        naming.check_custom_field_name(name)


@pytest.mark.parametrize(
    ("name", "column"),
    [("paper", "Paper"), ("funding_agency", "Funding agency"), ("DOI", "DOI")],
)
def test_custom_field_column(name: str, column: str) -> None:
    assert naming.custom_field_column(name) == column
    assert naming.custom_field_columns({name: "x"}) == {column: "x"}
