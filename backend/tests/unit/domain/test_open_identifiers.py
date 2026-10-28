"""The open identifiers: learned at a contact, or standing in confirmed documents at no contact."""

from dataclasses import replace
from datetime import date

from lekto.core.domain.document_facts import (
    DocumentFact,
    FactOrigin,
    FactRole,
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
    Recommendation,
    Sighting,
    excerpt,
    open_identifiers,
)
from lekto.core.domain.profiles import Person
from lekto.core.domain.reasons import ReasonCode
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


def test_a_recipient_s_domain_or_vat_id_is_suggested_for_no_profile() -> None:
    """A person has no e-mail domain or VAT ID among their numbers: nothing to suggest."""
    bank = Contact.create(name="Bank", now=NOW)
    max_ = UserId(new_id())
    named = Holder(HolderKind.RECIPIENT, HolderSource.RULE, "Max Nord")
    domain = (IdentifierKind.EMAIL_DOMAIN, "nord-familie.example")
    sightings = [seen(bank.id, domain, 3, holder=named), seen(bank.id, VAT, 4, holder=named)]
    assert open_identifiers([bank], sightings, persons=[Person(max_, "Max Nord")]) == []


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


# --- recommendations (Tobi, 28.10.2026) ---------------------------------------------------------

SENDER = Holder(HolderKind.SENDER, HolderSource.RULE)
THIRD = Holder(HolderKind.THIRD_PARTY, HolderSource.RULE)


def advice(item: object) -> tuple[Recommendation, ReasonCode] | None:
    recommended = item.recommended  # type: ignore[attr-defined]
    return None if recommended is None else (recommended.action, recommended.reason.code)


def test_one_in_two_documents_of_its_contact_alone_is_recommended_to_confirm() -> None:
    utility = Contact.create(name="Stadtwerke", now=NOW)
    utility.set_learned([Identifier(*CUSTOMER, IdentifierSource.LEARNED)])
    (one,) = open_identifiers([utility], [seen(utility.id, CUSTOMER, 1)])
    assert advice(one) is None  # one document tells too little
    (two,) = open_identifiers(
        [utility], [seen(utility.id, CUSTOMER, 1), seen(utility.id, CUSTOMER, 2)]
    )
    assert advice(two) == (Recommendation.CONFIRM, ReasonCode.RECOMMEND_CONFIRM)
    assert two.recommended is not None and two.recommended.reason.params == {
        "count": 2,
        "name": "Stadtwerke",
    }


def test_a_number_of_a_kind_with_a_holder_needs_its_contact_s_each_time() -> None:
    utility = Contact.create(name="Stadtwerke", now=NOW)
    unread = [seen(utility.id, IBAN, 1), seen(utility.id, IBAN, 2)]  # read before holders
    assert advice(open_identifiers([utility], unread)[0]) is None
    own = [seen(utility.id, IBAN, 1, holder=SENDER), seen(utility.id, IBAN, 2, holder=SENDER)]
    assert advice(open_identifiers([utility], own)[0]) == (
        Recommendation.CONFIRM,
        ReasonCode.RECOMMEND_CONFIRM,
    )


def test_a_learned_one_someone_else_holds_is_recommended_to_reject() -> None:
    bank = Contact.create(name="Bank", now=NOW)
    bank.set_learned([Identifier(*IBAN, IdentifierSource.LEARNED)])
    payees = [seen(bank.id, IBAN, day, holder=THIRD) for day in (1, 2, 3)]
    (item,) = open_identifiers([bank], payees)
    assert advice(item) == (Recommendation.REJECT, ReasonCode.RECOMMEND_REJECT_FOREIGN)
    assert item.recommended is not None and item.recommended.reason.params["count"] == 3


def test_one_other_contacts_hold_as_theirs_is_recommended_to_reject() -> None:
    shop, other = (Contact.create(name=name, now=NOW) for name in ("Versandhaus", "Portal"))
    shop.set_learned([Identifier(*VAT, IdentifierSource.LEARNED)])
    sightings = [
        seen(shop.id, VAT, 1, holder=SENDER),
        seen(shop.id, VAT, 2, holder=SENDER),
        seen(other.id, VAT, 3, holder=SENDER),
    ]
    (item,) = open_identifiers([shop, other], sightings)
    assert advice(item) == (Recommendation.REJECT, ReasonCode.RECOMMEND_REJECT_CONTACTS)


def test_a_payee_on_another_s_statement_does_not_count_against_it() -> None:
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    utility.set_learned([Identifier(*IBAN, IdentifierSource.LEARNED)])
    sightings = [
        seen(utility.id, IBAN, 1, holder=SENDER),
        seen(utility.id, IBAN, 2, holder=SENDER),
        seen(bank.id, IBAN, 3, holder=THIRD),  # a booking on the bank's statement
    ]
    (item,) = open_identifiers([utility, bank], sightings)
    assert advice(item) == (Recommendation.CONFIRM, ReasonCode.RECOMMEND_CONFIRM)


def test_no_recommendation_for_a_reference_or_one_of_several_contacts() -> None:
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    referred = [
        seen(utility.id, CUSTOMER, 1),
        Sighting(
            DocumentId(new_id()),
            utility.id,
            date(2026, 10, 2),
            replace(fact(CUSTOMER), role=FactRole.REFERS),
        ),
    ]
    assert advice(open_identifiers([utility], referred)[0]) is None
    shared = [
        seen(utility.id, CUSTOMER, 1),
        seen(utility.id, CUSTOMER, 2),
        seen(bank.id, CUSTOMER, 3),
    ]
    (unknown,) = open_identifiers([utility, bank], shared)
    assert (unknown.source, advice(unknown)) == (OpenSource.UNKNOWN, None)


def test_a_suggestion_two_documents_name_is_recommended() -> None:
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    payee = Holder(HolderKind.SENDER, HolderSource.RULE, "Stadtwerke")
    (item,) = open_identifiers([utility, bank], [seen(bank.id, IBAN, 3, holder=payee)])
    assert (item.source, advice(item)) == (OpenSource.SUGGESTED, None)
    twice = [seen(bank.id, IBAN, 3, holder=payee), seen(bank.id, IBAN, 4, holder=payee)]
    (item,) = open_identifiers([utility, bank], twice)
    assert advice(item) == (Recommendation.CONFIRM, ReasonCode.RECOMMEND_CONFIRM_NAMED)
