"""A person's decisions about the facts of a document (`.idea/fakten.md`, issue #145 PR 6):
adding one the sources did not find, correcting the value or the role of one, rejecting one
(it is no fact of the document), and withdrawing a decision. Editors of the document's space
and admins decide; the kinds that are a person's alone (tax ID, social security number, ...;
`person_only`) only admins.
A decision outlasts the runs of the facts signal (`DocumentFactRepository.replace_found`).

The person's first decision about the facts of a document is a verdict on them
(`first_runs.FACTS`): a correction or a rejection says the sources were wrong, an addition that
they missed one. An admin who corrects a contact's kind of fact may correct it at the document's
contact too (`at_contact`): the old value goes from the contact's identifiers, the new one is
entered by hand, as a person's choice it takes the value from another contact that only learned
or rejected it."""

from dataclasses import dataclass
from enum import StrEnum

from lekto.core.domain.document_facts import (
    DocumentFact,
    FactRole,
    FactState,
    added,
    corrected,
    person_fact,
    rejected,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.first_runs import FACTS, Decision, FieldVerdict, Verdict
from lekto.core.domain.identifiers import (
    CONTACT_KINDS,
    TYPES,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    Key,
)
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, writable_document
from lekto.core.services._identifiers import claim_identifiers
from lekto.core.services.classification.kept_facts import facts_lock
from lekto.core.services.objects import load_text


class FactAction(StrEnum):
    ADD = "add"
    CORRECT = "correct"
    REJECT = "reject"
    WITHDRAW = "withdraw"


@dataclass(frozen=True, kw_only=True)
class FactDecision:
    """What a person decides about the fact of `kind` and `value` (for `ADD` the value as
    they write it, else the fact's normalised value): `role` the role it has (`ADD`: required),
    `new_value` the value it has instead (`CORRECT`, as written), `at_contact` the correction
    made at the document's contact too (admins, a contact's kinds)."""

    action: FactAction
    kind: IdentifierKind
    value: str
    role: FactRole | None = None
    new_value: str | None = None
    at_contact: bool = False


async def decide_fact(
    uow_factory: UnitOfWorkFactory,
    store: ObjectStore,
    clock: Clock,
    actor: UserId,
    id: DocumentId,
    decision: FactDecision,
) -> None:
    """Keep `decision` about a fact of the document. NotFoundError if the caller may not read
    it, or it has no fact of that kind and value; PermissionDeniedError if they only read it,
    for a person's kind if they are no admin, and for `at_contact` if they are no admin;
    ConflictError for adding a fact it has, and while it has no text; ValidationError for a
    value that is none of the kind, a decision without what it needs, and `at_contact` without
    a contact or for a kind that is no contact's."""
    try:
        text = (await load_text(store, id)).decode("utf-8", errors="replace")
    except NotFoundError:
        text = None
    now = clock.now()
    async with uow_factory() as uow:
        # One store of the document's facts at a time: the signals' and a person's.
        await uow.lock(facts_lock(id))
        user = await load_actor(uow, actor)
        document, _ = await writable_document(uow, user, id)
        if text is None:
            raise ConflictError(because(ReasonCode.NO_TEXT_YET))
        if person_only(decision.kind) and not user.is_active_admin:
            raise PermissionDeniedError(because(ReasonCode.FACT_OF_PERSON))
        facts = {fact.key: fact for fact in await uow.document_facts.of_document(id)}
        key: Key = (decision.kind, decision.value)
        verdict: Verdict | None = None
        match decision.action:
            case FactAction.ADD:
                if decision.role is None:
                    raise ValidationError(because(ReasonCode.FACT_ROLE_MISSING))
                given = person_fact(
                    text, decision.kind, decision.value, decision.role, FactState.ADDED
                )
                known = facts.get(given.key)
                if known is not None and known.state is not FactState.REJECTED:
                    raise ConflictError(
                        because(ReasonCode.FACT_EXISTS, kind=given.kind.value, value=given.value)
                    )
                await uow.document_facts.decide(id, added(given, known))
                verdict = Verdict.ADDED
            case FactAction.CORRECT:
                fact = _fact(facts, key)
                new = None
                if decision.new_value is not None:
                    new = person_fact(
                        text,
                        decision.kind,
                        decision.new_value,
                        decision.role or fact.role,
                        FactState.CORRECTED,
                    )
                    known = facts.get(new.key)
                    if known is not None and new.key != fact.key:
                        new = added(new, known)  # a fact a source found: its origins stay
                changes = corrected(fact, role=decision.role, new=new)
                for change in changes:
                    await uow.document_facts.decide(id, change)
                if decision.at_contact:
                    await _at_contact(uow, user, document, fact, changes)
                verdict = Verdict.CORRECTED if changes else None
            case FactAction.REJECT:
                await uow.document_facts.decide(id, rejected(_fact(facts, key)))
                verdict = Verdict.CORRECTED
            case FactAction.WITHDRAW:
                _fact(facts, key)
                await uow.document_facts.withdraw(id, key)
        if verdict is not None:
            await uow.processing_facts.add_verdicts(
                [
                    FieldVerdict(
                        document_id=id,
                        field=FACTS,
                        verdict=verdict,
                        decided_at=now,
                        decision=Decision.CHANGE,
                    )
                ]
            )
        await uow.commit()


def person_only(kind: IdentifierKind) -> bool:
    """A kind of a person's and no contact's (the IBAN is both)."""
    return TYPES[kind].for_persons and not TYPES[kind].for_contacts


def _fact(facts: dict[Key, DocumentFact], key: Key) -> DocumentFact:
    fact = facts.get(key)
    if fact is None:
        kind, value = key
        raise NotFoundError(
            "fact", value, because(ReasonCode.FACT_NOT_FOUND, kind=kind.value, value=value)
        )
    return fact


async def _at_contact(
    uow: UnitOfWork,
    user: User,
    document: Document,
    old: DocumentFact,
    changes: list[DocumentFact],
) -> None:
    """The correction of `old` at the document's contact: its value there gives way to the
    corrected one, entered by hand with the old one's topic and user."""
    if not user.is_active_admin:
        raise PermissionDeniedError(because(ReasonCode.FACT_AT_CONTACT_ADMIN))
    if document.contact_id is None or old.kind not in CONTACT_KINDS:
        raise ValidationError(because(ReasonCode.FACT_NOT_AT_CONTACT, kind=old.kind.value))
    new = next((fact for fact in changes if fact.state is FactState.CORRECTED), None)
    if new is None or new.key == old.key:
        return  # only the role changed: a contact keeps no roles
    contact = await uow.contacts.get(document.contact_id)
    before = next((item for item in contact.identifiers if item.key == old.key), None)
    entered = Identifier(
        new.kind,
        new.value,
        IdentifierSource.MANUAL,
        None if before is None else before.topic_id,
        None if before is None else before.user_id,
    )
    manual = [
        item
        for item in contact.identifiers
        if item.source is IdentifierSource.MANUAL and item.key not in (old.key, new.key)
    ]
    rejected_ = [
        item
        for item in contact.identifiers
        if item.source is IdentifierSource.REJECTED and item.key != new.key
    ]
    contact.set_identifiers([*manual, entered], rejected_)
    await claim_identifiers(uow, [contact])
    await uow.contacts.update(contact)
