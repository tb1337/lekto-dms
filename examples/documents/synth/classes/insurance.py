"""Insurance: policies of household contents, liability and the car, premium invoices and
adjustments, a claim from the report by hand to the settlement, the health insurer's letters
and a pension policy's annual statement."""

from datetime import date
from decimal import Decimal

from synth import contacts as c
from synth.classes.common import ERIKA, MAX, greeting, letter, notice
from synth.document import Doc, doc, money
from synth.fonts import HAND, SANS, SANS_BOLD
from synth.household import LENA, LICENSE_PLATE, MAX_IBAN, street
from synth.layout import GREY, Page
from synth.letter import Column
from synth.numbers import euro, german

D = Decimal
HOUSEHOLD_POLICY = "HV-2025-4471182"
LIABILITY_POLICY = "PH-2019-0083317"
CAR_POLICY = "KS-61-2207431"
CLAIM = "S-26-0047711"
PENSION_POLICY = "VL-2019-338812"
HANSE_CUSTOMER = "HV 300 4471"


def policy(
    day: date,
    number: str,
    kind: str,
    begin: date,
    premium: Decimal,
    rows: list[tuple[str, str]],
    *,
    seed: int = 0,
) -> Doc:
    s = c.HANSE_VERS
    road, city = street(begin)
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Versicherungsschein-Nr.", number),
            ("Kundennummer", HANSE_CUSTOMER),
            ("Vermittler", "Agentur Nord, 0815"),
        ],
        f"Versicherungsschein {kind}",
        reference=f"Versicherungsschein {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "vielen Dank für Ihr Vertrauen. Mit diesem Versicherungsschein dokumentieren wir Ihren Vertrag. Bitte prüfen Sie die Angaben und bewahren Sie den Versicherungsschein sorgfältig auf."
    )
    bill.heading("Vertragsdaten")
    bill.pairs(
        [
            ("Versicherungsnehmer", "Max Mustermann"),
            ("Versicherungsort", f"{road}, {city}"),
            ("Versicherungsbeginn", german(begin)),
            ("Ablauf", f"{german(begin.replace(year=begin.year + 1))}, verlängert sich jährlich"),
            ("Zahlungsweise", "jährlich per SEPA-Lastschrift"),
            *rows,
        ],
        label_width=60,
    )
    bill.heading("Beitrag")
    bill.table(
        [Column("Baustein", 115), Column("Jahresbeitrag EUR", 50, "right")],
        [
            (f"{kind} Komfort", euro(premium / D("1.19"))),
            ("Versicherungsteuer 19 %", euro(premium - (premium / D("1.19")).quantize(D("0.01")))),
            ("Jahresbeitrag", euro(premium)),
        ],
        bold_rows=(2,),
        shade=True,
    )
    bill.paragraph(
        f"Der Beitrag wird zum {german(begin)} von Ihrem Konto {MAX_IBAN} abgebucht (Mandatsreferenz {number})."
    )
    bill.heading("Vertragsgrundlagen")
    bill.paragraph(
        f"Es gelten die Allgemeinen Versicherungsbedingungen {kind} (AVB {begin.year}), die Besonderen Bedingungen und die Tarifbestimmungen. "
        * 2,
        size=8.5,
    )
    bill.paragraph(
        "Widerrufsbelehrung: Sie können Ihre Vertragserklärung innerhalb von 14 Tagen ohne Angabe von Gründen in Textform widerrufen. Die Frist beginnt, nachdem Sie den Versicherungsschein, die Vertragsbestimmungen und diese Belehrung erhalten haben.",
        size=8.5,
    )
    bill.signature("Mit freundlichen Grüßen", "Lars Jansen", "Vorstand")
    return doc(
        "insurance-policy",
        "Versicherung",
        s,
        day,
        f"Versicherungsschein {kind}",
        bill,
        fields={
            "Versicherungsnummer": number,
            "Beitrag": money(premium),
            "Vertragsbeginn": begin.isoformat(),
        },
        facts=[
            ("policy_number", number),
            ("customer_number", HANSE_CUSTOMER),
            ("mandate_reference", number),
        ],
        download=f"Versicherungsschein_{number}.pdf",
    )


def premium_invoice(
    sender,
    day: date,
    number: str,
    rows: list[tuple[str, Decimal]],
    period: tuple[date, date],
    *,
    customer: str,
    seed: int = 0,
) -> Doc:
    total = sum((amount for _, amount in rows), D("0"))
    bill = letter(
        sender,
        MAX,
        day,
        [("Kundennummer", customer), ("Versicherungsnummer", number)],
        f"Beitragsrechnung {german(period[0])} – {german(period[1])}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph("für den kommenden Versicherungszeitraum berechnen wir Ihnen folgende Beiträge:")
    bill.table(
        [Column("Vertrag", 120), Column("Beitrag EUR", 45, "right")],
        [(name, euro(amount)) for name, amount in rows],
        shade=True,
    )
    bill.totals([("Gesamtbeitrag inkl. Versicherungsteuer", f"{euro(total)} EUR")])
    bill.paragraph(f"Wir buchen den Betrag zum {german(period[0])} von Ihrem Konto {MAX_IBAN} ab.")
    bill.paragraph(f"Mit freundlichen Grüßen\n{sender.head_name}")
    return doc(
        "premium-invoice",
        "Rechnung",
        sender,
        day,
        f"Beitragsrechnung {period[0].year}",
        bill,
        fields={
            "Beitrag": money(total),
            "Versicherungsnummer": number,
            "Bezugszeitraum": f"{period[0].isoformat()}/{period[1].isoformat()}",
        },
        facts=[("policy_number", number), ("customer_number", customer), ("iban", MAX_IBAN)],
        download=f"Beitragsrechnung_{period[0].year}.pdf",
    )


def premium_adjustment(day: date, seed: int = 0) -> Doc:
    return notice(
        c.HANSE_VERS,
        MAX,
        day,
        [("Versicherungsnummer", LIABILITY_POLICY), ("Kundennummer", HANSE_CUSTOMER)],
        "Beitragsanpassung Ihrer Privathaftpflichtversicherung",
        [
            "der unabhängige Treuhänder hat die Entwicklung der Schadenzahlungen geprüft. Nach § 15 unserer Bedingungen passen wir den Beitrag Ihrer Privathaftpflichtversicherung zum 01.01.2026 an."
        ],
        pairs=[("Jahresbeitrag bisher", "78,54 EUR"), ("Jahresbeitrag ab 01.01.2026", "84,20 EUR")],
        after=[
            "Erhöht sich der Beitrag, können Sie den Vertrag innerhalb eines Monats nach Zugang dieser Mitteilung zum Zeitpunkt des Wirksamwerdens kündigen."
        ],
        cls="premium-adjustment",
        document_type="Versicherung",
        title="Beitragsanpassung Haftpflicht 2026",
        facts=[("policy_number", LIABILITY_POLICY), ("customer_number", HANSE_CUSTOMER)],
        fields={"Beitrag": money("84.20"), "Versicherungsnummer": LIABILITY_POLICY},
        seed=seed,
    )


def claim_report(day: date) -> Doc:
    """The insurer's claim form, filled in by hand: a bicycle stolen from the cellar."""
    s = c.HANSE_VERS
    page = Page()
    page.text(25, 22, s.name, SANS_BOLD, 11, color=s.style.accent)
    page.text(25, 32, "Schadenanzeige Hausratversicherung", SANS_BOLD, 16)
    page.text(
        25, 38, "Bitte vollständig ausfüllen und mit Belegen zurücksenden.", SANS, 9, color=GREY
    )
    road, city = street(day)
    rows = [
        ("Versicherungsschein-Nr.", HOUSEHOLD_POLICY),
        ("Versicherungsnehmer", "Max Mustermann"),
        ("Anschrift", f"{road}, {city}"),
        ("Telefon / E-Mail", "0171 2345678 · max.mustermann@posteo-beispiel.example"),
        ("Schadentag, Uhrzeit", "01.06.2026, zwischen 18 und 22 Uhr"),
        ("Schadenort", "Kellerraum Nr. 7, Lindenallee 12"),
        ("Art des Schadens", "Einbruchdiebstahl (Kellertür aufgebrochen)"),
        ("Gestohlene Sachen", "Fahrrad Velotrek City 7, Rahmen-Nr. VT7-2291-AB-3304"),
        ("Anschaffung / Preis", "2023, ca. 649 EUR"),
        ("Polizeilich gemeldet", "ja, Polizeirevier Musterstadt-Mitte, Tgb.-Nr. 2026/18834"),
        ("Bankverbindung", MAX_IBAN),
    ]
    y = 50.0
    for label, value in rows:
        page.text(25, y, label, SANS, 8.5, color=GREY)
        page.rect(72, y - 5.5, 113, 8, stroke=(130, 130, 130), width=0.4)
        page.text(74, y, value, HAND, 12, color=(20, 40, 120))
        y += 11
    page.text(25, y + 6, "Schilderung des Hergangs", SANS_BOLD, 10)
    page.rect(25, y + 9, 160, 34, stroke=(130, 130, 130), width=0.4)
    for number, line in enumerate(
        [
            "Am Abend des 01.06. war die Kellertür aufgebrochen. Das Fahrrad",
            "war mit Schloss am Regal gesichert. Das Schloss lag durchtrennt am",
            "Boden. Die Polizei hat Spuren gesichert.",
        ]
    ):
        page.text(28, y + 17 + number * 8, line, HAND, 12, color=(20, 40, 120))
    page.text(25, y + 56, f"Musterstadt, {german(day)}", HAND, 13, color=(20, 40, 120))
    page.text(120, y + 56, "M. Mustermann", HAND, 16, color=(20, 40, 120))
    page.line((25, y + 59), (90, y + 59), width=0.3)
    page.line((115, y + 59), (185, y + 59), width=0.3)
    page.text(25, y + 63, "Ort, Datum", SANS, 7.5, color=GREY)
    page.text(115, y + 63, "Unterschrift Versicherungsnehmer", SANS, 7.5, color=GREY)
    return doc(
        "claim-report",
        "Versicherung",
        s,
        day,
        "Schadenanzeige Fahrraddiebstahl",
        [page],
        fields={"Versicherungsnummer": HOUSEHOLD_POLICY},
        facts=[("policy_number", HOUSEHOLD_POLICY), ("iban", MAX_IBAN)],
        layout="form",
        download="Schadenanzeige.pdf",
    )


def claim_receipt(day: date, letter_day: date, seed: int = 0) -> Doc:
    return notice(
        c.HANSE_VERS,
        MAX,
        day,
        [
            ("Schadennummer", CLAIM),
            ("Versicherungsnummer", HOUSEHOLD_POLICY),
            ("Unser Zeichen", "SD-H/kr 2611"),
        ],
        "Ihre Schadenmeldung – Eingangsbestätigung",
        [
            f"vielen Dank für Ihre Schadenanzeige vom {german(letter_day)}. Wir haben den Schaden unter der Schadennummer {CLAIM} erfasst. Bitte geben Sie diese bei allen Rückfragen an.",
            "Für die weitere Bearbeitung benötigen wir noch: den Kaufbeleg des Fahrrads oder einen Nachweis des Werts und die Bestätigung der Polizei über die Anzeige (Stehlgutliste).",
        ],
        cls="claim-letter",
        document_type="Versicherung",
        title="Schaden Eingangsbestätigung",
        facts=[
            ("claim_number", CLAIM),
            ("policy_number", HOUSEHOLD_POLICY),
            ("our_reference", "SD-H/kr 2611"),
            ("letter_date", german(letter_day)),
        ],
        fields={"Versicherungsnummer": HOUSEHOLD_POLICY},
        sign=("Kerstin Ruge", "Schadenservice Hausrat"),
        seed=seed,
    )


def claim_settlement(day: date, seed: int = 0) -> Doc:
    return notice(
        c.HANSE_VERS,
        MAX,
        day,
        [
            ("Schadennummer", CLAIM),
            ("Versicherungsnummer", HOUSEHOLD_POLICY),
            ("Unser Zeichen", "SD-H/kr 2611"),
        ],
        f"Regulierung Ihres Schadens {CLAIM}",
        [
            "wir haben Ihren Schaden geprüft und freuen uns, Ihnen mitteilen zu können, dass wir ihn wie folgt regulieren:"
        ],
        pairs=[
            ("Wiederbeschaffungswert Fahrrad", "620,00 EUR"),
            ("Abzug neu für alt", "-0,00 EUR"),
            ("Selbstbeteiligung", "-150,00 EUR"),
            ("Entschädigung", "470,00 EUR"),
        ],
        after=[
            f"Den Betrag überweisen wir in den nächsten Tagen auf Ihr Konto {MAX_IBAN}. Damit ist der Schaden für uns abgeschlossen. Wird das Fahrrad wieder aufgefunden, informieren Sie uns bitte."
        ],
        cls="claim-letter",
        document_type="Versicherung",
        title="Schadenregulierung Fahrrad",
        facts=[
            ("claim_number", CLAIM),
            ("policy_number", HOUSEHOLD_POLICY),
            ("our_reference", "SD-H/kr 2611"),
            ("iban", MAX_IBAN),
        ],
        fields={"Betrag": money("470.00"), "Versicherungsnummer": HOUSEHOLD_POLICY},
        sign=("Kerstin Ruge", "Schadenservice Hausrat"),
        seed=seed,
    )


def car_policy(day: date, seed: int = 0) -> Doc:
    s = c.KRAFTSCHUTZ
    bill = letter(
        s,
        MAX,
        day,
        [("Versicherungsnummer", CAR_POLICY), ("Kennzeichen", LICENSE_PLATE)],
        "Versicherungsschein Kfz-Versicherung 2025",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "Ihr Fahrzeug ist bei uns versichert. Hier sind Ihre Vertragsdaten für das Jahr 2025:"
    )
    bill.pairs(
        [
            ("Fahrzeug", "Kompakt 1.5, Pkw, 110 kW"),
            ("Amtliches Kennzeichen", LICENSE_PLATE),
            ("Erstzulassung", "03/2020"),
            ("Fahrleistung", "bis 12.000 km jährlich"),
            ("Fahrer", "Versicherungsnehmer und Ehepartnerin, ab 25 Jahren"),
            ("Regionalklasse", "Haftpflicht 6, Vollkasko 5"),
        ],
        label_width=60,
    )
    bill.table(
        [
            Column("Sparte", 60),
            Column("SF-Klasse", 30),
            Column("Beitragssatz", 30, "right"),
            Column("Beitrag EUR", 45, "right"),
        ],
        [
            ("Kfz-Haftpflicht", "SF 18", "28 %", "251,40"),
            ("Vollkasko (SB 300/150)", "SF 16", "31 %", "234,90"),
            ("Gesamtbeitrag jährlich", "", "", "486,30"),
        ],
        bold_rows=(2,),
        shade=True,
    )
    bill.paragraph(
        f"Der Beitrag wird am 02.01.2025 per Lastschrift von Ihrem Konto {MAX_IBAN} eingezogen."
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre KRAFTSCHUTZ Versicherung")
    return doc(
        "insurance-policy",
        "Versicherung",
        s,
        day,
        "Kfz-Versicherungsschein 2025",
        bill,
        fields={"Versicherungsnummer": CAR_POLICY, "Beitrag": money("486.30")},
        facts=[("policy_number", CAR_POLICY), ("license_plate", LICENSE_PLATE), ("iban", MAX_IBAN)],
        download=f"Versicherungsschein_{CAR_POLICY}.pdf",
    )


def no_claims_notice(day: date, seed: int = 0) -> Doc:
    return notice(
        c.KRAFTSCHUTZ,
        MAX,
        day,
        [("Versicherungsnummer", CAR_POLICY), ("Kennzeichen", LICENSE_PLATE)],
        "Ihre neue Schadenfreiheitsklasse",
        [
            "weil Sie 2025 unfallfrei gefahren sind, stufen wir Ihren Vertrag zum 01.01.2026 in eine bessere Schadenfreiheitsklasse ein:"
        ],
        pairs=[
            ("Kfz-Haftpflicht", "SF 18 auf SF 19 (27 %)"),
            ("Vollkasko", "SF 16 auf SF 17 (30 %)"),
            ("Neuer Jahresbeitrag", "471,20 EUR"),
        ],
        cls="insurance-notice",
        document_type="Versicherung",
        title="SF-Einstufung 2026",
        facts=[("policy_number", CAR_POLICY), ("license_plate", LICENSE_PLATE)],
        fields={"Beitrag": money("471.20"), "Versicherungsnummer": CAR_POLICY},
        seed=seed,
    )


GESUND_MEMBER = "Mitglieds-Nr. 88 4471 20"


def health_membership(day: date, seed: int = 0) -> Doc:
    return notice(
        c.GESUNDKASSE,
        MAX,
        day,
        [("Versichertennummer", MAX.health_insurance_number)],
        "Mitgliedsbescheinigung",
        [
            f"wir bescheinigen, dass Herr Max Mustermann, geboren am {german(MAX.born)}, seit dem 01.04.2019 bei der Gesundkasse BKK als Pflichtmitglied (Arbeitnehmer) versichert ist.",
            f"Krankenversichertennummer: {MAX.health_insurance_number}.",
        ],
        cls="membership-certificate",
        document_type="Bescheinigung",
        title="Mitgliedsbescheinigung Krankenkasse",
        facts=[("health_insurance_number", MAX.health_insurance_number)],
        closing="Mit freundlichen Grüßen\nIhre Gesundkasse BKK",
        seed=seed,
    )


def health_contribution(day: date, seed: int = 0) -> Doc:
    return notice(
        c.GESUNDKASSE,
        MAX,
        day,
        [("Versichertennummer", MAX.health_insurance_number)],
        "Ihr Zusatzbeitrag ab 1. Januar 2026",
        [
            "der Verwaltungsrat der Gesundkasse BKK hat beschlossen, den Zusatzbeitrag zum 01.01.2026 von 2,5 % auf 2,9 % anzuheben. Ihr Arbeitgeber zieht den geänderten Beitrag automatisch ab.",
            "Sie haben wegen der Erhöhung ein Sonderkündigungsrecht bis zum Ablauf des Monats, für den der Zusatzbeitrag erstmals erhoben wird. Eine Übersicht der Zusatzbeiträge aller Krankenkassen finden Sie beim Spitzenverband.",
        ],
        cls="contribution-change",
        document_type="Mitteilung",
        title="Zusatzbeitrag 2026",
        facts=[("health_insurance_number", MAX.health_insurance_number)],
        seed=seed,
    )


def family_insurance(day: date, seed: int = 0) -> Doc:
    return notice(
        c.GESUNDKASSE,
        MAX,
        day,
        [("Versichertennummer", MAX.health_insurance_number)],
        "Familienversicherung Ihrer Tochter Lena",
        [
            f"die Familienversicherung für Ihre Tochter Lena Mustermann, geboren am {german(LENA.born)}, wurde zum 01.03.2025 überprüft und besteht weiter.",
            f"Lenas Krankenversichertennummer: {LENA.health_insurance_number}. Die neue Gesundheitskarte erhalten Sie in den nächsten Tagen.",
        ],
        cls="family-insurance",
        document_type="Mitteilung",
        title="Familienversicherung Lena",
        facts=[
            ("health_insurance_number", MAX.health_insurance_number),
            ("health_insurance_number", LENA.health_insurance_number),
        ],
        seed=seed,
    )


def pension_statement(day: date, seed: int = 0) -> Doc:
    s = c.VORSORGE
    bill = letter(
        s,
        ERIKA,
        day,
        [("Vertragsnummer", PENSION_POLICY), ("Tarif", "Vorsorge Rente Flex")],
        "Ihre jährliche Standmitteilung",
        seed=seed,
    )
    bill.paragraph(greeting(ERIKA))
    bill.paragraph(
        f"wie jedes Jahr informieren wir Sie über den Stand Ihrer privaten Rentenversicherung zum 31.12.{day.year - 1}."
    )
    bill.pairs(
        [
            ("Versicherte Person", "Erika Musterfrau"),
            ("Beitrag", "100,00 EUR monatlich"),
            ("Gezahlte Beiträge bisher", "8.200,00 EUR"),
            ("Vertragsguthaben", "8.912,44 EUR"),
            ("Garantierte Monatsrente ab 01.12.2053", "214,30 EUR"),
            ("Mögliche Monatsrente (Prognose)", "301,80 EUR"),
        ],
        label_width=80,
    )
    bill.paragraph(
        "Die Prognose ist nicht garantiert. Sie hängt von der Entwicklung der Kapitalmärkte und der Überschussbeteiligung ab.",
        size=9,
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Vorsorge Leben AG")
    return doc(
        "pension-statement",
        "Versicherung",
        s,
        day,
        f"Standmitteilung Rentenversicherung {day.year - 1}",
        bill,
        recipient="erika",
        fields={"Versicherungsnummer": PENSION_POLICY},
        facts=[("contract_number", PENSION_POLICY)],
        download=f"Standmitteilung_{day.year - 1}.pdf",
    )


__all__ = ["ERIKA"]
