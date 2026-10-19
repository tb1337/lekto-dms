"""Codes on the pages: a GiroCode read as a credit transfer, identifiers in codes, codes.json."""

from decimal import Decimal

import pytest

from lekto.core.domain.codes import (
    CODES_VERSION,
    Code,
    GiroCode,
    code_identifiers,
    codes_from_json,
    codes_to_json,
    giro_code,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import Money
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.locations import Box

GIRO = "\n".join(
    [
        "BCD",
        "002",
        "1",
        "SCT",
        "MUSTDEM1XXX",
        "Stadtwerke Musterstadt GmbH",
        "DE89 3704 0044 0532 0130 00",
        "EUR84.2",
        "",
        "",
        "Abschlag 03/2026",
    ]
)


def code(text: str, format: str = "QR Code") -> Code:
    return Code(page=1, format=format, text=text, box=Box(0.1, 0.2, 0.3, 0.1))


def test_a_giro_code_is_a_credit_transfer() -> None:
    assert giro_code(GIRO) == GiroCode(
        name="Stadtwerke Musterstadt GmbH",
        iban="DE89370400440532013000",
        bic="MUSTDEM1XXX",
        amount=Money(Decimal("84.2"), "EUR"),
        purpose="Abschlag 03/2026",
    )


def test_a_giro_code_of_version_001_with_crlf_and_a_reference() -> None:
    lines = ["BCD", "001", "1", "SCT", "", "Verein e.V.", "DE89370400440532013000", "", ""]
    text = "\r\n".join([*lines, "RF18539007547034"])
    assert giro_code(text) == GiroCode(
        name="Verein e.V.", iban="DE89370400440532013000", purpose="RF18539007547034"
    )


@pytest.mark.parametrize(
    "text",
    [
        "https://example.org",
        GIRO.replace("BCD", "SPC"),
        GIRO.replace("SCT", "INST"),
        GIRO.replace("DE89 3704 0044 0532 0130 00", "DE00 1234"),
        "BCD\n002\n1\nSCT",
    ],
)
def test_other_texts_are_no_giro_code(text: str) -> None:
    assert giro_code(text) is None


def test_the_identifiers_of_a_code() -> None:
    assert code_identifiers(code(GIRO)) == {(IdentifierKind.IBAN, "DE89370400440532013000")}
    assert code_identifiers(code("https://www.stadtwerke-musterstadt.example/portal")) == {
        (IdentifierKind.EMAIL_DOMAIN, "stadtwerke-musterstadt.example")
    }
    assert code_identifiers(code("300118554", "Code 128")) == set()


def test_codes_json_round_trip() -> None:
    codes = (code(GIRO), code("K-20047718", "Code 128"))
    data = codes_to_json(codes)
    assert data["version"] == CODES_VERSION
    assert codes_from_json(data) == codes
    # Codes read by an earlier version are read again.
    assert codes_from_json({**data, "version": CODES_VERSION - 1}) is None
    with pytest.raises(ValidationError):
        codes_from_json({"version": CODES_VERSION})
    with pytest.raises(ValidationError):
        codes_from_json({"version": CODES_VERSION, "codes": [{"page": 0}]})
