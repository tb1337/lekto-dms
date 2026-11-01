"""Invoices and what belongs to them: utility bills, telephone bills, craftsmen, doctors, the
garage, shops; offers, order confirmations, delivery notes, reminders, credit notes,
corrections."""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from synth import contacts as c
from synth import ids
from synth.classes.common import CENT, MAX, greeting, letter, lines_table, vat
from synth.codes import code, girocode
from synth.document import Doc, doc, money
from synth.household import LICENSE_PLATE, MAX_IBAN, Person, street
from synth.letter import Column
from synth.numbers import MONTHS, euro, german, plain, short
from synth.printout import printout
from synth.screen import confirmation

STADTWERKE_CUSTOMER = "2004 7718"
STADTWERKE_CREDITOR = ids.creditor_id("00000471108")


def _pay_by_transfer(
    bill, sender, amount: Decimal, due: date, purpose: str, *, giro: bool = True
) -> None:
    bill.paragraph(
        f"Bitte überweisen Sie den Betrag von {euro(amount)} EUR bis zum {german(due)} unter "
        f"Angabe von „{purpose}“ auf unser Konto, IBAN {sender.iban}."
    )
    if giro:
        bill.code(
            code(girocode(sender.name, sender.iban, plain(amount), purpose, sender.bic)),
            ["Bequem bezahlen", "Scannen Sie den Code", "mit Ihrer Banking-App."],
            side=24,
        )


def utility_bill(
    number: str,
    day: date,
    start: date,
    end: date,
    meter: str,
    kwh: int,
    paid_months: int,
    advance: Decimal,
    *,
    final: bool = False,
    new_advance: Decimal | None = None,
    price_ct: Decimal = Decimal("32.48"),
    seed: int = 0,
) -> Doc:
    """An annual or final power bill of the Stadtwerke, with GiroCode for an extra payment or
    a credit refunded."""
    s = c.STADTWERKE
    road, city = street(start)
    days = (end - start).days + 1
    months = round(days / 30.4)
    energy = (kwh * price_ct / 100).quantize(CENT)
    base = (Decimal("11.90") * months).quantize(CENT)
    metering = (Decimal("1.67") * months).quantize(CENT)
    net = energy + base + metering
    tax = vat(net)
    total = net + tax
    paid = advance * paid_months
    rest = total - paid
    kind = "Schlussrechnung" if final else "Jahresabrechnung"
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Kundennummer", STADTWERKE_CUSTOMER),
            ("Rechnungsnummer", number),
            ("Zählernummer", meter),
            ("Ansprechpartner", "Kundenservice"),
        ],
        f"{kind} Strom {german(start)} – {german(end)}",
        reference=f"Rechnung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"mit diesem Schreiben erhalten Sie Ihre {kind} für Strom an der Lieferstelle {road}, "
        f"{city}."
        + (
            " Wir bedanken uns für Ihr Vertrauen und wünschen Ihnen alles Gute in Ihrem neuen Zuhause."
            if final
            else ""
        )
    )
    period = f"{short(start)}–{short(end)}"
    bill.table(
        [
            Column("Position", 52),
            Column("Zeitraum", 38),
            Column("Menge", 22, "right"),
            Column("Preis", 28, "right"),
            Column("Betrag EUR", 25, "right"),
        ],
        [
            (
                "Arbeitspreis Strom",
                period,
                f"{kwh:,} kWh".replace(",", "."),
                f"{euro(price_ct)} ct/kWh",
                euro(energy),
            ),
            ("Grundpreis", period, f"{months} Monate", "11,90 €/Monat", euro(base)),
            ("Messstellenbetrieb", period, f"{months} Monate", "1,67 €/Monat", euro(metering)),
        ],
        shade=True,
    )
    rows = [
        ("Summe netto", euro(net)),
        ("Umsatzsteuer 19 %", euro(tax)),
        ("Rechnungsbetrag", f"{euro(total)} EUR"),
        (f"abzüglich {paid_months} Abschläge", euro(-paid)),
        ("Nachzahlung" if rest > 0 else "Guthaben", f"{euro(abs(rest))} EUR"),
    ]
    bill.totals(rows)
    due = day + timedelta(days=15)
    if rest > 0:
        _pay_by_transfer(bill, s, rest, due, f"{number} Kd {STADTWERKE_CUSTOMER.replace(' ', '')}")
    else:
        bill.paragraph(
            f"Ihr Guthaben von {euro(-rest)} EUR überweisen wir in den nächsten Tagen auf Ihr Konto "
            f"{MAX_IBAN[:4]} **** **** **** {MAX_IBAN[-5:].replace(' ', '')}."
        )
    if new_advance:
        bill.box(
            [
                f"Ihr neuer Abschlag ab {MONTHS[(day.month) % 12]} {day.year + (day.month == 12)}",
                f"{euro(new_advance)} EUR monatlich, jeweils zum 15. des Monats",
            ]
        )
    bill.heading("Ihre Zählerstände")
    reading = 41226 + seed * 311
    bill.table(
        [
            Column("Zählernummer", 45),
            Column("Ablesedatum", 30),
            Column("Zählerstand", 30, "right"),
            Column("Ablesung", 60),
        ],
        [
            (
                meter,
                german(start - timedelta(days=1)),
                f"{reading:,} kWh".replace(",", "."),
                "durch Sie",
            ),
            (
                meter,
                german(end),
                f"{reading + kwh:,} kWh".replace(",", "."),
                "durch unseren Ableser",
            ),
        ],
    )
    bill.paragraph("Ihr Verbrauch im Vergleich (kWh)", bold=True, after=0)
    bill.chart([("Vorvorjahr", kwh * 1.11), ("Vorjahr", kwh * 1.04), ("Aktuell", kwh)], unit="kWh")
    bill.paragraph(
        "Stromkennzeichnung: Der Strom Ihres Tarifs stammt zu 61,3 % aus erneuerbaren Energien, zu "
        "24,1 % aus Erdgas und zu 14,6 % aus sonstigen fossilen Energieträgern. CO2-Emissionen "
        "182 g/kWh. Verbraucher können sich bei Streitigkeiten an die Schlichtungsstelle Energie "
        "Musterland, Postfach 1 23, 12340 Musterstadt, wenden.",
        size=8.5,
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Stadtwerke Musterstadt")
    bill.paragraph(
        "Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift gültig.", size=8
    )
    fields = {
        "Betrag": money(total),
        "Rechnungsnummer": number,
        "Kundennummer": STADTWERKE_CUSTOMER,
        "Bezugszeitraum": f"{start.isoformat()}/{end.isoformat()}",
    }
    if rest > 0:
        fields["Fällig am"] = due.isoformat()
    return doc(
        "utility-bill",
        "Rechnung",
        s,
        day,
        f"{kind} Strom {start.year}/{end.year}"
        if start.year != end.year
        else f"{kind} Strom {start.year}",
        bill,
        fields=fields,
        facts=[
            ("invoice_number", number),
            ("customer_number", STADTWERKE_CUSTOMER),
            ("meter_number", meter),
            ("iban", s.iban),
            ("vat_id", s.vat_id),
        ],
        codes=["QR Code"] if rest > 0 else [],
        download=f"Rechnung_{number}.pdf",
    )


def utility_bill_printout(
    number: str, day: date, start: date, end: date, meter: str, total: Decimal
) -> Doc:
    """The same kind of bill from the Stadtwerke's old billing system, as a line printer wrote it."""
    road, city = street(start)
    lines = [
        "STADTWERKE MUSTERSTADT GMBH          JAHRESABRECHNUNG STROM",
        "",
        f"MAX MUSTERMANN                       KUNDENNR.     : {STADTWERKE_CUSTOMER}",
        f"{road.upper():<37}RECHNUNGSNR.  : {number}",
        f"{city.upper():<37}ZAEHLERNR.    : {meter}",
        f"{'':37}DATUM         : {german(day)}",
        "",
        f"ABRECHNUNGSZEITRAUM {german(start)} - {german(end)}",
        "",
        "+-----------------------------------------------+-----------+",
        "| POSITION                                      | BETRAG EUR|",
        "+-----------------------------------------------+-----------+",
        f"| ARBEITSPREIS, GRUNDPREIS, MESSSTELLE (NETTO)  | {euro(total / Decimal('1.19')):>9} |",
        f"| UMSATZSTEUER 19 %                             | {euro(total - (total / Decimal('1.19')).quantize(CENT)):>9} |",
        f"| RECHNUNGSBETRAG                               | {euro(total):>9} |",
        "+-----------------------------------------------+-----------+",
        "",
        f"DER RECHNUNGSBETRAG WIRD AM {german(day + timedelta(days=14))} ABGEBUCHT.",
        f"GLAEUBIGER-ID {STADTWERKE_CREDITOR}  MANDATSREFERENZ SWM-{STADTWERKE_CUSTOMER.replace(' ', '')}-01",
        "",
        "STADTWERKE MUSTERSTADT GMBH * AM WASSERTURM 3 * 12345 MUSTERSTADT",
        f"AMTSGERICHT MUSTERSTADT HRB 4711 * UST-IDNR. {c.STADTWERKE.vat_id}",
    ]
    pages = printout("Stadtwerke Musterstadt GmbH - Abrechnungssystem EVA 4.2", lines)
    return doc(
        "utility-bill",
        "Rechnung",
        c.STADTWERKE,
        day,
        f"Jahresabrechnung Strom {start.year}/{end.year}",
        pages,
        fields={
            "Betrag": money(total),
            "Rechnungsnummer": number,
            "Kundennummer": STADTWERKE_CUSTOMER,
            "Bezugszeitraum": f"{start.isoformat()}/{end.isoformat()}",
        },
        facts=[
            ("invoice_number", number),
            ("customer_number", STADTWERKE_CUSTOMER),
            ("meter_number", meter, None, False),  # "ZAEHLERNR.": no umlaut on the printer
            ("creditor_id", STADTWERKE_CREDITOR),
            ("mandate_reference", f"SWM-{STADTWERKE_CUSTOMER.replace(' ', '')}-01"),
            ("vat_id", c.STADTWERKE.vat_id),
        ],
        layout="printout",
        download=f"EVA_{number}.pdf",
    )


def utility_correction(
    number: str,
    original: str,
    original_day: date,
    day: date,
    meter: str,
    old: Decimal,
    new: Decimal,
    seed: int = 0,
) -> Doc:
    s = c.STADTWERKE
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Kundennummer", STADTWERKE_CUSTOMER),
            ("Rechnungsnummer", number),
            ("Zählernummer", meter),
        ],
        f"Rechnungskorrektur zu Ihrer Rechnung Nr. {original} vom {german(original_day)}",
        reference=f"Rechnung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "bei Ihrer Jahresabrechnung ist uns ein Fehler unterlaufen: Der Zählerstand vom Ende des "
        "Abrechnungszeitraums wurde falsch übernommen. Diese Rechnung ersetzt Ihre Rechnung "
        f"Nr. {original} vom {german(original_day)} vollständig."
    )
    bill.totals(
        [
            ("Bisheriger Rechnungsbetrag", euro(old)),
            ("Korrigierter Rechnungsbetrag", euro(new)),
            ("Differenz zu Ihren Gunsten", f"{euro(old - new)} EUR"),
        ]
    )
    bill.paragraph(
        f"Den Differenzbetrag von {euro(old - new)} EUR verrechnen wir mit Ihrem nächsten Abschlag. Wir bitten den Fehler zu entschuldigen."
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Stadtwerke Musterstadt")
    return doc(
        "invoice-correction",
        "Rechnung",
        s,
        day,
        f"Rechnungskorrektur {number}",
        bill,
        fields={
            "Betrag": money(new),
            "Rechnungsnummer": number,
            "Kundennummer": STADTWERKE_CUSTOMER,
        },
        facts=[
            ("invoice_number", number),
            ("invoice_number", original, "refers"),
            ("customer_number", STADTWERKE_CUSTOMER),
            ("meter_number", meter),
        ],
        download=f"Rechnungskorrektur_{number}.pdf",
    )


def utility_contract(
    day: date, start: date, meter: str, advance: Decimal, contract: str, seed: int = 0
) -> Doc:
    s = c.STADTWERKE
    road, city = street(start)
    bill = letter(
        s,
        MAX,
        day,
        [("Kundennummer", STADTWERKE_CUSTOMER), ("Vertragsnummer", contract)],
        "Ihr Stromvertrag an Ihrer neuen Adresse – Auftragsbestätigung",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"vielen Dank für Ihren Umzugsauftrag. Wir beliefern Sie ab dem {german(start)} an Ihrer neuen Lieferstelle mit Strom und bestätigen Ihnen folgende Vertragsdaten:"
    )
    bill.pairs(
        [
            ("Lieferstelle", f"{road}, {city}"),
            ("Tarif", "MusterStrom Öko 24"),
            ("Vertragsbeginn", german(start)),
            ("Zählernummer", meter),
            ("Arbeitspreis", "32,48 ct/kWh brutto"),
            ("Grundpreis", "11,90 EUR/Monat brutto"),
            ("Erstlaufzeit", "12 Monate, danach monatlich kündbar"),
            ("Monatlicher Abschlag", f"{euro(advance)} EUR, fällig zum 15. des Monats"),
        ]
    )
    bill.paragraph(
        f"Die Abschläge buchen wir per SEPA-Lastschrift von Ihrem Konto ab (Gläubiger-ID {STADTWERKE_CREDITOR}, "
        f"Mandatsreferenz SWM-{STADTWERKE_CUSTOMER.replace(' ', '')}-02)."
    )
    bill.paragraph(
        "Ihr Widerrufsrecht: Sie können Ihre Vertragserklärung innerhalb von 14 Tagen ohne Angabe von Gründen widerrufen. Die Frist beginnt mit Erhalt dieser Bestätigung.",
        size=8.5,
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Stadtwerke Musterstadt")
    return doc(
        "contract-confirmation",
        "Vertrag",
        s,
        day,
        "Auftragsbestätigung Stromvertrag Lindenallee",
        bill,
        fields={"Vertragsbeginn": start.isoformat(), "Kundennummer": STADTWERKE_CUSTOMER},
        facts=[
            ("contract_number", contract),
            ("customer_number", STADTWERKE_CUSTOMER),
            ("meter_number", meter),
            ("creditor_id", STADTWERKE_CREDITOR),
            ("mandate_reference", f"SWM-{STADTWERKE_CUSTOMER.replace(' ', '')}-02"),
        ],
        download="Auftragsbestaetigung.pdf",
    )


def price_change(day: date, valid: date, contract: str, seed: int = 0) -> Doc:
    s = c.STADTWERKE
    bill = letter(
        s,
        MAX,
        day,
        [("Kundennummer", STADTWERKE_CUSTOMER), ("Vertragsnummer", contract)],
        f"Anpassung Ihrer Strompreise zum {german(valid)}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"zum {german(valid)} ändern sich die staatlich veranlassten Preisbestandteile. Deshalb passen wir Ihre "
        "Preise wie folgt an. Ihr monatlicher Abschlag bleibt unverändert."
    )
    bill.table(
        [
            Column("Preisbestandteil", 70),
            Column("bisher", 45, "right"),
            Column(f"ab {german(valid)}", 50, "right"),
        ],
        [
            ("Arbeitspreis (brutto)", "32,48 ct/kWh", "30,96 ct/kWh"),
            ("Grundpreis (brutto)", "11,90 €/Monat", "12,50 €/Monat"),
        ],
        shade=True,
    )
    bill.paragraph(
        f"Sie haben das Recht, Ihren Vertrag ohne Einhaltung einer Frist zum {german(valid - timedelta(days=1))} zu kündigen. Bitte beachten Sie, dass Sie dann einen neuen Lieferanten benötigen."
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Stadtwerke Musterstadt")
    return doc(
        "price-change",
        "Mitteilung",
        s,
        day,
        "Preisanpassung Strom",
        bill,
        facts=[("contract_number", contract), ("customer_number", STADTWERKE_CUSTOMER)],
        download="Preisanpassung.pdf",
    )


def meter_card(day: date, meter: str, due: date, seed: int = 0) -> Doc:
    """A request to read the meter, with a card to fill in and a QR code to report online."""
    s = c.STADTWERKE
    bill = letter(
        s,
        MAX,
        day,
        [("Kundennummer", STADTWERKE_CUSTOMER), ("Zählernummer", meter)],
        "Bitte teilen Sie uns Ihren Zählerstand mit",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"für Ihre Jahresabrechnung benötigen wir den Stand Ihres Stromzählers. Bitte lesen Sie ihn bis zum {german(due)} ab und teilen Sie ihn uns online oder mit der Karte unten mit."
    )
    bill.code(
        code(f"https://www.stadtwerke-musterstadt.example/zaehlerstand?z={meter.replace(' ', '')}"),
        ["Online melden", "Code scannen und", "Zählerstand eingeben."],
        side=24,
    )
    bill.box(
        [
            "Ablesekarte",
            f"Zählernummer {meter}",
            "Zählerstand: ____________ kWh     Ablesedatum: ____________",
        ]
    )
    bill.paragraph("Mit freundlichen Grüßen\nIhre Stadtwerke Musterstadt")
    return doc(
        "meter-reading",
        "Mitteilung",
        s,
        day,
        "Ablesekarte Stromzähler",
        bill,
        fields={"Fällig am": due.isoformat()},
        facts=[("customer_number", STADTWERKE_CUSTOMER), ("meter_number", meter)],
        codes=["QR Code"],
        download="Ablesekarte.pdf",
    )


FERNNETZ_CUSTOMER = "40012345"
FERNNETZ_CONTRACT = "FN-V-778812"
FERNNETZ_CREDITOR = ids.creditor_id("00000881234")


def phone_bill(month: date, seed: int) -> Doc:
    """FernNetz's monthly bill: DSL and mobile, extras some months, a list of calls on the
    second page some months; paid by direct debit."""
    rng = random.Random(seed)
    s = c.FERNNETZ
    day = date(month.year, month.month, 5)
    number = f"FN{month:%y%m}{rng.randint(100000, 999999)}"
    items = [
        ("Internet DSL 100 Flat", Decimal("1"), "Monat", Decimal("29.40")),
        ("Mobil Allnet M (0171 2345678)", Decimal("1"), "Monat", Decimal("16.80")),
    ]
    if rng.random() < 0.35:
        items.append(
            (
                "Verbindungen ins Ausland",
                Decimal("1"),
                "pauschal",
                Decimal(rng.randint(80, 900)) / 100,
            )
        )
    if rng.random() < 0.2:
        items.append(("Datenpaket 5 GB", Decimal("1"), "Stück", Decimal("4.20")))
    if month.month == 3 and month.year == 2025:
        items.append(("Gutschrift Treuebonus", Decimal("1"), "einmalig", Decimal("-10.00")))
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Kundennummer", FERNNETZ_CUSTOMER),
            ("Rechnungsnummer", number),
            ("Vertragsnummer", FERNNETZ_CONTRACT),
        ],
        f"Ihre Rechnung für {MONTHS[month.month - 1]} {month.year}",
        reference=f"Rechnung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"hier ist Ihre Rechnung für den Zeitraum 01.{month:%m.%Y} bis {_month_end(month):%d.%m.%Y}."
    )
    net, tax, gross = lines_table(bill, items)
    bill.totals(
        [
            ("Summe netto", euro(net)),
            ("Umsatzsteuer 19 %", euro(tax)),
            ("Rechnungsbetrag", f"{euro(gross)} EUR"),
        ]
    )
    debit = day + timedelta(days=10)
    bill.paragraph(
        f"Den Rechnungsbetrag buchen wir frühestens am {german(debit)} von Ihrem Konto {MAX_IBAN} ab. "
        f"Gläubiger-ID {FERNNETZ_CREDITOR}, Mandatsreferenz {FERNNETZ_CUSTOMER}-01."
    )
    bill.paragraph(
        "Ihre Rechnungen der letzten 12 Monate finden Sie jederzeit unter Mein FernNetz.", size=9
    )
    if rng.random() < 0.4:
        bill.heading("Einzelverbindungsnachweis Mobil (gekürzt)")
        calls = []
        for _ in range(rng.randint(8, 22)):
            when = datetime(month.year, month.month, 1) + timedelta(
                days=rng.randint(0, 27), minutes=rng.randint(420, 1300)
            )
            calls.append(
                (
                    f"{when:%d.%m. %H:%M}",
                    f"0{rng.randint(151, 179)} {rng.randint(1000, 9999)}xxx",
                    f"{rng.randint(0, 40)}:{rng.randint(0, 59):02d}",
                    "0,00",
                )
            )
        bill.table(
            [
                Column("Datum, Uhrzeit", 40),
                Column("Rufnummer", 50),
                Column("Dauer", 30, "right"),
                Column("Betrag EUR", 30, "right"),
            ],
            sorted(calls),
            size=8,
        )
    return doc(
        "phone-bill",
        "Rechnung",
        s,
        day,
        f"Telefonrechnung {MONTHS[month.month - 1]} {month.year}",
        bill,
        fields={
            "Betrag": money(gross),
            "Rechnungsnummer": number,
            "Kundennummer": FERNNETZ_CUSTOMER,
            "Bezugszeitraum": f"{month:%Y-%m}",
        },
        facts=[
            ("invoice_number", number),
            ("customer_number", FERNNETZ_CUSTOMER),
            ("contract_number", FERNNETZ_CONTRACT),
            ("creditor_id", FERNNETZ_CREDITOR),
            ("mandate_reference", f"{FERNNETZ_CUSTOMER}-01"),
            ("vat_id", s.vat_id),
            ("iban", MAX_IBAN),
        ],
        download=f"Rechnung_{month:%Y_%m}.pdf",
    )


def _month_end(month: date) -> date:
    following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return following - timedelta(days=1)


def offer(
    sender,
    number: str,
    day: date,
    subject: str,
    items,
    *,
    valid_days: int = 30,
    to: Person = MAX,
    seed: int = 0,
    intro: str = "",
) -> Doc:
    bill = letter(
        sender,
        to,
        day,
        [("Angebotsnummer", number), ("Gültig bis", german(day + timedelta(days=valid_days)))],
        f"Angebot Nr. {number}: {subject}",
        seed=seed,
    )
    bill.paragraph(greeting(to))
    bill.paragraph(
        intro or "vielen Dank für Ihre Anfrage. Gerne bieten wir Ihnen die folgenden Leistungen an:"
    )
    net, tax, gross = lines_table(bill, items)
    bill.totals(
        [
            ("Summe netto", euro(net)),
            ("Umsatzsteuer 19 %", euro(tax)),
            ("Angebotssumme", f"{euro(gross)} EUR"),
        ]
    )
    bill.paragraph(
        f"Dieses Angebot ist bis zum {german(day + timedelta(days=valid_days))} gültig. Über Ihren Auftrag würden wir uns sehr freuen."
    )
    bill.signature(
        "Mit freundlichen Grüßen",
        sender.managers.split(": ")[-1].split(",")[0] if sender.managers else sender.name,
    )
    return doc(
        "offer",
        "Angebot",
        sender,
        day,
        f"Angebot {subject}",
        bill,
        fields={"Betrag": money(gross)},
        facts=[("iban", sender.iban)] if sender.iban else [],
        download=f"Angebot_{number}.pdf",
    )


def craft_invoice(
    sender,
    number: str,
    day: date,
    subject: str,
    items,
    *,
    to: Person = MAX,
    offer_ref: tuple[str, date] | None = None,
    order: str = "",
    seed: int = 0,
    due_days: int = 14,
    giro: bool = True,
    site: str = "",
    labour_note: bool = True,
) -> Doc:
    info = [("Rechnungsnummer", number), ("Kundennummer", f"K{seed % 9000 + 1000}")]
    if order:
        info.append(("Auftragsnummer", order))
    bill = letter(
        sender,
        to,
        day,
        info,
        f"Rechnung Nr. {number}: {subject}",
        reference=f"Rechnung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(to))
    text = "für die ausgeführten Arbeiten erlauben wir uns, Ihnen Folgendes in Rechnung zu stellen"
    if offer_ref:
        text += f" (gemäß unserem Angebot Nr. {offer_ref[0]} vom {german(offer_ref[1])})"
    bill.paragraph(text + ".")
    if site:
        bill.pairs(
            [
                ("Leistungsort", site),
                (
                    "Leistungszeitraum",
                    f"{german(day - timedelta(days=9))} – {german(day - timedelta(days=2))}",
                ),
            ]
        )
    net, tax, gross = lines_table(bill, items)
    bill.totals(
        [
            ("Summe netto", euro(net)),
            ("Umsatzsteuer 19 %", euro(tax)),
            ("Rechnungsbetrag", f"{euro(gross)} EUR"),
        ]
    )
    due = day + timedelta(days=due_days)
    _pay_by_transfer(bill, sender, gross, due, f"Rechnung {number}", giro=giro)
    if labour_note:
        bill.paragraph(
            "Der Anteil der Arbeitskosten kann nach § 35a EStG steuerlich geltend gemacht werden. Bitte bewahren Sie diese Rechnung zwei Jahre auf.",
            size=8.5,
        )
    bill.paragraph("Vielen Dank für Ihren Auftrag!\nMit freundlichen Grüßen")
    facts = [("invoice_number", number), ("customer_number", f"K{seed % 9000 + 1000}")]
    if sender.iban:
        facts.append(("iban", sender.iban))
    if sender.vat_id:
        facts.append(("vat_id", sender.vat_id))
    if order:
        facts.append(("order_number", order, "refers"))
    return doc(
        "craftsman-invoice",
        "Rechnung",
        sender,
        day,
        f"Rechnung {subject}",
        bill,
        recipient=to.username,
        fields={"Betrag": money(gross), "Rechnungsnummer": number, "Fällig am": due.isoformat()},
        facts=facts,
        codes=["QR Code"] if giro else [],
        download=f"Rechnung_{number}.pdf",
    )


def reminder(
    sender,
    invoice: str,
    invoice_day: date,
    amount: Decimal,
    day: date,
    *,
    level: int = 1,
    fee: Decimal = Decimal("0"),
    to: Person = MAX,
    seed: int = 0,
    customer: str = "",
    english: bool = False,
) -> Doc:
    titles = {1: "Zahlungserinnerung", 2: "2. Mahnung", 3: "Letzte Mahnung"}
    info = [("Kundennummer", customer)] if customer else []
    bill = letter(
        sender,
        to,
        day,
        info,
        f"{titles[level]} zu unserer Rechnung Nr. {invoice} vom {german(invoice_day)}",
        seed=seed,
    )
    bill.paragraph(greeting(to))
    if level == 1:
        bill.paragraph(
            "sicher ist es Ihrer Aufmerksamkeit entgangen: Für die unten genannte Rechnung konnten wir bis heute keinen Zahlungseingang feststellen."
        )
    else:
        bill.paragraph(
            "leider haben Sie auf unsere Zahlungserinnerung nicht reagiert. Wir bitten Sie dringend, den offenen Betrag zuzüglich Mahngebühr auszugleichen."
        )
    bill.table(
        [
            Column("Rechnung", 40),
            Column("vom", 30),
            Column("fällig seit", 30),
            Column("offen EUR", 30, "right"),
        ],
        [(invoice, german(invoice_day), german(invoice_day + timedelta(days=14)), euro(amount))],
    )
    rows = [("Offener Betrag", euro(amount))]
    if fee:
        rows.append(("Mahngebühr", euro(fee)))
    rows.append(("Zu zahlen", f"{euro(amount + fee)} EUR"))
    bill.totals(rows)
    due = day + timedelta(days=10 if level == 1 else 7)
    _pay_by_transfer(bill, sender, amount + fee, due, f"Rechnung {invoice}", giro=sender.iban != "")
    bill.paragraph(
        "Sollten Sie die Zahlung inzwischen geleistet haben, betrachten Sie dieses Schreiben bitte als gegenstandslos."
    )
    bill.paragraph("Mit freundlichen Grüßen")
    facts = [("invoice_number", invoice, "refers")]
    if customer:
        facts.append(("customer_number", customer))
    if sender.iban:
        facts.append(("iban", sender.iban))
    return doc(
        "reminder",
        "Mahnung",
        sender,
        day,
        f"{titles[level]} Rechnung {invoice}",
        bill,
        recipient=to.username,
        fields={
            "Betrag": money(amount + fee),
            "Fällig am": due.isoformat(),
            "Rechnungsnummer": invoice,
        },
        facts=facts,
        codes=["QR Code"] if sender.iban else [],
        download=f"Mahnung_{invoice}.pdf",
    )


def doctor_invoice(
    sender,
    number: str,
    day: date,
    patient: Person,
    treatments,
    *,
    seed: int = 0,
    dental: bool = False,
    plan: tuple[str, date] | None = None,
) -> Doc:
    """A private invoice after the scales of fees (GOÄ, GOZ): items with number, factor and amount."""
    scale = "GOZ" if dental else "GOÄ"
    # A child's invoice goes to a parent.
    addressee = MAX if patient.username == "lena" else patient
    bill = letter(
        sender,
        addressee,
        day,
        [("Rechnungsnummer", number), ("Patient", patient.name), ("geb. am", german(patient.born))],
        f"Privatliquidation nach {scale}",
        seed=seed,
    )
    bill.paragraph(greeting(addressee))
    bill.paragraph(
        f"für die ärztliche Behandlung von {patient.name} erlaube ich mir, folgende Leistungen zu berechnen"
        + (f" (Heil- und Kostenplan vom {german(plan[1])})" if plan else "")
        + ":"
    )
    rows = []
    total = Decimal("0")
    for when, item, text, factor, amount in treatments:
        rows.append((german(when), item, text, factor, euro(amount)))
        total += amount
    bill.table(
        [
            Column("Datum", 22),
            Column(scale, 15),
            Column("Leistung", 88),
            Column("Faktor", 15, "right"),
            Column("EUR", 25, "right"),
        ],
        rows,
        size=8.5,
    )
    bill.totals([("Rechnungsbetrag", f"{euro(total)} EUR")])
    due = day + timedelta(days=30)
    _pay_by_transfer(bill, sender, total, due, f"Rg {number}")
    bill.paragraph(
        "Ärztliche Leistungen sind nach § 4 Nr. 14 UStG von der Umsatzsteuer befreit.", size=8.5
    )
    bill.signature("Mit freundlichen Grüßen", sender.name)
    return doc(
        "doctor-invoice",
        "Rechnung",
        sender,
        day,
        f"Arztrechnung {patient.first} {german(day)}",
        bill,
        recipient=addressee.username,
        fields={"Betrag": money(total), "Rechnungsnummer": number, "Fällig am": due.isoformat()},
        facts=[("invoice_number", number), ("iban", sender.iban)],
        codes=["QR Code"],
        download=f"Rechnung_{number}.pdf",
    )


def treatment_plan(day: date, number: str, patient: Person, seed: int = 0) -> Doc:
    s = c.ZAHNARZT
    bill = letter(
        s,
        patient,
        day,
        [
            ("Plan-Nr.", number),
            ("Patient", patient.name),
            ("Versichertennr.", patient.health_insurance_number),
        ],
        "Heil- und Kostenplan: Krone Zahn 36",
        seed=seed,
    )
    bill.paragraph(greeting(patient))
    bill.paragraph(
        "anbei erhalten Sie den Heil- und Kostenplan für die geplante Versorgung. Bitte reichen Sie ihn vor Behandlungsbeginn bei Ihrer Krankenkasse ein."
    )
    bill.table(
        [
            Column("Zahn", 15),
            Column("Befund / Leistung", 95),
            Column("Anzahl", 20, "right"),
            Column("EUR", 35, "right"),
        ],
        [
            ("36", "Vollkeramikkrone", "1", "780,00"),
            ("36", "Provisorium", "1", "65,40"),
            ("", "Material- und Laborkosten (geschätzt)", "1", "312,00"),
        ],
        shade=True,
    )
    bill.totals(
        [
            ("Voraussichtliche Gesamtkosten", "1.157,40 EUR"),
            ("Festzuschuss der Krankenkasse", "-412,30"),
            ("Voraussichtlicher Eigenanteil", "745,10 EUR"),
        ]
    )
    bill.signature("Mit freundlichen Grüßen", "Dr. med. dent. Jonas Lehmann")
    return doc(
        "treatment-plan",
        "Mitteilung",
        s,
        day,
        "Heil- und Kostenplan Zahn 36",
        bill,
        recipient=patient.username,
        fields={"Betrag": money("745.10")},
        facts=[("health_insurance_number", patient.health_insurance_number)],
        download=f"HKP_{number}.pdf",
    )


def garage_invoice(number: str, day: date, km: int, items, order: str, seed: int = 0) -> Doc:
    s = c.AUTOHAUS
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Rechnungsnummer", number),
            ("Auftragsnummer", order),
            ("Kennzeichen", LICENSE_PLATE),
            ("Kilometerstand", f"{km:,}".replace(",", ".")),
        ],
        f"Rechnung Nr. {number}: Inspektion Kompakt 1.5 TSI",
        reference=f"Rechnung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"vielen Dank für Ihren Werkstattauftrag. Fahrzeug: Kompakt 1.5, amtliches Kennzeichen {LICENSE_PLATE}, FIN WMZZZ1KZ8LW123456."
    )
    net, tax, gross = lines_table(bill, items)
    bill.totals(
        [
            ("Summe netto", euro(net)),
            ("Umsatzsteuer 19 %", euro(tax)),
            ("Rechnungsbetrag", f"{euro(gross)} EUR"),
        ]
    )
    bill.paragraph(f"Betrag dankend per Karte erhalten am {german(day)}.", bold=True)
    bill.paragraph("Nächste Inspektion: in 12 Monaten oder 15.000 km. Wir wünschen gute Fahrt!")
    return doc(
        "garage-invoice",
        "Rechnung",
        s,
        day,
        f"Werkstattrechnung Inspektion {day.year}",
        bill,
        fields={"Betrag": money(gross), "Rechnungsnummer": number},
        facts=[
            ("invoice_number", number),
            ("order_number", order),
            ("license_plate", LICENSE_PLATE),
            ("vat_id", s.vat_id),
            ("iban", s.iban),
        ],
        download=f"Rechnung_{number}.pdf",
    )


def inspection_report(day: date, number: str, km: int, seed: int = 0) -> Doc:
    """The report of the general inspection (HU) with its sticker until the month two years on."""
    s = c.PRUEFDIENST
    bill = letter(
        s,
        MAX,
        day,
        [("Prüfbericht-Nr.", number), ("Kennzeichen", LICENSE_PLATE)],
        "Untersuchungsbericht Hauptuntersuchung nach § 29 StVZO",
        seed=seed,
    )
    bill.pairs(
        [
            ("Fahrzeug", "Kompakt 1.5, Pkw, Erstzulassung 03.2020"),
            ("FIN", "WMZZZ1KZ8LW123456"),
            ("Kilometerstand", f"{km:,} km".replace(",", ".")),
            ("Ergebnis", "Ohne festgestellte Mängel – Prüfplakette zugeteilt"),
            ("Nächste HU", f"{MONTHS[day.month - 1]} {day.year + 2}"),
            ("Gebühr", "142,50 EUR inkl. 19 % USt. – bar bezahlt"),
        ],
        label_width=45,
    )
    bill.heading("Hinweise")
    bill.paragraph(
        "Geringe Mängel: keine. Hinweis: Bremsscheiben vorne bald verschleißgrenze erreicht. Reifen hinten 3 mm Profil."
    )
    bill.signature(
        "Prüfingenieur", "Dipl.-Ing. Kemal Özdemir", "amtlich anerkannter Sachverständiger"
    )
    return doc(
        "inspection-report",
        "Bescheinigung",
        s,
        day,
        f"HU-Bericht {day.year}",
        bill,
        fields={"Betrag": money("142.50")},
        facts=[("license_plate", LICENSE_PLATE), ("vat_id", s.vat_id)],
        download=f"HU_{number}.pdf",
    )


BERGMANN_CUSTOMER = "7700 4521"


def shop_order_screen(
    sender, order: str, day: date, items: list[tuple[str, Decimal]], url: str
) -> Doc:
    total = sum((price for _, price in items), Decimal("0"))
    page = confirmation(
        sender,
        "Vielen Dank für Ihre Bestellung!",
        f"Ihre Bestellung ist bei uns eingegangen. Eine Bestätigung haben wir an {'max.mustermann@posteo-beispiel.example'} gesendet.",
        [
            ("Bestellnummer", order),
            ("Bestelldatum", german(day)),
            ("Lieferadresse", f"Max Mustermann, {', '.join(street(day))}"),
            ("Zahlungsart", "Rechnung"),
            ("Gesamtsumme", f"{euro(total)} €"),
        ],
        [(name, f"{euro(price)} €") for name, price in items]
        + [("Versand", "0,00 €"), ("Summe inkl. MwSt.", f"{euro(total)} €")],
        "Voraussichtliche Lieferung in 2–4 Werktagen.",
    )
    return doc(
        "order-confirmation",
        "Bestellbestätigung",
        sender,
        day,
        f"Bestellung {order}",
        [page],
        fields={"Betrag": money(total)},
        facts=[("order_number", order)],
        layout="screen",
        url=url,
        download=f"Bestellung_{order}.pdf",
    )


def shop_order_letter(
    sender, order: str, day: date, items: list[tuple[str, Decimal]], *, customer: str, seed: int = 0
) -> Doc:
    total = sum((price for _, price in items), Decimal("0"))
    bill = letter(
        sender,
        MAX,
        day,
        [("Kundennummer", customer), ("Bestellnummer", order)],
        f"Ihre Bestellung {order}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "vielen Dank für Ihre Bestellung. Wir haben folgende Artikel für Sie reserviert:"
    )
    bill.table(
        [Column("Artikel", 120), Column("Preis EUR", 45, "right")],
        [(name, euro(price)) for name, price in items],
        shade=True,
    )
    bill.totals([("Gesamtsumme inkl. MwSt.", f"{euro(total)} EUR")])
    bill.paragraph("Die Rechnung erhalten Sie mit der Lieferung. Sie haben 30 Tage Rückgaberecht.")
    bill.paragraph("Ihr Bergmann-Team")
    return doc(
        "order-confirmation",
        "Bestellbestätigung",
        sender,
        day,
        f"Bestellbestätigung {order}",
        bill,
        fields={"Betrag": money(total), "Kundennummer": customer},
        facts=[("order_number", order), ("customer_number", customer)],
        download=f"Bestellbestaetigung_{order}.pdf",
    )


def delivery_note(
    sender,
    number: str,
    order: str,
    day: date,
    items: list[tuple[str, int]],
    *,
    customer: str = "",
    seed: int = 0,
    printout_style: bool = False,
) -> Doc:
    if printout_style:
        road, city = street(day)
        lines = [
            f"LIEFERSCHEIN {number}                 DATUM {german(day)}",
            "",
            "MAX MUSTERMANN",
            road.upper(),
            city.upper(),
            "",
            f"BESTELLNR. {order}    KUNDENNR. {customer}",
            "",
            "POS  ARTIKELNR   BEZEICHNUNG                          MENGE",
            "---  ----------  -----------------------------------  -----",
        ]
        for n, (name, qty) in enumerate(items, start=1):
            lines.append(f"{n:>3}  {4400000 + n * 137:>10}  {name[:35]:<35}  {qty:>5}")
        lines += [
            "",
            f"PAKETE: {len(items)}   GEWICHT: {len(items) * 3.4:.1f} KG",
            "",
            "WARE ERHALTEN: ________________________",
        ]
        pages = printout(f"{sender.name} - Lager Paketstadt", lines)
        return doc(
            "delivery-note",
            "Lieferschein",
            sender,
            day,
            f"Lieferschein {number}",
            pages,
            facts=[("order_number", order, "refers"), ("customer_number", customer)]
            if customer
            else [("order_number", order, "refers")],
            layout="printout",
            download=f"Lieferschein_{number}.pdf",
        )
    info = [("Lieferschein-Nr.", number), ("Bestellnummer", order)]
    if customer:
        info.append(("Kundennummer", customer))
    bill = letter(
        sender, MAX, day, info, f"Lieferschein {number}", seed=seed, date_label="Lieferdatum"
    )
    bill.table(
        [Column("Pos.", 15), Column("Artikel", 120), Column("Menge", 30, "right")],
        [(str(n), name, str(qty)) for n, (name, qty) in enumerate(items, start=1)],
        shade=True,
    )
    bill.paragraph("Ware vollständig und unbeschädigt erhalten:")
    bill.space(10)
    bill.paragraph("_______________________________   Datum, Unterschrift")
    facts = [("order_number", order, "refers")]
    if customer:
        facts.append(("customer_number", customer))
    return doc(
        "delivery-note",
        "Lieferschein",
        sender,
        day,
        f"Lieferschein {number}",
        bill,
        facts=facts,
        download=f"Lieferschein_{number}.pdf",
    )


def shop_invoice(
    sender,
    number: str,
    order: str,
    day: date,
    items,
    *,
    customer: str,
    seed: int = 0,
    due_days: int = 14,
) -> Doc:
    bill = letter(
        sender,
        MAX,
        day,
        [("Kundennummer", customer), ("Rechnungsnummer", number), ("Bestellnummer", order)],
        f"Rechnung {number}",
        reference=f"Rechnung {number}",
        seed=seed,
        date_label="Rechnungsdatum",
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"vielen Dank für Ihren Einkauf. Wir berechnen Ihnen für Ihre Bestellung {order}:"
    )
    _net, tax, gross = lines_table(bill, items, gross_prices=True)
    bill.totals(
        [
            ("Gesamtbetrag", euro(gross)),
            ("darin enthaltene MwSt. 19 %", euro(tax)),
            ("Zu zahlen", f"{euro(gross)} EUR"),
        ]
    )
    due = day + timedelta(days=due_days)
    _pay_by_transfer(bill, sender, gross, due, f"{number} {customer.replace(' ', '')}")
    bill.paragraph("Ihr Kundenservice")
    return doc(
        "shop-invoice",
        "Rechnung",
        sender,
        day,
        f"Rechnung {sender.head_name} {number}",
        bill,
        fields={
            "Betrag": money(gross),
            "Rechnungsnummer": number,
            "Kundennummer": customer,
            "Fällig am": due.isoformat(),
        },
        facts=[
            ("invoice_number", number),
            ("order_number", order, "refers"),
            ("customer_number", customer),
            ("iban", sender.iban),
            ("vat_id", sender.vat_id),
        ],
        codes=["QR Code"],
        download=f"Rechnung_{number}.pdf",
    )


def credit_note(
    sender,
    number: str,
    invoice: str,
    invoice_day: date,
    day: date,
    items,
    *,
    customer: str,
    seed: int = 0,
) -> Doc:
    bill = letter(
        sender,
        MAX,
        day,
        [("Kundennummer", customer), ("Gutschriftsnummer", number)],
        f"Gutschrift {number} zu Ihrer Rechnung Nr. {invoice} vom {german(invoice_day)}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "Ihre Rücksendung ist bei uns eingegangen. Für die folgenden Artikel schreiben wir Ihnen gut:"
    )
    _net, tax, gross = lines_table(bill, items, gross_prices=True)
    bill.totals(
        [("Gutschriftsbetrag", f"{euro(gross)} EUR"), ("darin enthaltene MwSt. 19 %", euro(tax))]
    )
    bill.paragraph(
        f"Den Betrag verrechnen wir mit der offenen Rechnung {invoice}. Es verbleibt ein Restbetrag, den Sie bitte wie auf der Rechnung angegeben begleichen."
    )
    bill.paragraph("Ihr Kundenservice")
    return doc(
        "credit-note",
        "Gutschrift",
        sender,
        day,
        f"Gutschrift {number}",
        bill,
        fields={"Betrag": money(gross), "Kundennummer": customer},
        facts=[
            ("credit_note_number", number),
            ("invoice_number", invoice, "refers"),
            ("customer_number", customer),
        ],
        download=f"Gutschrift_{number}.pdf",
    )


def warranty(day: date, serial: str, invoice: str, seed: int = 0) -> Doc:
    s = c.TECHNIKWELT
    bill = letter(
        s,
        MAX,
        day,
        [("Rechnungsnummer", invoice), ("Seriennummer", serial)],
        "Garantiezertifikat: 3 Jahre Garantie-Plus",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "herzlichen Glückwunsch zu Ihrem neuen Gerät! Mit diesem Zertifikat verlängert sich die Herstellergarantie auf insgesamt drei Jahre."
    )
    bill.pairs(
        [
            ("Gerät", "Notebook ProBook 14, 16 GB, 512 GB SSD"),
            ("Seriennummer", serial),
            ("Kaufdatum", german(day)),
            ("Garantie bis", german(day.replace(year=day.year + 3))),
            ("Kaufbeleg", f"Ihre Rechnung {invoice}"),
        ]
    )
    bill.paragraph(
        "Bitte bewahren Sie dieses Zertifikat zusammen mit der Rechnung auf. Im Garantiefall wenden Sie sich an unseren Service."
    )
    bill.code(
        code(f"TW-GARANTIE:{serial}", "Data Matrix"), ["Garantie-Code", "für den Service"], side=18
    )
    return doc(
        "warranty",
        "Garantie",
        s,
        day,
        "Garantiezertifikat Notebook",
        bill,
        facts=[("invoice_number", invoice, "refers")],
        codes=["Data Matrix"],
        download="Garantiezertifikat.pdf",
    )


def furniture_order(day: date, number: str, items, deposit: Decimal, seed: int = 0) -> Doc:
    s = c.MOEBEL
    bill = letter(
        s,
        MAX,
        day,
        [("Auftragsnummer", number), ("Kundennummer", "WF-30455"), ("Berater", "Herr Sander")],
        f"Kaufvertrag / Auftragsbestätigung {number}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        "vielen Dank für Ihren Einkauf in unserem Haus. Wir bestätigen Ihren Auftrag wie folgt:"
    )
    _net, _tax, gross = lines_table(bill, items, gross_prices=True)
    bill.totals(
        [
            ("Kaufpreis inkl. MwSt.", euro(gross)),
            ("Anzahlung erhalten", euro(-deposit)),
            ("Restbetrag bei Lieferung", f"{euro(gross - deposit)} EUR"),
        ]
    )
    bill.paragraph(
        "Liefertermin: KW 33/2025, Lieferung frei Haus in die Lindenallee 12, inkl. Montage. Es gelten unsere Allgemeinen Geschäftsbedingungen."
    )
    bill.signature("Mit freundlichen Grüßen", "Lars Sander", "Einrichtungsberater")
    return doc(
        "purchase-contract",
        "Vertrag",
        s,
        day,
        f"Kaufvertrag Sofa {number}",
        bill,
        fields={"Betrag": money(gross)},
        facts=[("order_number", number), ("customer_number", "WF-30455"), ("vat_id", s.vat_id)],
        download=f"Auftrag_{number}.pdf",
    )


def hosting_invoice(month: date, seed: int) -> Doc:
    """Cloudberry's monthly invoice in English, in US dollars."""
    rng = random.Random(seed)
    s = c.CLOUDBERRY
    number = f"CB-{month:%Y%m}-{rng.randint(1000, 9999)}"
    day = date(month.year, month.month, 1)
    bill = letter(
        s,
        MAX,
        day,
        [
            ("Invoice no.", number),
            ("Customer ID", "CBH-88412"),
            ("Billing period", f"{month:%b %Y}"),
        ],
        f"Invoice {number}",
        reference=f"Invoice {number}",
        seed=seed,
        date_label="Invoice date",
    )
    bill.page_word, bill.of_word = "Page", "of"
    bill.recipient = ("Max Mustermann", *street(day), "Germany")
    bill.paragraph("Dear Max Mustermann,")
    bill.paragraph(
        "thank you for hosting with Cloudberry. This invoice covers your subscription for the period below."
    )
    items = [
        ("Cloud VPS M (2 vCPU, 4 GB)", Decimal("1"), "month", Decimal("12.00")),
        ("Daily backups", Decimal("1"), "month", Decimal("2.40")),
    ]
    if rng.random() < 0.4:
        items.append(("Additional storage 50 GB", Decimal("1"), "month", Decimal("2.50")))
    if month.month == 1:
        items.append(
            ("Domain renewal mustermann-familie.example", Decimal("1"), "year", Decimal("14.99"))
        )
    net, _tax, gross = lines_table(bill, items, english=True, rate=0)
    bill.totals(
        [
            ("Subtotal", f"USD {net:.2f}"),
            ("Sales tax (0 %)", "USD 0.00"),
            ("Total", f"USD {gross:.2f}"),
        ]
    )
    bill.paragraph(
        f"Paid by credit card ending in 4242 on {month:%B} {day.day}, {month.year}. No action is required."
    )
    bill.paragraph(
        "Questions? Write to billing@cloudberry-hosting.example. Thank you for your business!"
    )
    return doc(
        "hosting-invoice",
        "Rechnung",
        s,
        day,
        f"Cloudberry invoice {month:%B %Y}",
        bill,
        language="en",
        fields={
            "Betrag": money(gross, "USD"),
            "Rechnungsnummer": number,
            "Bezugszeitraum": f"{month:%Y-%m}",
        },
        facts=[
            ("invoice_number", number),
            ("customer_number", "CBH-88412"),
            ("email_domain", "cloudberry-hosting.example"),
        ],
        download=f"invoice_{number}.pdf",
    )
