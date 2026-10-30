"""The holders and the recommendations against a person's decisions at the contacts."""

from datetime import date

from lekto.core.domain.document_facts import (
    DocumentFact,
    FactOrigin,
    Holder,
    HolderKind,
    HolderSource,
    role_of,
)
from lekto.core.domain.holder_evaluation import HolderOutcome, Tally, evaluate
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.ids import ContactId, DocumentId, new_id
from lekto.core.domain.master_data import Contact
from lekto.core.domain.open_identifiers import Sighting
from tests.builders import NOW

IBAN = (IdentifierKind.IBAN, "DE02120300000000202051")
PAYEE = (IdentifierKind.IBAN, "DE89370400440532013000")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
CUSTOMER = (IdentifierKind.CUSTOMER_NUMBER, "20047718")
SENDER = Holder(HolderKind.SENDER, HolderSource.RULE)
THIRD = Holder(HolderKind.THIRD_PARTY, HolderSource.RULE)


def seen(
    contact: ContactId, key: tuple[IdentifierKind, str], day: int, holder: Holder | None = None
) -> Sighting:
    kind, value = key
    fact = DocumentFact(
        kind=kind,
        value=value,
        role=role_of(kind),
        origins=frozenset({FactOrigin.PATTERN}),
        written=value,
        position=0,
        holder=holder,
    )
    return Sighting(DocumentId(new_id()), contact, date(2026, 10, day), fact)


def test_the_holders_and_the_recommendation_against_the_decisions() -> None:
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    utility.set_identifiers(
        [Identifier(*IBAN), Identifier(*CUSTOMER)],
        [Identifier(*VAT, IdentifierSource.REJECTED)],
    )
    bank.set_identifiers([], [Identifier(*PAYEE, IdentifierSource.REJECTED)])
    sightings = [
        # The utility's IBAN, its own twice: right, and recommended to confirm.
        seen(utility.id, IBAN, 1, SENDER),
        seen(utility.id, IBAN, 2, SENDER),
        # A payee among the bank's bookings, rejected there: right, and recommended to reject.
        seen(bank.id, PAYEE, 3, THIRD),
        # A VAT ID read before it had a holder, rejected: unread.
        seen(utility.id, VAT, 4),
        # A customer number of one document: no recommendation.
        seen(utility.id, CUSTOMER, 5),
    ]

    found = evaluate([utility, bank], sightings)

    assert found.kinds[IdentifierKind.IBAN] == Tally(right=2)
    assert found.kinds[IdentifierKind.VAT_ID] == Tally(unread=1)
    assert found.kinds[IdentifierKind.EMAIL_DOMAIN] == Tally()
    # IBAN twice right; the VAT ID, unread, has no holder to confirm by (none); the customer
    # number of one document neither.
    assert found.recommendation == Tally(right=2, unclear=2)
    assert found.recommendation.told == 2


def test_the_ways_wrong_are_kept_apart() -> None:
    utility = Contact.create(name="Stadtwerke", now=NOW)
    utility.set_identifiers([Identifier(*PAYEE)], [Identifier(*IBAN, IdentifierSource.REJECTED)])
    sightings = [
        seen(utility.id, IBAN, 1, SENDER),  # the rule's, rejected: training learns it
        seen(utility.id, IBAN, 2, SENDER),
        seen(utility.id, PAYEE, 3, THIRD),  # foreign, confirmed
    ]
    found = evaluate([utility], sightings)
    assert found.kinds[IdentifierKind.IBAN] == Tally(learned_rejected=1, refused_confirmed=1)
    assert found.recommendation == Tally(learned_rejected=1, refused_confirmed=1)
    # Behind each number its decisions, with the documents they were measured in, newest first.
    learned = [
        case
        for case in found.cases
        if case.measure is IdentifierKind.IBAN and case.outcome is HolderOutcome.LEARNED_REJECTED
    ]
    (case,) = learned
    assert (case.value, case.contact, case.confirmed) == (IBAN[1], utility.id, False)
    assert case.documents == (sightings[1].document, sightings[0].document)
    assert {case.measure for case in found.cases} == {IdentifierKind.IBAN, None}
    assert len(found.cases) == 4
