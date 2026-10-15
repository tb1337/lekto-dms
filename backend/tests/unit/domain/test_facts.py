"""The facts of a text and of the codes on its pages, with where they stand in the text."""

from papiq.core.domain.codes import Code
from papiq.core.domain.facts import (
    FoundIdentifier,
    NamedContact,
    Span,
    facts_in,
    identifier_spans,
    name_spans,
)
from papiq.core.domain.identifiers import Identifier, IdentifierKind
from papiq.core.domain.locations import Box
from papiq.core.domain.master_data import Contact
from tests.builders import NOW

TEXT = """\
Stadtwerke   Müllheim-Süd GmbH
Kundennummer 2004-7718
service@stadtwerke-muellheim.example
IBAN DE89 3704 0044 0532 0130 00
Lastschrift von DE02120300000000202051
"""
GIRO = Code(
    page=1,
    format="QR Code",
    text="BCD\n002\n1\nSCT\n\nKasse Süd\nDE75512108001245126199\nEUR10.00\n\n\nBeitrag",
    box=Box(0.7, 0.8, 0.1, 0.1),
)


def spanned(text: str, spans: tuple[Span, ...]) -> list[str]:
    return [text[span.start : span.end] for span in spans]


def test_a_name_is_found_however_it_is_spaced_and_spelt() -> None:
    assert spanned(TEXT, name_spans(TEXT, "Stadtwerke Muellheim-Sued GmbH")) == [
        "Stadtwerke   Müllheim-Süd"
    ]
    assert name_spans(TEXT, "Stadtwerke Nord") == ()
    assert name_spans(TEXT, "GmbH") == ()  # nothing but a legal form


def test_an_identifier_is_found_as_it_is_written() -> None:
    iban = identifier_spans(TEXT, IdentifierKind.IBAN, "DE89370400440532013000")
    assert spanned(TEXT, iban) == ["DE89 3704 0044 0532 0130 00"]
    customer = identifier_spans(TEXT, IdentifierKind.CUSTOMER_NUMBER, "20047718")
    assert spanned(TEXT, customer) == ["2004-7718"]
    domain = identifier_spans(TEXT, IdentifierKind.EMAIL_DOMAIN, "stadtwerke-muellheim.example")
    assert spanned(TEXT, domain) == ["stadtwerke-muellheim.example"]
    # Not inside a longer value.
    assert identifier_spans("X20047718", IdentifierKind.CUSTOMER_NUMBER, "20047718") == ()
    # A personnel number is kept without its leading zeros and found with them.
    printout = "Personalnummer : 00012345   Seite 1"
    personnel = identifier_spans(printout, IdentifierKind.PERSONNEL_NUMBER, "12345")
    assert spanned(printout, personnel) == ["00012345"]
    assert identifier_spans("112345", IdentifierKind.PERSONNEL_NUMBER, "12345") == ()


def test_facts_of_text_and_codes_with_their_places() -> None:
    iban = Identifier.parse(IdentifierKind.IBAN, "DE89 3704 0044 0532 0130 00")
    rejected = Identifier.parse(IdentifierKind.IBAN, "DE02120300000000202051")
    utility = Contact.create(name="Stadtwerke Müllheim-Süd", now=NOW, identifiers=[iban])
    bank = Contact.create(name="Bank", now=NOW)
    bank.set_identifiers([], rejected=[rejected])
    club = Contact.create(name="Kasse Süd", now=NOW)
    facts = facts_in(TEXT, [utility, bank, club], [GIRO], places=True)
    assert facts.named == (
        NamedContact(
            contact_id=utility.id,
            name="Stadtwerke Müllheim-Süd",
            alias=False,
            in_text=True,
            in_code=False,
            spans=(Span(0, 25),),
        ),
        NamedContact(
            contact_id=club.id, name="Kasse Süd", alias=False, in_text=False, in_code=True
        ),
    )
    by_value = {item.value: item for item in facts.identifiers}
    assert by_value["DE89370400440532013000"] == FoundIdentifier(
        kind=IdentifierKind.IBAN,
        value="DE89370400440532013000",
        contact_id=utility.id,
        in_text=True,
        in_code=False,
        spans=(Span(TEXT.index("DE89"), TEXT.index("DE89") + 27),),
    )
    # The GiroCode's IBAN belongs to no contact; the rejected one is neither shown nor evidence.
    giro = by_value["DE75512108001245126199"]
    assert (giro.contact_id, giro.in_text, giro.in_code, giro.spans) == (None, False, True, ())
    assert "DE02120300000000202051" not in by_value
    # Those of contacts first.
    assert facts.identifiers[0].contact_id == utility.id
    # Without places, no spans.
    assert all(item.spans == () for item in facts_in(TEXT, [utility], [GIRO]).identifiers)
