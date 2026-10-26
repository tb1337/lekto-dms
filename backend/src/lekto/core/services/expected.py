"""The documents expected next (`.idea/bezuege.md`, decisions 10 to 12; issue #145 PR 12): the
series among the documents a person may read, each with its next date. Derived on each call,
nothing stored, no events."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, tzinfo

from lekto.core.domain.document_facts import DocumentFact, FactRole, FactState, role_of
from lekto.core.domain.documents import Document
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, DocumentId, DocumentTypeId, UserId
from lekto.core.domain.periods import Period
from lekto.core.domain.reasons import Action
from lekto.core.domain.series import Dated, Series, SeriesKey, SeriesState, series_of
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import DocumentFilter, DocumentPosition
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_lister

PAGE = 500


@dataclass(frozen=True)
class Expected:
    """A series with the names of its contact and type, its newest document and where its next
    document stands today."""

    series: Series
    contact: str
    document_type: str
    last: Document
    state: SeriesState


class ExpectedService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def expected(
        self, actor: UserId, *, all_users: bool = False, zone: tzinfo = UTC
    ) -> list[Expected]:
        """The series among the documents the caller may read (with `all_users`, an admin's,
        of every user), the overdue first, then by their next date (the ended newest first);
        today as it is in `zone`."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, Action.LIST_ALL_DOCUMENTS)
            documents = await _dated(uow, None if all_users else actor)
            facts = await uow.document_facts.of_documents([item.id for item in documents])
            contacts = {item.id: item.name for item in await uow.contacts.list_all()}
            types = {item.id: item.name for item in await uow.document_types.list_all()}
        by_id = {item.id: item for item in documents}
        groups = series_groups(documents, facts)
        today = self._clock.now().astimezone(zone).date()
        found = []
        for key, items in groups.items():
            series = series_of(key, items)
            if series is None:
                continue
            found.append(
                Expected(
                    series=series,
                    contact=contacts.get(key.contact_id, ""),
                    document_type=types.get(key.document_type_id, ""),
                    last=by_id[series.last.id],
                    state=series.state(today),
                )
            )
        order = list(SeriesState)
        return sorted(
            found,
            key=lambda item: (
                order.index(item.state),
                -item.series.next_date.toordinal()
                if item.state is SeriesState.ENDED
                else item.series.next_date.toordinal(),
            ),
        )


def series_groups(
    documents: Sequence[Document], facts: Mapping[DocumentId, Sequence[DocumentFact]]
) -> dict[SeriesKey, list[Dated]]:
    """The documents with contact, type and date by what their series share: contact, type and
    number, compared by value whatever its kind (one contract number written as a customer
    number on some). A document without a number belongs to the only numbered group of its
    contact and type, if there is one (its number was not read)."""
    numbers: dict[tuple[ContactId, DocumentTypeId], dict[str, IdentifierKind]] = {}
    keyed: list[tuple[Document, tuple[IdentifierKind, str] | None]] = []
    for document in documents:
        if (
            document.contact_id is None
            or document.document_type_id is None
            or document.document_date is None
        ):
            continue
        found = number(facts.get(document.id, []))
        keyed.append((document, found))
        if found is not None:
            kinds = numbers.setdefault((document.contact_id, document.document_type_id), {})
            # A contract number names the series before a customer number of the same value.
            if found[1] not in kinds or role_of(found[0]) is FactRole.TARGET:
                kinds[found[1]] = found[0]
    groups: dict[SeriesKey, list[Dated]] = {}
    for document, found in keyed:
        assert document.contact_id is not None and document.document_type_id is not None
        assert document.document_date is not None
        kinds = numbers.get((document.contact_id, document.document_type_id), {})
        if found is None and len(kinds) == 1:
            (value,) = kinds
            found = (kinds[value], value)
        elif found is not None:
            found = (kinds[found[1]], found[1])
        key = SeriesKey(document.contact_id, document.document_type_id, found)
        groups.setdefault(key, []).append(
            Dated(document.id, document.document_date, period_of(document))
        )
    return groups


def number(facts: Sequence[DocumentFact]) -> tuple[IdentifierKind, str] | None:
    """The number a document's series follows: the first contract, policy or like number it
    shows (role `target`), else its customer number; none a person rejected."""
    # A person's number (by kind or role) is no series' name others may read.
    kept = [
        fact
        for fact in facts
        if fact.state is not FactState.REJECTED and fact.role is not FactRole.PERSON
    ]
    found = next(
        (
            fact
            for fact in kept
            if fact.role is FactRole.TARGET and role_of(fact.kind) is FactRole.TARGET
        ),
        None,
    ) or next((fact for fact in kept if fact.kind is IdentifierKind.CUSTOMER_NUMBER), None)
    return None if found is None else (found.kind, found.value)


async def _dated(uow: UnitOfWork, user: UserId | None) -> list[Document]:
    """The documents with contact, type and date, of `user`'s reach (None: all), through
    processing."""
    found: list[Document] = []
    after: DocumentPosition | None = None
    while True:
        if user is None:
            page = await uow.documents.query(DocumentFilter(), after=after, limit=PAGE)
        else:
            page = await uow.documents.query_visible(
                user, DocumentFilter(), after=after, limit=PAGE
            )
        found += [
            item
            for item in page
            if item.lane is not None
            and item.contact_id is not None
            and item.document_type_id is not None
            and item.document_date is not None
        ]
        if len(page) < PAGE:
            return found
        after = DocumentPosition.after(page[-1].id)


def period_of(document: Document) -> Period | None:
    """The first period among its fields, by field id."""
    return next(
        (
            value
            for _, value in sorted(document.fields.items(), key=lambda item: str(item[0]))
            if isinstance(value, Period)
        ),
        None,
    )
