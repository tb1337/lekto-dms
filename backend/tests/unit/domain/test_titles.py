from datetime import date

import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.rules import SetTitle
from papiq.core.domain.titles import (
    TitleValues,
    check_pattern,
    field_names,
    rename_field,
    render,
)

VALUES = TitleValues(
    contact="Stadtwerke",
    document_type="Rechnung",
    document_date=date(2026, 3, 9),
    filename="scan_0042",
    fields={"Rechnungsnummer": "R-2026-0815"},
)


@pytest.mark.parametrize(
    ("pattern", "title"),
    [
        ("{document_date:YYYY}/{document_date:MM}", "2026/03"),
        ("{contact} {document_type} {document_date}", "Stadtwerke Rechnung 2026-03-09"),
        ("{document_date:DD.MM.YY}  {filename}", "09.03.26 scan_0042"),
        ("{contact} {field:Rechnungsnummer}", "Stadtwerke R-2026-0815"),
    ],
)
def test_patterns_render_the_documents_values(pattern: str, title: str) -> None:
    assert render(pattern, VALUES) == title


def test_a_pattern_missing_a_value_is_no_title_where_it_must_be_complete() -> None:
    values = TitleValues(contact="Stadtwerke")
    assert render("{contact} {document_date:YYYY}", values) == "Stadtwerke"
    assert render("{contact} {document_date:YYYY}", values, complete=True) is None
    assert render("{document_type}", values) is None


@pytest.mark.parametrize(
    ("pattern", "fields", "message"),
    [
        ("{amount}", None, r"unknown placeholder \{amount\}"),
        ("{document_date:Q}", None, "needs YYYY"),
        ("{field:Rechnungsnummer}", None, r"unknown placeholder \{field:Rechnungsnummer\}"),
        ("{field:Betrag}", ["Rechnungsnummer"], "no such field"),
        ("   ", None, "must not be empty"),
    ],
)
def test_bad_patterns(pattern: str, fields: list[str] | None, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        check_pattern(pattern, fields=fields)


def test_field_placeholders_follow_a_rename() -> None:
    pattern = "{field:Nummer} {contact}"
    assert field_names(pattern) == {"Nummer"}
    assert rename_field(pattern, "Nummer", "Rechnungsnummer") == "{field:Rechnungsnummer} {contact}"


def test_the_title_rule_takes_date_formats_but_no_fields() -> None:
    assert SetTitle("{contact} {document_date:YYYY}").template == "{contact} {document_date:YYYY}"
    with pytest.raises(ValidationError):
        SetTitle("{field:Nummer}")
