"""Health: a hospital's discharge letter, a doctor's findings, a certificate of incapacity for
work."""

from datetime import date

from synth import contacts as c
from synth.classes.common import MAX, greeting, letter
from synth.document import Doc, doc
from synth.fonts import HAND, MONO, SANS, SANS_BOLD
from synth.household import LENA, street
from synth.layout import GREY, Page
from synth.letter import Column
from synth.numbers import german


def discharge_letter(day: date, seed: int = 0) -> Doc:
    s = c.KLINIKUM
    bill = letter(
        s,
        MAX,
        day,
        [("Patientin", LENA.name), ("geb. am", german(LENA.born)), ("Fall-Nr.", "2025-118834")],
        f"Entlassungsbrief – stationärer Aufenthalt vom 14.10. bis 17.10.{day.year}",
        seed=seed,
    )
    bill.paragraph("Sehr geehrte Eltern, sehr geehrte Frau Kollegin Dr. Beispiel,")
    bill.paragraph(
        f"wir berichten über Ihre Tochter Lena Mustermann, geboren am {german(LENA.born)}, die sich vom 14.10. bis 17.10.{day.year} in unserer stationären Behandlung befand."
    )
    bill.heading("Diagnosen", size=10)
    bill.paragraph(
        "Akute Tonsillitis mit Exsikkose (J03.9, E86). Keine relevanten Vorerkrankungen."
    )
    bill.heading("Verlauf", size=10)
    bill.paragraph(
        "Aufnahme bei Fieber bis 39,8 °C und Trinkverweigerung. Unter intravenöser Flüssigkeitsgabe und antibiotischer Therapie rasche Besserung. Bei Entlassung fieberfrei, trinkt und isst ausreichend."
    )
    bill.heading("Empfehlung", size=10)
    bill.paragraph(
        "Fortführung der antibiotischen Therapie bis einschließlich 23.10. Wiedervorstellung bei der Kinderärztin in einer Woche. Schulbesuch ab 27.10. möglich."
    )
    bill.signature(
        "Mit freundlichen kollegialen Grüßen", "Dr. med. Sofia Brandt", "Oberärztin Kinderklinik"
    )
    return doc(
        "discharge-letter",
        "Arztbrief",
        s,
        day,
        "Entlassungsbrief Lena",
        bill,
        recipient="lena",
        download="Entlassungsbrief.pdf",
    )


def findings(day: date, seed: int = 0) -> Doc:
    s = c.DR_BEISPIEL
    bill = letter(
        s,
        MAX,
        day,
        [("Patient", MAX.name), ("geb. am", german(MAX.born))],
        "Ihre Laborwerte vom Gesundheits-Check",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "wie besprochen sende ich Ihnen die Ergebnisse Ihrer Blutuntersuchung. Die Werte sind insgesamt erfreulich; das LDL-Cholesterin ist leicht erhöht."
    )
    bill.table(
        [
            Column("Wert", 60),
            Column("Ergebnis", 30, "right"),
            Column("Einheit", 30),
            Column("Referenz", 45),
        ],
        [
            ("Hämoglobin", "14,8", "g/dl", "13,5 – 17,5"),
            ("Leukozyten", "6,2", "/nl", "4,0 – 10,0"),
            ("Glukose nüchtern", "92", "mg/dl", "70 – 99"),
            ("Cholesterin gesamt", "214", "mg/dl", "< 200"),
            ("LDL-Cholesterin", "142", "mg/dl", "< 130"),
            ("HDL-Cholesterin", "54", "mg/dl", "> 40"),
            ("TSH", "1,8", "mU/l", "0,4 – 4,0"),
        ],
        size=8.5,
        shade=True,
    )
    bill.paragraph(
        "Ich empfehle mehr Bewegung und eine Kontrolle in sechs Monaten. Bei Fragen melden Sie sich gern in der Praxis."
    )
    bill.signature("Mit freundlichen Grüßen", "Dr. med. Anna Beispiel")
    return doc(
        "findings",
        "Arztbrief",
        s,
        day,
        "Laborbefund Gesundheits-Check",
        bill,
        download="Befund.pdf",
    )


def sick_note(day: date) -> Doc:
    """A certificate of incapacity for work, the copy for the insured person, as the practice
    software prints it into the boxes of the form."""
    page = Page(148, 210)
    page.rect(5, 5, 138, 200, stroke=(200, 80, 80), width=0.6)
    page.text(10, 14, "Arbeitsunfähigkeitsbescheinigung", SANS_BOLD, 12, color=(170, 40, 40))
    page.text(
        10,
        19,
        "Ausfertigung zur Vorlage beim Arbeitgeber / für Versicherte",
        SANS,
        7,
        color=(170, 40, 40),
    )
    road, city = street(day)
    boxes = [
        ("Krankenkasse bzw. Kostenträger", "Gesundkasse BKK", 26),
        (
            "Name, Vorname des Versicherten",
            f"{MAX.last}, {MAX.first}   geb. am {german(MAX.born)}",
            38,
        ),
        ("Anschrift", f"{road}, {city}", 50),
        ("Versicherten-Nr.", MAX.health_insurance_number, 62),
        ("Betriebsstätten-Nr. / Arzt-Nr.", "123456700 / 987654321", 74),
    ]
    for label, value, y in boxes:
        page.text(10, y, label, SANS, 6, color=(170, 40, 40))
        page.rect(10, y + 1.2, 128, 7, stroke=(200, 120, 120), width=0.3)
        page.text(12, y + 6.4, value, MONO, 9)
    rows = [
        ("[X] Erstbescheinigung   [ ] Folgebescheinigung", 90),
        (f"arbeitsunfähig seit        {german(day)}", 100),
        (f"voraussichtlich bis        {german(date(day.year, day.month, day.day + 4))}", 108),
        (f"festgestellt am            {german(day)}", 116),
        ("AU-begründende Diagnose    J06.9 G", 128),
    ]
    for text, y in rows:
        page.text(12, y, text, MONO, 9)
    page.text(
        10, 150, "Vertragsarztstempel / Unterschrift des Arztes", SANS, 6, color=(170, 40, 40)
    )
    page.rect(10, 152, 128, 30, stroke=(200, 120, 120), width=0.3)
    page.text(14, 160, "Dr. med. Anna Beispiel", SANS_BOLD, 8)
    page.text(14, 164, "Fachärztin für Allgemeinmedizin", SANS, 7)
    page.text(14, 168, "Parkstraße 3, 12345 Musterstadt", SANS, 7)
    page.text(85, 176, "A. Beispiel", HAND, 15, color=(20, 40, 120))
    page.text(
        10,
        198,
        "Die Daten wurden elektronisch an die Krankenkasse übermittelt (eAU).",
        SANS,
        6.5,
        color=GREY,
    )
    return doc(
        "sick-note",
        "Bescheinigung",
        c.DR_BEISPIEL,
        day,
        "Arbeitsunfähigkeitsbescheinigung",
        [page],
        facts=[("health_insurance_number", MAX.health_insurance_number)],
        layout="form",
        download="AU_Bescheinigung.pdf",
    )
