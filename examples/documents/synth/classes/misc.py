"""Everyday life: the sports club, a donation receipt, train and plane tickets, a hotel bill in
English, a lawyer's letters, the music school, the primary school, an adult education course,
advertising, a software licence."""

from datetime import date, datetime
from decimal import Decimal

from synth import contacts as c
from synth import ids
from synth.classes.common import ERIKA, MAX, greeting, letter, lines_table, notice
from synth.codes import code
from synth.document import Doc, doc, money
from synth.fonts import MONO, SANS, SANS_BOLD, Font
from synth.household import LENA, MAX_IBAN, street
from synth.layout import GREY, WHITE, Page
from synth.letter import Column, _tint, logo
from synth.numbers import MONTHS, euro, german
from synth.screen import confirmation

D = Decimal
TSV_MEMBER = "1890-3317"
TSV_CREDITOR = ids.creditor_id("00000189012")


def club_membership(day: date, seed: int = 0) -> Doc:
    return notice(
        c.TSV,
        MAX,
        day,
        [("Mitgliedsnummer", TSV_MEMBER)],
        "Willkommen im TSV Musterstadt 1890!",
        [
            f"wir freuen uns, Lena als neues Mitglied in der Abteilung Schwimmen begrüßen zu dürfen. Die Familienmitgliedschaft wurde zum {german(day)} auf Lena erweitert.",
            "Training ist dienstags und donnerstags von 16:30 bis 17:30 Uhr im Hallenbad Musterstadt. Bitte Badekappe nicht vergessen!",
        ],
        pairs=[
            ("Mitgliedsnummer", TSV_MEMBER),
            ("Mitgliedschaft", "Familie (2 Erwachsene, 1 Kind)"),
            ("Jahresbeitrag", "168,00 EUR"),
            (
                "Einzug",
                f"jährlich am 15.01. (Gläubiger-ID {TSV_CREDITOR}, Mandatsreferenz TSV-3317)",
            ),
        ],
        cls="club-membership",
        document_type="Bescheinigung",
        title="Mitgliedschaft TSV Lena",
        facts=[
            ("membership_number", TSV_MEMBER),
            ("creditor_id", TSV_CREDITOR),
            ("mandate_reference", "TSV-3317"),
        ],
        sign=("Gisela Brandt", "1. Vorsitzende"),
        seed=seed,
    )


def club_fee(day: date, seed: int = 0) -> Doc:
    s = c.TSV
    bill = letter(
        s,
        MAX,
        day,
        [("Mitgliedsnummer", TSV_MEMBER), ("Rechnungsnummer", f"B-{day.year}-3317")],
        f"Beitragsrechnung {day.year}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(f"für das Jahr {day.year} berechnen wir Ihnen folgende Mitgliedsbeiträge:")
    bill.table(
        [Column("Position", 120), Column("EUR", 45, "right")],
        [
            ("Familienbeitrag", "144,00"),
            ("Abteilungsbeitrag Schwimmen (Lena)", "24,00"),
            ("Summe", "168,00"),
        ],
        bold_rows=(2,),
        shade=True,
    )
    bill.paragraph(
        f"Der Betrag wird am 15.01.{day.year} per Lastschrift eingezogen (Gläubiger-ID {TSV_CREDITOR}, Mandatsreferenz TSV-3317). Der Verein ist als gemeinnützig anerkannt; Beiträge sind nicht als Spende absetzbar."
    )
    bill.paragraph("Sportliche Grüße\nTSV Musterstadt 1890 e.V. – Kassenwart")
    return doc(
        "club-fee",
        "Rechnung",
        s,
        day,
        f"TSV Beitrag {day.year}",
        bill,
        fields={
            "Betrag": money("168.00"),
            "Rechnungsnummer": f"B-{day.year}-3317",
            "Bezugszeitraum": str(day.year),
        },
        facts=[
            ("membership_number", TSV_MEMBER),
            ("invoice_number", f"B-{day.year}-3317"),
            ("creditor_id", TSV_CREDITOR),
            ("mandate_reference", "TSV-3317"),
        ],
        download=f"Beitragsrechnung_{day.year}.pdf",
    )


def donation_receipt(year: int, day: date, amount: Decimal, seed: int = 0) -> Doc:
    s = c.TIERHEIM
    bill = letter(
        s,
        MAX,
        day,
        [],
        f"Bestätigung über Geldzuwendungen im Sinne des § 10b EStG für {year}",
        seed=seed,
    )
    bill.paragraph(
        "Bestätigung über Geldzuwendungen an eine der in § 5 Abs. 1 Nr. 9 KStG bezeichneten Körperschaften."
    )
    bill.pairs(
        [
            ("Name und Anschrift des Zuwendenden", f"Max Mustermann, {', '.join(street(day))}"),
            ("Betrag der Zuwendung", f"{euro(amount)} EUR"),
            ("in Buchstaben", "einhundert Euro" if amount == 100 else "einhundertfünfzig Euro"),
            ("Tag der Zuwendung", f"20.12.{year}"),
        ],
        label_width=75,
    )
    bill.paragraph("Es handelt sich nicht um den Verzicht auf Erstattung von Aufwendungen.")
    bill.paragraph(
        f"Wir sind wegen Förderung des Tierschutzes nach dem letzten uns zugegangenen Freistellungsbescheid des Finanzamts Musterstadt, StNr. {s.tax_number}, vom 12.04.{year - 1} nach § 5 Abs. 1 Nr. 9 KStG von der Körperschaftsteuer befreit. Es wird bestätigt, dass die Zuwendung nur zur Förderung des Tierschutzes verwendet wird.",
        size=9,
    )
    bill.signature(f"Musterstadt, {german(day)}", "Dagmar Kühn", "Schatzmeisterin")
    bill.paragraph(
        "Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige Zuwendungsbestätigung erstellt, haftet für die entgangene Steuer (§ 10b Abs. 4 EStG).",
        size=7.5,
    )
    return doc(
        "donation-receipt",
        "Spendenbescheinigung",
        s,
        day,
        f"Spendenbescheinigung {year}",
        bill,
        fields={"Betrag": money(amount), "Bezugszeitraum": str(year)},
        facts=[("tax_number", s.tax_number)],
        download=f"Zuwendungsbestaetigung_{year}.pdf",
    )


def train_ticket(
    day: date,
    travel: datetime,
    origin: str,
    destination: str,
    price: Decimal,
    number: str,
    travellers: str = "1 Erwachsener",
) -> Doc:
    """A print-at-home ticket of the RegioBahn: a band, the trip, an Aztec code."""
    s = c.REGIOBAHN
    page = Page()
    accent = s.style.accent
    page.rect(0, 0, 210, 26, fill=accent)
    logo(page, "triangle", 15, 6, 14, WHITE, "")
    page.text(35, 17, "RegioBahn Online-Ticket", SANS_BOLD, 16, color=WHITE)
    page.text(195, 17, f"Auftragsnummer {number}", SANS, 10, "right", WHITE)
    page.text(15, 42, f"{origin} – {destination}", SANS_BOLD, 18)
    page.text(
        15,
        50,
        f"Fahrt am {travel:%d.%m.%Y}, ab {travel:%H:%M} Uhr · {travellers} · 2. Klasse",
        SANS,
        11,
    )
    page.rect(15, 58, 120, 62, stroke=(200, 200, 200), width=0.5)
    rows = [
        ("Ticketnummer", number),
        ("Reisender", "Max Mustermann"),
        ("Ausweis", "Bankkarte endet auf 6789"),
        ("Gültigkeit", f"{travel:%d.%m.%Y} bis {travel:%d.%m.%Y} 23:59"),
        ("Zugbindung", "keine (Flexpreis)"),
        ("Preis", f"{euro(price)} EUR inkl. 7 % MwSt."),
    ]
    y = 66.0
    for label, value in rows:
        page.text(18, y, label, SANS, 9, color=GREY)
        page.text(55, y, value, SANS_BOLD, 9.5)
        y += 8.5
    symbol = code(
        f"RB:{number}:{travel:%Y%m%d%H%M}:{origin[:3].upper()}-{destination[:3].upper()}:MUSTERMANN/MAX",
        "Aztec",
    )
    page.picture(145, 58, 50, 50, symbol)
    page.text(170, 113, "Bitte Code nicht knicken", SANS, 7, "center", GREY)
    page.text(15, 135, "Ihre Verbindung", SANS_BOLD, 11)
    legs = [
        (f"{travel:%H:%M}", origin, "RE 4412", "Gleis 3"),
        (f"{travel.hour + 1:02d}:{(travel.minute + 47) % 60:02d}", destination, "", "Gleis 1"),
    ]
    y = 145.0
    for time, station, train, track in legs:
        page.text(15, y, time, SANS_BOLD, 10)
        page.text(35, y, station, SANS, 10)
        page.text(120, y, train, SANS, 10)
        page.text(195, y, track, SANS, 10, "right")
        y += 8
    page.text(
        15,
        280,
        "Es gelten die Beförderungsbedingungen der RegioBahn Musterland. Dieses Ticket ist nur mit dem angegebenen Ausweis gültig.",
        SANS,
        7,
        color=GREY,
    )
    page.text(
        15, 285, f"{s.name} · {s.street} · {s.city} · USt-IdNr. {s.vat_id}", SANS, 7, color=GREY
    )
    return doc(
        "train-ticket",
        "Ticket",
        s,
        day,
        f"Bahnticket {origin} – {destination} {travel:%d.%m.%Y}",
        [page],
        fields={"Betrag": money(price)},
        facts=[("ticket_number", number), ("vat_id", s.vat_id)],
        codes=["Aztec"],
        layout="ticket",
        download=f"Ticket_{number}.pdf",
    )


def train_ticket_screen(
    day: date, travel: datetime, origin: str, destination: str, price: Decimal, number: str
) -> Doc:
    page = confirmation(
        c.REGIOBAHN,
        "Buchung erfolgreich",
        "Ihr Ticket ist gebucht. Sie finden es in der App und in Ihrem Postfach.",
        [
            ("Auftragsnummer", number),
            ("Strecke", f"{origin} → {destination}"),
            ("Hinfahrt", f"{travel:%d.%m.%Y}, {travel:%H:%M} Uhr"),
            ("Reisende", "1 Erwachsener, 1 Kind (6–14)"),
            ("Preis", f"{euro(price)} €"),
        ],
        nav=("Reiseauskunft", "Tickets", "Meine Reisen", "Anmelden"),
        note="Kinder bis 14 Jahre fahren in Begleitung kostenlos.",
    )
    return doc(
        "train-ticket",
        "Ticket",
        c.REGIOBAHN,
        day,
        f"Bahnbuchung {origin} – {destination}",
        [page],
        fields={"Betrag": money(price)},
        facts=[("order_number", number)],
        layout="screen",
        url="https://www.regiobahn.example/buchung/bestaetigung",
    )


def flight_booking(day: date, booking: str, ticket: str) -> Doc:
    s = c.SKYNORD
    bill = letter(
        s,
        MAX,
        day,
        [("Booking reference", booking), ("Ticket no.", ticket)],
        f"Your booking confirmation {booking}",
        date_label="Issued",
    )
    bill.page_word, bill.of_word = "Page", "of"
    bill.paragraph("Dear Mr Mustermann,")
    bill.paragraph("thank you for flying with SkyNord Airlines. Your booking is confirmed.")
    bill.table(
        [
            Column("Flight", 25),
            Column("Date", 25),
            Column("From", 40),
            Column("To", 40),
            Column("Dep", 15),
            Column("Arr", 20),
        ],
        [
            ("SN 1452", "10 Aug 2026", "Hamburg (HAM)", "Bristol (BRS)", "07:15", "08:05"),
            ("SN 1453", "14 Aug 2026", "Bristol (BRS)", "Hamburg (HAM)", "18:40", "21:25"),
        ],
        shade=True,
    )
    bill.pairs(
        [
            ("Passengers", "MUSTERMANN/MAX MR, MUSTERFRAU/ERIKA MRS, MUSTERMANN/LENA MISS"),
            ("Fare", "EUR 612.40 (3 passengers, incl. taxes and fees)"),
            ("Baggage", "1 x 23 kg per passenger"),
            ("Payment", "Credit card ending 4242"),
        ],
        label_width=35,
    )
    bill.paragraph(
        "Online check-in opens 30 hours before departure. Please carry a valid passport or ID card."
    )
    bill.paragraph("Kind regards,\nSkyNord Airlines Customer Service")
    return doc(
        "flight-booking",
        "Ticket",
        s,
        day,
        f"Flight booking {booking}",
        bill,
        language="en",
        recipient="max+erika",
        fields={"Betrag": money("612.40")},
        facts=[("ticket_number", ticket)],
        download=f"Booking_{booking}.pdf",
    )


def boarding_pass(day: date, ticket: str, booking: str) -> Doc:
    s = c.SKYNORD
    page = Page(210, 99)
    page.rect(0, 0, 210, 14, fill=s.style.accent)
    page.text(8, 9.5, "SkyNord Airlines · BOARDING PASS", SANS_BOLD, 12, color=WHITE)
    rows = [
        ("Name", "MUSTERMANN/MAX MR"),
        ("From", "HAMBURG HAM"),
        ("To", "BRISTOL BRS"),
        ("Flight", "SN 1452"),
        ("Date", "10AUG26"),
        ("Boarding", "06:35"),
        ("Gate", "B14"),
        ("Seat", "14C"),
        ("E-ticket", ticket),
        ("Booking", booking),
    ]
    for index, (label, value) in enumerate(rows):
        x = 8 + (index % 2) * 60
        y = 24 + (index // 2) * 11
        page.text(x, y, label.upper(), SANS, 6.5, color=GREY)
        page.text(x, y + 4.5, value, SANS_BOLD, 10)
    symbol = code(f"M1MUSTERMANN/MAX MR   {booking} HAMBRSSN 1452 222Y014C0047 100", "PDF417")
    page.picture(132, 24, 70, 70 * symbol.height / symbol.width, symbol)
    page.text(8, 94, "Gate closes 20 minutes before departure.", SANS, 7, color=GREY)
    return doc(
        "boarding-pass",
        "Ticket",
        s,
        day,
        "Boarding pass SN 1452",
        [page],
        language="en",
        facts=[("ticket_number", ticket, None, False)],
        codes=["PDF417"],
        layout="ticket",
        download="BoardingPass_SN1452.pdf",
    )


def hotel_invoice(day: date, seed: int = 0) -> Doc:
    s = c.HOTEL
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Invoice no.", "HV-26-08812"),
            ("Room", "214"),
            ("Arrival", "10 Aug 2026"),
            ("Departure", "14 Aug 2026"),
        ],
        "Invoice",
        date_label="Date",
        seed=seed,
    )
    bill.page_word, bill.of_word = "Page", "of"
    bill.recipient = ("Mr Max Mustermann", *street(day), "Germany")
    bill.paragraph("Thank you for staying with us. We hope to welcome you again soon.")
    items = [
        ("Family room, bed & breakfast", D("4"), "nights", D("162.50")),
        ("Dinner, restaurant", D("1"), "", D("78.40")),
        ("Parking", D("4"), "days", D("12.00")),
    ]
    _net, tax, gross = lines_table(bill, items, english=True, rate=20, gross_prices=True)
    bill.totals(
        [
            ("Total (GBP)", f"{gross:.2f}"),
            ("of which VAT 20 %", f"{tax:.2f}"),
            ("Paid by card", f"{-gross:.2f}"),
            ("Balance", "0.00"),
        ]
    )
    bill.paragraph("Harbour View Hotel Ltd · VAT Reg. No. GB 987 6543 21")
    return doc(
        "hotel-invoice",
        "Rechnung",
        s,
        day,
        "Hotel invoice Bristol",
        bill,
        language="en",
        fields={"Betrag": money(gross, "GBP"), "Rechnungsnummer": "HV-26-08812"},
        facts=[("invoice_number", "HV-26-08812")],
        download="Invoice_HV-26-08812.pdf",
    )


LAW_FILE = "112/25 KL03"


def lawyer_letter(day: date, *, second: bool = False, seed: int = 0) -> Doc:
    s = c.ANWALT
    subject = "Mustermann ./. Hausverwaltung Klein – Rückzahlung der Mietkaution"
    if not second:
        paragraphs = [
            "in der oben genannten Angelegenheit hat uns Herr Werner Klein, Hausverwaltung Klein, mit der Wahrnehmung seiner rechtlichen Interessen beauftragt. Eine auf uns lautende Vollmacht liegt vor.",
            "Unser Mandant hat die Mietkaution mit Schreiben vom 15.10.2025 abgerechnet. Sie haben der Abrechnung widersprochen, soweit ein Betrag von 48,00 EUR für die Reparatur des Türschlosses der Kellertür einbehalten wurde. Unser Mandant hält an dem Einbehalt fest; das Schloss war bei der Übergabe beschädigt, wie das Übergabeprotokoll ausweist.",
            "Wir regen an, die Angelegenheit ohne weitere Kosten zu erledigen, und erwarten Ihre Stellungnahme bis zum 21.11.2025.",
        ]
        letter_day = None
    else:
        paragraphs = [
            "wir danken für Ihr Schreiben vom 18.11.2025. Nach Rücksprache mit unserem Mandanten ist dieser bereit, den Betrag von 48,00 EUR ohne Anerkennung einer Rechtspflicht zu erstatten, um die Angelegenheit abzuschließen.",
            f"Der Betrag wird in den nächsten Tagen auf Ihr Konto {MAX_IBAN} überwiesen. Damit betrachten wir die Angelegenheit als erledigt.",
        ]
        letter_day = date(2025, 11, 18)
    info = [("Unser Zeichen", LAW_FILE), ("Sachbearbeiterin", "RAin Dr. Julia Meier")]
    if second:
        info.insert(0, ("Ihr Zeichen", "MM/K-2025"))
    facts = [("our_reference", LAW_FILE)]
    if second:
        facts += [
            ("your_reference", "MM/K-2025"),
            ("letter_date", german(letter_day)),
            ("iban", MAX_IBAN),
        ]
    return notice(
        s,
        MAX,
        day,
        info,
        subject,
        paragraphs,
        cls="lawyer-letter",
        document_type="Mitteilung",
        title="Anwaltsschreiben Kaution" + (" Erledigung" if second else ""),
        both=True,
        facts=facts,
        sign=("Dr. Julia Meier", "Rechtsanwältin"),
        seed=seed,
    )


def music_contract(day: date, seed: int = 0) -> Doc:
    return notice(
        c.MUSIKSCHULE,
        MAX,
        day,
        [("Vertragsnummer", "MSK-0912"), ("Schülerin", LENA.name)],
        "Unterrichtsvertrag Klavier",
        [
            f"wir freuen uns, Lena ab dem 15.09.{day.year} in unserer Musikschule zu unterrichten, und bestätigen die vereinbarten Bedingungen:"
        ],
        pairs=[
            ("Fach", "Klavier, Einzelunterricht 30 Minuten wöchentlich"),
            ("Lehrkraft", "Frau Mira Hollstein"),
            ("Unterrichtszeit", "mittwochs 15:30 Uhr"),
            ("Gebühr", "65,00 EUR monatlich, vierteljährlich 195,00 EUR"),
            ("Kündigung", "mit sechs Wochen Frist zum Quartalsende"),
            ("Mandatsreferenz", "MSK-0912"),
        ],
        after=[
            "In den Schulferien des Landes findet kein Unterricht statt; die Gebühr ist als Jahresgebühr in gleichen Raten berechnet."
        ],
        cls="music-contract",
        document_type="Vertrag",
        title="Musikschule Vertrag Lena",
        facts=[("contract_number", "MSK-0912"), ("mandate_reference", "MSK-0912")],
        fields={"Vertragsbeginn": f"{day.year}-09-15", "Betrag": money("195.00")},
        sign=("Klara Weiß", "Schulleitung"),
        seed=seed,
    )


def music_fee(day: date, seed: int = 0) -> Doc:
    return notice(
        c.MUSIKSCHULE,
        MAX,
        day,
        [("Vertragsnummer", "MSK-0912")],
        "Anpassung der Unterrichtsgebühren ab 1. Oktober 2026",
        [
            "nach drei Jahren stabiler Gebühren müssen wir die Unterrichtsgebühren wegen gestiegener Honorare und Raumkosten anpassen. Für Lenas Klavierunterricht gilt ab dem 01.10.2026:"
        ],
        pairs=[
            ("Monatlich bisher", "65,00 EUR"),
            ("Monatlich neu", "69,00 EUR"),
            ("Quartal neu", "207,00 EUR"),
        ],
        after=[
            "Sie können den Vertrag wegen der Anpassung außerordentlich zum 30.09.2026 kündigen. Wir würden uns freuen, wenn Lena weiter bei uns bleibt."
        ],
        cls="price-change",
        document_type="Mitteilung",
        title="Musikschule Gebühren 2026",
        facts=[("contract_number", "MSK-0912")],
        fields={"Betrag": money("207.00")},
        sign=("Klara Weiß", "Schulleitung"),
        seed=seed,
    )


def school_letter(day: date, subject: str, paragraphs: list[str], seed: int = 0) -> Doc:
    s = c.SCHULE
    bill = letter(
        s, MAX, day, [("Klasse", "3b" if day.year == 2025 else "4b")], subject, both=True, seed=seed
    )
    bill.paragraph("Liebe Eltern der Klasse " + ("3b" if day.year == 2025 else "4b") + ",")
    for text in paragraphs:
        bill.paragraph(text)
    bill.signature("Herzliche Grüße", "Anke Sommer", "Klassenlehrerin")
    bill.paragraph(
        "-" * 60
        + "\nBitte abtrennen und bis Freitag zurückgeben:\nName des Kindes: ______________________   Unterschrift: ______________________",
        size=9,
    )
    return doc(
        "school-letter",
        "Mitteilung",
        s,
        day,
        f"Elternbrief {subject}",
        bill,
        recipient="max+erika",
        download=f"Elternbrief_{day:%Y%m%d}.pdf",
    )


def course_confirmation(day: date, seed: int = 0) -> Doc:
    s = c.VHS
    bill = letter(
        s,
        ERIKA,
        day,
        [
            ("Kursnummer", "26F-3104"),
            ("Kundennummer", "T-208811"),
            ("Rechnungsnummer", "VHS-2026-01877"),
        ],
        "Anmeldebestätigung und Rechnung: Spanisch A2 – Abendkurs",
        seed=seed,
    )
    bill.paragraph(greeting(ERIKA))
    bill.paragraph(
        "vielen Dank für Ihre Anmeldung. Ihr Platz im folgenden Kurs ist verbindlich reserviert:"
    )
    bill.pairs(
        [
            ("Kurs", "26F-3104 Spanisch A2 – Abendkurs"),
            ("Termine", "12 × dienstags, 19:00–20:30 Uhr, ab 03.02.2026"),
            ("Ort", "Bildungszentrum, Raum 2.14"),
            ("Kursleitung", "Carmen Ortega"),
        ]
    )
    bill.totals([("Kursgebühr", "132,00 EUR")])
    bill.paragraph(
        "Die Gebühr wird am 03.02.2026 von Ihrem Konto abgebucht. Ein Rücktritt ist bis 14 Tage vor Kursbeginn kostenfrei möglich."
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Volkshochschule Musterstadt")
    return doc(
        "course-confirmation",
        "Rechnung",
        s,
        day,
        "VHS Spanisch A2",
        bill,
        recipient="erika",
        fields={"Betrag": money("132.00"), "Rechnungsnummer": "VHS-2026-01877"},
        facts=[("invoice_number", "VHS-2026-01877"), ("customer_number", "T-208811")],
        download="Anmeldebestaetigung_26F-3104.pdf",
    )


def advert_solar(day: date) -> Doc:
    s = c.SONNENKRAFT
    page = Page()
    accent = s.style.accent
    page.rect(0, 0, 210, 80, fill=accent)
    page.text(105, 35, "Ihr Dach kann mehr!", SANS_BOLD, 34, "center", WHITE)
    page.text(105, 50, "Jetzt Solaranlage sichern – ab 0 € Anzahlung", SANS, 16, "center", WHITE)
    page.ellipse(150, 55, 45, 45, fill=(255, 255, 255))
    page.text(172.5, 76, "-30 %", SANS_BOLD, 22, "center", accent)
    page.text(172.5, 84, "nur bis 31.05.!", SANS, 9, "center", accent)
    y = 100
    page.text(25, y, "Sehr geehrte Familie Mustermann,", SANS, 11)
    for line in [
        "in Ihrer Straße haben sich schon viele Nachbarn für saubere Energie entschieden.",
        "Sparen Sie bis zu 80 % Ihrer Stromkosten – mit einer Photovoltaikanlage von Sonnenkraft.",
        "",
        "• Kostenlose Vor-Ort-Beratung",
        "• Montage in nur einem Tag",
        "• 25 Jahre Garantie",
    ]:
        y += 7
        page.text(25, y, line, SANS, 11)
    page.rect(25, y + 12, 160, 20, fill=_tint(accent, 0.8))
    page.text(105, y + 25, "Gratis-Hotline 0800 765 765", SANS_BOLD, 16, "center")
    page.picture(150, 230, 30, 30, code("https://www.sonnenkraft-solar.example/aktion?c=MS2026"))
    page.text(25, 240, "Gutscheincode: MS2026", MONO, 11)
    page.text(
        25,
        285,
        f"{s.name} · {s.street} · {s.city} · {s.register}. Sie erhalten diese Werbung, weil Sie keinen Widerspruch eingelegt haben.",
        SANS,
        6.5,
        color=GREY,
    )
    return doc(
        "advertising",
        "Werbung",
        s,
        day,
        "Werbung Solaranlage",
        [page],
        recipient="max+erika",
        codes=["QR Code"],
        layout="flyer",
        download="Werbung.pdf",
    )


def advert_prize(day: date, seed: int = 0) -> Doc:
    return notice(
        c.GEWINN,
        MAX,
        day,
        [("Gewinn-Nr.", "GB-7741-XZ")],
        "AMTLICHE GEWINNBENACHRICHTIGUNG – Sie haben 25.000 € gewonnen!*",
        [
            "herzlichen Glückwunsch! Bei unserer großen Jubiläumsziehung wurde Ihre Adresse als Hauptgewinner ermittelt. Um Ihren Gewinn anzufordern, senden Sie einfach den beiliegenden Abschnitt zusammen mit Ihrer Bestellung aus unserem Katalog zurück.",
            "Fordern Sie Ihren Gewinn bis zum 30.11. an – danach verfällt Ihr Anspruch!",
        ],
        after=[
            "* Teilnahmebedingungen: Der Hauptgewinn wird unter allen Einsendungen verlost. Die Benachrichtigung begründet keinen Anspruch. Keine Barauszahlung."
        ],
        cls="advertising",
        document_type="Werbung",
        title="Werbung Gewinnspiel",
        sign=("Holger Glück", "Gewinnabteilung"),
        seed=seed,
    )


def software_invoice(day: date, seed: int = 0) -> Doc:
    s = c.NORTHWIND
    bill = letter(
        s,
        MAX,
        day,
        [("Invoice no.", "NW-25-1188"), ("Order no.", "PO-77120"), ("Customer no.", "C-55102")],
        "Invoice NW-25-1188",
        date_label="Date",
        seed=seed,
    )
    bill.page_word, bill.of_word = "Page", "of"
    bill.recipient = ("Max Mustermann", *street(day), "Germany")
    bill.paragraph("Dear Max Mustermann,")
    bill.paragraph("thank you for your order. Your licence key has been sent separately.")
    net, tax, gross = lines_table(
        bill,
        [
            ("Northwind Office Planner, personal licence (1 year)", D("1"), "", D("39.00")),
            ("Priority support", D("1"), "", D("9.00")),
        ],
        english=True,
        rate=20,
    )
    bill.totals(
        [("Net", f"GBP {net:.2f}"), ("VAT 20 %", f"GBP {tax:.2f}"), ("Total", f"GBP {gross:.2f}")]
    )
    bill.paragraph("Paid by credit card. Northwind Software Ltd, VAT Reg. No. GB 123 4567 89.")
    return doc(
        "software-invoice",
        "Rechnung",
        s,
        day,
        "Northwind invoice NW-25-1188",
        bill,
        language="en",
        fields={"Betrag": money(gross, "GBP"), "Rechnungsnummer": "NW-25-1188"},
        facts=[
            ("invoice_number", "NW-25-1188"),
            ("order_number", "PO-77120"),
            ("customer_number", "C-55102"),
        ],
        download="Invoice_NW-25-1188.pdf",
    )


def licence_certificate(day: date) -> Doc:
    s = c.NORTHWIND
    page = Page(297, 210)
    page.rect(10, 10, 277, 190, stroke=s.style.accent, width=2.5)
    page.rect(14, 14, 269, 182, stroke=s.style.accent, width=0.6)
    page.text(
        148.5, 50, "Certificate of Licence", Font("serif", bold=True), 30, "center", s.style.accent
    )
    page.text(148.5, 70, "Northwind Office Planner – Personal Edition", Font("serif"), 16, "center")
    page.text(148.5, 95, "licensed to", Font("serif", italic=True), 12, "center", GREY)
    page.text(148.5, 108, "Max Mustermann", Font("serif", bold=True), 22, "center")
    page.text(
        148.5,
        130,
        f"Licence key NWOP-7Q2K-88XD-41MM · valid until {day.replace(year=day.year + 1):%d %B %Y}",
        MONO,
        11,
        "center",
    )
    page.text(
        148.5, 140, "Invoice no. NW-25-1188 · Order no. PO-77120", Font("serif"), 10, "center", GREY
    )
    page.text(60, 175, "Northwind Software Ltd", Font("serif"), 10, "center", GREY)
    page.text(237, 175, f"{day:%d %B %Y}", Font("serif"), 10, "center", GREY)
    return doc(
        "licence-certificate",
        "Bescheinigung",
        s,
        day,
        "Lizenzzertifikat Northwind",
        [page],
        language="en",
        facts=[("invoice_number", "NW-25-1188", "refers")],
        layout="certificate",
        download="Licence_Certificate.pdf",
    )


__all__ = ["MONTHS", "SANS"]
