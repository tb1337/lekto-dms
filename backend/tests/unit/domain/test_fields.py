from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.fields import (
    FieldDefinition,
    FieldType,
    Money,
    Url,
    field_from_json,
    field_to_json,
)
from papiq.core.domain.ids import DocumentTypeId, new_id
from papiq.core.domain.periods import Period, PeriodKind

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def definition(data_type: FieldType, choices: tuple[str, ...] = ()) -> FieldDefinition:
    return FieldDefinition.create(name="field", data_type=data_type, now=NOW, choices=choices)


ACCEPTED: list[tuple[FieldType, object, object]] = [
    (FieldType.TEXT, "Contract 42", "Contract 42"),
    (FieldType.NUMBER, Decimal("12.5"), Decimal("12.5")),
    (FieldType.NUMBER, 3, Decimal(3)),
    (FieldType.AMOUNT, Money(Decimal("99.90"), "EUR"), Money(Decimal("99.90"), "EUR")),
    (FieldType.DATE, date(2026, 10, 6), date(2026, 10, 6)),
    (FieldType.BOOLEAN, True, True),
    (FieldType.BOOLEAN, False, False),
    (FieldType.CHOICE, "monthly", "monthly"),
    (FieldType.LINK, Url("https://example.org/a?b=c"), Url("https://example.org/a?b=c")),
    (FieldType.PERIOD, Period.month(2026, 9), Period(date(2026, 9, 1), date(2026, 9, 30))),
]

REJECTED: list[tuple[FieldType, object]] = [
    (FieldType.TEXT, ""),
    (FieldType.TEXT, "   "),
    (FieldType.TEXT, 42),
    (FieldType.NUMBER, 1.5),
    (FieldType.NUMBER, True),
    (FieldType.NUMBER, Decimal("NaN")),
    (FieldType.NUMBER, Decimal("Infinity")),
    (FieldType.NUMBER, "12"),
    (FieldType.AMOUNT, Decimal("12")),
    (FieldType.DATE, datetime(2026, 10, 6, tzinfo=UTC)),
    (FieldType.DATE, "2026-10-06"),
    (FieldType.BOOLEAN, 1),
    (FieldType.BOOLEAN, "true"),
    (FieldType.CHOICE, "weekly"),
    (FieldType.CHOICE, "Monthly"),
    (FieldType.LINK, "https://example.org"),
    (FieldType.PERIOD, date(2026, 9, 1)),
    (FieldType.PERIOD, {"start": "2026-09-01", "end": "2026-09-30"}),
    (FieldType.TEXT, None),
]


@pytest.mark.parametrize(("data_type", "value", "expected"), ACCEPTED)
def test_value_fits_data_type(data_type: FieldType, value: object, expected: object) -> None:
    choices = ("monthly", "yearly") if data_type is FieldType.CHOICE else ()
    assert definition(data_type, choices).validate(value) == expected


@pytest.mark.parametrize(("data_type", "value"), REJECTED)
def test_value_of_wrong_type_is_rejected(data_type: FieldType, value: object) -> None:
    choices = ("monthly", "yearly") if data_type is FieldType.CHOICE else ()
    with pytest.raises(ValidationError, match="does not accept"):
        definition(data_type, choices).validate(value)


def test_every_data_type_is_covered() -> None:
    assert {row[0] for row in ACCEPTED} == set(FieldType)
    assert {row[0] for row in REJECTED} == set(FieldType)


def test_one_json_form_for_api_rules_and_the_log() -> None:
    # Numbers in plain notation, whatever exponent the value arrived with.
    assert field_to_json(Decimal("5.335E+7")) == "53350000"
    assert field_to_json(Money(Decimal("5.335E+7"), "EUR")) == {
        "amount": "53350000",
        "currency": "EUR",
    }
    # A number may also be a JSON number, also as an amount.
    assert field_from_json(definition(FieldType.NUMBER), 12.5) == Decimal("12.5")
    amount = field_from_json(definition(FieldType.AMOUNT), {"amount": 7, "currency": "EUR"})
    assert amount == Money(Decimal("7"), "EUR")
    # An amount is exactly its amount and currency; a yes/no is no number.
    for refused in (
        {"amount": "7", "currency": "EUR", "note": "x"},
        {"amount": "7"},
        {"amount": True, "currency": "EUR"},
        {"amount": "7", "currency": "eu"},
    ):
        with pytest.raises(ValidationError, match="does not accept"):
            field_from_json(definition(FieldType.AMOUNT), refused)
    with pytest.raises(ValidationError, match="does not accept"):
        field_from_json(definition(FieldType.NUMBER), True)
    # What comes from anyone is shortened in the message.
    with pytest.raises(ValidationError) as caught:
        field_from_json(definition(FieldType.DATE), "x" * 500)
    assert len(str(caught.value)) < 200


@pytest.mark.parametrize(
    ("period", "kind"),
    [
        (Period.day(date(2026, 9, 15)), PeriodKind.DAY),
        (Period.week(2026, 38), PeriodKind.WEEK),
        (Period(date(2026, 9, 14), date(2026, 9, 20)), PeriodKind.WEEK),  # Monday to Sunday
        (Period(date(2026, 9, 15), date(2026, 9, 21)), PeriodKind.SPAN),  # Tuesday to Monday
        (Period.month(2026, 2), PeriodKind.MONTH),
        (Period.month(2028, 2), PeriodKind.MONTH),  # a leap year
        (Period.quarter(2026, 3), PeriodKind.QUARTER),
        (Period(date(2026, 2, 1), date(2026, 4, 30)), PeriodKind.SPAN),  # three months, no quarter
        (Period.year(2025), PeriodKind.YEAR),
        (Period(date(2026, 1, 1), date(2027, 12, 31)), PeriodKind.SPAN),
    ],
)
def test_what_a_period_is_follows_from_its_ends(period: Period, kind: PeriodKind) -> None:
    assert period.kind is kind


@pytest.mark.parametrize(
    ("period", "notation"),
    [
        (Period.day(date(2026, 9, 15)), "2026-09-15"),
        (Period.week(2026, 38), "2026-W38"),
        (Period.week(2026, 1), "2026-W01"),  # from 29 December 2025
        (Period.week(2026, 53), "2026-W53"),
        (Period.month(2026, 9), "2026-09"),
        (Period.quarter(2026, 3), "2026-Q3"),
        (Period.year(2025), "2025"),
        (Period(date(2026, 9, 1), date(2026, 9, 14)), "2026-09-01/2026-09-14"),
    ],
)
def test_a_period_is_written_in_iso_8601(period: Period, notation: str) -> None:
    assert period.notation == notation


def test_a_period_has_dates_for_ends_and_does_not_end_before_it_starts() -> None:
    assert Period.week(2026, 38) == Period(date(2026, 9, 14), date(2026, 9, 20))
    assert Period.month(2028, 2).end == date(2028, 2, 29)
    assert Period.quarter(2026, 4) == Period(date(2026, 10, 1), date(2026, 12, 31))
    with pytest.raises(ValidationError, match="before it starts"):
        Period(date(2026, 9, 30), date(2026, 9, 1))
    with pytest.raises(ValidationError, match="dates"):
        Period(datetime(2026, 9, 1, tzinfo=UTC), date(2026, 9, 30))
    with pytest.raises(ValidationError):
        Period.quarter(2026, 5)
    september = Period.month(2026, 9)
    assert september.overlaps(Period.day(date(2026, 9, 30)))
    assert september.overlaps(Period(date(2026, 8, 20), date(2026, 9, 1)))
    assert not september.overlaps(Period.month(2026, 10))


def test_a_period_in_json_is_its_start_and_end() -> None:
    september = Period.month(2026, 9)
    assert field_to_json(september) == {"start": "2026-09-01", "end": "2026-09-30"}
    period = definition(FieldType.PERIOD)
    assert field_from_json(period, field_to_json(september)) == september
    for refused in (
        {"start": "2026-09-30", "end": "2026-09-01"},
        {"start": "2026-09-01"},
        {"start": "2026-09-01", "end": "2026-09-30", "kind": "month"},
        {"start": "September", "end": "2026-09-30"},
        "2026-09",
    ):
        with pytest.raises(ValidationError, match="does not accept"):
            field_from_json(period, refused)


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(Decimal("NaN"), "EUR"), (Decimal(1), "eur"), (Decimal(1), "EURO"), (1.5, "EUR")],
)
def test_money_needs_finite_decimal_and_iso_currency(amount: object, currency: str) -> None:
    with pytest.raises(ValidationError):
        Money(amount, currency)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    ["example.org", "ftp://example.org", "https://", "https://exa mple.org", "mailto:a@b.c"],
)
def test_url_must_be_absolute_http(value: str) -> None:
    with pytest.raises(ValidationError):
        Url(value)


def test_choices_belong_to_choice_fields_only() -> None:
    with pytest.raises(ValidationError, match="at least one choice"):
        definition(FieldType.CHOICE)
    with pytest.raises(ValidationError, match="unique"):
        definition(FieldType.CHOICE, ("a", "a"))
    with pytest.raises(ValidationError, match="only choice"):
        definition(FieldType.TEXT, ("a",))


def test_scope_is_global_or_bound_to_document_types() -> None:
    invoice, letter = DocumentTypeId(new_id()), DocumentTypeId(new_id())
    everywhere = definition(FieldType.TEXT)
    bound = FieldDefinition.create(
        name="IBAN", data_type=FieldType.TEXT, now=NOW, document_type_ids=[invoice]
    )
    assert everywhere.is_global
    assert everywhere.applies_to(None)
    assert everywhere.applies_to(letter)
    assert not bound.is_global
    assert bound.applies_to(invoice)
    assert not bound.applies_to(letter)
    assert not bound.applies_to(None)


def test_choices_and_scope_change() -> None:
    kind = FieldDefinition.create(
        name="Kind", data_type=FieldType.CHOICE, now=NOW, choices=["a", "b"]
    )
    assert kind.change_choices(["b", "c"]) == frozenset({"a"})
    assert kind.choices == ("b", "c")
    with pytest.raises(ValidationError):
        kind.change_choices([])
    with pytest.raises(ValidationError):
        kind.change_choices(["x", "x"])
    text = FieldDefinition.create(name="Note", data_type=FieldType.TEXT, now=NOW)
    with pytest.raises(ValidationError):
        text.change_choices(["a"])
    one, two = DocumentTypeId(new_id()), DocumentTypeId(new_id())
    assert text.change_scope([one, two]) is True  # global -> two types
    assert text.change_scope([one, two]) is False
    assert text.change_scope([one]) is True
    assert text.change_scope(None) is False  # global again
    with pytest.raises(ValidationError):
        text.change_scope([])
