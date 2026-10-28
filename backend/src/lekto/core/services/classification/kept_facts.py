"""Keeping a document's facts (`domain.document_facts`) from both readers: the patterns and
codes of `signal_facts`, and the facts with their role the language model read in `signal_llm`
(`facts-2`, with the holders of the IBANs and creditor IDs). The two signals run side by side,
so whichever stores its result merges both: the facts signal the model's latest facts and
holders from the log, the model's signal the codes and the rule's holders (`domain.holders`)
already kept.
One lock per document keeps two stores from overwriting each other's half; a person's decisions
stay either way (`DocumentFactRepository.replace_found`)."""

import asyncio
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from lekto.core.domain.document_facts import (
    HOLDER_KINDS,
    DocumentFact,
    FactOrigin,
    FactRole,
    Holder,
    ReadFact,
    checked_read,
    found_facts,
    with_read,
)
from lekto.core.domain.holders import ReadHolder, checked_holder, merged_holder
from lekto.core.domain.identifiers import (
    TYPES,
    IdentifierKind,
    Key,
    identifiers_in,
    places_in,
    referred_in,
)
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.reasons import Reason
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._identifiers import person_identifiers
from lekto.core.services.classification.prompts import FACT_KINDS, FACT_ROLES

READ_FACTS = "read_facts"
"""Key of what became of the language model's facts in the output of the signal that kept them:
how many were taken, and those refused with why."""

_KINDS: frozenset[IdentifierKind] = frozenset(FACT_KINDS)
_ROLES: frozenset[FactRole] = frozenset(FACT_ROLES)


def facts_lock(document: DocumentId) -> str:
    return f"document-facts:{document}"


@dataclass(frozen=True)
class TextFacts:
    """What the patterns read in a document's text (`identifiers_in`, `places_in`,
    `referred_in`), read outside the transaction that keeps the facts."""

    text: str
    in_text: frozenset[Key]
    places: dict[Key, int]
    referred: frozenset[Key]

    @classmethod
    async def read(cls, text: str) -> "TextFacts":
        def reading() -> "TextFacts":
            return cls(
                text,
                frozenset(identifiers_in(text)),
                places_in(text),
                frozenset(referred_in(text)),
            )

        # Every kind's patterns over a long text take a while: not in the loop.
        return await asyncio.to_thread(reading)

    def found(self, in_codes: Iterable[Key] = ()) -> tuple[DocumentFact, ...]:
        """The facts of the patterns and of the codes on the pages (`in_codes`)."""
        return found_facts(self.text, self.in_text, in_codes, self.places, self.referred)


def merged_facts(
    text: TextFacts,
    in_codes: Collection[Key],
    read: Iterable[ReadFact] | None,
    personal: Collection[Key],
    holders: Mapping[Key, Holder] | None = None,
    told: Iterable[ReadHolder] | None = None,
) -> tuple[list[DocumentFact], JsonObject | None]:
    """The facts of the patterns and codes, each with its holder: the rule's (`holders`) merged
    with what the model told that passes its check (`checked_holder`, `merged_holder`); with
    those the model read that pass their check (`checked_read`: of the kinds and roles it was
    asked for, none of a person's), and the report of the model's facts and holders (None
    without them)."""
    patterns = text.found(in_codes)
    listed = {fact.key for fact in patterns if fact.key[0] in HOLDER_KINDS}
    checked_holders = [(item, checked_holder(text.text, item, listed)) for item in told or ()]
    model = {item[0]: item[1] for _, item in checked_holders if not isinstance(item, Reason)}
    found = [
        replace(fact, holder=held)
        if (held := merged_holder((holders or {}).get(fact.key), model.get(fact.key)))
        else fact
        for fact in patterns
    ]
    told_report: JsonObject = {
        "taken": len(model),
        "refused": [
            {"kind": holder.kind, "value": holder.value, "reason": item.to_json()}
            for holder, item in checked_holders
            if isinstance(item, Reason)
        ],
    }
    if read is None:
        return found, {"holders": told_report} if checked_holders else None
    checked = [
        (
            fact,
            checked_read(text.text, fact, kinds=_KINDS, roles=_ROLES, personal=personal),
        )
        for fact in read
    ]
    taken = [item for _, item in checked if isinstance(item, DocumentFact)]
    report: JsonObject = {
        "taken": len(taken),
        "refused": [
            {"kind": fact.kind, "value": fact.value, "reason": item.to_json()}
            for fact, item in checked
            if isinstance(item, Reason)
        ],
    }
    if checked_holders:
        report["holders"] = told_report
    return with_read(found, taken), report


async def keep_facts(
    uow: UnitOfWork,
    document: DocumentId,
    text: TextFacts,
    read: Iterable[ReadFact] | None,
    *,
    in_codes: Collection[Key] | None = None,
    holders: Mapping[Key, Holder] | None = None,
    told: Iterable[ReadHolder] | None = None,
) -> JsonObject | None:
    """Keep the document's facts in `uow` (`merged_facts`): `in_codes` the identifiers of its
    codes, `holders` whose its numbers are by the rule (None: those kept already, the model's
    signal reads neither codes nor pages), `told` the holders the model told. The users'
    numbers and the person's kinds in the text are a person's. Returns the report of the
    model's facts."""
    await uow.lock(facts_lock(document))
    return await refresh_facts(
        uow, document, text, read, in_codes=in_codes, holders=holders, told=told
    )


async def refresh_facts(
    uow: UnitOfWork,
    document: DocumentId,
    text: TextFacts,
    read: Iterable[ReadFact] | None,
    *,
    in_codes: Collection[Key] | None = None,
    holders: Mapping[Key, Holder] | None = None,
    told: Iterable[ReadHolder] | None = None,
) -> JsonObject | None:
    """`keep_facts` in a unit that holds the document's lock (`facts_lock`) already."""
    if in_codes is None or holders is None:
        kept = await uow.document_facts.of_document(document)
        if in_codes is None:
            in_codes = {fact.key for fact in kept if FactOrigin.CODE in fact.origins}
        if holders is None:
            holders = {fact.key: fact.holder for fact in kept if fact.holder is not None}
    personal = {key for key in text.in_text if TYPES[key[0]].for_persons}
    personal |= await person_identifiers(uow)
    facts, report = merged_facts(text, in_codes, read, personal, holders, told)
    await uow.document_facts.replace_found(document, facts)
    return report
