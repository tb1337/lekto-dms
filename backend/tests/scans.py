"""Synthetic scans as Tesseract's hOCR, for the rules about how sure a reading is: a pay slip
shaped like a real one whose correct date stayed yellow (no real document is used).

On that scan almost every unsure word was noise: the dot leaders after the labels read as
`«oso:` and `see` on the date's own line, the tiny letterhead, stray marks read as `gy`, `TI`,
`j`, `cae`, the table rules as `en EEE`. Two amounts were truly unsure (31 % and 32 %), and one
was misread with 79 %. Counting every word, 10 % of them are unsure; counting content only,
fewer than 8 %. Leaders and rules read as letters keep the low box of the dots (`flat`), as
Tesseract gave them on a scan made for the test.

`hocr` places the lines as `FakeTextLocator` places text: line `n` of `L` at the height
`n / L`, a character at `column / length of its line`, so that the boxes of the words and those
of a quote the locator finds agree.
"""

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

BODY = 42  # Tesseract's x_size of a body line, in pixels
SMALL = 22  # the letterhead's
WIDTH = 10_000  # the page's width in pixels
LINE = 100  # the height of a line's slot in pixels


@dataclass(frozen=True)
class ScanLine:
    """A line of a scan: its text (words apart by single spaces), its size (`x_size`), how
    sure Tesseract was of its words, and of some of them by text; the words read from dots or
    rules, whose box is a sixth of the line high (`flat`)."""

    text: str
    size: int = BODY
    confidence: int = 93
    unsure: Mapping[str, int] = field(default_factory=dict)
    flat: frozenset[str] = frozenset()


PAYSLIP: tuple[ScanLine, ...] = (
    ScanLine(
        "Muster Lohnbüro GmbH · Hauptstraße 1 · 12345 Musterstadt",
        SMALL,
        71,
        {"Lohnbüro": 41, "Hauptstraße": 38},
    ),
    ScanLine(
        "Telefon 0123 456789 · info@lohnbuero.example · Steuer-Nr. 12/345/67890",
        SMALL,
        66,
        {"info@lohnbuero.example": 35, "Steuer-Nr.": 52, "·": 20},
    ),
    ScanLine("Muster Handel GmbH Industriestraße 4 12345 Musterstadt"),
    ScanLine("Frau Erika Beispiel Musterweg 7 12345 Musterstadt gy", unsure={"gy": 31}),
    ScanLine("Abrechnung der Brutto/Netto-Bezüge für Juni 2022"),
    ScanLine(
        "Datum «oso: see 24.06.2022",
        unsure={"«oso:": 22, "see": 47, "24.06.2022": 96},
        flat=frozenset({"«oso:", "see"}),
    ),
    ScanLine("Personalnummer .......... 004711 TI", unsure={"..........": 18, "TI": 25}),
    ScanLine("Steuerklasse .......... 1 Kinderfreibeträge 0,5", unsure={"..........": 21}),
    ScanLine("Krankenkasse .......... AOK Musterland j", unsure={"..........": 30, "j": 12}),
    ScanLine("Eintritt 01.04.2019 Austritt — Urlaubsanspruch 30 Tage"),
    ScanLine("en EEE ———", unsure={"en": 25, "EEE": 30, "———": 10}, flat=frozenset({"EEE"})),
    ScanLine("Lohnart Bezeichnung Menge Satz Betrag"),
    ScanLine("1000 Gehalt 1,00 3.250,00 3.250,00"),
    ScanLine("1100 Vermögenswirksame Leistungen 40,00 40,00"),
    ScanLine("1200 Zulage Schicht 22,00 5,50 121,00", unsure={"5,50": 64}),
    ScanLine("Gesamt-Brutto 3.411,00"),
    ScanLine("en EEE ———", unsure={"en": 22, "EEE": 28, "———": 9}, flat=frozenset({"EEE"})),
    ScanLine("Steuer- und Sozialversicherungsabzüge für Juni 2022"),
    ScanLine("Lohnsteuer 412,33", unsure={"412,33": 31}),
    ScanLine("Solidaritätszuschlag 0,00"),
    ScanLine("Kirchensteuer 32,99", unsure={"32,99": 32}),
    ScanLine("Krankenversicherung 7,30 % 249,00 Zusatzbeitrag 0,65 % 22,17"),
    ScanLine("Rentenversicherung 9,30 % 317,22"),
    ScanLine("Arbeitslosenversicherung 1,20 % 40,93"),
    ScanLine("Pflegeversicherung 1,525 % 52,02 cae", unsure={"cae": 35}),
    ScanLine("Netto-Verdienst 2.235,81", unsure={"2.235,81": 79}),  # misread: 2.255,81
    ScanLine("Abzug vermögenswirksame Leistungen 40,00"),
    ScanLine("Auszahlungsbetrag 2.195,81"),
    ScanLine("Überweisung an DE12 3456 7890 1234 5678 90 Musterbank eG"),
    ScanLine("Bitte bewahren Sie diese Abrechnung sorgfältig auf. Sie wird nur einmal erstellt."),
    ScanLine("Die Abrechnung wurde maschinell erstellt und ist ohne Unterschrift gültig."),
    ScanLine("Jahressummen Januar bis Juni 2022"),
    ScanLine("Steuerbrutto 20.466,00 Lohnsteuer 2.473,98 Kirchensteuer 197,94"),
    ScanLine("KV-Brutto 20.466,00 RV-Brutto 20.466,00 AV-Brutto 20.466,00"),
    ScanLine("Gesamtbetrag der Sozialversicherung 4.115,64 davon Arbeitgeber 4.212,90"),
    ScanLine("Resturlaub zum Monatsende 18 Tage Überstunden 6,5 Stunden"),
    ScanLine("Bei Fragen zu Ihrer Abrechnung wenden Sie sich bitte an die Personalabteilung."),
    ScanLine("Hinweise zur Lohnsteuerbescheinigung erhalten Sie mit der Abrechnung für Dezember."),
    ScanLine("Ihre Lohnsteuer-Identifikationsnummer und Ihre Steuerklasse wurden elektronisch"),
    ScanLine("vom Bundeszentralamt für Steuern abgerufen. Änderungen teilen Sie uns bitte mit."),
)

PAYSLIP_TEXT = "\n".join(line.text for line in PAYSLIP)
"""The text of the pay slip as the archive's text layer gives it, for `FakeTextLocator`."""


def hocr(lines: Sequence[ScanLine]) -> str:
    """A page of hOCR as Tesseract writes it, with the words of `lines`."""
    height = LINE * len(lines)
    rows = []
    for number, line in enumerate(lines):
        top = number * LINE + (LINE - line.size) // 2
        bottom = top + line.size
        words, column = [], 0
        for index, text in enumerate(line.text.split(" ")):
            left = column * WIDTH // len(line.text)
            right = (column + len(text)) * WIDTH // len(line.text)
            confidence = line.unsure.get(text, line.confidence)
            high = top if text not in line.flat else bottom - line.size // 6
            words.append(
                f"<span class='ocrx_word' id='word_1_{number}_{index}' "
                f"title='bbox {left} {high} {right} {bottom}; x_wconf {confidence}'>"
                f"{html.escape(text)}</span>"
            )
            column += len(text) + 1
        rows.append(
            f"<span class='ocr_line' id='line_1_{number}' title='bbox 0 {top} {WIDTH} {bottom}; "
            f"baseline 0 -8; x_size {line.size}; x_descenders 8; x_ascenders 10'>"
            + " ".join(words)
            + "</span>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
        f"<div class='ocr_page' id='page_1' title='image \"page.png\"; bbox 0 0 {WIDTH} {height}; "
        "ppageno 0; scan_res 300 300'>"
        "<div class='ocr_carea' id='block_1_1'><p class='ocr_par' id='par_1_1' lang='deu'>"
        + "\n".join(rows)
        + "</p></div></div></body></html>"
    )


def scan(lines: Sequence[ScanLine], replace: Mapping[str, int]) -> tuple[ScanLine, ...]:
    """`lines` with the confidences of some words changed, by text."""
    return tuple(
        ScanLine(line.text, line.size, line.confidence, {**line.unsure, **replace}, line.flat)
        for line in lines
    )
