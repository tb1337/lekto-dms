"""The holders and the recommendations against a person's decisions (`.idea/umsetzungsplan.md`,
"Empfehlungen im Reiter Kennungen und laufende Auswertung der Inhaber", Tobi 28.10.2026): no
test set, the identifiers a person confirmed or rejected at a contact.

Measured is each identifier a person decided at a contact (entered or confirmed by hand,
`manual`; rejected, `rejected`) that confirmed documents of that contact show. The rule says
the contact's where its holder there is the contact once or more and someone else nowhere,
foreign where someone else holds it there (a person, a third party), and unclear otherwise; a
document read before its kind had a holder leaves it unread. Right is the contact's and
confirmed, or foreign and rejected; the two ways wrong are kept apart: the contact's but
rejected (training would have learned it), foreign but confirmed. The recommendation of the
open list is measured the same way, over every kind of a contact: as if training had learned
each decided identifier at its contact. Each decision measured is kept as a case, with the
documents it was measured in, to show what stands behind a number.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from lekto.core.domain.document_facts import HOLDER_KINDS, HolderKind
from lekto.core.domain.holders import foreign, held_by
from lekto.core.domain.identifiers import IdentifierKind, IdentifierSource, Key
from lekto.core.domain.ids import ContactId, DocumentId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.open_identifiers import Recommendation, Sighting, recommendation_for

_DECIDED = frozenset({IdentifierSource.MANUAL, IdentifierSource.REJECTED})


class Said(StrEnum):
    """What a measure said about an identifier at its contact."""

    OURS = "ours"  # the contact's, or: confirm it
    FOREIGN = "foreign"  # someone else's, or: reject it
    UNCLEAR = "unclear"  # neither
    UNREAD = "unread"  # read before its kind had a holder


class HolderOutcome(StrEnum):
    """How a measure fared on one decision: a column of the tally."""

    RIGHT = "right"
    LEARNED_REJECTED = "learned_rejected"
    REFUSED_CONFIRMED = "refused_confirmed"
    UNCLEAR = "unclear"
    UNREAD = "unread"


@dataclass(frozen=True)
class Case:
    """One decision measured: by the holders of `measure` (a kind; None: the recommendation),
    with its `outcome`; the identifier, its contact, whether the person confirmed it, and the
    confirmed documents of the contact that show it, the newest first."""

    measure: IdentifierKind | None
    outcome: HolderOutcome
    kind: IdentifierKind
    value: str
    contact: ContactId
    confirmed: bool
    documents: tuple[DocumentId, ...]


@dataclass
class Tally:
    """How a measure fared: `right`, the two ways wrong (`learned_rejected`: it said the
    contact's or confirm, the person rejected; `refused_confirmed`: it said foreign or reject,
    the person confirmed), `unclear` (it said neither) and `unread` (read before its kind had a
    holder)."""

    right: int = 0
    learned_rejected: int = 0
    refused_confirmed: int = 0
    unclear: int = 0
    unread: int = 0

    @property
    def told(self) -> int:
        """The decisions it told something about."""
        return self.right + self.learned_rejected + self.refused_confirmed


@dataclass
class HolderEvaluation:
    """The holders' tally per kind with a holder, and the recommendation's over all kinds."""

    kinds: dict[IdentifierKind, Tally] = field(default_factory=dict)
    recommendation: Tally = field(default_factory=Tally)
    cases: list[Case] = field(default_factory=list)


def evaluate(contacts: Iterable[Contact], sightings: Iterable[Sighting]) -> HolderEvaluation:
    """Measure the holders and the recommendations against the decisions at `contacts`, in the
    confirmed documents `sightings` (`DocumentFactRepository.sightings`)."""
    contacts = list(contacts)
    by_key: dict[Key, list[Sighting]] = defaultdict(list)
    for sighting in sightings:
        by_key[sighting.fact.key].append(sighting)
    names = {contact.id: contact.names() for contact in contacts}
    labels = {contact.id: contact.name for contact in contacts}
    evaluation = HolderEvaluation({kind: Tally() for kind in sorted(HOLDER_KINDS)})
    for contact in contacts:
        for identifier in contact.identifiers:
            if identifier.source not in _DECIDED:
                continue
            seen = by_key.get(identifier.key, [])
            own = [item for item in seen if item.contact == contact.id]
            if not own:
                continue
            confirmed = identifier.source is IdentifierSource.MANUAL
            documents = tuple(
                item.document for item in sorted(own, key=lambda item: item.dated, reverse=True)
            )
            case = Case(
                None,
                HolderOutcome.UNCLEAR,
                identifier.kind,
                identifier.value,
                contact.id,
                confirmed,
                documents,
            )

            if identifier.kind in HOLDER_KINDS:
                tally = evaluation.kinds[identifier.kind]
                outcome = _count(tally, _rule(own, names[contact.id]), confirmed)
                evaluation.cases.append(replace(case, measure=identifier.kind, outcome=outcome))
            advised = recommendation_for(contact.id, identifier.key, seen, names, labels)
            if advised is None:
                said = Said.UNCLEAR
            elif advised.action is Recommendation.CONFIRM:
                said = Said.OURS
            else:
                said = Said.FOREIGN
            outcome = _count(evaluation.recommendation, said, confirmed)
            evaluation.cases.append(replace(case, outcome=outcome))
    return evaluation


def _rule(own: Sequence[Sighting], names: Sequence[str]) -> Said:
    """What the holders say in the contact's documents."""
    if any(item.fact.holder is None for item in own):
        return Said.UNREAD
    if any(foreign(item.fact.holder, names) for item in own):
        return Said.FOREIGN
    if any(held_by(item.fact.holder, names) is HolderKind.SENDER for item in own):
        return Said.OURS
    return Said.UNCLEAR


def _count(tally: Tally, said: Said, confirmed: bool) -> HolderOutcome:
    if said is Said.UNREAD:
        tally.unread += 1
        return HolderOutcome.UNREAD
    if said is Said.UNCLEAR:
        tally.unclear += 1
        return HolderOutcome.UNCLEAR
    if (said is Said.OURS) == confirmed:
        tally.right += 1
        return HolderOutcome.RIGHT
    if said is Said.OURS:
        tally.learned_rejected += 1
        return HolderOutcome.LEARNED_REJECTED
    tally.refused_confirmed += 1
    return HolderOutcome.REFUSED_CONFIRMED
