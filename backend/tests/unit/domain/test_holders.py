"""Whose an IBAN, a creditor ID or a VAT ID is where it stands, and whose an e-mail domain is by
its name (`domain.holders`), on invented documents."""

from dataclasses import replace

import pytest

from lekto.core.domain.document_facts import (
    Holder,
    HolderKind,
    HolderSource,
    found_facts,
)
from lekto.core.domain.holders import (
    FOOT,
    Parties,
    Party,
    Place,
    ReadHolder,
    checked_holder,
    domain_holder,
    domain_owner,
    foreign,
    held_by,
    holder_at,
    holders,
    merged_holder,
    unlearned,
)
from lekto.core.domain.identifiers import IdentifierKind, Key, identifiers_in
from lekto.core.domain.reasons import Reason, ReasonCode

IBAN, CREDITOR = IdentifierKind.IBAN, IdentifierKind.CREDITOR_ID
OWN = "DE02120300000000202051"  # Max Nord's
UTILITY = "DE89370400440532013000"  # Stadtwerke Musterstadt
LANDLORD = "DE17100500000123456789"  # Hausverwaltung Ost
CARETAKER = "DE65120300001111222233"  # Hausmeisterdienst Weber, unknown to Lekto
EMPLOYER = "DE13430609671234567890"  # Nordwerk
SAVINGS = "DE44500105175407324931"  # a fund, unknown to Lekto
LONDON = "GB29NWBK60161331926819"
UTILITY_CI = "DE98ZZZ09999999999"

PARTIES = Parties(
    person_names=["Max Nord", "Max", "mnord"],
    person_numbers=[(IBAN, OWN)],
    contact_names=["Stadtwerke Musterstadt GmbH", "Hausverwaltung Ost", "Nordwerk AG", "Acme Ltd"],
)


def holders_of(
    text: str, *, foot: frozenset[str] = frozenset(), parties: Parties = PARTIES
) -> dict[Key, Holder]:
    """The holders in `text`; the numbers whose value is in `foot` stand at the foot of the
    page."""
    facts = found_facts(text, identifiers_in(text))

    def top(start: int, end: int) -> float:
        written = text[start:end].replace(" ", "")
        return 0.95 if written in foot else 0.3

    return holders(text, facts, parties, tops=top)


def kinds(found: dict[Key, Holder]) -> dict[str, tuple[HolderKind, str | None]]:
    return {value: (holder.kind, holder.name) for (_, value), holder in found.items()}


def spaced(value: str) -> str:
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))


def test_a_statement_with_its_payees_in_the_lines_of_bookings() -> None:
    text = f"""Kontoauszug 10/2026
Kontoinhaber: Max Nord   IBAN {spaced(OWN)}

Buchungstag   Vorgang                                  Betrag
02.10.2026    Lastschrift   Stadtwerke Musterstadt   {spaced(UTILITY)}   -45,00 EUR
05.10.2026    Dauerauftrag   Hausverwaltung Ost   {spaced(LANDLORD)}   -720,00 EUR
07.10.2026    Gutschrift   Hausmeisterdienst Weber   {spaced(CARETAKER)}   12,50 EUR
"""
    assert kinds(holders_of(text)) == {
        OWN: (HolderKind.RECIPIENT, None),
        # A name in a booking, known or not: another party's.
        UTILITY: (HolderKind.THIRD_PARTY, "Stadtwerke Musterstadt"),
        LANDLORD: (HolderKind.THIRD_PARTY, "Hausverwaltung Ost"),
        CARETAKER: (HolderKind.THIRD_PARTY, "Hausmeisterdienst Weber"),
    }


def test_a_statement_with_the_payee_above_the_number() -> None:
    text = f"""Datum        Buchungstext                       Betrag
03.10.2026   Hausmeisterdienst Weber            -80,00 EUR
             {spaced(CARETAKER)}
04.10.2026   Sparfonds Union                    -50,00 EUR
             {spaced(SAVINGS)}
"""
    found = kinds(holders_of(text))
    assert found[CARETAKER] == (HolderKind.THIRD_PARTY, "Hausmeisterdienst Weber")
    assert found[SAVINGS] == (HolderKind.THIRD_PARTY, "Sparfonds Union")


def test_an_invoice_with_its_bank_details_at_the_foot() -> None:
    text = f"""Stadtwerke Musterstadt GmbH
Rechnung Nr. 2026-0042

Bitte zahlen Sie bis zum 15.11.2026.

Sparkasse Musterstadt   IBAN {spaced(UTILITY)}   BIC SPMUDE33
Gläubiger-ID {UTILITY_CI}
"""
    found = kinds(holders_of(text, foot=frozenset({UTILITY, UTILITY_CI})))
    assert found == {
        UTILITY: (HolderKind.SENDER, None),
        UTILITY_CI: (HolderKind.SENDER, None),
    }


def test_bank_details_tell_the_sender_on_their_line() -> None:
    text = f"Unsere Bankverbindung: IBAN {spaced(UTILITY)}\n"
    assert kinds(holders_of(text)) == {UTILITY: (HolderKind.SENDER, None)}


def test_a_pay_slip_pays_the_person() -> None:
    text = f"""Nordwerk AG   Entgeltabrechnung Oktober 2026
Auszahlung
Max Nord   {spaced("DE44500105175407324931")}   2.345,67 EUR
"""
    # A number of no profile, but the person's name beside it.
    found = kinds(holders_of(text))
    assert found["DE44500105175407324931"] == (HolderKind.RECIPIENT, "Max Nord")


def test_an_operating_cost_statement_with_an_enclosed_bill() -> None:
    text = f"""Hausverwaltung Ost
Nebenkostenabrechnung 2025

Bitte überweisen Sie den Betrag auf unser Konto {spaced(LANDLORD)}.

Anlage: Rechnung Hausmeisterdienst
Hausmeisterdienst Weber
{spaced(CARETAKER)}
"""
    found = kinds(holders_of(text))
    assert found[LANDLORD] == (HolderKind.SENDER, None)
    # Neither booking nor list: an unknown name tells nothing, nor do the lines above.
    assert found[CARETAKER] == (HolderKind.UNCLEAR, None)


def test_an_english_letter() -> None:
    text = f"""Acme Ltd, 1 Long Road, London

Please pay the amount within 14 days.
Our bank details: IBAN {spaced(LONDON)}

Your account {spaced(OWN)} will not be debited.

Payee
{spaced(UTILITY)}
"""
    found = kinds(holders_of(text, parties=Parties(contact_names=["Acme Ltd"])))
    assert found == {
        LONDON: (HolderKind.SENDER, None),
        OWN: (HolderKind.RECIPIENT, None),
        UTILITY: (HolderKind.THIRD_PARTY, None),  # where money goes: not the sender
    }


def test_a_person_s_own_number_is_theirs_wherever_it_stands() -> None:
    text = f"Unsere Bankverbindung: IBAN {spaced(OWN)}\n"
    assert kinds(holders_of(text)) == {OWN: (HolderKind.RECIPIENT, None)}


def test_a_list_of_numbers_holds_other_parties() -> None:
    values = [OWN, UTILITY, LANDLORD, CARETAKER, EMPLOYER, SAVINGS]
    text = "\n".join(spaced(value) for value in values) + "\n"
    found = kinds(holders_of(text, parties=Parties()))
    assert set(found.values()) == {(HolderKind.THIRD_PARTY, None)}


def test_a_girocode_names_its_payee() -> None:
    facts = found_facts("", (), [(IBAN, UTILITY)])  # only in the code
    found = holders("", facts, PARTIES, codes={(IBAN, UTILITY): "Stadtwerke Musterstadt"})
    assert found == {
        (IBAN, UTILITY): Holder(HolderKind.SENDER, HolderSource.RULE, "Stadtwerke Musterstadt")
    }


def test_places_that_disagree() -> None:
    sender = f"Unsere Bankverbindung: {spaced(UTILITY)}\n"
    payee = f"Empfänger\n{spaced(UTILITY)}\n"
    assert kinds(holders_of(sender + payee))[UTILITY] == (HolderKind.UNCLEAR, None)
    person = f"Max Nord   {spaced(UTILITY)}\n"
    assert kinds(holders_of(sender + person))[UTILITY] == (HolderKind.RECIPIENT, "Max Nord")


def test_a_number_glued_to_a_word_is_none_of_its_own() -> None:
    place = Place(f"Ref{UTILITY}X", 3, UTILITY)
    assert holder_at(place, PARTIES).kind is HolderKind.UNCLEAR


def test_the_foot_of_a_page_tells_the_sender() -> None:
    line = f"Musterstadt   {spaced(UTILITY)}"
    at = line.index("DE")
    assert holder_at(Place(line, at, spaced(UTILITY), top=FOOT + 0.05), Parties()).kind is (
        HolderKind.SENDER
    )
    assert holder_at(Place(line, at, spaced(UTILITY), top=0.4), Parties()).kind is (
        HolderKind.UNCLEAR
    )


def test_names_of_persons_and_contacts() -> None:
    parties = Parties(person_names=["Max", "Max Nord"], contact_names=["Stadtwerke Musterstadt"])
    assert parties.person("Herrn Max Nord")
    assert not parties.person("Max Mustermann")  # a lone first name names no one
    assert parties.contact("Stadtwerke Musterstadt GmbH")
    assert parties.contact("Stadtwerke Musterstsdt")  # a letter off in a long word (OCR)
    assert not parties.contact("Stadtwerke Nordstadt")


def test_a_named_sender_is_the_contact_only_by_its_names() -> None:
    utility = ["Stadtwerke Musterstadt GmbH", "SWM"]
    named = Holder(HolderKind.SENDER, HolderSource.RULE, "Stadtwerke Musterstadt")
    assert held_by(named, utility) is HolderKind.SENDER
    # The bank's statement names the utility as the payee: not the bank's.
    assert held_by(named, ["Beispielbank"]) is HolderKind.THIRD_PARTY
    assert foreign(named, ["Beispielbank"])
    assert held_by(Holder(HolderKind.SENDER, HolderSource.RULE), ["Beispielbank"]) is (
        HolderKind.SENDER
    )
    assert foreign(Holder(HolderKind.RECIPIENT, HolderSource.RULE), utility)
    assert not foreign(Holder(HolderKind.UNCLEAR, HolderSource.RULE), utility)
    assert held_by(None, utility) is None and not foreign(None, utility)  # read before 0.8


def test_a_known_name_outside_a_booking_is_the_sender_s() -> None:
    text = f"Stadtwerke Musterstadt GmbH   IBAN {spaced(UTILITY)}\n"
    assert kinds(holders_of(text)) == {UTILITY: (HolderKind.SENDER, "Stadtwerke Musterstadt GmbH")}


# --- the holders the language model tells (`facts-2`) -----------------------------------------

STATEMENT = f"""Beispielbank   Kontoauszug 10/2026
02.10.2026   Lastschrift   Stadtwerke Musterstadt   {spaced(UTILITY)}   -45,00 EUR
"""
LISTED = [(IBAN, UTILITY)]


def told(**changes: str | None) -> ReadHolder:
    given: dict[str, str | None] = {
        "kind": "iban",
        "value": spaced(UTILITY),
        "holder": "third_party",
        "name": "Stadtwerke Musterstadt",
        "evidence": f"Lastschrift   Stadtwerke Musterstadt   {spaced(UTILITY)}",
    }
    given.update(changes)
    return ReadHolder(**given)  # type: ignore[arg-type]


def test_a_holder_the_model_tells_is_checked() -> None:
    assert checked_holder(STATEMENT, told(), LISTED) == (
        (IBAN, UTILITY),
        Holder(HolderKind.THIRD_PARTY, HolderSource.MODEL, "Stadtwerke Musterstadt"),
    )
    assert checked_holder(STATEMENT, told(name=None), LISTED) == (
        (IBAN, UTILITY),
        Holder(HolderKind.THIRD_PARTY, HolderSource.MODEL),
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"value": LONDON}, ReasonCode.HOLDER_NOT_LISTED),  # not asked about
        ({"kind": "vat_id"}, ReasonCode.HOLDER_NOT_LISTED),
        ({"holder": "owner"}, ReasonCode.HOLDER_KIND_UNKNOWN),
        ({"evidence": None}, ReasonCode.QUOTE_MISSING),
        ({"evidence": "Überweisung an Stadtwerke"}, ReasonCode.QUOTE_NOT_IN_TEXT),
        ({"evidence": "Kontoauszug 10/2026"}, ReasonCode.QUOTE_WITHOUT_VALUE),
        ({"name": "Hausverwaltung Ost"}, ReasonCode.HOLDER_NAME_NOT_NEAR),  # invented
    ],
)
def test_a_holder_the_model_tells_that_does_not_pass(
    changes: dict[str, str | None], code: ReasonCode
) -> None:
    refused = checked_holder(STATEMENT, told(**changes), LISTED)
    assert isinstance(refused, Reason) and refused.code is code


def test_rule_and_model_together() -> None:
    def holder(kind: HolderKind, source: HolderSource = HolderSource.RULE) -> Holder:
        return Holder(kind, source)

    model = holder(HolderKind.THIRD_PARTY, HolderSource.MODEL)
    assert merged_holder(holder(HolderKind.RECIPIENT), None) == holder(HolderKind.RECIPIENT)
    assert merged_holder(None, model) == model
    assert merged_holder(holder(HolderKind.UNCLEAR), model) == model
    # The model cannot tell: the rule's stands.
    unclear = holder(HolderKind.UNCLEAR, HolderSource.MODEL)
    assert merged_holder(holder(HolderKind.RECIPIENT), unclear) == holder(HolderKind.RECIPIENT)
    assert merged_holder(None, unclear) == unclear
    assert merged_holder(holder(HolderKind.RECIPIENT), model) == model  # not about the sender
    # One says the sender's, the other another's: unclear.
    assert merged_holder(holder(HolderKind.SENDER), model) == holder(
        HolderKind.UNCLEAR, HolderSource.MODEL
    )
    sender = holder(HolderKind.SENDER, HolderSource.MODEL)
    assert merged_holder(holder(HolderKind.THIRD_PARTY), sender) == holder(
        HolderKind.UNCLEAR, HolderSource.MODEL
    )
    # What the model told before is no rule's.
    assert merged_holder(sender, model) == model


# --- VAT IDs (Tobi, 29.10.2026) ---------------------------------------------------------------

OURS_VAT, YOURS_VAT, PARENT_VAT = "DE123456789", "DE811569869", "DE136695976"


def test_a_vat_id_s_label_tells_whose_it_is() -> None:
    text = f"""Rechnung 4711
Ihre USt-IdNr.: {YOURS_VAT}
Leistung                                   120,00 EUR
Unsere USt-IdNr.: {OURS_VAT}
"""
    assert kinds(holders_of(text)) == {
        YOURS_VAT: (HolderKind.RECIPIENT, None),
        OURS_VAT: (HolderKind.SENDER, None),
    }


def test_a_vat_id_beside_a_name_is_that_contact_s() -> None:
    text = f"""Rechnung 4711
Leistung                                   120,00 EUR

Stadtwerke Musterstadt GmbH · USt-IdNr. {OURS_VAT}
Nordwerk AG · USt-IdNr. {PARENT_VAT}
"""
    found = kinds(holders_of(text))
    assert found[OURS_VAT] == (HolderKind.SENDER, "Stadtwerke Musterstadt GmbH ·")
    assert found[PARENT_VAT][0] is HolderKind.SENDER
    # To the document's contact, the other company's is a third party's.
    held = holders_of(text)[(IdentifierKind.VAT_ID, PARENT_VAT)]
    assert held_by(held, ["Stadtwerke Musterstadt GmbH"]) is HolderKind.THIRD_PARTY


def test_a_vat_id_alone_is_the_sender_s_two_unlabelled_are_unclear() -> None:
    alone = f"Rechnung 4711\nLeistung   120,00 EUR\nUSt-IdNr. {OURS_VAT}\n"
    assert kinds(holders_of(alone)) == {OURS_VAT: (HolderKind.SENDER, None)}
    two = f"Rechnung\nUSt-IdNr. {OURS_VAT}\nUSt-IdNr. {PARENT_VAT}\n"
    assert {kind for kind, _ in kinds(holders_of(two)).values()} == {HolderKind.UNCLEAR}
    # The label of the line above with its own number is not this one's.
    under = (
        f"Rechnung\nUnsere USt-IdNr. {OURS_VAT}\n"
        f"Eine Gesellschaft der Holding SE · USt-IdNr. {PARENT_VAT}\n"
    )
    assert kinds(holders_of(under)) == {
        OURS_VAT: (HolderKind.SENDER, None),
        PARENT_VAT: (HolderKind.UNCLEAR, None),
    }
    # At the foot of the page, as an IBAN there: the sender's.
    assert kinds(holders_of(two, foot=frozenset({OURS_VAT})))[OURS_VAT][0] is HolderKind.SENDER


# --- e-mail domains: by the name ----------------------------------------------------------------

UTILITY_PARTY = Party(
    "Stadtwerke Musterstadt GmbH", ("Stadtwerke Musterstadt GmbH", "SWM"), frozenset({"swm.de"})
)
DOMAIN_PARTIES = Parties(
    person_names=["Max Nord"],
    person_numbers=[(IdentifierKind.EMAIL_ADDRESS, "max@nord-familie.de")],
    contact_names=["Stadtwerke Musterstadt GmbH", "Hausverwaltung Ost"],
    contacts=[
        UTILITY_PARTY,
        Party("Hausverwaltung Ost", ("Hausverwaltung Ost",)),
        Party("Stadtwerke Süd", ("Stadtwerke Süd",)),
    ],
)


@pytest.mark.parametrize(
    ("domain", "owner"),
    [
        ("stadtwerke-musterstadt.de", "Stadtwerke Musterstadt GmbH"),  # most letters
        ("www.hausverwaltung-ost.de", "Hausverwaltung Ost"),
        ("swm.de", "Stadtwerke Musterstadt GmbH"),  # a person gave it
        ("stadtwerke-sued.de", "Stadtwerke Süd"),  # umlauts folded as in the names
        ("stadtwerke.de", None),  # two contacts as much: not to tell
        ("paypal.com", None),
    ],
)
def test_a_domain_is_the_contact_s_whose_name_it_carries(domain: str, owner: str | None) -> None:
    assert domain_owner(domain, DOMAIN_PARTIES.contacts) == owner


def test_whose_a_domain_is() -> None:
    def holder(domain: str, text: str = "") -> tuple[HolderKind, str | None]:
        found = domain_holder(domain, text, DOMAIN_PARTIES)
        assert found.source is HolderSource.RULE
        return found.kind, found.name

    assert holder("stadtwerke-musterstadt.de") == (HolderKind.SENDER, "Stadtwerke Musterstadt GmbH")
    assert holder("gmx.de") == (HolderKind.UNCLEAR, None)  # a free mail domain: no one's
    assert holder("nord-familie.de") == (HolderKind.RECIPIENT, None)  # of a person's address
    assert holder("nordmail.de", "Ihre Adresse: max.nord@nordmail.de") == (
        HolderKind.RECIPIENT,
        None,
    )
    assert holder("paypal.com", "Zahlung über info@paypal.com") == (HolderKind.UNCLEAR, None)
    # Another contact's domain on the utility's letter is a third party's.
    held = domain_holder("hausverwaltung-ost.de", "", DOMAIN_PARTIES)
    assert held_by(held, ["Stadtwerke Musterstadt GmbH"]) is HolderKind.THIRD_PARTY


def test_an_unclear_domain_is_not_learned_an_unclear_iban_is() -> None:
    unclear = Holder(HolderKind.UNCLEAR, HolderSource.RULE)
    names = ["Stadtwerke Musterstadt GmbH"]
    text = f"Zahlung über info@paypal.com auf {spaced(UTILITY)}"
    facts = {fact.kind: fact for fact in found_facts(text, identifiers_in(text))}
    domain, iban = facts[IdentifierKind.EMAIL_DOMAIN], facts[IBAN]
    assert unlearned(replace(domain, holder=unclear), names)
    assert not unlearned(replace(iban, holder=unclear), names)
    # Read before 0.8, without a holder: learned as before.
    assert not unlearned(domain, names)
