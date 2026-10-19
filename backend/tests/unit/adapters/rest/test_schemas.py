"""JSON forms of field values."""

from datetime import date
from decimal import Decimal

import pytest

from lekto.adapters.inbound.schemas import MoneyValue, PeriodValue, field_json
from lekto.core.domain.fields import Money, Url
from lekto.core.domain.periods import Period


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("5.335E+7"), "53350000"),
        (Decimal("1E+2"), "100"),
        (Decimal("12.50"), "12.50"),
        (Decimal("-0.001"), "-0.001"),
        (Decimal("7"), "7"),
    ],
)
def test_numbers_are_written_in_plain_notation(value: Decimal, expected: str) -> None:
    assert field_json(value) == expected


def test_amounts_are_written_in_plain_notation() -> None:
    assert field_json(Money(Decimal("5.335E+7"), "EUR")) == MoneyValue(
        amount="53350000", currency="EUR"
    )
    assert field_json(Money(Decimal("84.20"), "EUR")) == MoneyValue(amount="84.20", currency="EUR")


def test_other_types_keep_their_form() -> None:
    assert field_json("text") == "text"
    assert field_json(True) is True
    assert field_json(Url("https://example.org/x")) == "https://example.org/x"
    assert field_json(date(2026, 3, 31)) == "2026-03-31"


def test_periods_are_their_start_and_end() -> None:
    assert field_json(Period.month(2026, 9)) == PeriodValue(
        start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
