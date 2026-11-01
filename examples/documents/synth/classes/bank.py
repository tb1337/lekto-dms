"""Banking: account statements (from online banking or the statement printer), credit card
statements, loan and building society statements, tax certificates, SEPA mandates."""

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from synth import contacts as c
from synth.classes.common import ERIKA, MAX, greeting, letter
from synth.document import Doc, doc, money
from synth.fonts import HAND, SANS_BOLD, Font
from synth.household import ERIKA_IBAN, MAX_IBAN, MOVED, Person, address, street
from synth.layout import GREY, Page
from synth.letter import Column, Letter
from synth.numbers import MONTHS, euro, german, short
from synth.printout import printout
from synth.screen import confirmation

D = Decimal


@dataclass(frozen=True)
class Booking:
    day: date
    text: tuple[str, ...]  # what, who, purpose
    amount: Decimal


def _month_bookings(month: date, rng: random.Random, salary: Decimal) -> list[Booking]:
    """A month of Max's giro account: salary, rent, utilities, phone, card, shopping, cash."""
    y, m = month.year, month.month
    rent_to, rent = (c.HAUSVERWALTUNG, D("845.00")) if month < MOVED else (c.WOHNBAU, D("1032.00"))
    out = [
        Booking(
            date(y, m, 1),
            ("Dauerauftrag", rent_to.name, f"Miete {MONTHS[m - 1]} {y}", f"IBAN {rent_to.iban}"),
            -rent,
        ),
        Booking(
            date(y, m, 15),
            (
                "Lastschrift",
                c.STADTWERKE.name,
                f"Abschlag Strom {m:02d}/{y} Kd 20047718",
                "Mandatsref. SWM-20047718-0" + ("1" if month < MOVED else "2"),
            ),
            D("-98.00") if month < MOVED else D("-95.00"),
        ),
        Booking(
            date(y, m, 15),
            (
                "Lastschrift",
                c.FERNNETZ.name,
                f"Rechnung {MONTHS[(m - 2) % 12]} Kd 40012345",
                "Mandatsref. 40012345-01",
            ),
            -D(rng.randint(4300, 5600)) / 100,
        ),
        Booking(
            date(y, m, 28),
            (
                "Gehalt",
                c.BRUECKNER.name,
                f"Lohn/Gehalt {m:02d}/{y} Pers.-Nr. 004711",
                f"IBAN {c.BRUECKNER.iban}",
            ),
            salary,
        ),
        Booking(
            date(y, m, 5),
            ("Gutschrift", "Familienkasse Musterland", f"Kindergeld {m:02d}/{y} {('245FK112233')}"),
            D("255.00") if y == 2025 else D("259.00") if y == 2026 else D("250.00"),
        ),
        Booking(
            date(y, m, 10),
            ("Lastschrift", c.HANSEBANK.name, "Kreditkartenabrechnung", "Karte 4242"),
            -D(rng.randint(9000, 42000)) / 100,
        ),
    ]
    for _ in range(rng.randint(3, 7)):
        out.append(
            Booking(
                date(y, m, rng.randint(1, 27)),
                (
                    "Kartenzahlung",
                    rng.choice(
                        [
                            "Frischmarkt KG",
                            "Baumarkt Hammer GmbH",
                            "Drogerie Sonne e.K.",
                            "Tankstelle Nord GmbH",
                        ]
                    ),
                    "girocard Musterstadt",
                ),
                -D(rng.randint(850, 9800)) / 100,
            )
        )
    out.append(
        Booking(
            date(y, m, rng.randint(2, 25)),
            ("Bargeldauszahlung", "Geldautomat Sparkasse Marktplatz"),
            -D(rng.choice([50, 100, 150, 200])),
        )
    )
    if m == 1:
        out.append(
            Booking(
                date(y, m, 2),
                (
                    "Lastschrift",
                    c.KRAFTSCHUTZ.name,
                    "Kfz-Versicherung MU-MM 1984 Jahresbeitrag",
                    "Vers.-Nr. KS-61-2207431",
                ),
                D("-486.30"),
            )
        )
        out.append(
            Booking(
                date(y, m, 15),
                (
                    "Lastschrift",
                    c.TSV.name,
                    "Mitgliedsbeitrag Familie, Mitgl.-Nr. 1890-3317",
                    "Mandatsref. TSV-3317",
                ),
                D("-168.00"),
            )
        )
    if m in (3, 6, 9, 12):
        out.append(
            Booking(
                date(y, m, 1),
                (
                    "Lastschrift",
                    c.MUSIKSCHULE.name,
                    "Unterrichtsgebühr Lena Quartal",
                    "Mandatsref. MSK-0912",
                ),
                D("-195.00"),
            )
        )
    if m == 12:
        out.append(
            Booking(
                date(y, m, 20),
                ("Überweisung", c.TIERHEIM.name, "Spende", f"IBAN {c.TIERHEIM.iban}"),
                D("-100.00"),
            )
        )
    return sorted(out, key=lambda booking: booking.day)


def salary_net(month: date) -> Decimal:
    base = (
        D("2961.42")
        if month < date(2025, 4, 1)
        else D("3048.17")
        if month < date(2026, 4, 1)
        else D("3127.90")
    )
    if month.month == 11:
        base += D("1690.00")  # Christmas bonus
    if month.month == 6:
        base += D("820.00")  # holiday pay
    return base


def account_statement(
    month: date, number: int, opening: Decimal, seed: int, *, printer: bool = False
) -> tuple[Doc, Decimal]:
    """Max's monthly statement of the Sparkasse and the balance it closes with. `printer`: the
    statement printer's layout (Courier)."""
    rng = random.Random(seed)
    bookings = _month_bookings(month, rng, salary_net(month))
    closing = opening + sum((booking.amount for booking in bookings), D("0"))
    end = _month_end(month)
    title = f"Kontoauszug {month.month}/{month.year}"
    facts = [
        ("iban", MAX_IBAN),
        ("iban", c.HAUSVERWALTUNG.iban if month < MOVED else c.WOHNBAU.iban),
        ("iban", c.BRUECKNER.iban),
        ("mandate_reference", "40012345-01"),
    ]
    fields = {"Kontostand": money(closing), "Bezugszeitraum": f"{month:%Y-%m}"}
    if printer:
        lines = [
            f"SPARKASSE MUSTERSTADT        KONTOAUSZUG  {month.month:>2}/{month.year}   BLATT 1",
            f"IBAN {MAX_IBAN}   BIC SPMUDE2MXXX",
            "KONTOINHABER MAX MUSTERMANN     GIROKONTO",
            "",
            "BU-TAG WERT   VORGANG                                     BETRAG EUR",
            "-" * 72,
            f"              ALTER KONTOSTAND VOM {german(month - timedelta(days=1))}      {euro(opening, sign=True):>14}",
        ]
        for booking in bookings:
            first, *rest = booking.text
            lines.append(
                f"{short(booking.day)[:6]} {short(booking.day)[:6]} {first.upper():<36}{euro(booking.amount, sign=True):>16}"
            )
            for part in rest:
                lines.append(f"              {part.upper()[:56]}")
        lines += [
            "-" * 72,
            f"              NEUER KONTOSTAND VOM {german(end)}      {euro(closing, sign=True):>14}",
            "",
            "BITTE PRUEFEN SIE IHREN KONTOAUSZUG. EINWENDUNGEN INNERHALB VON 6 WOCHEN.",
        ]
        pages = printout(
            "Sparkasse Musterstadt - Kontoauszugsdrucker Filiale Marktplatz", lines, size=8.5
        )
        return doc(
            "account-statement",
            "Kontoauszug",
            c.SPARKASSE,
            end,
            title,
            pages,
            fields=fields,
            facts=facts,
            layout="printout",
            download=f"Kontoauszug_{month:%Y_%m}.pdf",
        ), closing
    s = c.SPARKASSE
    bill = Letter(
        s,
        address(MAX, end),
        [
            ("IBAN", MAX_IBAN),
            ("BIC", "SPMUDE2MXXX"),
            ("Kontoart", "Giro Komfort"),
            ("Auszug", f"{number} / {month.year}"),
            ("Erstellt am", german(end)),
        ],
        f"Kontoauszug {number}/{month.year} vom {german(month)} bis {german(end)}",
        reference=f"Kontoauszug {number}/{month.year}",
        seed=seed,
    )
    rows = [
        ("", "", f"Kontostand am {german(month - timedelta(days=1))}", euro(opening, sign=True))
    ]
    for booking in bookings:
        rows.append(
            (
                short(booking.day),
                short(booking.day),
                booking.text[0],
                euro(booking.amount, sign=True),
            )
        )
        for part in booking.text[1:]:
            rows.append(("", "", part, ""))
    rows.append(("", "", f"Kontostand am {german(end)}", euro(closing, sign=True)))
    bill.table(
        [
            Column("Buchung", 18),
            Column("Wert", 18),
            Column("Vorgang / Buchungsinformation", 99),
            Column("Betrag EUR", 30, "right"),
        ],
        rows,
        size=8,
        bold_rows=(0, len(rows) - 1),
        rules=False,
        shade=True,
    )
    bill.paragraph(
        "Bitte erheben Sie Einwendungen gegen einzelne Buchungen unverzüglich. Guthaben sind als Einlagen nach Maßgabe des Einlagensicherungsgesetzes entschädigungsfähig.",
        size=7.5,
    )
    return doc(
        "account-statement",
        "Kontoauszug",
        s,
        end,
        title,
        bill,
        fields=fields,
        facts=facts,
        download=f"Konto_{MAX_IBAN.replace(' ', '')[-10:]}_Auszug_{month:%Y_%m}.pdf",
    ), closing


def _month_end(month: date) -> date:
    following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return following - timedelta(days=1)


def card_statement(month: date, seed: int) -> Doc:
    """The Hansebank's monthly credit card statement: purchases in euro and dollars, settled
    by direct debit."""
    rng = random.Random(seed)
    s = c.HANSEBANK
    day = _month_end(month)
    merchants = [
        ("CLOUDBERRY HOSTING PORTSMOUTH", "USD", (1200, 2900)),
        ("TECHNIKWELT ONLINE", "EUR", (1999, 18900)),
        ("BERGMANN VERSAND", "EUR", (1490, 8990)),
        ("REGIOBAHN TICKETSHOP", "EUR", (690, 8900)),
        ("STREAMFLIX ABO", "EUR", (1299, 1299)),
        ("HOTEL SEEBLICK OSTSEE", "EUR", (18900, 41000)),
        ("BUCHLADEN SEITENWEISE", "EUR", (1299, 4990)),
        ("NORTHWIND SOFTWARE CAMBRIDGE", "GBP", (2900, 4900)),
    ]
    purchases = []
    for _ in range(rng.randint(4, 9)):
        name, currency, (low, high) = rng.choice(merchants)
        purchases.append(
            (
                date(month.year, month.month, rng.randint(1, 27)),
                name,
                currency,
                D(rng.randint(low, high)) / 100,
            )
        )
    rows = []
    total = D("0")
    for when, name, currency, amount in sorted(purchases):
        if currency == "EUR":
            rows.append((short(when), short(when + timedelta(days=1)), name, "", euro(-amount)))
            total += amount
        else:
            rate = D("1.0862") if currency == "USD" else D("0.8571")
            eur = (amount / rate).quantize(D("0.01"))
            fee = (eur * D("0.0175")).quantize(D("0.01"))
            rows.append(
                (
                    short(when),
                    short(when + timedelta(days=1)),
                    name,
                    f"{currency} {amount:.2f} Kurs {rate}",
                    euro(-eur),
                )
            )
            rows.append(("", "", "Auslandseinsatzentgelt 1,75 %", "", euro(-fee)))
            total += eur + fee
    bill = Letter(
        s,
        address(MAX, day),
        [
            ("Kartennummer", "4242 •••• •••• 4242"),
            ("Kundennummer", "8812 4471 00"),
            ("Abrechnung", f"{MONTHS[month.month - 1]} {month.year}"),
            ("Datum", german(day)),
        ],
        f"Ihre Kreditkartenabrechnung {MONTHS[month.month - 1]} {month.year}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph("hier ist die Übersicht Ihrer Umsätze mit der Hansebank Kreditkarte Gold.")
    bill.table(
        [
            Column("Kaufdatum", 20),
            Column("Buchung", 20),
            Column("Umsatz", 60),
            Column("Fremdwährung", 40),
            Column("EUR", 25, "right"),
        ],
        rows,
        size=8,
        shade=True,
    )
    bill.totals(
        [("Summe der Umsätze", euro(-total)), ("Ausgleich per Lastschrift", f"{euro(total)} EUR")]
    )
    bill.paragraph(
        f"Der Betrag wird am {german(day + timedelta(days=10))} von Ihrem Referenzkonto {MAX_IBAN} eingezogen. Verfügungsrahmen 5.000,00 EUR."
    )
    return doc(
        "card-statement",
        "Kreditkartenabrechnung",
        s,
        day,
        f"Kreditkarte {MONTHS[month.month - 1]} {month.year}",
        bill,
        fields={"Betrag": money(total), "Bezugszeitraum": f"{month:%Y-%m}"},
        facts=[("customer_number", "8812 4471 00"), ("iban", MAX_IBAN)],
        download=f"Kreditkartenabrechnung_{month:%Y%m}.pdf",
    )


def quarter_statement(year: int, quarter: int, opening: Decimal, seed: int) -> tuple[Doc, Decimal]:
    """Erika's quarterly statement of the Direktbank: salary, transfers, card payments."""
    rng = random.Random(seed)
    s = c.DIREKTBANK
    start = date(year, 3 * quarter - 2, 1)
    end = _month_end(date(year, 3 * quarter, 1))
    bookings = []
    for offset in range(3):
        m = 3 * quarter - 2 + offset
        employer = (
            (c.STADT_PERSONAL, f"Bezüge {m:02d}/{year} Pers.-Nr. 7712345")
            if (year, m) >= (2025, 3)
            else ("Buchhandlung Seitenweise", f"Gehalt {m:02d}/{year}")
        )
        bookings.append(
            Booking(
                date(year, m, 28 if offset else 30 if m != 2 else 27),
                (
                    "Gutschrift",
                    employer[0].name if not isinstance(employer[0], str) else employer[0],
                    employer[1],
                ),
                D("2214.36") if (year, m) >= (2025, 3) else D("1688.20"),
            )
        )
        bookings.append(
            Booking(
                date(year, m, 2),
                ("Überweisung", "Max Mustermann", "Haushaltskasse", f"IBAN {MAX_IBAN}"),
                D("-700.00"),
            )
        )
        bookings.append(
            Booking(
                date(year, m, 15),
                (
                    "Lastschrift",
                    c.VORSORGE.name,
                    "Beitrag Rentenversicherung Vertr. VL-2019-338812",
                ),
                D("-100.00"),
            )
        )
        for _ in range(rng.randint(2, 4)):
            bookings.append(
                Booking(
                    date(year, m, rng.randint(3, 26)),
                    (
                        "Kartenzahlung",
                        rng.choice(
                            [
                                "Drogerie Sonne e.K.",
                                "Frischmarkt KG",
                                "Café Lindenblüte",
                                "Buchladen Seitenweise",
                            ]
                        ),
                    ),
                    -D(rng.randint(500, 6500)) / 100,
                )
            )
    bookings.sort(key=lambda booking: booking.day)
    closing = opening + sum((booking.amount for booking in bookings), D("0"))
    bill = Letter(
        s,
        address(ERIKA, end),
        [
            ("Konto", "Girokonto Plus"),
            ("IBAN", ERIKA_IBAN),
            ("Zeitraum", f"Q{quarter}/{year}"),
            ("Datum", german(end)),
        ],
        f"Kontoauszug {quarter}. Quartal {year}",
        reference=f"Kontoauszug Q{quarter}/{year}",
        seed=seed,
    )
    rows = [(german(start), "Anfangssaldo", euro(opening, sign=True))]
    for booking in bookings:
        rows.append(
            (german(booking.day), " · ".join(booking.text), euro(booking.amount, sign=True))
        )
    rows.append((german(end), "Endsaldo", euro(closing, sign=True)))
    bill.table(
        [Column("Datum", 25), Column("Buchungstext", 110), Column("Betrag EUR", 30, "right")],
        rows,
        size=8,
        bold_rows=(0, len(rows) - 1),
    )
    return doc(
        "account-statement",
        "Kontoauszug",
        s,
        end,
        f"Kontoauszug Erika Q{quarter}/{year}",
        bill,
        recipient="erika",
        fields={"Kontostand": money(closing), "Bezugszeitraum": f"{year}-Q{quarter}"},
        facts=[("iban", ERIKA_IBAN), ("iban", MAX_IBAN)],
        download=f"Kontoauszug_Q{quarter}_{year}.pdf",
    ), closing


def transfer_screen(day: date, amount: Decimal, recipient, purpose: str) -> Doc:
    """Online banking's confirmation of a credit transfer, as the browser shows it."""
    page = confirmation(
        c.SPARKASSE,
        "Ihre Überweisung wurde ausgeführt",
        f"Auftrag vom {german(day)}, freigegeben mit pushTAN. Den Beleg finden Sie im Postfach.",
        [
            ("Empfänger", recipient.name),
            ("IBAN", recipient.iban),
            ("Betrag", f"{euro(amount)} EUR"),
            ("Verwendungszweck", purpose),
            ("Auftraggeber", f"Max Mustermann, {MAX_IBAN}"),
            ("Ausführung", german(day)),
        ],
        nav=("Übersicht", "Konten", "Überweisung", "Postfach"),
    )
    return doc(
        "transfer-confirmation",
        "Mitteilung",
        c.SPARKASSE,
        day,
        f"Überweisung {recipient.head_name}",
        [page],
        fields={"Betrag": money(amount)},
        facts=[("iban", recipient.iban), ("iban", MAX_IBAN)],
        layout="screen",
        url="https://banking.sparkasse-musterstadt.example/ueberweisung/bestaetigung",
    )


def bank_letter(
    sender,
    to: Person,
    day: date,
    subject: str,
    info,
    paragraphs: list[str],
    *,
    cls: str,
    document_type: str,
    title: str,
    facts=(),
    fields=None,
    pairs=(),
    seed: int = 0,
    sign: str = "",
) -> Doc:
    bill = letter(sender, to, day, info, subject, seed=seed)
    bill.paragraph(greeting(to))
    for text in paragraphs:
        bill.paragraph(text)
    if pairs:
        bill.pairs(pairs)
    if sign:
        bill.signature("Mit freundlichen Grüßen", sign)
    else:
        bill.paragraph(f"Mit freundlichen Grüßen\nIhre {sender.head_name}")
    return doc(
        cls,
        document_type,
        sender,
        day,
        title,
        bill,
        recipient=to.username,
        facts=facts,
        fields=fields or {},
        download=f"{title.replace(' ', '_')}.pdf",
    )


def loan_contract(
    day: date, number: str, amount: Decimal, rate: str, months: int, seed: int = 0
) -> Doc:
    s = c.AUTOBANK
    monthly = (amount * D("1.065") / months).quantize(D("0.01"))
    bill = letter(
        s,
        MAX,
        day,
        [("Darlehensnummer", number), ("Händler", "Autohaus Weber GmbH & Co. KG")],
        f"Darlehensvertrag Nr. {number} – Fahrzeugfinanzierung",
        seed=seed,
    )
    bill.paragraph(
        "Zwischen der AutoFinanz Bank GmbH (Darlehensgeberin) und Herrn Max Mustermann (Darlehensnehmer) wird folgender Darlehensvertrag geschlossen:"
    )
    bill.pairs(
        [
            ("Nettodarlehensbetrag", f"{euro(amount)} EUR"),
            ("Sollzinssatz (gebunden)", f"{rate} % p. a."),
            ("Effektiver Jahreszins", f"{rate.replace(',', '.')[:-1]}9 %".replace(".", ",")),
            ("Laufzeit", f"{months} Monate"),
            ("Monatliche Rate", f"{euro(monthly)} EUR"),
            ("Erste Rate", german(day + timedelta(days=35))),
            (
                "Sicherheit",
                "Sicherungsübereignung des Fahrzeugs Kompakt 1.5, FIN WMZZZ1KZ8LW123456",
            ),
        ],
        label_width=60,
    )
    bill.heading("1. Auszahlung")
    bill.paragraph(
        "Der Darlehensbetrag wird direkt an das Autohaus Weber GmbH & Co. KG ausgezahlt. Der Darlehensnehmer weist die Darlehensgeberin hiermit unwiderruflich an."
    )
    bill.heading("2. Rückzahlung")
    bill.paragraph(
        f"Die Raten werden monatlich per SEPA-Lastschrift von Ihrem Konto {MAX_IBAN} eingezogen. Sondertilgungen sind jederzeit kostenfrei möglich."
    )
    bill.heading("3. Widerrufsrecht")
    bill.paragraph(
        "Der Darlehensnehmer kann seine Vertragserklärung innerhalb von 14 Tagen ohne Angabe von Gründen widerrufen. Die Frist beginnt nach Abschluss des Vertrags, aber erst, nachdem der Darlehensnehmer alle Pflichtangaben erhalten hat.",
        size=9,
    )
    bill.heading("4. Europäische Standardinformationen")
    bill.paragraph(
        "Die Europäischen Standardinformationen für Verbraucherkredite hat der Darlehensnehmer vor Vertragsschluss erhalten. "
        * 3,
        size=8.5,
    )
    bill.space(8)
    bill.signature("Musterstadt, " + german(day), "Max Mustermann", "Darlehensnehmer")
    return doc(
        "loan-contract",
        "Vertrag",
        s,
        day,
        f"Darlehensvertrag Auto {number}",
        bill,
        fields={"Betrag": money(amount), "Vertragsbeginn": day.isoformat()},
        facts=[("loan_number", number), ("iban", MAX_IBAN)],
        download=f"Darlehensvertrag_{number}.pdf",
    )


def loan_statement(year: int, number: str, opening: Decimal, rate: Decimal, seed: int = 0) -> Doc:
    s = c.AUTOBANK
    day = date(year + 1, 1, 12)
    interest = (opening * D("0.0349") * D("0.55")).quantize(D("0.01"))
    paid = rate * 12
    closing = opening + interest - paid
    bill = letter(
        s,
        MAX,
        day,
        [("Darlehensnummer", number)],
        f"Jahreskontoauszug {year} zu Ihrem Darlehen Nr. {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(f"wir übersenden Ihnen den Kontoauszug Ihres Darlehens für das Jahr {year}.")
    bill.table(
        [Column("Datum", 30), Column("Vorgang", 100), Column("Betrag EUR", 35, "right")],
        [
            (f"01.01.{year}", "Saldo Vortrag", euro(-opening)),
            (f"{year}", "Zinsen", euro(-interest)),
            (f"{year}", f"12 Raten à {euro(rate)}", euro(paid)),
            (f"31.12.{year}", "Saldo", euro(-closing)),
        ],
        bold_rows=(3,),
        shade=True,
    )
    bill.paragraph(
        f"Für Ihre Unterlagen: Im Jahr {year} haben Sie {euro(interest)} EUR Zinsen gezahlt."
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre AutoFinanz Bank")
    return doc(
        "loan-statement",
        "Kontoauszug",
        s,
        day,
        f"Darlehen Jahresauszug {year}",
        bill,
        fields={"Kontostand": money(-closing), "Bezugszeitraum": f"{year}"},
        facts=[("loan_number", number)],
        download=f"Jahreskontoauszug_{year}_{number}.pdf",
    )


def building_savings(day: date, contract: str, *, annual: int | None = None, seed: int = 0) -> Doc:
    s = c.BAUSPAR
    if annual is None:
        bill = letter(
            s,
            MAX,
            day,
            [("Vertragsnummer", contract), ("Tarif", "Classic N")],
            f"Ihr Bausparvertrag Nr. {contract}",
            seed=seed,
        )
        bill.paragraph(greeting(MAX))
        bill.paragraph(
            "herzlichen Glückwunsch zu Ihrem neuen Bausparvertrag! Wir haben Ihren Antrag angenommen und bestätigen:"
        )
        bill.pairs(
            [
                ("Bausparsumme", "40.000,00 EUR"),
                ("Regelsparbeitrag", "160,00 EUR monatlich"),
                ("Abschlussgebühr", "400,00 EUR (1 %)"),
                ("Guthabenzins", "0,10 % p. a."),
                ("Darlehenszins", "2,45 % p. a."),
            ]
        )
        bill.paragraph(
            "Bitte beachten Sie: Die Abschlussgebühr wird mit Ihren ersten Sparbeiträgen verrechnet."
        )
        bill.paragraph("Mit freundlichen Grüßen\nIhre Bausparkasse Musterland")
        return doc(
            "savings-contract",
            "Vertrag",
            s,
            day,
            f"Bausparvertrag {contract}",
            bill,
            fields={"Vertragsbeginn": day.isoformat()},
            facts=[("contract_number", contract)],
            download=f"Vertrag_{contract}.pdf",
        )
    bill = letter(
        s,
        MAX,
        day,
        [("Vertragsnummer", contract)],
        f"Jahreskontoauszug {annual} Bausparvertrag {contract}",
        seed=seed,
    )
    balance = D("1520.00") + D("1920.00") * (annual - 2024)
    bill.table(
        [Column("Datum", 30), Column("Vorgang", 100), Column("Betrag EUR", 35, "right")],
        [
            (f"01.01.{annual}", "Guthaben Vortrag", euro(balance - D("1920"))),
            (f"{annual}", "Sparbeiträge 12 × 160,00", "1.920,00"),
            (f"31.12.{annual}", "Zinsen", "2,35"),
            (f"31.12.{annual}", "Guthaben", euro(balance + D("2.35"))),
        ],
        bold_rows=(3,),
        shade=True,
    )
    bill.paragraph("Bewertungszahl zum Stichtag: 112 (Mindestbewertungszahl 280).")
    bill.paragraph("Mit freundlichen Grüßen\nIhre Bausparkasse Musterland")
    return doc(
        "savings-statement",
        "Kontoauszug",
        s,
        day,
        f"Bausparvertrag Jahresauszug {annual}",
        bill,
        fields={"Kontostand": money(balance + D("2.35")), "Bezugszeitraum": str(annual)},
        facts=[("contract_number", contract)],
        download=f"Jahresauszug_{annual}.pdf",
    )


def tax_certificate(year: int, seed: int = 0) -> Doc:
    s = c.SPARKASSE
    day = date(year + 1, 2, 10)
    bill = letter(
        s,
        MAX,
        day,
        [("Kunde", "Max Mustermann"), ("Steuer-ID", MAX.tax_id)],
        f"Jahressteuerbescheinigung {year} für Privatkonten und Depots",
        seed=seed,
    )
    bill.paragraph(
        f"Für Herrn Max Mustermann, Steuer-ID {MAX.tax_id}, bescheinigen wir für das Kalenderjahr {year}:"
    )
    bill.pairs(
        [
            ("Höhe der Kapitalerträge", "38,12 EUR"),
            ("Freistellungsauftrag in Anspruch genommen", "38,12 EUR"),
            ("Kapitalertragsteuer", "0,00 EUR"),
            ("Solidaritätszuschlag", "0,00 EUR"),
            ("Kirchensteuer", "0,00 EUR"),
        ],
        label_width=95,
    )
    bill.paragraph(
        "Diese Bescheinigung ist maschinell erstellt und wird nicht unterschrieben.", size=8
    )
    return doc(
        "tax-certificate",
        "Bescheinigung",
        s,
        day,
        f"Jahressteuerbescheinigung {year}",
        bill,
        fields={"Bezugszeitraum": str(year)},
        facts=[("tax_id", MAX.tax_id)],
        download=f"Steuerbescheinigung_{year}.pdf",
    )


def sepa_mandate(
    creditor, creditor_id: str, mandate: str, day: date, purpose: str, *, by_hand: bool = True
) -> Doc:
    """A SEPA direct debit mandate as a printed form, filled in by hand."""
    page = Page()
    font, bold = Font("sans"), SANS_BOLD
    page.text(25, 30, "SEPA-Lastschriftmandat", bold, 16)
    page.text(25, 38, creditor.name, font, 10)
    page.text(25, 43, f"{creditor.street}, {creditor.city}", font, 10)
    page.text(25, 52, f"Gläubiger-Identifikationsnummer: {creditor_id}", font, 10)
    page.text(25, 58, f"Mandatsreferenz: {mandate}", font, 10)
    page.text(25, 70, f"Zweck: {purpose}", font, 10)
    text = [
        f"Ich ermächtige {creditor.name}, Zahlungen von meinem Konto mittels Lastschrift einzuziehen.",
        "Zugleich weise ich mein Kreditinstitut an, die von dem Zahlungsempfänger auf mein Konto",
        "gezogenen Lastschriften einzulösen. Hinweis: Ich kann innerhalb von acht Wochen, beginnend",
        "mit dem Belastungsdatum, die Erstattung des belasteten Betrages verlangen.",
    ]
    y = 82.0
    for line in text:
        page.text(25, y, line, font, 9)
        y += 5
    road, city = street(day)
    entries = [
        ("Kontoinhaber", "Max Mustermann"),
        ("Straße, Hausnummer", road),
        ("PLZ, Ort", city),
        ("IBAN", MAX_IBAN),
        ("Kreditinstitut", "Sparkasse Musterstadt"),
    ]
    y += 8
    hand = HAND if by_hand else font
    for label, value in entries:
        page.text(25, y, label, font, 8.5, color=GREY)
        page.rect(70, y - 5.5, 115, 8, stroke=(120, 120, 120), width=0.4)
        page.text(
            72, y, value, hand, 13 if by_hand else 10, color=(20, 40, 120) if by_hand else (0, 0, 0)
        )
        y += 11
    y += 8
    page.text(25, y, "Ort, Datum", font, 8.5, color=GREY)
    page.text(110, y, "Unterschrift", font, 8.5, color=GREY)
    page.text(25, y - 7, f"Musterstadt, {german(day)}", hand, 13, color=(20, 40, 120))
    page.text(112, y - 7, "M. Mustermann", hand, 16, color=(20, 40, 120))
    page.line((25, y - 4), (95, y - 4), width=0.3)
    page.line((110, y - 4), (185, y - 4), width=0.3)
    return doc(
        "sepa-mandate",
        "Vertrag",
        creditor,
        day,
        f"SEPA-Mandat {creditor.head_name}",
        [page],
        facts=[("creditor_id", creditor_id), ("mandate_reference", mandate), ("iban", MAX_IBAN)],
        layout="form",
        download=f"SEPA_Mandat_{mandate}.pdf",
    )


def fees_notice(day: date, seed: int = 0) -> Doc:
    return bank_letter(
        c.SPARKASSE,
        MAX,
        day,
        "Ihre Entgeltinformation für das Jahr 2025",
        [("IBAN", MAX_IBAN)],
        [
            "mit dieser Aufstellung informieren wir Sie über die Entgelte, die für Ihr Zahlungskonto im vergangenen Jahr angefallen sind, und über die Zinsen."
        ],
        cls="fee-statement",
        document_type="Mitteilung",
        title="Entgeltaufstellung 2025",
        pairs=[
            ("Kontoführung Giro Komfort", "12 × 6,90 EUR = 82,80 EUR"),
            ("girocard", "12,00 EUR"),
            ("Überweisungen beleglos", "0,00 EUR"),
            ("Gesamtsumme der Entgelte", "94,80 EUR"),
            ("Sollzinssatz Dispo", "11,25 % p. a."),
        ],
        facts=[("iban", MAX_IBAN)],
        fields={"Betrag": money("94.80"), "Bezugszeitraum": "2025"},
        seed=seed,
    )


def exemption_order(day: date, seed: int = 0) -> Doc:
    return bank_letter(
        c.SPARKASSE,
        MAX,
        day,
        "Bestätigung Ihres Freistellungsauftrags",
        [("Kunde", "Max Mustermann, Erika Musterfrau")],
        [
            "wir bestätigen den Eingang Ihres gemeinsamen Freistellungsauftrags für Kapitalerträge.",
            f"Steuer-ID Max Mustermann: {MAX.tax_id}; Steuer-ID Erika Musterfrau: {ERIKA.tax_id}.",
        ],
        cls="exemption-order",
        document_type="Bescheinigung",
        title="Freistellungsauftrag Bestätigung",
        pairs=[
            ("Freistellungsbetrag", "2.000,00 EUR"),
            ("gültig ab", german(date(day.year, 1, 1))),
            ("gültig bis", "auf Widerruf"),
        ],
        facts=[("tax_id", MAX.tax_id), ("tax_id", ERIKA.tax_id)],
        seed=seed,
    )
