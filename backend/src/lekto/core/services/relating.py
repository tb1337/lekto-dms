"""Recognising the relations of a document (the node `relate`, issue #145 PR 11;
`.idea/bezuege.md`, decisions 7 to 9): the older documents it refers to, and the newer ones
already there that refer to it, from what both show.

- A number it refers to (`Ihre Rechnung Nr. 4711`, role `refers`) that another document carries
  as its own (an invoice, credit note or order number), and the other way round.
- A contract or customer number it shares with a document of a type that is a relation target
  (a contract, a policy; `DocumentType.relation_target`), and, for such a document, the documents
  that share its number.
- The same contact, type and period (a field of type period) at another document date: the
  correction of the original.
- The day of a letter it answers (`Ihr Schreiben vom 18.06.2026`, `letter_date`) as the document
  date of a document of the same contact, and the other way round.

A source that finds exactly one document of the same contact sets the relation; several, or a
document without a contact, give suggestions; a document of another contact is none. A relation
never makes a document yellow. A pair a person decided, or Lekto related before, stays as it is:
only a suggestion of Lekto's becomes set when a source is sure now. Relations go from the newer
to the older document, whichever of the two came in first."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from lekto.core.domain.classification import (
    CHANGE_FIELDS,
    CONTACT,
    CUSTOM_FIELDS,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
)
from lekto.core.domain.document_facts import (
    DocumentFact,
    FactCriterion,
    FactRole,
    FactState,
    role_of,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import DocumentId, DocumentTypeId
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import NodeResult, Outcome
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState, ordered
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._jobs import document_payload
from lekto.core.services.relations import find_pair

RELATE = "relate-1"
"""The version of the recognition, in the log entries of the node."""

RELATE_JOB = "pipeline.relate"
"""Job kind of finding a document's relations outside processing: after a person decided its
contact, type, date, fields or facts, and for every document (`lekto relate`); payload: the
document id. Processing and log stay as they are."""

RELATIONS_LOCK = "relations"
"""One recognition at a time: two documents that find each other store one relation."""

LIMIT = 200
"""The most documents a source looks at for one value: a contract number every invoice of a
series shows connects many, a number far more common than that is no evidence."""

TARGET_KINDS: frozenset[IdentifierKind] = frozenset(
    {kind for kind in IdentifierKind if role_of(kind) is FactRole.TARGET}
    | {IdentifierKind.CUSTOMER_NUMBER}
)
"""The numbers that connect a document with a relation target: contract, policy and the like,
and the customer number (decision 8)."""

OWN_KINDS: frozenset[IdentifierKind] = frozenset(
    kind for kind in IdentifierKind if role_of(kind) is FactRole.OWN
)
"""The numbers that mark a document itself: invoice, credit note, order number."""


@dataclass(frozen=True)
class Found:
    """A document a source relates the document with, how sure, and why."""

    other: Document
    state: RelationState
    evidence: JsonObject


async def recognise(uow: UnitOfWork, document: Document) -> list[Found]:
    """The documents the sources relate `document` with, one entry each (a sure source wins)."""
    kept = await _kept(uow, document)
    targets = frozenset(
        item.id for item in await uow.document_types.list_all() if item.relation_target
    )
    found: dict[DocumentId, Found] = {}
    for item in [
        *await _numbers(uow, document, kept),
        *await _targets(uow, document, kept, targets),
        *await _periods(uow, document, kept),
        *await _letters(uow, document, kept),
    ]:
        known = found.get(item.other.id)
        if known is None or (
            known.state is RelationState.SUGGESTED and item.state is RelationState.SET
        ):
            found[item.other.id] = item
    return list(found.values())


async def relate(uow: UnitOfWork, document: Document, now: datetime) -> list[Relation]:
    """Store what the sources find for `document` (`recognise`) in the unit, which holds
    `RELATIONS_LOCK`; returns the relations made or made sure."""
    made: list[Relation] = []
    for item in await recognise(uow, document):
        known = await find_pair(uow, document.id, item.other.id)
        if known is not None:
            if (
                known.origin is RelationOrigin.LEKTO
                and known.state is RelationState.SUGGESTED
                and item.state is RelationState.SET
            ):
                sure = replace(known, state=RelationState.SET, evidence=item.evidence)
                await uow.document_relations.put(sure)
                made.append(sure)
            continue
        newer, older = ordered(
            (document.id, document.document_date, document.created_at),
            (item.other.id, item.other.document_date, item.other.created_at),
        )
        relation = Relation(
            newer=newer,
            older=older,
            origin=RelationOrigin.LEKTO,
            state=item.state,
            evidence=item.evidence,
            created_at=now,
        )
        await uow.document_relations.put(relation)
        made.append(relation)
    return made


def relates_by(changed: Iterable[str]) -> bool:
    """Whether a change of these attributes (`Document.apply_changes`) may change what the
    sources find: the contact, the type, the date or the fields."""
    relevant = {CHANGE_FIELDS[CONTACT], CHANGE_FIELDS[DOCUMENT_TYPE], CHANGE_FIELDS[DOCUMENT_DATE]}
    return any(name in relevant or name == CUSTOM_FIELDS for name in changed)


async def queue_relate(uow: UnitOfWork, document: DocumentId, now: datetime) -> None:
    """A `RELATE_JOB` for the document, once while one waits."""
    await uow.jobs.enqueue(
        RELATE_JOB, document_payload(document), run_at=now, dedup_key=f"{document}:relate"
    )


class RelateNode:
    """The node `relate`: recognises the document's relations when its run stores the result,
    on the documents as they are then."""

    async def run(self, document: Document) -> "RelateResult":
        return RelateResult()


@dataclass(frozen=True)
class RelateResult:
    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        await uow.lock(RELATIONS_LOCK)
        made = await relate(uow, document, now)
        return NodeResult(
            outcome=Outcome.OK,
            model_version=RELATE,
            output={"relations": [relation_json(item, document.id) for item in made]},
        )


def relation_json(relation: Relation, document: DocumentId) -> JsonObject:
    """A relation as the log of `document` names it: the other document, which way, how sure,
    and why."""
    return {
        "document_id": str(relation.other(document)),
        "direction": "refers_to" if relation.newer == document else "referred_by",
        "state": relation.state.value,
        "evidence": dict(relation.evidence),
    }


# --- the sources ------------------------------------------------------------------------------


async def _kept(uow: UnitOfWork, document: Document) -> list[DocumentFact]:
    return [
        fact
        for fact in await uow.document_facts.of_document(document.id)
        if fact.state is not FactState.REJECTED
    ]


def _fits(document: Document, other: Document) -> bool | None:
    """Whether the two are of the same contact: None where one has none (then only a
    suggestion)."""
    if document.contact_id is None or other.contact_id is None:
        return None
    return document.contact_id == other.contact_id


def _sure(fit: bool | None, alone: bool) -> RelationState:
    return RelationState.SET if fit and alone else RelationState.SUGGESTED


async def _with_fact(
    uow: UnitOfWork,
    kind: IdentifierKind,
    value: str,
    role: FactRole | None = None,
    *,
    document_types: frozenset[DocumentTypeId] | None = None,
) -> list[Document]:
    return await uow.documents.query(
        DocumentFilter(
            facts=(FactCriterion(kind=kind, value=value, role=role),),
            document_types=document_types or None,
        ),
        limit=LIMIT,
    )


def _of_contact(documents: Iterable[Document], document: Document) -> list[Document]:
    """The documents of `document`'s contact; all of them where it has none."""
    return [
        item
        for item in documents
        if document.contact_id is None or item.contact_id == document.contact_id
    ]


async def _numbers(
    uow: UnitOfWork, document: Document, kept: Sequence[DocumentFact]
) -> list[Found]:
    """A number it refers to that another document carries as its own, and the documents that
    refer to its own number."""
    found: list[Found] = []
    for fact in kept:
        if fact.kind not in OWN_KINDS:
            continue
        evidence: JsonObject = {"kind": "fact", "fact_kind": fact.kind.value, "value": fact.shown}
        if fact.role is FactRole.REFERS:
            owners = [
                item
                for item in await _with_fact(uow, fact.kind, fact.value, FactRole.OWN)
                if item.id != document.id and _fits(document, item) is not False
            ]
            alone = len(_of_contact(owners, document)) == 1
            found += [Found(item, _sure(_fits(document, item), alone), evidence) for item in owners]
        elif fact.role is FactRole.OWN:
            owners = await _with_fact(uow, fact.kind, fact.value, FactRole.OWN)
            alone = len(_of_contact(owners, document)) == 1
            for item in await _with_fact(uow, fact.kind, fact.value, FactRole.REFERS):
                fit = _fits(document, item)
                if item.id != document.id and fit is not False:
                    found.append(Found(item, _sure(fit, alone), evidence))
    return found


async def _targets(
    uow: UnitOfWork,
    document: Document,
    kept: Sequence[DocumentFact],
    targets: frozenset[DocumentTypeId],
) -> list[Found]:
    """A contract or customer number it shares with a document of a relation target's type, and,
    for a relation target, the documents that share its number."""
    if not targets:
        return []
    found: list[Found] = []
    seen: set[tuple[IdentifierKind, str]] = set()
    for fact in kept:
        if fact.kind not in TARGET_KINDS or fact.key in seen or fact.role is FactRole.PERSON:
            continue
        seen.add(fact.key)
        evidence: JsonObject = {
            "kind": "target",
            "fact_kind": fact.kind.value,
            "value": fact.shown,
        }
        sharing = [
            item
            for item in await _with_fact(uow, fact.kind, fact.value)
            if item.id != document.id and _fits(document, item) is not False
        ]
        aimed = [item for item in sharing if item.document_type_id in targets]
        alone = len(_of_contact(aimed, document)) == 1
        found += [Found(item, _sure(_fits(document, item), alone), evidence) for item in aimed]
        if document.document_type_id in targets:
            # The target came: those that share its number refer to it, sure while it is the
            # only target that has it.
            alone = not _of_contact(aimed, document)
            found += [
                Found(item, _sure(_fits(document, item), alone), evidence)
                for item in sharing
                if item.document_type_id not in targets
            ]
    return found


IDENTITY_KINDS: frozenset[IdentifierKind] = TARGET_KINDS | {IdentifierKind.PERSONNEL_NUMBER}
"""Numbers that tell whose a document is: two payslips of one month with different personnel
numbers are two people's, not a correction of the other."""


def _apart(mine: Sequence[DocumentFact], theirs: Sequence[DocumentFact]) -> bool:
    """Whether the two show different numbers of a kind that tells whose they are."""
    for kind in IDENTITY_KINDS:
        own = {fact.value for fact in mine if fact.kind is kind}
        other = {fact.value for fact in theirs if fact.kind is kind}
        if own and other and not own & other:
            return True
    return False


async def _periods(
    uow: UnitOfWork, document: Document, kept: Sequence[DocumentFact]
) -> list[Found]:
    """The same contact, type and period at another document date: the correction and the
    original, unless their numbers tell they are two people's (`IDENTITY_KINDS`)."""
    periods = [(id, value) for id, value in document.fields.items() if isinstance(value, Period)]
    if (
        not periods
        or document.contact_id is None
        or document.document_type_id is None
        or document.document_date is None
    ):
        return []
    others = await uow.documents.query(
        DocumentFilter(
            contacts=frozenset({document.contact_id}),
            document_types=frozenset({document.document_type_id}),
        ),
        limit=LIMIT,
    )
    found: list[Found] = []
    for field, period in periods:
        same = [
            item
            for item in others
            if item.id != document.id
            and item.fields.get(field) == period
            and item.document_date is not None
            and item.document_date != document.document_date
            and not _apart(kept, await _kept(uow, item))
        ]
        evidence: JsonObject = {"kind": "period", "field_id": str(field), "period": period.notation}
        state = RelationState.SET if len(same) == 1 else RelationState.SUGGESTED
        found += [Found(item, state, evidence) for item in same]
    return found


async def _letters(
    uow: UnitOfWork, document: Document, kept: Sequence[DocumentFact]
) -> list[Found]:
    """The day of a letter it answers as the document date of a document of the same contact,
    and the documents of the contact that answer a letter of its date."""
    if document.contact_id is None:
        return []
    contact = frozenset({document.contact_id})
    found: list[Found] = []
    for fact in kept:
        if fact.kind is not IdentifierKind.LETTER_DATE or fact.role is not FactRole.REFERS:
            continue
        day = date.fromisoformat(fact.value)
        dated = [
            item
            for item in await uow.documents.query(
                DocumentFilter(contacts=contact, document_dates=Period.day(day)), limit=LIMIT
            )
            if item.id != document.id
        ]
        evidence: JsonObject = {"kind": "letter_date", "date": fact.value}
        state = RelationState.SET if len(dated) == 1 else RelationState.SUGGESTED
        found += [Found(item, state, evidence) for item in dated]
    if document.document_date is not None:
        day_value = document.document_date.isoformat()
        same_day = await uow.documents.query(
            DocumentFilter(contacts=contact, document_dates=Period.day(document.document_date)),
            limit=LIMIT,
        )
        evidence = {"kind": "letter_date", "date": day_value}
        state = RelationState.SET if len(same_day) <= 1 else RelationState.SUGGESTED
        referring = await uow.documents.query(
            DocumentFilter(
                contacts=contact,
                facts=(
                    FactCriterion(
                        kind=IdentifierKind.LETTER_DATE, value=day_value, role=FactRole.REFERS
                    ),
                ),
            ),
            limit=LIMIT,
        )
        found += [Found(item, state, evidence) for item in referring if item.id != document.id]
    return found
