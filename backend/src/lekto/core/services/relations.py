"""Relations between documents (`domain.relations`, `.idea/bezuege.md`, issue #145 PR 9): which
a person sees, sets, accepts and removes.

Only who reads both documents sees a relation. Who edits the newer and reads the older sets one
by hand, accepts a suggestion or removes one: a relation Lekto made is rejected then (so it is
not suggested again), one a person set goes. The first decision about the relations of a document
(the newer one) is a verdict on them (`first_runs.RELATIONS`): added, accepted, or corrected.
No event goes out for relations yet (`bezuege.md`, decision 20)."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError, NotFoundError
from lekto.core.domain.first_runs import RELATIONS, Decision, FieldVerdict, Verdict
from lekto.core.domain.ids import DocumentId, DocumentTypeId, UserId
from lekto.core.domain.permissions import can_edit_document, can_read_document
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState, ordered
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, readable_document, writable_document


class Direction(StrEnum):
    REFERS_TO = "refers_to"  # the document refers to the other ("bezieht sich auf")
    REFERRED_BY = "referred_by"  # the other refers to the document ("darauf beziehen sich")


@dataclass(frozen=True)
class Related:
    """A relation of a document with the document at its other end, seen from it;
    `changeable`: whether the caller edits the newer of the two (then they accept, reject or
    remove it)."""

    relation: Relation
    other: Document
    direction: Direction
    changeable: bool


@dataclass(frozen=True)
class DocumentRelations:
    """The relations of a document the caller sees: those that hold in either direction, and
    the suggestions; `editable`: whether the caller edits the document (then they relate it
    with another: the newer of the two must be one they edit)."""

    refers_to: tuple[Related, ...]
    referred_by: tuple[Related, ...]
    suggested: tuple[Related, ...]
    editable: bool


class RelationService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def relations(self, actor: UserId, id: DocumentId) -> DocumentRelations:
        """The relations of the document whose other end the caller reads, rejected ones aside.
        NotFoundError if they do not read the document."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, space = await readable_document(uow, user, id)
            visible = await visible_relations(uow, user, document, space)
        refers = [item for item in visible if item.relation.state is RelationState.SET]
        return DocumentRelations(
            refers_to=tuple(item for item in refers if item.direction is Direction.REFERS_TO),
            referred_by=tuple(item for item in refers if item.direction is Direction.REFERRED_BY),
            suggested=tuple(
                item for item in visible if item.relation.state is RelationState.SUGGESTED
            ),
            editable=can_edit_document(user, document, space),
        )

    async def relate(self, actor: UserId, id: DocumentId, other: DocumentId) -> None:
        """Set the relation between the two documents, from the newer to the older (by their
        document dates, else when they came in), or accept Lekto's suggestion of it.
        NotFoundError if the caller reads neither, PermissionDeniedError if they do not edit
        the newer; ConflictError if it is set already."""
        now = self._clock.now()
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            newer, older = await _pair(uow, user, id, other)
            known = await find_pair(uow, newer.id, older.id)
            if known is not None and known.state is RelationState.SET:
                raise ConflictError(because(ReasonCode.RELATION_EXISTS))
            accepting = known is not None and known.state is RelationState.SUGGESTED
            # One Lekto made stays Lekto's (a suggestion accepted, a rejection taken back):
            # removed again, it is rejected again, not forgotten.
            relation = (
                replace(known, state=RelationState.SET, decided_by=user.id, decided_at=now)
                if known is not None
                else Relation(
                    newer=newer.id,
                    older=older.id,
                    origin=RelationOrigin.PERSON,
                    state=RelationState.SET,
                    created_at=now,
                    decided_by=user.id,
                    decided_at=now,
                )
            )
            await uow.document_relations.put(relation)
            await _verdict(uow, newer, Verdict.ACCEPTED if accepting else Verdict.ADDED, now)
            await uow.commit()

    async def unrelate(self, actor: UserId, id: DocumentId, other: DocumentId) -> None:
        """Remove the relation between the two documents, or reject Lekto's suggestion of it:
        one Lekto made is kept as rejected (it is not suggested again), one a person set goes.
        NotFoundError if there is none (or the caller reads neither document),
        PermissionDeniedError if they do not edit the newer."""
        now = self._clock.now()
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            newer, older = await _pair(uow, user, id, other)
            known = await find_pair(uow, newer.id, older.id)
            if known is None or known.state is RelationState.REJECTED:
                raise NotFoundError(
                    "relation", f"{newer.id}:{older.id}", because(ReasonCode.RELATION_NOT_FOUND)
                )
            if known.origin is RelationOrigin.LEKTO:
                rejected = replace(
                    known, state=RelationState.REJECTED, decided_by=user.id, decided_at=now
                )
                await uow.document_relations.put(rejected)
                await _verdict(uow, newer, Verdict.CORRECTED, now)
            else:
                await uow.document_relations.remove(known.newer, known.older)
            await uow.commit()


async def referred_types(uow: UnitOfWork, document: Document) -> tuple[DocumentTypeId | None, ...]:
    """The types of the documents `document` refers to by a set relation (the direction as
    the dates are now; a suggestion does not count): what the rules' condition `relation`
    sees. Whether the rule's author reads them does not matter, as for the facts."""
    found: list[DocumentTypeId | None] = []
    for relation in await uow.document_relations.of_document(document.id):
        if relation.state is not RelationState.SET:
            continue
        other = await uow.documents.find(relation.other(document.id))
        if other is not None and _newer(document, other) == document.id:
            found.append(other.document_type_id)
    return tuple(found)


async def find_pair(uow: UnitOfWork, first: DocumentId, second: DocumentId) -> Relation | None:
    """The relation between the two documents, stored in either order: it keeps the order of
    when it was made, and a document date set or changed since may have turned it."""
    found = await uow.document_relations.find(first, second)
    return found or await uow.document_relations.find(second, first)


async def visible_relations(
    uow: UnitOfWork, user: User, document: Document, space: Space
) -> list[Related]:
    """The relations of the document `user` reads whose other end they read too, rejected ones
    aside, the newest first."""
    found: list[Related] = []
    spaces = {space.id: space}
    for relation in await uow.document_relations.of_document(document.id):
        if relation.state is RelationState.REJECTED:
            continue
        other = await uow.documents.find(relation.other(document.id))
        if other is None:
            continue
        if other.space_id not in spaces:
            spaces[other.space_id] = await uow.spaces.get(other.space_id)
        if not can_read_document(user, other, spaces[other.space_id]):
            continue
        # The direction as the documents' dates are now (`find_pair`).
        newer = document if _newer(document, other) == document.id else other
        found.append(
            Related(
                relation,
                other,
                Direction.REFERS_TO if newer is document else Direction.REFERRED_BY,
                can_edit_document(user, newer, spaces[newer.space_id]),
            )
        )
    return found


async def _pair(
    uow: UnitOfWork, user: User, id: DocumentId, other: DocumentId
) -> tuple[Document, Document]:
    """The two documents, the newer first, checked: the caller reads both and edits the newer."""
    if id == other:
        raise ConflictError(because(ReasonCode.RELATION_TO_ITSELF))
    first, _ = await readable_document(uow, user, id)
    second, _ = await readable_document(uow, user, other)
    newer, older = (first, second) if _newer(first, second) == first.id else (second, first)
    await writable_document(uow, user, newer.id)
    return newer, older


def _newer(first: Document, second: Document) -> DocumentId:
    """Which of the two is the newer, by their document dates now (`relations.ordered`)."""
    newer, _ = ordered(
        (first.id, first.document_date, first.created_at),
        (second.id, second.document_date, second.created_at),
    )
    return newer


async def _verdict(uow: UnitOfWork, newer: Document, verdict: Verdict, now: datetime) -> None:
    """The first decision about the newer document's relations; before its first run stopped,
    early."""
    if newer.processing.run == 1 and newer.first_lane is None:
        verdict = Verdict.EARLY
    await uow.processing_facts.add_verdicts(
        [
            FieldVerdict(
                document_id=newer.id,
                field=RELATIONS,
                verdict=verdict,
                decided_at=now,
                decision=Decision.CHANGE,
            )
        ]
    )
