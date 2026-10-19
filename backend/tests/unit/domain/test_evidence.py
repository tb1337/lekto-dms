from datetime import date
from decimal import Decimal

import pytest

from lekto.core.domain.evidence import (
    DocumentText,
    amounts_in,
    contains,
    currencies_in,
    dates_in,
    normalise,
    numbers_in,
    periods_in,
    read_amount,
    read_date,
    read_number,
    read_period,
    truth_value,
)
from lekto.core.domain.periods import Period


def test_normalise() -> None:
    text = "**Rechnungs-\nnummer:**  4711\u00a0| Straße\tGROSS ﬁ #"
    assert normalise(text) == "rechnungsnummer: 4711 strasse gross fi"


def test_entities_of_older_parses_count_as_their_characters() -> None:
    # Texts parsed before 0.2.0 carry Docling's HTML escapes.
    text = DocumentText("Müller &amp; Söhne &lt;GmbH&gt;\n\n| Std.&#124;TAZPL | 7,48 &#124; 0,54 |")
    assert text.contains("Müller & Söhne <GmbH>")
    assert text.has_number(Decimal("0.54"))
    assert normalise("&amp;") == "&"


@pytest.mark.parametrize(
    "written",
    [
        "31.03.2026",
        "31.3.2026",
        "31.03.26",
        "31/03/2026",
        "31-03-2026",
        "2026-03-31",
        "2026/03/31",
        "31. März 2026",
        "31. Maerz 2026",
        "31 Mär. 2026",
        "31. Mrz. 2026",
        "31st March 2026",
        "March 31, 2026",
        "Mar 31st 2026",
    ],
)
def test_dates_in_every_usual_notation(written: str) -> None:
    assert date(2026, 3, 31) in dates_in(normalise(f"Datum: {written}, Seite 1"))


def test_dates_need_a_whole_date() -> None:
    found = dates_in(normalise("Version 1.2.3.4, Zeitraum 03/2026, Konto 12.34.5678, 31.02.2026"))
    assert found == set()


def test_two_digit_years() -> None:
    assert dates_in("01.02.69 01.02.70") == {date(2069, 2, 1), date(1970, 2, 1)}


@pytest.mark.parametrize(
    ("written", "number"),
    [
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1'234.56", "1234.56"),
        ("84,20", "84.2"),
        ("84.20", "84.2"),
        ("-84,20", "84.2"),
        ("2026", "2026"),
        ("1.000.000", "1000000"),
        ("0,125", "0.125"),
    ],
)
def test_numbers_in_german_and_english_notation(written: str, number: str) -> None:
    assert Decimal(number) in numbers_in(normalise(f"Betrag {written} EUR"))


def test_ambiguous_numbers_have_both_readings() -> None:
    assert {Decimal("1234"), Decimal("1.234")} <= numbers_in("1.234")


def test_dates_and_odd_groups_are_no_numbers() -> None:
    found = numbers_in(normalise("31.03.2026 1.23.456 12,3,4"))
    assert Decimal("31.03") not in found
    assert Decimal("123456") not in found


@pytest.mark.parametrize(
    ("written", "amount"),
    [
        ("620,00", "620"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("620 €", "620"),
        ("€620", "620"),
        ("EUR 620", "620"),
        ("620 Euro", "620"),
        ("620,-", "620"),
        ("620,\u2013 EUR", "620"),  # en dash
    ],
)
def test_amounts_as_amounts(written: str, amount: str) -> None:
    assert Decimal(amount) in amounts_in(normalise(f"Gesamt-Brutto {written}"))


@pytest.mark.parametrize("written", ["620", "1.234", "Kto.-Nr.: 620", "84,2", "Seite 620"])
def test_a_bare_number_is_no_amount(written: str) -> None:
    """On a broken scan a lone fragment like `620` may stand for anything."""
    assert amounts_in(normalise(f"Gesamt-Brutto\n{written}\nNetto")) == set()


@pytest.mark.parametrize(
    ("written", "code"),
    [
        ("84,20 €", "EUR"),
        ("EUR 84,20", "EUR"),
        ("84,20 Euro", "EUR"),
        ("$84.20", "USD"),
        ("US$ 84.20", "USD"),
        ("84.20 USD", "USD"),
        ("£84.20", "GBP"),
        ("CHF 84.20", "CHF"),
        ("Fr. 84.20", "CHF"),
        ("84,20 kr", "SEK"),
    ],
)
def test_currencies(written: str, code: str) -> None:
    assert code in currencies_in(normalise(written))


def test_currency_not_shown() -> None:
    assert "USD" not in currencies_in(normalise("Betrag 84,20 €"))
    # Three-letter words that are no ISO 4217 code.
    assert currencies_in(normalise("bis den Sie von")) == set()


def test_contains() -> None:
    text = normalise("Mueller GmbH, IBAN DE12 3456 7890 1234 5678 90, Straße 1")
    assert contains(text, "Mueller GmbH")
    assert contains(text, "Müller GmbH")
    assert contains(text, "STRASSE 1")
    assert contains(text, "DE12345678901234567890")
    assert not contains(text, "Meier")
    assert not contains(text, "  ")
    assert not contains(normalise("1 2 3 4"), "1234")  # short values need their spaces
    assert not contains(normalise("Rechnung Z-3141"), "Z-3")  # whole words only
    assert not contains(normalise("vom 31.03.2026"), "31")
    assert contains(normalise("Rechnung Z-3141, bezahlt"), "Z-3141")


def test_document_text() -> None:
    facts = DocumentText("Rechnung vom 31.03.2026 über 84,20 €")
    assert facts.has_date(date(2026, 3, 31))
    assert not facts.has_date(date(2026, 3, 30))
    assert facts.has_number(Decimal("84.20"))
    assert facts.has_number(Decimal("-84.2"))
    assert facts.has_currency("EUR")
    assert facts.contains("rechnung")


@pytest.mark.parametrize(
    ("written", "number"),
    [
        ("2.111,68", "2111.68"),
        ("2111.68", "2111.68"),
        ("1,234.56", "1234.56"),
        ("84,20", "84.20"),
        ("1 234", "1234"),
        ("-12,50 €", "-12.50"),
        ("12,50-", "-12.50"),
        ("€ -5", "-5"),
        ("ca. 84,20 EUR", "84.20"),
    ],
)
def test_numbers_as_written(written: str, number: str) -> None:
    assert read_number(written) == Decimal(number)


def test_a_number_needs_to_stand_alone() -> None:
    assert read_number("R-2026") == Decimal("2026")
    assert read_number("R-2026-0815") is None
    assert read_number("keine Angabe") is None


def test_an_ambiguous_number_is_read_the_way_the_text_shows_it() -> None:
    assert read_number("1.234") == Decimal("1234")
    assert read_number("1.234", language="en") == Decimal("1.234")
    assert read_number("1.234", DocumentText("Faktor 1.2340")) == Decimal("1.234")
    assert read_number("1.234", DocumentText("Menge 1,234 kg")) == Decimal("1234")
    assert read_number("1.234", DocumentText("Menge 1234 Stück")) == Decimal("1234")


@pytest.mark.parametrize(
    "written", ["2026-03-12", "12.03.2026", "12.3.26", "12. März 2026", "March 12, 2026"]
)
def test_dates_as_written(written: str) -> None:
    assert read_date(written) == date(2026, 3, 12)


def test_of_several_dates_the_one_in_the_text() -> None:
    assert read_date("01.06.2026 bis 30.06.2026") is None
    facts = DocumentText("Leistung bis 30.06.2026")
    assert read_date("01.06.2026 bis 30.06.2026", facts) == date(2026, 6, 30)


def test_amounts_as_written() -> None:
    assert read_amount("2.111,68 EUR") == (Decimal("2111.68"), "EUR")
    assert read_amount("€ 84,20") == (Decimal("84.20"), "EUR")
    assert read_amount("84,20") is None
    assert read_amount("84,20", DocumentText("Summe 84,20 €")) == (Decimal("84.20"), "EUR")
    assert read_amount("120 kr", DocumentText("Pris 120 SEK")) == (Decimal("120"), "SEK")


def test_an_amount_in_a_text_without_currency_is_in_the_default_one() -> None:
    """A pay slip prints bare numbers; where the text shows a currency, that one counts."""
    bare = DocumentText("Gesamtbrutto 2.111,68 Netto 1.500,00")
    assert read_amount("2.111,68", bare, default="EUR") == (Decimal("2111.68"), "EUR")
    assert read_amount("2.111,68", bare) is None
    assert read_amount("2.111,68 USD", bare, default="EUR") == (Decimal("2111.68"), "USD")
    shown = DocumentText("Total 2,111.68 USD")
    assert read_amount("2,111.68", shown, default="EUR") == (Decimal("2111.68"), "USD")


# --- periods ------------------------------------------------------------------------------------

DOCUMENT_DATE = date(2026, 10, 5)
SEPTEMBER = Period.month(2026, 9)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("September 2026", SEPTEMBER),
        ("für Sept. 2026", SEPTEMBER),
        ("09/2026", SEPTEMBER),
        ("9.2026", SEPTEMBER),
        ("2026-09", SEPTEMBER),
        ("KW 38/2026", Period.week(2026, 38)),
        ("Kalenderwoche 38 2026", Period.week(2026, 38)),
        ("week 38, 2026", Period.week(2026, 38)),
        ("38. KW 2026", Period.week(2026, 38)),
        ("Q3 2026", Period.quarter(2026, 3)),
        ("3. Quartal 2026", Period.quarter(2026, 3)),
        ("Lohnsteuerbescheinigung 2025", Period.year(2025)),
        ("01.09.2026 \u2013 30.09.2026", SEPTEMBER),
        ("vom 01.09.2026 bis 30.09.2026", SEPTEMBER),
        ("01.09.-30.09.2026", SEPTEMBER),
        ("1.-30.09.2026", SEPTEMBER),
        ("1. bis 30. September 2026", SEPTEMBER),
        ("Leistungszeitraum 14.09.-18.09.2026", Period(date(2026, 9, 14), date(2026, 9, 18))),
        ("15. September 2026", Period.day(date(2026, 9, 15))),
        ("2026-09-30", Period.day(date(2026, 9, 30))),
    ],
)
def test_periods_as_written(raw: str, expected: Period) -> None:
    assert read_period(raw, DOCUMENT_DATE) == (expected, False)


def test_a_period_without_its_year_takes_that_of_the_document_date() -> None:
    assert read_period("für September", DOCUMENT_DATE) == (SEPTEMBER, True)
    # After the document date in its year: the year before.
    assert read_period("November", DOCUMENT_DATE) == (Period.month(2025, 11), True)
    assert read_period("KW 38", DOCUMENT_DATE) == (Period.week(2026, 38), True)
    assert read_period("September", None) is None


@pytest.mark.parametrize(
    "raw",
    ["September 2026 und Oktober 2026", "01.09.2026 und 05.09.2026", "30.09.2026 bis 01.09.2026"],
)
def test_two_periods_or_none_are_no_reading(raw: str) -> None:
    found = read_period(raw, DOCUMENT_DATE)
    assert found is None or found[0] != SEPTEMBER


def test_a_text_shows_a_period_as_written_or_by_its_first_and_last_day() -> None:
    text = DocumentText("Abrechnung September 2026; erfasst vom 01.08.2026 ... bis 31.08.2026")
    assert text.has_period(SEPTEMBER)
    assert text.has_period(Period.month(2026, 8))  # its ends, apart
    assert not text.has_period(Period.month(2026, 10))
    assert DocumentText("für September").has_period(SEPTEMBER, DOCUMENT_DATE)
    assert not DocumentText("für September").has_period(SEPTEMBER)
    # Numbers that only look like a period are none: a customer number, a date's year.
    assert periods_in(normalise("Kunden-Nr. 2026-0412, Rechnung vom 01.09.2026")) == {
        Period.day(date(2026, 9, 1))
    }


def test_yes_and_no_as_written() -> None:
    assert [truth_value(text) for text in ("Ja", " yes ", "true", "nein", "No", "false")] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert truth_value("vielleicht") is None


def test_a_text_read_at_once_has_found_everything() -> None:
    text = DocumentText.read("Rechnung vom 31.03.2026 über 84,20 EUR")
    assert {"normalised", "dates", "periods", "numbers", "amounts", "currencies"} <= set(vars(text))
    assert text.has_date(date(2026, 3, 31)) and text.has_currency("EUR")
