"""Authorities: income tax assessments and the tax office's request, motor vehicle tax, the
city's registration and dog tax, child benefit, pension information, a fine with its hearing."""

from datetime import date
from decimal import Decimal

from synth import contacts as c
from synth.classes.common import ERIKA, MAX, greeting, letter, notice
from synth.document import Doc, doc, money
from synth.household import CHILD_BENEFIT_NUMBER, LENA, LICENSE_PLATE, MAX_IBAN, Person, street
from synth.letter import Column
from synth.numbers import euro, german

D = Decimal
TAX_NUMBER = "21/815/08150"
VEHICLE_FILE = "KR 2150 4471 1984"
DOG_FILE = "4.31-HSt-11982"
FINE_FILE = "754.26.018833.4"


def income_tax(
    year: int,
    day: date,
    refund: Decimal,
    income_max: Decimal,
    income_erika: Decimal,
    *,
    seed: int = 0,
) -> Doc:
    s = c.FINANZAMT
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Steuernummer", TAX_NUMBER),
            ("IdNr. Ehemann", MAX.tax_id),
            ("IdNr. Ehefrau", ERIKA.tax_id),
            ("Bearbeiter", "Frau Lorenz, Zi. 214"),
        ],
        f"Bescheid für {year} über Einkommensteuer, Solidaritätszuschlag und Kirchensteuer – Zusammenveranlagung",
        both=True,
        reference=f"St.-Nr. {TAX_NUMBER}",
        seed=seed,
        date_label="Datum",
    )
    tax = ((income_max + income_erika) * D("0.142")).quantize(D("1"))
    church = (tax * D("0.09")).quantize(D("0.01"))
    paid_tax = tax + refund
    bill.heading("Festsetzung")
    bill.table(
        [
            Column("", 70),
            Column("Einkommensteuer", 35, "right"),
            Column("Solidaritätszuschlag", 32, "right"),
            Column("Kirchensteuer rk", 28, "right"),
        ],
        [
            ("Festgesetzt werden", euro(tax), "0,00", euro(church)),
            (
                "ab Steuerabzug vom Lohn",
                euro(-paid_tax),
                "0,00",
                euro(-(paid_tax * D("0.09")).quantize(D("0.01"))),
            ),
            (
                "verbleibende Beträge",
                euro(-refund),
                "0,00",
                euro(church - (paid_tax * D("0.09")).quantize(D("0.01"))),
            ),
        ],
        bold_rows=(2,),
        shade=True,
    )
    total = refund + (paid_tax * D("0.09")).quantize(D("0.01")) - church
    bill.box(
        [
            "Abrechnung",
            f"Der Erstattungsbetrag von {euro(total)} EUR wird auf das Konto {MAX_IBAN} überwiesen.",
        ]
    )
    bill.heading("Berechnung der Einkommensteuer")
    bill.table(
        [Column("", 105), Column("Ehemann EUR", 30, "right"), Column("Ehefrau EUR", 30, "right")],
        [
            ("Bruttoarbeitslohn", euro(income_max + D("1230")), euro(income_erika + D("1230"))),
            ("Werbungskosten", "-1.230,00", "-1.230,00"),
            ("Einkünfte aus nichtselbständiger Arbeit", euro(income_max), euro(income_erika)),
            ("Summe der Einkünfte", euro(income_max + income_erika), ""),
            ("Vorsorgeaufwendungen", "-11.240,00", ""),
            ("Sonderausgaben (Spenden)", "-100,00", ""),
            ("Zu versteuerndes Einkommen", euro(income_max + income_erika - D("11340")), ""),
        ],
        size=8.5,
    )
    bill.heading("Erläuterungen")
    bill.paragraph(
        "Die Aufwendungen für haushaltsnahe Dienstleistungen und Handwerkerleistungen wurden nach § 35a EStG berücksichtigt. Bei der Berechnung des Kindergeldes wurde die Günstigerprüfung durchgeführt; der Anspruch auf Kindergeld war günstiger."
    )
    bill.heading("Rechtsbehelfsbelehrung")
    bill.paragraph(
        "Dieser Bescheid kann mit dem Einspruch angefochten werden. Der Einspruch ist beim Finanzamt Musterstadt schriftlich einzureichen, diesem elektronisch zu übermitteln oder dort zur Niederschrift zu erklären. Die Frist für die Einlegung des Einspruchs beträgt einen Monat. Sie beginnt mit Ablauf des Tages, an dem Ihnen dieser Bescheid bekannt gegeben worden ist.",
        size=8.5,
    )
    return doc(
        "income-tax-assessment",
        "Bescheid",
        s,
        day,
        f"Einkommensteuerbescheid {year}",
        bill,
        recipient="max+erika",
        fields={"Betrag": money(total), "Bezugszeitraum": str(year)},
        facts=[
            ("tax_number", TAX_NUMBER),
            ("tax_id", MAX.tax_id),
            ("tax_id", ERIKA.tax_id),
            ("iban", MAX_IBAN),
        ],
        download=f"Steuerbescheid_{year}.pdf",
    )


def tax_request(day: date, letter_day: date, seed: int = 0) -> Doc:
    return notice(
        c.FINANZAMT,
        MAX,
        day,
        [("Steuernummer", TAX_NUMBER), ("Bearbeiter", "Frau Lorenz, Zi. 214")],
        "Einkommensteuer 2025 – Anforderung von Unterlagen",
        [
            f"zu Ihrer Einkommensteuererklärung 2025, eingegangen am {german(letter_day)}, benötige ich für die weitere Bearbeitung noch folgende Unterlagen:"
        ],
        pairs=[
            (
                "1.",
                "Rechnungen über die Handwerkerleistungen (Elektro Krause GmbH, Malerbetrieb Sonnenschein)",
            ),
            ("2.", "Nachweis über die Umzugskosten (Rechnung Umzüge Express Nord GmbH)"),
            ("3.", "Zuwendungsbestätigung des Tierschutzvereins Musterstadt e.V."),
        ],
        after=[
            "Bitte reichen Sie die Unterlagen bis zum "
            + german(date(day.year, day.month + 1, 1))
            + " ein, gern auch elektronisch über das Steuerportal. Andernfalls muss ich die Besteuerungsgrundlagen ohne die geltend gemachten Aufwendungen ermitteln."
        ],
        cls="tax-office-letter",
        document_type="Mitteilung",
        title="Finanzamt Unterlagen 2025",
        both=True,
        pairs_width=10,
        facts=[("tax_number", TAX_NUMBER)],
        fields={"Fällig am": date(day.year, day.month + 1, 1).isoformat()},
        sign=("Lorenz", "Sachbearbeiterin"),
        seed=seed,
    )


def vehicle_tax(day: date, *, change: bool = False, seed: int = 0) -> Doc:
    s = c.HAUPTZOLLAMT
    subject = "Kraftfahrzeugsteuerbescheid" + (
        " – Änderung wegen Anschriftenwechsel" if change else ""
    )
    bill = letter(
        s,
        MAX,
        day,
        [("Aktenzeichen", VEHICLE_FILE), ("Kennzeichen", LICENSE_PLATE)],
        subject,
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"für das Fahrzeug mit dem amtlichen Kennzeichen {LICENSE_PLATE} wird die Kraftfahrzeugsteuer ab dem {german(day if change else date(2024, 3, 1))} wie folgt festgesetzt:"
    )
    bill.pairs(
        [
            ("Fahrzeugart", "Pkw, Benzin, Euro 6d"),
            ("Hubraum", "1.498 cm³"),
            ("CO2-Emission", "128 g/km"),
            ("Jahressteuer", "62,00 EUR"),
            ("Fälligkeit", "jährlich im Voraus am 01.03."),
            ("Zahlungsweise", f"SEPA-Lastschrift von {MAX_IBAN}"),
        ],
        label_width=50,
    )
    bill.paragraph(
        "Die Steuer wird für die Dauer der Zulassung festgesetzt. Bei einer Änderung der Verhältnisse ergeht ein neuer Bescheid."
    )
    bill.paragraph(
        "Rechtsbehelfsbelehrung: Gegen diesen Bescheid ist der Einspruch gegeben. Er ist innerhalb eines Monats nach Bekanntgabe beim Hauptzollamt Musterstadt einzulegen.",
        size=8.5,
    )
    return doc(
        "vehicle-tax",
        "Bescheid",
        s,
        day,
        "Kfz-Steuerbescheid" + (" Änderung" if change else ""),
        bill,
        fields={"Betrag": money("62.00"), "Aktenzeichen": VEHICLE_FILE},
        facts=[
            ("file_reference", VEHICLE_FILE),
            ("license_plate", LICENSE_PLATE),
            ("iban", MAX_IBAN),
        ],
        download="Kfz_Steuerbescheid.pdf",
    )


def registration(day: date, seed: int = 0) -> Doc:
    road, city = street(day)
    return notice(
        c.STADT,
        MAX,
        day,
        [("Aktenzeichen", "33.1-MB-2025-08812")],
        "Meldebestätigung nach § 24 Abs. 2 Bundesmeldegesetz",
        [
            f"hiermit wird bestätigt, dass die nachstehenden Personen seit dem 01.08.2025 mit alleiniger Wohnung in {road}, {city} gemeldet sind:"
        ],
        pairs=[
            ("Max Mustermann", f"geb. {german(MAX.born)}"),
            ("Erika Musterfrau", f"geb. {german(ERIKA.born)}"),
            (LENA.name, f"geb. {german(LENA.born)}"),
            ("Bisherige Wohnung", "Birkenweg 5, 12347 Musterstadt"),
        ],
        cls="registration",
        document_type="Bescheinigung",
        title="Meldebestätigung Lindenallee",
        both=True,
        greet=False,
        facts=[("file_reference", "33.1-MB-2025-08812")],
        fields={"Aktenzeichen": "33.1-MB-2025-08812"},
        closing="Im Auftrag\nBürgeramt Musterstadt",
        seed=seed,
    )


def dog_tax(year: int, day: date, seed: int = 0) -> Doc:
    s = c.STADT
    bill = letter(
        s,
        MAX,
        day,
        [("Aktenzeichen", DOG_FILE), ("Kassenzeichen", "5.110.004471.9")],
        f"Hundesteuerbescheid {year}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"aufgrund der Hundesteuersatzung der Stadt Musterstadt wird für das Kalenderjahr {year} folgende Hundesteuer festgesetzt:"
    )
    bill.table(
        [
            Column("Hund", 60),
            Column("Steuermarke", 35),
            Column("Zeitraum", 40),
            Column("Steuer EUR", 30, "right"),
        ],
        [("Bello (Mischling)", "Nr. 1187", f"01.01.–31.12.{year}", "120,00")],
        shade=True,
    )
    bill.paragraph(
        f"Die Steuer ist zu je einem Viertel am 15.02., 15.05., 15.08. und 15.11.{year} fällig und wird von Ihrem Konto abgebucht."
    )
    bill.paragraph(
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch beim Oberbürgermeister der Stadt Musterstadt erhoben werden.",
        size=8.5,
    )
    bill.paragraph("Mit freundlichen Grüßen\nIm Auftrag – Steueramt")
    return doc(
        "dog-tax",
        "Bescheid",
        s,
        day,
        f"Hundesteuer {year}",
        bill,
        fields={"Betrag": money("120.00"), "Aktenzeichen": DOG_FILE, "Bezugszeitraum": str(year)},
        facts=[("file_reference", DOG_FILE)],
        download=f"Hundesteuer_{year}.pdf",
    )


def child_benefit(day: date, amount: Decimal, valid: date, seed: int = 0) -> Doc:
    return notice(
        c.FAMILIENKASSE,
        ERIKA,
        day,
        [("Kindergeld-Nr.", CHILD_BENEFIT_NUMBER)],
        f"Kindergeld ab {german(valid)}",
        [
            f"aufgrund der gesetzlichen Änderung beträgt das Kindergeld ab dem {german(valid)} {euro(amount)} EUR monatlich für jedes Kind. Für Ihr Kind Lena Mustermann, geboren am {german(LENA.born)}, zahlen wir Ihnen den neuen Betrag ab dem genannten Monat automatisch aus.",
            "Einen Antrag müssen Sie nicht stellen. Bitte teilen Sie uns alle Änderungen, die für den Anspruch von Bedeutung sind, unverzüglich mit, insbesondere einen Umzug ins Ausland oder eine Änderung der Bankverbindung.",
        ],
        pairs=[
            ("Kindergeld-Nr.", CHILD_BENEFIT_NUMBER),
            ("Auszahlung auf", MAX_IBAN),
            ("Monatlicher Betrag", f"{euro(amount)} EUR"),
        ],
        cls="child-benefit",
        document_type="Bescheid",
        title=f"Kindergeld {valid.year}",
        facts=[("child_benefit_number", CHILD_BENEFIT_NUMBER), ("iban", MAX_IBAN)],
        fields={"Betrag": money(amount)},
        closing="Mit freundlichen Grüßen\nIhre Familienkasse Musterland",
        seed=seed,
    )


def pension_info(
    person: Person, day: date, earned: Decimal, projected: Decimal, seed: int = 0
) -> Doc:
    s = c.RENTENKASSE
    bill = letter(
        s,
        person,
        day,
        [("Versicherungsnummer", person.social_security_number)],
        f"Renteninformation {day.year}",
        seed=seed,
    )
    bill.paragraph(greeting(person))
    bill.paragraph(
        "mit dieser Renteninformation erhalten Sie einen Überblick über Ihre bisher erreichten Anwartschaften und die voraussichtliche Höhe Ihrer Rente."
    )
    bill.box(
        [
            "Ihre voraussichtliche Regelaltersrente",
            f"Wenn Sie weiter Beiträge wie im Durchschnitt der letzten fünf Jahre zahlen: {euro(projected)} EUR monatlich",
        ]
    )
    bill.pairs(
        [
            ("Erreichte Rentenanwartschaft", f"{euro(earned)} EUR monatlich"),
            ("Rente wegen voller Erwerbsminderung", f"{euro(earned * D('1.4'))} EUR monatlich"),
            ("Regelaltersgrenze", f"{german(person.born.replace(year=person.born.year + 67))}"),
            ("Beitragszeiten bis", f"31.12.{day.year - 1}"),
        ],
        label_width=75,
    )
    bill.paragraph(
        "Bitte beachten Sie: Die Rente unterliegt der Steuer- und Sozialversicherungspflicht. Wegen des Kaufkraftverlusts sollten Sie zusätzlich vorsorgen.",
        size=9,
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Rentenkasse Musterland")
    return doc(
        "pension-information",
        "Mitteilung",
        s,
        day,
        f"Renteninformation {day.year} {person.first}",
        bill,
        recipient=person.username,
        facts=[("social_security_number", person.social_security_number)],
        download=f"Renteninformation_{day.year}.pdf",
    )


def hearing(day: date, seed: int = 0) -> Doc:
    return notice(
        c.BUSSGELD,
        MAX,
        day,
        [("Aktenzeichen", FINE_FILE), ("Kennzeichen", LICENSE_PLATE)],
        "Anhörung im Bußgeldverfahren – Zeugenfragebogen / Anhörungsbogen",
        [
            f"Ihnen wird vorgeworfen, am 21.02.2026 um 07:42 Uhr in Kreisstadt, Bundesstraße B 4, Höhe km 12,3, als Führer des Pkw mit dem amtlichen Kennzeichen {LICENSE_PLATE} die zulässige Höchstgeschwindigkeit außerhalb geschlossener Ortschaften um 13 km/h überschritten zu haben (zulässig 70 km/h, festgestellt nach Toleranzabzug 83 km/h).",
            "Sie haben Gelegenheit, sich zu dem Vorwurf zu äußern. Es steht Ihnen frei, sich zur Sache zu äußern oder nicht. Bitte senden Sie den Anhörungsbogen innerhalb einer Woche zurück.",
        ],
        pairs=[
            ("Tatvorwurf", "§ 41 Abs. 1 i. V. m. Anlage 2, § 49 StVO; § 24 StVG"),
            ("Beweismittel", "Messung mit stationärer Anlage, Lichtbild"),
            ("Voraussichtliches Verwarnungsgeld", "50,00 EUR"),
        ],
        cls="fine-hearing",
        document_type="Mitteilung",
        title="Anhörungsbogen Geschwindigkeit",
        greet=False,
        facts=[("file_reference", FINE_FILE), ("license_plate", LICENSE_PLATE)],
        fields={"Aktenzeichen": FINE_FILE},
        closing="Zentrale Bußgeldstelle",
        seed=seed,
    )


def fine(day: date, seed: int = 0) -> Doc:
    s = c.BUSSGELD
    bill = letter(
        s,
        MAX,
        day,
        [("Aktenzeichen", FINE_FILE), ("Kennzeichen", LICENSE_PLATE)],
        "Bußgeldbescheid",
        seed=seed,
    )
    bill.paragraph(
        f"Gegen Herrn Max Mustermann, geboren am {german(MAX.born)}, wird wegen der Ordnungswidrigkeit vom 21.02.2026 (Überschreitung der zulässigen Höchstgeschwindigkeit um 13 km/h außerhalb geschlossener Ortschaften, Kennzeichen {LICENSE_PLATE}) eine Geldbuße festgesetzt."
    )
    bill.table(
        [Column("Position", 120), Column("EUR", 45, "right")],
        [
            ("Geldbuße", "50,00"),
            ("Gebühr (§ 107 Abs. 1 OWiG)", "28,50"),
            ("Auslagen (§ 107 Abs. 3 OWiG)", "3,50"),
            ("Gesamtbetrag", "82,00"),
        ],
        bold_rows=(3,),
        shade=True,
    )
    bill.paragraph(
        f"Zahlen Sie den Gesamtbetrag bis spätestens zwei Wochen nach Rechtskraft auf das Konto der Kreiskasse, IBAN {s.iban}, Verwendungszweck {FINE_FILE}."
    )
    bill.paragraph(
        "Rechtsbehelfsbelehrung: Gegen diesen Bescheid kann innerhalb von zwei Wochen nach Zustellung schriftlich oder zur Niederschrift bei der oben bezeichneten Behörde Einspruch eingelegt werden.",
        size=8.5,
    )
    bill.paragraph("Im Auftrag\nZentrale Bußgeldstelle Musterkreis")
    return doc(
        "fine",
        "Bescheid",
        s,
        day,
        "Bußgeldbescheid Geschwindigkeit",
        bill,
        fields={"Betrag": money("82.00"), "Aktenzeichen": FINE_FILE},
        facts=[("file_reference", FINE_FILE), ("license_plate", LICENSE_PLATE), ("iban", s.iban)],
        download="Bussgeldbescheid.pdf",
    )
