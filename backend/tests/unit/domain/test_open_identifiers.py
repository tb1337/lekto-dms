"""The open identifiers: learned at a contact, or standing in confirmed documents at no contact."""

from datetime import date

from lekto.core.domain.document_facts import (
    DocumentFact,
    FactOrigin,
    Holder,
    HolderKind,
    HolderSource,
    role_of,
)
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.ids import ContactId, DocumentId, UserId, new_id
from lekto.core.domain.master_data import Contact
from lekto.core.domain.open_identifiers import (
    OpenSource,
    Sighting,
    excerpt,
    open_identifiers,
)
from lekto.core.domain.profiles import Person
from tests.builders import NOW

IBAN = (IdentifierKind.IBAN, "DE02120300000000202051")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
CUSTOMER = (IdentifierKind.CUSTOMER_NUMBER, "20047718")
CONTRACT = (IdentifierKind.CONTRACT_NUMBER, "20047718")
INVOICE = (IdentifierKind.INVOICE_NUMBER, "R-4711")


def fact(
    key: tuple[IdentifierKind, str], written: str | None = None, holder: Holder | None = None
) -> DocumentFact:
    kind, value = key
    return DocumentFact(
        kind=kind,
        value=value,
        role=role_of(kind),
        origins=frozenset({FactOrigin.PATTERN}),
        written=written,
        position=0,
        holder=holder,
    )


def seen(
    contact: ContactId,
    key: tuple[IdentifierKind, str],
    day: int,
    written: str | None = None,
    holder: Holder | None = None,
    owner: UserId | None = None,
) -> Sighting:
    return Sighting(
        DocumentId(new_id()), contact, date(2026, 10, day), fact(key, written, holder), owner
    )


def test_a_learned_one_is_open_with_the_documents_that_show_it() -> None:
    utility = Contact.create(name="Stadtwerke", now=NOW)
    utility.set_learned([Identifier(*CUSTOMER, IdentifierSource.LEARNED)])
    sightings = [seen(utility.id, CUSTOMER, 1), seen(utility.id, CONTRACT, 9, "2004 7718")]
    (item,) = open_identifiers([utility], sightings)
    # A customer number stands for the contract number of its value.
    assert (item.key, item.source, item.contacts) == (CUSTOMER, OpenSource.LEARNED, (utility.id,))
    assert [each.dated.day for each in item.seen] == [9, 1]
    assert (item.written, item.last) == ("2004 7718", date(2026, 10, 9))


def test_an_unknown_one_is_open_with_the_contacts_of_its_documents() -> None:
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    sightings = [
        seen(bank.id, VAT, 3),
        seen(utility.id, VAT, 4),
        seen(utility.id, VAT, 5),
        seen(utility.id, INVOICE, 5),  # not a contact's kind
    ]
    (item,) = open_identifiers([utility, bank], sightings)
    assert (item.key, item.source) == (VAT, OpenSource.UNKNOWN)
    assert item.contacts == (utility.id, bank.id)  # most documents first
    assert (len(item.seen), item.written) == (3, VAT[1])


def test_an_iban_is_open_only_where_it_is_its_contact_s() -> None:
    """The bank's statements name the utility as the payee of an IBAN: it is open at the
    utility, with its own bill only; one a person holds anywhere is not open."""
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    payee = Holder(HolderKind.SENDER, HolderSource.RULE, "Stadtwerke")
    sightings = [
        seen(bank.id, IBAN, 3, holder=payee),
        seen(bank.id, IBAN, 4, holder=Holder(HolderKind.THIRD_PARTY, HolderSource.RULE)),
        seen(utility.id, IBAN, 5, holder=payee),
    ]
    (item,) = open_identifiers([utility, bank], sightings)
    assert (item.contacts, len(item.seen)) == ((utility.id,), 1)
    mine = seen(utility.id, IBAN, 6, holder=Holder(HolderKind.RECIPIENT, HolderSource.RULE))
    assert open_identifiers([utility, bank], [*sightings, mine]) == []
    # Only in the bank's bookings: no unknown one, but a suggestion for the utility.
    only_payee = [seen(bank.id, IBAN, 3, holder=payee)]
    (item,) = open_identifiers([utility, bank], only_payee)
    assert (item.source, item.contacts) == (OpenSource.SUGGESTED, (utility.id,))


def test_a_contact_s_iban_in_another_s_bookings_is_suggested_for_it() -> None:
    """The bank's statements name the landlord as the payee: suggested for the landlord, the
    contact the name names; a name of two contacts or of none suggests nothing."""
    landlord, bank = (Contact.create(name=name, now=NOW) for name in ("Hausverwaltung Ost", "Bank"))
    payee = Holder(HolderKind.THIRD_PARTY, HolderSource.RULE, "Hausverwaltung Ost")
    (item,) = open_identifiers(
        [landlord, bank],
        [seen(bank.id, IBAN, 3, holder=payee), seen(bank.id, IBAN, 4, holder=payee)],
    )
    assert (item.source, item.contacts, item.person, len(item.seen)) == (
        OpenSource.SUGGESTED,
        (landlord.id,),
        None,
        2,
    )
    other = Holder(HolderKind.THIRD_PARTY, HolderSource.RULE, "Hausmeisterdienst Weber")
    assert open_identifiers([landlord, bank], [seen(bank.id, IBAN, 3, holder=other)]) == []
    rejected = Contact.create(name="Hausverwaltung Ost", now=NOW)
    rejected.set_identifiers([], rejected=[Identifier(*IBAN)])
    assert open_identifiers([rejected, bank], [seen(bank.id, IBAN, 3, holder=payee)]) == []


def test_a_recipient_s_iban_is_suggested_for_their_profile() -> None:
    """Named, for the person it names; unnamed, for the user whose personal space holds the
    document; not one they declined, nor where the documents point to two people."""
    bank = Contact.create(name="Bank", now=NOW)
    max_, lisa = UserId(new_id()), UserId(new_id())
    persons = [Person(max_, "Max Nord"), Person(lisa, "Lisa Nord", aliases=("Lisa Süd",))]
    named = Holder(HolderKind.RECIPIENT, HolderSource.RULE, "Max Nord")
    (item,) = open_identifiers([bank], [seen(bank.id, IBAN, 3, holder=named)], persons=persons)
    assert (item.source, item.contacts, item.person) == (OpenSource.SUGGESTED, (), max_)
    yours = Holder(HolderKind.RECIPIENT, HolderSource.RULE)
    (item,) = open_identifiers(
        [bank], [seen(bank.id, IBAN, 3, holder=yours, owner=lisa)], persons=persons
    )
    assert item.person == lisa
    both = [seen(bank.id, IBAN, 3, holder=named), seen(bank.id, IBAN, 4, holder=yours, owner=lisa)]
    assert open_identifiers([bank], both, persons=persons) == []
    assert (
        open_identifiers(
            [bank], [seen(bank.id, IBAN, 3, holder=named)], persons=persons, declined={max_: [IBAN]}
        )
        == []
    )
    # In a profile already: nothing to suggest.
    assert open_identifiers([bank], [seen(bank.id, IBAN, 3, holder=named)], [IBAN], persons) == []


def test_what_a_contact_or_a_person_has_is_not_open() -> None:
    utility = Contact.create(
        name="Stadtwerke",
        now=NOW,
        identifiers=[Identifier(*VAT), Identifier(IdentifierKind.EMAIL_DOMAIN, "nord.example")],
    )
    utility.set_identifiers(
        [Identifier(*VAT), Identifier(IdentifierKind.EMAIL_DOMAIN, "nord.example")],
        rejected=[Identifier(*CUSTOMER)],
    )
    sightings = [
        seen(utility.id, VAT, 1),
        seen(utility.id, CONTRACT, 1),  # the rejected customer number's value
        seen(utility.id, (IdentifierKind.EMAIL_DOMAIN, "post.nord.example"), 1),  # subdomain
        seen(utility.id, IBAN, 1),  # the person's
        seen(utility.id, (IdentifierKind.EMAIL_DOMAIN, "gmail.com"), 1),
    ]
    assert open_identifiers([utility], sightings, personal=[IBAN]) == []


def test_the_most_documents_come_first_then_the_newest() -> None:
    utility = Contact.create(name="Stadtwerke", now=NOW)
    sightings = [
        seen(utility.id, VAT, 1),
        seen(utility.id, IBAN, 2),
        seen(utility.id, CUSTOMER, 3),
        seen(utility.id, CUSTOMER, 4),
    ]
    assert [item.key for item in open_identifiers([utility], sightings)] == [CUSTOMER, IBAN, VAT]


def test_an_excerpt_shows_the_text_around_on_one_line() -> None:
    text = "Rechnung\n\nBitte überweise an\nIBAN DE02 1203 0000 0000 2020 51 bis Monatsende."
    start = text.index("DE02")
    cut = excerpt(text, start, len("DE02 1203 0000 0000 2020 51"))
    assert cut.before == "Rechnung Bitte überweise an IBAN "
    assert cut.match == "DE02 1203 0000 0000 2020 51"
    assert cut.after == " bis Monatsende."
    long = "Wort " * 60 + "DE312456789" + " Wort" * 60
    short = excerpt(long, long.index("DE3"), 11, reach=20)
    assert short.before.startswith("…") and short.after.endswith("…")
    assert short.match == "DE312456789"
    assert len(short.before) <= 21 and len(short.after) <= 21
