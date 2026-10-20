"""How the in-memory repository and search index sort documents, as the real ones do."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from lekto.core.ports.repository import DocumentOrder, SortKey

type Rank = tuple[int | Decimal | tuple[int, ...], ...]
"""Numbers, and the code points of a title, compared in turn."""


def rank(
    order: DocumentOrder, id: UUID, value: date | str | Decimal | None, *, ties_by_id: bool
) -> Rank:
    """A key that sorts ascending as `order` sorts a document with `id` and its `value` of the
    sort key (`DocumentPosition.value`): documents without a date (or a field's value) last.
    Ties go by id the same way (`ties_by_id`, the repository) or stay as they come (the search
    index: by relevance)."""
    sign = 1 if order.ascending else -1
    tie = (sign * id.int,) if ties_by_id else ()
    match order.key:
        case SortKey.CREATED:
            return (sign * id.int,)
        case SortKey.DOCUMENT_DATE:
            if not isinstance(value, date):
                return (1, 0, *tie)
            return (0, sign * value.toordinal(), *tie)
        case SortKey.FIELD:
            if isinstance(value, date):
                return (0, sign * value.toordinal(), *tie)
            if isinstance(value, Decimal):
                return (0, sign * value, *tie)
            return (1, 0, *tie)
        case SortKey.TITLE:
            # Text cannot be negated: descending compares the code points negated.
            letters = tuple(ord(char) for char in str(value))
            return (letters if order.ascending else (*(-code for code in letters), 1), *tie)
