"""Counting and summing over documents (umsetzungsplan "MCP", decision 7)."""

from datetime import date
from decimal import Decimal

from lekto.core.domain.aggregates import Group, GroupBy, aggregate
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import Money
from lekto.core.domain.ids import ContactId, FieldId, SpaceId, TagId, UserId, new_id
from tests import builders

AMOUNT = FieldId(new_id())
STROM, GAS = ContactId(new_id()), ContactId(new_id())
HOME = TagId(new_id())


def bill(
    dated: date | None,
    amount: str | None,
    currency: str = "EUR",
    contact: ContactId | None = STROM,
    tags: frozenset[TagId] = frozenset(),
) -> Document:
    document = builders.document(UserId(new_id()), SpaceId(new_id()))
    document.document_date = dated
    document.contact_id = contact
    document.tag_ids = set(tags)
    if amount is not None:
        document.fields = {AMOUNT: Money(Decimal(amount), currency)}
    return document


def test_count_and_sum_per_currency() -> None:
    bills = [
        bill(date(2025, 1, 31), "80.10"),
        bill(date(2025, 2, 28), "79.90"),
        bill(date(2025, 3, 31), "12.00", "CHF"),
        bill(None, None),
    ]

    counted = aggregate(bills, None, AMOUNT)

    assert counted.total == 4
    assert counted.sums == {"EUR": Decimal("160.00"), "CHF": Decimal("12.00")}
    assert counted.groups is None


def test_by_year_and_month_in_the_order_of_time_undated_last() -> None:
    bills = [
        bill(date(2025, 3, 1), "1"),
        bill(None, "2"),
        bill(date(2024, 12, 1), "3"),
        bill(date(2025, 3, 20), "4"),
    ]

    assert aggregate(bills, GroupBy.YEAR, AMOUNT).groups == (
        Group("2024", 1, {"EUR": Decimal(3)}),
        Group("2025", 2, {"EUR": Decimal(5)}),
        Group(None, 1, {"EUR": Decimal(2)}),
    )
    months = aggregate(bills, GroupBy.MONTH, None).groups
    assert months is not None
    assert [(group.key, group.count) for group in months] == [
        ("2024-12", 1),
        ("2025-03", 2),
        (None, 1),
    ]


def test_by_contact_the_largest_first_and_each_tag_of_a_document() -> None:
    bills = [
        bill(None, None, contact=GAS),
        bill(None, None, contact=STROM, tags=frozenset({HOME})),
        bill(None, None, contact=STROM),
        bill(None, None, contact=None, tags=frozenset({HOME})),
    ]

    by_contact = aggregate(bills, GroupBy.CONTACT, None).groups
    assert by_contact is not None
    assert [(group.key, group.count) for group in by_contact] == [(STROM, 2), (GAS, 1), (None, 1)]
    by_tag = aggregate(bills, GroupBy.TAG, None).groups
    assert by_tag is not None
    assert [(group.key, group.count) for group in by_tag] == [(HOME, 2), (None, 2)]
