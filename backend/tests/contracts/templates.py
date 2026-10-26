"""Contract suite for the `TemplateRenderer` port: templates of rules, title patterns and webhook
bodies, from users, in Liquid."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from lekto.core.domain.errors import MissingValueError, ValidationError
from lekto.core.domain.fields import (
    FieldDefinition,
    FieldType,
    FieldValue,
    Money,
    Url,
    read_written,
)
from lekto.core.domain.periods import Period
from lekto.core.domain.templates import TemplateValue
from lekto.core.ports.templates import TemplateRenderer

VALUES: dict[str, TemplateValue] = {
    "contact": "Stadtwerke Musterstadt",
    "document_type": "Rechnung",
    "document_date": date(2026, 3, 31),
    "tags": ["Strom", "Gas"],
    "pages": 2,
    "field": {
        "betrag": Money(Decimal("3650.00"), "EUR"),
        "netto": Decimal("2401.12"),
        "bezahlt": True,
        "nummer": "R-2026-0815",
    },
}


class TemplateRendererContract:
    """Needs the fixture `template_renderer`, set to the locale `de` (the expected texts are
    German)."""

    @pytest.mark.parametrize(
        ("data_type", "value"),
        [
            (FieldType.TEXT, "R-2026-0815"),
            (FieldType.NUMBER, Decimal("1.234")),
            (FieldType.NUMBER, Decimal("-1234567.5")),
            (FieldType.AMOUNT, Money(Decimal("3650.00"), "EUR")),
            (FieldType.AMOUNT, Money(Decimal("-0.99"), "USD")),
            (FieldType.DATE, date(2026, 3, 31)),
            (FieldType.BOOLEAN, True),
            (FieldType.BOOLEAN, False),
            (FieldType.LINK, "https://example.org/a?b=1"),
            (FieldType.PERIOD, Period.quarter(2026, 3)),
            (FieldType.PERIOD, Period.week(2026, 1)),
            (FieldType.PERIOD, Period(date(2026, 9, 1), date(2026, 9, 14))),
        ],
    )
    def test_reads_back_what_it_writes(
        self, template_renderer: TemplateRenderer, data_type: FieldType, value: TemplateValue
    ) -> None:
        """A field set from another field's value gets that value (`fields.read_written` with
        the renderer's `writing`)."""
        definition = FieldDefinition.create(
            name="F", data_type=data_type, now=datetime(2026, 10, 1, tzinfo=UTC)
        )
        written = template_renderer.render("{{ value }}", {"value": value})
        read: FieldValue | None = read_written(definition, written, template_renderer.writing)
        assert read == (Url(str(value)) if data_type is FieldType.LINK else value)

    def test_writes_the_values(self, template_renderer: TemplateRenderer) -> None:
        render = template_renderer.render
        assert render("{{ contact }} {{ document_type }}", VALUES) == (
            "Stadtwerke Musterstadt Rechnung"
        )
        assert render("{{ field.nummer }} ({{ pages }})", VALUES) == "R-2026-0815 (2)"
        assert render("{{ tags | join: ', ' }}", VALUES) == "Strom, Gas"
        assert render("{% for tag in tags %}[{{ tag }}]{% endfor %}", VALUES) == "[Strom][Gas]"

    def test_dates_and_amounts(self, template_renderer: TemplateRenderer) -> None:
        render = template_renderer.render
        assert render("{{ document_date }}", VALUES) == "2026-03-31"
        assert render("{{ document_date | date: '%Y-%m' }}", VALUES) == "2026-03"
        assert render("{{ document_date | datetime: format: 'MMMM yyyy' }}", VALUES) == (
            "März 2026"
        )
        assert render("{{ field.betrag }}", VALUES) == "3.650,00 EUR"
        assert render("{{ field.betrag.amount }} {{ field.betrag.currency }}", VALUES) == (
            "3650.00 EUR"
        )
        assert render("{{ field.netto }}", VALUES) == "2401.12"
        assert render("{{ field.betrag.amount | minus: field.netto }}", VALUES) == "1248.88"
        assert render("{% if field.betrag.amount > 3000 %}hoch{% endif %}", VALUES) == "hoch"

    def test_json_writes_values_as_the_api_does(self, template_renderer: TemplateRenderer) -> None:
        """For webhook bodies: each value as JSON in the API's form (`field_to_json`)."""
        render = template_renderer.render
        values: dict[str, TemplateValue] = {
            **VALUES,
            "title": 'Rechnung "März"',
            "period": Period(date(2026, 9, 1), date(2026, 9, 30)),
        }
        assert render("{{ title | json }}", values) == '"Rechnung \\"März\\""'
        assert render("{{ field.betrag | json }}", values) == (
            '{"amount": "3650.00", "currency": "EUR"}'
        )
        assert render("{{ field.netto | json }}", values) == '"2401.12"'
        assert render("{{ field.bezahlt | json }}", values) == "true"
        assert render("{{ document_date | json }}", values) == '"2026-03-31"'
        assert (
            render("{{ period | json }}", values) == '{"start": "2026-09-01", "end": "2026-09-30"}'
        )
        assert render("{{ tags | json }}", values) == '["Strom", "Gas"]'
        assert render("{{ pages | json }}", values) == "2"
        assert render("{{ topic | default: nil | json }}", values) == "null"
        with pytest.raises(MissingValueError) as missing:
            render("{{ topic | json }}", values)
        assert missing.value.path == "topic"

    def test_a_missing_value_can_be_tested_but_not_written(
        self, template_renderer: TemplateRenderer
    ) -> None:
        render = template_renderer.render
        assert render("{% if field.brutto %}x{% else %}ohne{% endif %}", VALUES) == "ohne"
        assert render("{{ field.brutto | default: '-' }}", VALUES) == "-"
        with pytest.raises(MissingValueError) as raised:
            render("{{ contact }} {{ field.brutto }}", VALUES)
        assert raised.value.path == "field.brutto"
        with pytest.raises(MissingValueError):
            render("{{ owner }}", VALUES)

    def test_tells_which_values_a_template_uses(self, template_renderer: TemplateRenderer) -> None:
        used = template_renderer.check(
            "{{ contact }}{% for tag in tags %}{{ tag }}{% endfor %}"
            "{% assign x = 'a' %}{{ x }}{{ field.betrag.amount }}"
        )
        assert used == {"contact", "tags", "field.betrag.amount"}

    @pytest.mark.parametrize(
        "template",
        ["{{ contact", "{% if %}x{% endif %}", "{{ contact | nonsense }}", "{% include 'x' %}"],
    )
    def test_an_invalid_template(self, template_renderer: TemplateRenderer, template: str) -> None:
        with pytest.raises(ValidationError, match="invalid template"):
            template_renderer.check(template)
        with pytest.raises(ValidationError, match="invalid template"):
            template_renderer.render(template, VALUES)

    def test_loops_and_output_are_bounded(self, template_renderer: TemplateRenderer) -> None:
        with pytest.raises(ValidationError):
            template_renderer.render("{% for i in (1..1000000) %}x{% endfor %}", VALUES)
        with pytest.raises(ValidationError):
            template_renderer.render(
                "{% for i in (1..900) %}{{ contact }}{{ contact }}{% endfor %}", VALUES
            )

    def test_no_attributes_of_objects(self, template_renderer: TemplateRenderer) -> None:
        with pytest.raises(MissingValueError):
            template_renderer.render("{{ contact.__class__ }}", VALUES)
        assert template_renderer.render("{{ contact.size }}", VALUES) == "22"
