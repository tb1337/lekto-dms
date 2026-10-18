"""Bar codes, QR codes and other machine-readable symbols on a document's pages, and what is
read from their content.

The OCR's archive holds the pages as they are shown; a reader (`CodeReader`) finds each code
there with its format, the text it holds and where it stands (a box in fractions of the page,
as the places of quotes). Content in a known form is read further: a GiroCode, the EPC QR code
of a SEPA credit transfer (`BCD`), names payee, IBAN, BIC, amount and purpose. Identifiers in a
code count like identifiers in the text: the identifiers its text shows (`identifiers_in`) and
the IBAN of a GiroCode.

A code's content is someone else's: it is shown as text and never followed.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.fields import Money
from papiq.core.domain.identifiers import (
    IdentifierKind,
    identifiers_in,
    normalise_identifier,
)
from papiq.core.domain.json_value import JsonObject, JsonValue, as_int
from papiq.core.domain.locations import Box

CODES_VERSION = 1
"""The version of reading codes and of `codes.json`: a document read before reads again."""

_GIRO_AMOUNT = re.compile(r"EUR(\d{1,9}(?:\.\d{1,2})?)")


@dataclass(frozen=True, kw_only=True)
class Code:
    """A code on page `page` (from 1): its `format` as the reader names it (`QR Code`,
    `Code 128`, `Data Matrix`, ...), the `text` it holds, and its `box` on the page."""

    page: int
    format: str
    text: str
    box: Box

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError("pages are numbered from 1")

    def to_json(self) -> JsonObject:
        return {
            "page": self.page,
            "format": self.format,
            "text": self.text,
            "box": self.box.to_json(),
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> "Code":
        if not isinstance(data, dict):
            raise ValidationError(f"invalid code {data!r:.100}")
        page, format, text = as_int(data.get("page")), data.get("format"), data.get("text")
        if not (page is not None and isinstance(format, str) and isinstance(text, str)):
            raise ValidationError(f"invalid code {data!r:.100}")
        return cls(page=page, format=format, text=text, box=Box.from_json(data.get("box")))


@dataclass(frozen=True, kw_only=True)
class GiroCode:
    """A SEPA credit transfer as a GiroCode (EPC069-12) holds it; `iban` normalised."""

    name: str
    iban: str
    bic: str | None = None
    amount: Money | None = None
    purpose: str | None = None


def giro_code(text: str) -> GiroCode | None:
    """The credit transfer of a GiroCode, or None if `text` is none (or names no valid IBAN)."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    if len(lines) < 7 or lines[0] != "BCD" or lines[1] not in ("001", "002"):
        return None
    if lines[3] != "SCT" or not lines[5]:
        return None
    try:
        iban = normalise_identifier(IdentifierKind.IBAN, lines[6])
    except ValidationError:
        return None
    amount = None
    raw_amount = lines[7] if len(lines) > 7 else ""
    if match := _GIRO_AMOUNT.fullmatch(raw_amount):
        amount = Money(Decimal(match.group(1)), "EUR")
    reference = lines[9] if len(lines) > 9 else ""
    remittance = lines[10] if len(lines) > 10 else ""
    return GiroCode(
        name=lines[5],
        iban=iban,
        bic=lines[4] or None,
        amount=amount,
        purpose=remittance or reference or None,
    )


def code_identifiers(code: Code) -> set[tuple[IdentifierKind, str]]:
    """The identifiers a code shows: those its text shows, and a GiroCode's IBAN."""
    found = identifiers_in(code.text)
    giro = giro_code(code.text)
    if giro is not None:
        found.add((IdentifierKind.IBAN, giro.iban))
    return found


def codes_to_json(codes: Sequence[Code]) -> JsonObject:
    """The content of `codes.json`, the codes of a document's archive."""
    return {"version": CODES_VERSION, "codes": [code.to_json() for code in codes]}


def codes_from_json(data: JsonValue) -> tuple[Code, ...] | None:
    """The codes of a stored `codes.json`; None if it is of another version, to be read again.
    ValidationError if it is not one."""
    if not isinstance(data, dict) or not isinstance(data.get("codes"), list):
        raise ValidationError("invalid codes: no list of codes")
    if data.get("version") != CODES_VERSION:
        return None
    codes = data["codes"]
    assert isinstance(codes, list)
    return tuple(Code.from_json(item) for item in codes)
