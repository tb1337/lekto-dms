"""A document as a class lays it out: its pages and what Lekto should find in it (the entry of
the manifest), in the JSON forms of Lekto's API."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from synth.layout import Page
from synth.letter import Letter, Sender

type Json = str | int | float | bool | dict[str, "Json"] | list["Json"] | None


@dataclass(frozen=True)
class Fact:
    """An identifier the document shows: its kind (Lekto's `IdentifierKind`), its value as
    written, and its role (`FactRole`: contact, target, own, thread, refers, person)."""

    kind: str
    value: str
    role: str | None = None  # None: the kind's usual role (`role_of`)
    pattern: bool = True  # False: Lekto's patterns don't read it as written, only a model can


@dataclass
class Doc:
    cls: str
    document_type: str
    contact: str
    date: date | None
    title: str
    pages: list[Page]
    recipient: str = "max"
    language: str = "de"
    fields: dict[str, Json] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    layout: str = "letter"  # letter, printout, receipt, form, screen, ticket
    download: str = "Dokument.pdf"  # the name a portal or program gives the file
    url: str = ""  # the address a screen layout shows


def money(value: Decimal | str | float, currency: str = "EUR") -> dict[str, Json]:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return {"amount": str(amount), "currency": currency}


def doc(
    cls: str,
    document_type: str,
    sender: Sender | str,
    day: date | None,
    title: str,
    pages: list[Page] | Letter,
    *,
    facts: Sequence[tuple[str, ...]] = (),
    **rest: object,
) -> Doc:
    """A `Doc`; a letter is set on its pages, facts are (kind, value) or (kind, value, role)."""
    name = sender.name if isinstance(sender, Sender) else sender
    laid_out = pages.pages() if isinstance(pages, Letter) else pages
    return Doc(
        cls,
        document_type,
        name,
        day,
        title,
        laid_out,
        facts=[Fact(*fact) for fact in facts],
        **rest,  # type: ignore[arg-type]
    )
