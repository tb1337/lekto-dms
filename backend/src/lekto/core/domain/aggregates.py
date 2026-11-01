"""Counting and summing over many documents (Tobi, 01.11.2026, umsetzungsplan "MCP", decision
7: the server counts, an assistant does not add up a hundred answers).

Documents are grouped by a key of theirs, each group with how many and, for an amount field,
its sum per currency (amounts in different currencies are never added). By the document date's
year or month, the groups come in the order of time and undated ones last; by contact, type,
topic or tag, the largest first. A document with several tags counts in the group of each, one
without a value in the group None.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.fields import Money
from lekto.core.domain.ids import FieldId


class GroupBy(StrEnum):
    YEAR = "year"
    MONTH = "month"
    CONTACT = "contact"
    DOCUMENT_TYPE = "document_type"
    TOPIC = "topic"
    TAG = "tag"


type GroupKey = str | UUID | None
"""A year (`2025`), a month (`2025-03`), the id of a contact, type, topic or tag, or None."""


@dataclass(frozen=True)
class Group:
    key: GroupKey
    count: int
    sums: dict[str, Decimal] = field(default_factory=dict)  # currency to sum


@dataclass(frozen=True)
class Aggregate:
    """The documents counted: all of them (`total`, `sums`), and per group if grouped."""

    total: int
    sums: dict[str, Decimal]
    groups: tuple[Group, ...] | None = None


def aggregate(
    documents: Iterable[Document], by: GroupBy | None, amount: FieldId | None
) -> Aggregate:
    """Count `documents`, grouped `by` a key if given, summing the field `amount` (an amount
    field) per currency if given."""
    total = 0
    sums: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[GroupKey, int] = defaultdict(int)
    group_sums: dict[GroupKey, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for document in documents:
        total += 1
        value = None if amount is None else document.fields.get(amount)
        money = value if isinstance(value, Money) else None
        if money is not None:
            sums[money.currency] += money.amount
        for key in _keys(document, by) if by is not None else ():
            counts[key] += 1
            if money is not None:
                group_sums[key][money.currency] += money.amount
    groups = None
    if by is not None:
        groups = tuple(
            Group(key, counts[key], dict(group_sums[key])) for key in _ordered(counts, by)
        )
    return Aggregate(total, dict(sums), groups)


def _keys(document: Document, by: GroupBy) -> tuple[GroupKey, ...]:
    dated = document.document_date
    match by:
        case GroupBy.YEAR:
            return (None if dated is None else f"{dated.year:04d}",)
        case GroupBy.MONTH:
            return (None if dated is None else f"{dated.year:04d}-{dated.month:02d}",)
        case GroupBy.CONTACT:
            return (document.contact_id,)
        case GroupBy.DOCUMENT_TYPE:
            return (document.document_type_id,)
        case GroupBy.TOPIC:
            return (document.topic_id,)
        case GroupBy.TAG:
            return tuple(sorted(document.tag_ids)) or (None,)


def _ordered(counts: dict[GroupKey, int], by: GroupBy) -> list[GroupKey]:
    if by in (GroupBy.YEAR, GroupBy.MONTH):
        return sorted(counts, key=lambda key: (key is None, str(key or "")))
    return sorted(counts, key=lambda key: (key is None, -counts[key], str(key)))
