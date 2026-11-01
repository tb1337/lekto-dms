"""Housing: the lease of the new flat and the cooperative's membership, the landlord's
confirmation for the registration office, utility statements, a rent increase; the old
landlord's confirmation of the notice and the deposit."""

from datetime import date
from decimal import Decimal

from synth import contacts as c
from synth.classes.common import ERIKA, MAX, greeting, letter, notice
from synth.document import Doc, doc, money
from synth.fonts import HAND, SANS, SANS_BOLD
from synth.household import LENA, MAX_IBAN
from synth.layout import GREY, Page
from synth.letter import Column
from synth.numbers import euro, german

D = Decimal
LEASE = "MV-2025-08-1204"
MEMBER = "40871"
OLD_TENANT = "BW5-EG-links"


def lease(day: date, seed: int = 0) -> Doc:
    s = c.WOHNBAU
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Vertragsnummer", LEASE),
            ("Mitgliedsnummer", MEMBER),
            ("Objekt", "Lindenallee 12, 2. OG rechts"),
        ],
        "Dauernutzungsvertrag (Mietvertrag) für Wohnraum",
        both=True,
        seed=seed,
    )
    bill.paragraph(
        "Zwischen der Wohnbau Musterstadt eG (Genossenschaft) und Herrn Max Mustermann und Frau Erika Musterfrau (Mitglieder) wird folgender Dauernutzungsvertrag geschlossen:"
    )
    clauses = [
        (
            "§ 1 Mietsache",
            "Die Genossenschaft überlässt den Mitgliedern die Wohnung im 2. Obergeschoss rechts des Hauses Lindenallee 12, 12345 Musterstadt, bestehend aus 4 Zimmern, Küche, Bad, Gäste-WC, Flur, Balkon und einem Kellerraum (Nr. 7). Die Wohnfläche beträgt 92,4 m².",
        ),
        (
            "§ 2 Mietzeit",
            "Das Nutzungsverhältnis beginnt am 01.08.2025 und läuft auf unbestimmte Zeit. Die Kündigungsfrist für die Mitglieder beträgt drei Monate.",
        ),
        ("§ 3 Miete und Betriebskosten", "Die monatliche Miete setzt sich wie folgt zusammen:"),
    ]
    for heading, text in clauses:
        bill.heading(heading, size=10)
        bill.paragraph(text)
    bill.table(
        [Column("Bestandteil", 120), Column("EUR monatlich", 45, "right")],
        [
            ("Grundmiete (92,4 m² × 8,10 EUR)", "748,44"),
            ("Vorauszahlung Betriebskosten", "185,00"),
            ("Vorauszahlung Heizung und Warmwasser", "98,56"),
            ("Gesamtmiete", "1.032,00"),
        ],
        bold_rows=(3,),
        shade=True,
    )
    more = [
        (
            "§ 4 Zahlung",
            f"Die Miete ist monatlich im Voraus, spätestens am dritten Werktag, auf das Konto der Genossenschaft {s.iban} zu zahlen.",
        ),
        (
            "§ 5 Genossenschaftsanteile",
            f"Die Mitglieder haben drei Geschäftsanteile zu je 300,00 EUR gezeichnet (Mitgliedsnummer {MEMBER}). Eine Mietkaution wird nicht erhoben.",
        ),
        (
            "§ 6 Schönheitsreparaturen",
            "Die Schönheitsreparaturen während der Mietzeit übernehmen die Mitglieder. Die Wohnung wird renoviert übergeben.",
        ),
        (
            "§ 7 Tierhaltung",
            "Die Haltung eines Hundes (Bello, Mischling) ist genehmigt. Weitere Tiere bedürfen der Zustimmung.",
        ),
        (
            "§ 8 Hausordnung",
            "Die Hausordnung ist Bestandteil dieses Vertrags. Die Mitglieder bestätigen ihren Erhalt.",
        ),
        (
            "§ 9 Schlüssel",
            "Die Mitglieder erhalten zwei Haustür-, zwei Wohnungs- und einen Briefkastenschlüssel.",
        ),
        (
            "§ 10 Sonstiges",
            "Änderungen und Ergänzungen dieses Vertrags bedürfen der Textform. Sollte eine Bestimmung unwirksam sein, bleibt der Vertrag im Übrigen wirksam.",
        ),
    ]
    for heading, text in more:
        bill.heading(heading, size=10)
        bill.paragraph(text)
    bill.space(4)
    bill.signature(
        f"Musterstadt, {german(day)}", "Ingrid Hoffmann", "Vorstand Wohnbau Musterstadt eG"
    )
    bill.signature("Die Mitglieder:", "Max Mustermann, Erika Musterfrau")
    return doc(
        "lease",
        "Vertrag",
        s,
        day,
        "Mietvertrag Lindenallee 12",
        bill,
        recipient="max+erika",
        fields={"Vertragsbeginn": "2025-08-01", "Betrag": money("1032.00")},
        facts=[("contract_number", LEASE), ("membership_number", MEMBER), ("iban", s.iban)],
        download="Mietvertrag_Lindenallee12.pdf",
    )


def membership(day: date, seed: int = 0) -> Doc:
    return notice(
        c.WOHNBAU,
        MAX,
        day,
        [("Mitgliedsnummer", MEMBER)],
        "Bestätigung Ihrer Mitgliedschaft",
        [
            "herzlich willkommen in unserer Genossenschaft! Der Vorstand hat Ihre Beitrittserklärung angenommen. Ihre Mitgliedschaft ist im Mitgliederverzeichnis eingetragen."
        ],
        pairs=[
            ("Mitglieder", "Max Mustermann, Erika Musterfrau"),
            ("Mitgliedsnummer", MEMBER),
            ("Geschäftsanteile", "3 × 300,00 EUR = 900,00 EUR"),
            ("Eintrittsgeld", "25,00 EUR"),
            ("Fällig", f"bis {german(date(2025, 7, 15))}"),
        ],
        after=[
            f"Bitte überweisen Sie den Betrag von 925,00 EUR auf unser Konto {c.WOHNBAU.iban} mit dem Verwendungszweck „Anteile {MEMBER}“."
        ],
        cls="membership",
        document_type="Bescheinigung",
        title="Mitgliedschaft Wohnbau",
        both=True,
        facts=[("membership_number", MEMBER), ("iban", c.WOHNBAU.iban)],
        fields={"Betrag": money("925.00"), "Fällig am": "2025-07-15"},
        sign=("Paul Wagner", "Vorstand"),
        seed=seed,
        download="Mitgliedschaft.pdf",
    )


def landlord_confirmation(day: date) -> Doc:
    """The landlord's confirmation (Wohnungsgeberbestätigung) for the registration office, a
    form filled in partly by hand."""
    s = c.WOHNBAU
    page = Page()
    page.text(25, 25, "Wohnungsgeberbestätigung", SANS_BOLD, 16)
    page.text(25, 31, "nach § 19 Bundesmeldegesetz (BMG)", SANS, 9, color=GREY)
    rows = [
        ("Name und Anschrift des Wohnungsgebers", f"{s.name}, {s.street}, {s.city}"),
        ("Art des meldepflichtigen Vorgangs", "Einzug"),
        ("Datum des Einzugs", "01.08.2025"),
        ("Anschrift der Wohnung", "Lindenallee 12, 2. OG rechts, 12345 Musterstadt"),
        ("Namen der meldepflichtigen Personen", f"Max Mustermann, Erika Musterfrau, {LENA.name}"),
    ]
    y = 46.0
    for label, value in rows:
        page.text(25, y, label, SANS, 8.5, color=GREY)
        page.rect(25, y + 2, 160, 10, stroke=(120, 120, 120), width=0.4)
        page.text(28, y + 9, value, HAND, 13, color=(20, 40, 120))
        y += 19
    page.text(
        25,
        y + 4,
        "Ich bestätige mit meiner Unterschrift den Ein- bzw. Auszug der oben genannten Person(en) in die",
        SANS,
        9,
    )
    page.text(
        25,
        y + 9,
        "bezeichnete Wohnung. Es ist verboten, eine Wohnanschrift anzubieten, ohne dass ein Einzug beabsichtigt ist.",
        SANS,
        9,
    )
    page.text(25, y + 30, f"Musterstadt, {german(day)}", HAND, 13, color=(20, 40, 120))
    page.text(115, y + 30, "I. Hoffmann", HAND, 17, color=(20, 40, 120))
    page.line((25, y + 33), (90, y + 33), width=0.3)
    page.line((110, y + 33), (185, y + 33), width=0.3)
    page.text(25, y + 37, "Ort, Datum", SANS, 7.5, color=GREY)
    page.text(110, y + 37, "Unterschrift des Wohnungsgebers", SANS, 7.5, color=GREY)
    return doc(
        "landlord-confirmation",
        "Bescheinigung",
        s,
        day,
        "Wohnungsgeberbestätigung",
        [page],
        recipient="max+erika",
        layout="form",
        download="Wohnungsgeberbestaetigung.pdf",
    )


def utility_statement(
    sender,
    day: date,
    start: date,
    end: date,
    costs: list[tuple[str, str, Decimal]],
    advances: Decimal,
    *,
    contract: str,
    seed: int = 0,
) -> Doc:
    """A statement of the operating costs (Betriebskostenabrechnung) for a period."""
    total = sum((share for _, _, share in costs), D("0"))
    rest = total - advances
    bill = letter(
        sender,
        MAX,
        day,
        [("Vertragsnummer", contract), ("Abrechnungszeitraum", f"{german(start)} – {german(end)}")],
        f"Betriebskostenabrechnung {german(start)} – {german(end)}",
        both=True,
        seed=seed,
    )
    bill.paragraph(greeting(MAX, both=True))
    bill.paragraph(
        "anbei erhalten Sie die Abrechnung der Betriebs- und Heizkosten für den oben genannten Zeitraum. Die Belege können nach Terminvereinbarung eingesehen werden."
    )
    bill.table(
        [
            Column("Kostenart", 70),
            Column("Verteilerschlüssel", 60),
            Column("Ihr Anteil EUR", 35, "right"),
        ],
        [(name, key, euro(share)) for name, key, share in costs],
        shade=True,
    )
    bill.totals(
        [
            ("Ihre Kosten", euro(total)),
            ("Ihre Vorauszahlungen", euro(-advances)),
            ("Nachzahlung" if rest > 0 else "Guthaben", f"{euro(abs(rest))} EUR"),
        ]
    )
    if rest > 0:
        bill.paragraph(
            f"Bitte überweisen Sie die Nachzahlung innerhalb von 30 Tagen auf unser Konto {sender.iban}."
        )
    else:
        bill.paragraph(f"Das Guthaben überweisen wir auf Ihr Konto {MAX_IBAN}.")
    bill.paragraph(f"Mit freundlichen Grüßen\n{sender.head_name}")
    return doc(
        "utility-statement",
        "Abrechnung",
        sender,
        day,
        f"Betriebskostenabrechnung {start.year}",
        bill,
        recipient="max+erika",
        fields={
            "Betrag": money(abs(rest)),
            "Bezugszeitraum": f"{start.isoformat()}/{end.isoformat()}",
        },
        facts=[("contract_number", contract)] + ([("iban", sender.iban)] if sender.iban else []),
        download=f"Betriebskostenabrechnung_{start.year}.pdf",
    )


def rent_increase(day: date, seed: int = 0) -> Doc:
    return notice(
        c.WOHNBAU,
        MAX,
        day,
        [("Vertragsnummer", LEASE), ("Mitgliedsnummer", MEMBER)],
        "Anpassung der Nutzungsgebühr nach § 558 BGB",
        [
            "nach § 558 BGB kann der Vermieter die Zustimmung zu einer Erhöhung der Miete bis zur ortsüblichen Vergleichsmiete verlangen. Der Mietspiegel der Stadt Musterstadt 2026 weist für Ihre Wohnung eine Spanne von 8,20 bis 9,40 EUR/m² aus.",
            "Wir bitten Sie, der folgenden Anpassung bis zum Ende des zweiten Monats nach Zugang dieses Schreibens zuzustimmen:",
        ],
        pairs=[
            ("Grundmiete bisher", "748,44 EUR (8,10 EUR/m²)"),
            ("Grundmiete neu ab 01.12.2026", "785,40 EUR (8,50 EUR/m²)"),
            ("Gesamtmiete neu", "1.068,96 EUR"),
        ],
        after=[
            "Ihre Zustimmung können Sie formlos erklären oder die beigefügte Erklärung unterschrieben zurücksenden."
        ],
        cls="rent-increase",
        document_type="Mitteilung",
        title="Mieterhöhung Dezember 2026",
        both=True,
        facts=[("contract_number", LEASE), ("membership_number", MEMBER)],
        fields={"Betrag": money("1068.96")},
        sign=("Ingrid Hoffmann", "Vorstand"),
        seed=seed,
    )


def notice_confirmation(day: date, letter_day: date, seed: int = 0) -> Doc:
    return notice(
        c.HAUSVERWALTUNG,
        MAX,
        day,
        [("Objekt", "Birkenweg 5, EG links"), ("Mieter-Nr.", OLD_TENANT)],
        "Ihre Kündigung der Wohnung Birkenweg 5",
        [
            f"hiermit bestätigen wir den Eingang Ihres Schreibens vom {german(letter_day)}. Das Mietverhältnis endet fristgerecht zum 31.07.2025.",
            "Für die Wohnungsübergabe schlagen wir Donnerstag, den 31.07.2025, um 10:00 Uhr vor. Bitte bringen Sie alle Schlüssel mit. Über die Mietkaution rechnen wir nach Vorliegen der Betriebskostenabrechnung ab.",
        ],
        cls="termination",
        document_type="Kündigung",
        title="Kündigungsbestätigung Birkenweg",
        both=True,
        facts=[("letter_date", german(letter_day)), ("customer_number", OLD_TENANT, None, False)],
        sign=("Werner Klein", "Hausverwaltung Klein"),
        seed=seed,
    )


def deposit_statement(day: date, seed: int = 0) -> Doc:
    s = c.HAUSVERWALTUNG
    bill = letter(
        s,
        MAX,
        day,
        [("Objekt", "Birkenweg 5, EG links"), ("Mieter-Nr.", OLD_TENANT)],
        "Abrechnung der Mietkaution",
        both=True,
        seed=seed,
    )
    bill.paragraph(greeting(MAX, both=True))
    bill.paragraph(
        "nach Beendigung des Mietverhältnisses rechnen wir die Mietkaution wie folgt ab:"
    )
    bill.table(
        [Column("Position", 125), Column("EUR", 40, "right")],
        [
            ("Kaution (Barkaution vom 01.04.2019)", "1.950,00"),
            ("Zinsen 01.04.2019 – 31.07.2025", "14,82"),
            ("Nachzahlung Betriebskosten 01.01.–31.07.2025", "-86,40"),
            ("Reparatur Türschloss Kellertür", "-48,00"),
            ("Auszahlungsbetrag", "1.830,42"),
        ],
        bold_rows=(4,),
        shade=True,
    )
    bill.paragraph(
        f"Den Betrag von 1.830,42 EUR überweisen wir in den nächsten Tagen auf Ihr Konto {MAX_IBAN}."
    )
    bill.signature("Mit freundlichen Grüßen", "Werner Klein")
    return doc(
        "deposit-statement",
        "Abrechnung",
        s,
        day,
        "Kautionsabrechnung Birkenweg",
        bill,
        recipient="max+erika",
        fields={"Betrag": money("1830.42")},
        facts=[("customer_number", OLD_TENANT, None, False)],
        download="Kautionsabrechnung.pdf",
    )


COSTS_2024 = [
    ("Grundsteuer", "Wohnfläche 78 m²", D("162.40")),
    ("Wasser/Abwasser", "Personen 3", D("412.10")),
    ("Müllabfuhr", "Personen 3", D("198.00")),
    ("Hausreinigung", "Wohnfläche", D("240.30")),
    ("Gartenpflege", "Wohnfläche", D("88.50")),
    ("Versicherung", "Wohnfläche", D("131.70")),
    ("Heizung und Warmwasser", "Verbrauch 70 % / Fläche 30 %", D("1032.80")),
]
COSTS_2025 = [
    ("Grundsteuer", "Wohnfläche 92,4 m²", D("82.10")),
    ("Wasser/Abwasser", "Zähler", D("201.70")),
    ("Müllabfuhr", "Personen 3", D("92.50")),
    ("Aufzug", "Wohnfläche", D("71.30")),
    ("Hausreinigung", "Wohnfläche", D("118.40")),
    ("Allgemeinstrom", "Wohnfläche", D("22.80")),
    ("Versicherung", "Wohnfläche", D("64.90")),
    ("Heizung und Warmwasser", "Verbrauch 70 % / Fläche 30 %", D("402.60")),
]


__all__ = ["ERIKA"]
