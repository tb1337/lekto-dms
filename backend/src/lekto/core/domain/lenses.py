"""Lenses: a user's saved looks at the documents (Tobi, 20.10.2026: "Lens" in German and English,
like "Space"; a space is where documents lie, a lens how one looks at them).

A lens holds the filters, the words of a search, the sort, the grouping, the layout, up to three
fields its cards show and the date field that is their deadline. It contains nothing: a document
stands in many lenses at once. Only its owner sees and changes it. Lenses are settings: no
events, no webhooks.

Master data a lens names may be deleted after; the services drop what is gone when they hand a
lens out, so a lens never fails for it.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum, StrEnum
from typing import Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    LensId,
    SpaceId,
    TagId,
    UserId,
    new_id,
)
from lekto.core.domain.validation import require_name, require_utc

MAX_NAME_LENGTH = 100
MAX_CARD_FIELDS = 3
MAX_QUERY_LENGTH = 500  # as the search takes it
MAX_FILTER_VALUES = 200  # of each kind


class Grouping(StrEnum):
    """What the documents of a lens stand under: nothing, the month of their document date, how
    soon their deadline is due, their type or their contact."""

    NONE = "none"
    MONTH = "month"
    DUE = "due"
    DOCUMENT_TYPE = "document_type"
    CONTACT = "contact"


class Layout(StrEnum):
    GRID = "grid"
    LIST = "list"


class RelativePeriod(StrEnum):
    """A period that moves with the day the lens is opened (the quick picks of the filters)."""

    THIS_YEAR = "this_year"
    LAST_12_MONTHS = "last_12_months"
    LAST_YEAR = "last_year"


class LensSort(StrEnum):
    """The sort of a lens: by relevance (only with words), or a key of the documents list,
    descending with a `-`; `field` sorts by `Lens.sort_field_id` (not with words: the search
    index holds no field values)."""

    RELEVANCE = "relevance"
    CREATED = "created_at"
    CREATED_DESC = "-created_at"
    DOCUMENT_DATE = "document_date"
    DOCUMENT_DATE_DESC = "-document_date"
    TITLE = "title"
    TITLE_DESC = "-title"
    FIELD = "field"
    FIELD_DESC = "-field"

    @property
    def by_field(self) -> bool:
        return self in {LensSort.FIELD, LensSort.FIELD_DESC}


@dataclass(frozen=True, kw_only=True)
class LensFilter:
    """The filters of a lens, as the documents list takes them: one of the contacts, types,
    groups, topics and spaces each, all of the tags, a value for `field_id`, and the document
    date either between `date_from` and `date_to` (both included, either open) or in
    `relative_period`."""

    contact_ids: tuple[ContactId, ...] = ()
    document_type_ids: tuple[DocumentTypeId, ...] = ()
    contact_group_ids: tuple[TagId, ...] = ()
    document_type_group_ids: tuple[TagId, ...] = ()
    topic_ids: tuple[TagId, ...] = ()
    tag_ids: tuple[TagId, ...] = ()
    space_ids: tuple[SpaceId, ...] = ()
    field_id: FieldId | None = None
    date_from: date | None = None
    date_to: date | None = None
    relative_period: RelativePeriod | None = None

    def __post_init__(self) -> None:
        for name in (
            "contact_ids",
            "document_type_ids",
            "contact_group_ids",
            "document_type_group_ids",
            "topic_ids",
            "tag_ids",
            "space_ids",
        ):
            values = tuple(dict.fromkeys(getattr(self, name)))  # once each, in order
            if len(values) > MAX_FILTER_VALUES:
                raise ValidationError(f"{name}: at most {MAX_FILTER_VALUES}")
            object.__setattr__(self, name, values)
        if self.relative_period is not None and (
            self.date_from is not None or self.date_to is not None
        ):
            raise ValidationError("document_period: not together with document_date_from or _to")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValidationError("document_date_from: after document_date_to")


@dataclass(kw_only=True)
class Lens:
    """A user's saved look at the documents; see the module. `position` orders a user's lenses
    (ascending). Names are unique per owner regardless of case."""

    id: LensId
    owner_id: UserId
    name: str
    position: int = 0
    filter: LensFilter = field(default_factory=LensFilter)
    query: str | None = None
    sort: LensSort | None = None  # None: as the list or the search sorts by default
    sort_field_id: FieldId | None = None
    grouping: Grouping = Grouping.NONE
    layout: Layout = Layout.GRID
    card_field_ids: tuple[FieldId, ...] = ()
    due_field_id: FieldId | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        self.name = require_name(self.name, "lens name", max_length=MAX_NAME_LENGTH)
        self.query = _query(self.query)
        self.card_field_ids = tuple(dict.fromkeys(self.card_field_ids))
        self.created_at = require_utc(self.created_at, "created_at")
        self.updated_at = require_utc(self.updated_at, "updated_at")
        self.check()

    @classmethod
    def create(cls, *, owner_id: UserId, name: str, position: int, now: datetime) -> Self:
        return cls(
            id=LensId(new_id()),
            owner_id=owner_id,
            name=name,
            position=position,
            created_at=now,
            updated_at=now,
        )

    def check(self) -> None:
        """ValidationError if the parts do not fit together."""
        if len(self.card_field_ids) > MAX_CARD_FIELDS:
            raise ValidationError(f"card_field_ids: at most {MAX_CARD_FIELDS}")
        by_field = self.sort is not None and self.sort.by_field
        if by_field != (self.sort_field_id is not None):
            raise ValidationError("sort_field_id: needed to sort by a field, and only then")
        if by_field and self.query is not None:
            raise ValidationError("sort: a lens with words cannot sort by a field")
        if self.sort is LensSort.RELEVANCE and self.query is None:
            raise ValidationError("sort: by relevance only with words")
        if self.grouping is Grouping.DUE and self.due_field_id is None:
            raise ValidationError("grouping: by when it is due only with a due_field_id")

    def change(self, changes: "LensChanges", *, now: datetime) -> None:
        """Apply what `changes` sets; ValidationError (and nothing changed) if the result does
        not fit together."""
        updated = replace(
            self,
            **{name: value for name, value in vars(changes).items() if value is not UNSET},
            updated_at=now,
        )
        for name in vars(changes):
            setattr(self, name, getattr(updated, name))
        self.updated_at = now


class _Unset(Enum):
    UNSET = "unset"


UNSET = _Unset.UNSET
"""Marks a part of `LensChanges` that stays as it is."""


@dataclass(frozen=True, kw_only=True)
class LensChanges:
    """A change of a lens; parts left UNSET stay as they are."""

    name: str | _Unset = UNSET
    filter: LensFilter | _Unset = UNSET
    query: str | _Unset | None = UNSET
    sort: LensSort | _Unset | None = UNSET
    sort_field_id: FieldId | _Unset | None = UNSET
    grouping: Grouping | _Unset = UNSET
    layout: Layout | _Unset = UNSET
    card_field_ids: tuple[FieldId, ...] | _Unset = UNSET
    due_field_id: FieldId | _Unset | None = UNSET


def _query(text: str | None) -> str | None:
    """Words stripped; none (empty) is None."""
    if text is None or not text.strip():
        return None
    words = text.strip()
    if len(words) > MAX_QUERY_LENGTH:
        raise ValidationError(f"query: at most {MAX_QUERY_LENGTH} characters")
    return words
