"""Work: pay slips of both employers, annual wage tax certificates, an employment contract,
salary letters, references, a termination, monthly time sheets."""

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from synth import contacts as c
from synth.classes.common import ERIKA, MAX, greeting, letter
from synth.document import Doc, doc, money
from synth.fonts import MONO, SANS, SANS_BOLD, Font
from synth.household import ERIKA_IBAN, MAX_IBAN, Person, address
from synth.layout import GREY, Page
from synth.letter import _tint
from synth.numbers import MONTHS, euro, german
from synth.printout import printout

D = Decimal
CENT = D("0.01")

MAX_PERSONNEL = "004711"
ERIKA_PERSONNEL = "7712345"


def _gross(month: date) -> Decimal:
    if month < date(2025, 4, 1):
        return D("4850.00")
    if month < date(2026, 4, 1):
        return D("5020.00")
    return D("5180.00")


def _deductions(gross: Decimal, klasse: int) -> list[tuple[str, Decimal]]:
    tax = (gross * (D("0.142") if klasse == 3 else D("0.185"))).quantize(CENT, ROUND_HALF_UP)
    return [
        ("Lohnsteuer", tax),
        ("Solidaritätszuschlag", D("0.00")),
        ("Kirchensteuer rk 9 %", (tax * D("0.09")).quantize(CENT, ROUND_HALF_UP)),
        (
            "Krankenversicherung 8,15 %",
            (min(gross, D("5512.50")) * D("0.0815")).quantize(CENT, ROUND_HALF_UP),
        ),
        (
            "Pflegeversicherung 1,80 %",
            (min(gross, D("5512.50")) * D("0.018")).quantize(CENT, ROUND_HALF_UP),
        ),
        ("Rentenversicherung 9,30 %", (gross * D("0.093")).quantize(CENT, ROUND_HALF_UP)),
        ("Arbeitslosenversicherung 1,30 %", (gross * D("0.013")).quantize(CENT, ROUND_HALF_UP)),
    ]


def payslip(month: date, *, seed: int = 0) -> Doc:
    """Max's monthly pay slip from Brückner Maschinenbau, in the boxed layout of a payroll
    program: personal data, earnings, deductions, net and payout."""
    s = c.BRUECKNER
    day = date(month.year, month.month, 25)
    base = _gross(month)
    earnings = [
        ("1000", "Gehalt", base),
        ("1200", "Vermögenswirksame Leistungen AG", D("40.00")),
        ("1510", "Fahrtkostenzuschuss pauschal", D("60.00")),
    ]
    if month.month == 11:
        earnings.append(("2100", "Weihnachtsgeld", (base * D("0.55")).quantize(CENT)))
    if month.month == 6:
        earnings.append(("2200", "Urlaubsgeld", D("1200.00")))
    if month.month in (3, 9):
        earnings.append(("1300", "Überstunden 25 %", D("312.40")))
    gross = sum((amount for _, _, amount in earnings), D("0"))
    deductions = _deductions(gross - D("60.00"), 3)
    total_deductions = sum((amount for _, amount in deductions), D("0"))
    net = gross - total_deductions
    payout = net - D("40.00")
    page = Page()
    font, bold = Font("sans"), SANS_BOLD
    accent = s.style.accent
    page.text(20, 18, s.name, bold, 12, color=accent)
    page.text(20, 23, f"{s.street} · {s.city}", font, 8, color=GREY)
    page.text(190, 18, "Abrechnung der Brutto/Netto-Bezüge", bold, 11, "right")
    page.text(190, 24, f"für {MONTHS[month.month - 1]} {month.year}", font, 10, "right")
    y = 40
    for line in address(MAX, day):
        page.text(25, y, line, font, 10)
        y += 4.6
    personal = [
        ("Personalnummer", MAX_PERSONNEL),
        ("Steuerklasse", "3"),
        ("Kinderfreibeträge", "0,5"),
        ("Konfession", "rk"),
        ("Steuer-ID", MAX.tax_id),
        ("SV-Nummer", MAX.social_security_number),
        ("Krankenkasse", "Gesundkasse BKK"),
        ("Eintritt", "01.04.2019"),
        ("Kostenstelle", "4100 Konstruktion"),
    ]
    page.rect(115, 34, 75, 4.5 * len(personal) + 3, stroke=(150, 150, 150), width=0.4)
    yy = 38.5
    for label, value in personal:
        page.text(117, yy, label, font, 7.5, color=GREY)
        page.text(188, yy, value, font, 7.5, "right")
        yy += 4.5
    y = 85.0

    def box(title: str, rows: list[tuple[str, str, str]], total: tuple[str, str]) -> None:
        nonlocal y
        page.rect(20, y, 170, 6, fill=_tint(accent, 0.85))
        page.text(22, y + 4.3, title, bold, 9)
        y += 11
        for code_, text, amount in rows:
            page.text(22, y, code_, MONO, 8.5)
            page.text(40, y, text, font, 9)
            page.text(188, y, amount, font, 9, "right")
            y += 4.8
        page.line((120, y - 2.8), (190, y - 2.8), width=0.4)
        y += 1.5
        page.text(122, y, total[0], bold, 9)
        page.text(188, y, total[1], bold, 9, "right")
        y += 9

    box(
        "Bezüge",
        [(code_, text, euro(amount)) for code_, text, amount in earnings],
        ("Gesamt-Brutto", euro(gross)),
    )
    box(
        "Steuer- und Sozialversicherungsabzüge",
        [("", text, euro(amount)) for text, amount in deductions],
        ("Summe Abzüge", euro(total_deductions)),
    )
    box(
        "Nettobezüge / Auszahlung",
        [
            ("", "Netto-Verdienst", euro(net)),
            ("3000", "Vermögensbildung an Bausparkasse Musterland", euro(-D("40.00"))),
        ],
        ("Auszahlungsbetrag", euro(payout)),
    )
    page.text(22, y, f"Überweisung an IBAN {MAX_IBAN}, Sparkasse Musterstadt", font, 9)
    y += 10
    year_gross = gross * month.month
    page.text(22, y, "Jahressummen", bold, 9)
    page.text(
        22,
        y + 5,
        f"Steuer-Brutto {euro(year_gross - D('60') * month.month)}   Lohnsteuer {euro(deductions[0][1] * month.month)}   KiSt {euro(deductions[2][1] * month.month)}",
        font,
        8,
        color=GREY,
    )
    page.text(
        20,
        285,
        "Erstellt mit Lohn+Gehalt 12 · Bitte bewahren Sie diese Abrechnung sorgfältig auf.",
        font,
        7,
        color=GREY,
    )
    return doc(
        "payslip",
        "Lohnabrechnung",
        s,
        day,
        f"Gehaltsabrechnung {MONTHS[month.month - 1]} {month.year}",
        [page],
        fields={
            "Bruttolohn": money(gross),
            "Nettolohn": money(net),
            "Bezugszeitraum": f"{month:%Y-%m}",
        },
        facts=[
            ("personnel_number", MAX_PERSONNEL),
            ("tax_id", MAX.tax_id),
            ("social_security_number", MAX.social_security_number),
            ("iban", MAX_IBAN),
        ],
        layout="form",
        download=f"Entgeltabrechnung_{month:%Y_%m}.pdf",
    )


def payslip_public(month: date, *, seed: int = 0) -> Doc:
    """Erika's notice of pay from the city (public service, TVöD), as a letter."""
    s = c.STADT_PERSONAL
    day = date(month.year, month.month, 20)
    gross = D("3412.66") if month < date(2026, 4, 1) else D("3540.71")
    rows = [("Tabellenentgelt EG 9a Stufe 3", euro(gross)), ("Zulage Bibliotheksdienst", "45,00")]
    gross += D("45.00")
    if month.month == 11:
        rows.append(("Jahressonderzahlung", "2.389,00"))
        gross += D("2389.00")
    deductions = _deductions(gross, 4)
    total = sum((amount for _, amount in deductions), D("0"))
    zvk = (gross * D("0.0181")).quantize(CENT)
    net = gross - total - zvk
    bill = letter(
        s,
        ERIKA,
        day,
        [
            ("Personalnummer", ERIKA_PERSONNEL),
            ("Dienststelle", "Stadtbibliothek"),
            ("Steuerklasse", "4"),
            ("Steuer-ID", ERIKA.tax_id),
        ],
        f"Bezügemitteilung für {MONTHS[month.month - 1]} {month.year}",
        seed=seed,
    )
    bill.pairs([*rows, ("Gesamtbrutto", euro(gross))], label_width=110)
    bill.pairs(
        [(text, euro(amount)) for text, amount in deductions]
        + [
            ("Zusatzversorgungskasse 1,81 %", euro(zvk)),
            ("Gesetzliche Abzüge gesamt", euro(total + zvk)),
        ],
        label_width=110,
    )
    bill.pairs([("Nettobezüge", euro(net)), ("Überweisung auf IBAN", ERIKA_IBAN)], label_width=110)
    bill.paragraph(
        f"SV-Nummer {ERIKA.social_security_number} · Krankenkasse Gesundkasse BKK", size=8.5
    )
    bill.paragraph(
        "Diese Mitteilung wurde maschinell erstellt und ist ohne Unterschrift gültig.", size=8
    )
    return doc(
        "payslip",
        "Lohnabrechnung",
        s,
        day,
        f"Bezügemitteilung Erika {MONTHS[month.month - 1]} {month.year}",
        bill,
        recipient="erika",
        fields={
            "Bruttolohn": money(gross),
            "Nettolohn": money(net),
            "Bezugszeitraum": f"{month:%Y-%m}",
        },
        facts=[
            ("personnel_number", ERIKA_PERSONNEL),
            ("tax_id", ERIKA.tax_id),
            ("social_security_number", ERIKA.social_security_number),
            ("iban", ERIKA_IBAN),
        ],
        download=f"Bezuegemitteilung_{month:%Y%m}.pdf",
    )


def wage_tax_certificate(
    year: int, person: Person, employer, personnel: str, gross: Decimal, *, seed: int = 0
) -> Doc:
    """The annual certificate of wage tax (Ausdruck der elektronischen Lohnsteuerbescheinigung):
    a form of numbered lines."""
    day = date(year + 1, 2, 15)
    tax = (gross * D("0.15")).quantize(CENT)
    page = Page()
    font, bold = SANS, SANS_BOLD
    page.text(20, 18, f"Ausdruck der elektronischen Lohnsteuerbescheinigung für {year}", bold, 12)
    page.text(
        20,
        23,
        "Nachstehende Daten wurden maschinell an die Finanzverwaltung übertragen.",
        font,
        8,
        color=GREY,
    )
    y = 34
    for line in address(person, day):
        page.text(25, y, line, font, 10)
        y += 4.6
    info = [
        ("Dauer des Dienstverhältnisses", f"01.01.{year} – 31.12.{year}"),
        ("Identifikationsnummer", person.tax_id),
        ("Personalnummer", personnel),
        ("Geburtsdatum", german(person.born)),
        ("eTIN", f"{person.last.upper()[:8]}{person.first.upper()[:2]}{person.born:%y%m%d}"),
    ]
    yy = 34
    for label, value in info:
        page.text(115, yy, label, font, 7.5, color=GREY)
        page.text(190, yy, value, font, 8, "right")
        yy += 4.5
    page.text(
        20, 70, f"Arbeitgeber: {employer.name}, {employer.street}, {employer.city}", font, 8.5
    )
    page.text(
        20,
        75,
        "Finanzamt der Betriebsstätte: Musterstadt (2150)  ·  Steuernummer 21/150/04711",
        font,
        8.5,
    )
    rows = [
        ("3.", "Bruttoarbeitslohn einschl. Sachbezüge ohne 9. und 10.", euro(gross)),
        ("4.", "Einbehaltene Lohnsteuer von 3.", euro(tax)),
        ("5.", "Einbehaltener Solidaritätszuschlag von 3.", "0,00"),
        (
            "6.",
            "Einbehaltene Kirchensteuer des Arbeitnehmers von 3.",
            euro((tax * D("0.09")).quantize(CENT)),
        ),
        (
            "17.",
            "Steuerfreie Arbeitgeberleistungen für Fahrten Wohnung – Arbeitsstätte",
            "720,00" if employer is c.BRUECKNER else "0,00",
        ),
        (
            "22a.",
            "Arbeitgeberanteil zur gesetzlichen Rentenversicherung",
            euro((gross * D("0.093")).quantize(CENT)),
        ),
        (
            "23a.",
            "Arbeitnehmeranteil zur gesetzlichen Rentenversicherung",
            euro((gross * D("0.093")).quantize(CENT)),
        ),
        (
            "25.",
            "Arbeitnehmerbeiträge zur gesetzlichen Krankenversicherung",
            euro((min(gross, D("66150")) * D("0.0815")).quantize(CENT)),
        ),
        (
            "26.",
            "Arbeitnehmerbeiträge zur sozialen Pflegeversicherung",
            euro((min(gross, D("66150")) * D("0.018")).quantize(CENT)),
        ),
        (
            "27.",
            "Arbeitnehmerbeiträge zur Arbeitslosenversicherung",
            euro((gross * D("0.013")).quantize(CENT)),
        ),
    ]
    y = 88.0
    for number, text, value in rows:
        page.rect(20, y - 4.5, 170, 7, stroke=(170, 170, 170), width=0.3)
        page.text(22, y, number, bold, 8.5)
        page.text(35, y, text, font, 8.5)
        page.text(188, y, value, font, 9, "right")
        y += 7
    page.text(
        20,
        y + 8,
        f"Steuerklasse {'3' if person is MAX else '4'} gültig ab 01.01.{year}  ·  Kinderfreibeträge 0,5  ·  Konfession rk",
        font,
        8.5,
    )
    return doc(
        "wage-tax-certificate",
        "Lohnsteuerbescheinigung",
        employer,
        day,
        f"Lohnsteuerbescheinigung {year} {person.first}",
        [page],
        recipient=person.username,
        fields={"Bruttolohn": money(gross), "Bezugszeitraum": str(year)},
        facts=[
            ("tax_id", person.tax_id),
            ("personnel_number", personnel),
            ("tax_number", "21/150/04711"),
        ],
        layout="form",
        download=f"Lohnsteuerbescheinigung_{year}.pdf",
    )


def employment_contract(day: date, seed: int = 0) -> Doc:
    s = c.STADT_PERSONAL
    bill = letter(
        s,
        ERIKA,
        day,
        [("Personalnummer", ERIKA_PERSONNEL), ("Aktenzeichen", "10.2-2025/117")],
        "Arbeitsvertrag",
        seed=seed,
    )
    bill.paragraph(
        "Zwischen der Stadt Musterstadt, vertreten durch den Oberbürgermeister, und Frau Erika Musterfrau, geboren am 02.11.1986, wird folgender Arbeitsvertrag geschlossen:"
    )
    clauses = [
        (
            "§ 1 Beginn und Dauer",
            "Frau Musterfrau wird ab dem 01.03.2025 auf unbestimmte Zeit als Teilzeitbeschäftigte mit 30 Stunden wöchentlich in der Stadtbibliothek eingestellt.",
        ),
        (
            "§ 2 Tarifvertrag",
            "Das Arbeitsverhältnis bestimmt sich nach dem Tarifvertrag für den öffentlichen Dienst (TVöD) in der für den Bereich der Vereinigung der kommunalen Arbeitgeberverbände jeweils geltenden Fassung.",
        ),
        ("§ 3 Probezeit", "Die ersten sechs Monate gelten als Probezeit."),
        (
            "§ 4 Eingruppierung",
            "Frau Musterfrau ist in der Entgeltgruppe 9a, Stufe 3, eingruppiert.",
        ),
        (
            "§ 5 Nebenabreden",
            "Nebenabreden sind nur wirksam, wenn sie schriftlich vereinbart werden. Die Zusatzversorgung erfolgt über die Zusatzversorgungskasse Musterland.",
        ),
        (
            "§ 6 Erholungsurlaub",
            "Der Urlaub richtet sich nach § 26 TVöD und beträgt bei einer Fünf-Tage-Woche 30 Arbeitstage im Kalenderjahr.",
        ),
        (
            "§ 7 Verschwiegenheit",
            "Frau Musterfrau verpflichtet sich, über alle dienstlichen Angelegenheiten Verschwiegenheit zu wahren, auch nach Beendigung des Arbeitsverhältnisses.",
        ),
    ]
    for heading, text in clauses:
        bill.heading(heading, size=10)
        bill.paragraph(text)
    bill.space(6)
    bill.signature(
        f"Musterstadt, {german(day)}", "i. A. Dr. Hartmut Franke", "Leiter des Personalamts"
    )
    bill.signature("Einverstanden:", "Erika Musterfrau")
    return doc(
        "employment-contract",
        "Vertrag",
        s,
        day,
        "Arbeitsvertrag Stadt Musterstadt",
        bill,
        recipient="erika",
        fields={"Vertragsbeginn": "2025-03-01", "Aktenzeichen": "10.2-2025/117"},
        facts=[("personnel_number", ERIKA_PERSONNEL), ("file_reference", "10.2-2025/117")],
        download="Arbeitsvertrag.pdf",
    )


def salary_letter(day: date, new: Decimal, valid: date, seed: int = 0) -> Doc:
    s = c.BRUECKNER
    bill = letter(
        s,
        MAX,
        day,
        [("Personalnummer", MAX_PERSONNEL), ("Unser Zeichen", "PA/ost-2503")],
        f"Anpassung Ihres Gehalts zum {german(valid)}",
        seed=seed,
    )
    bill.paragraph(greeting(MAX))
    bill.paragraph(
        f"in Anerkennung Ihrer Leistungen freuen wir uns, Ihnen mitzuteilen, dass Ihr monatliches Bruttogehalt ab dem {german(valid)} auf {euro(new)} EUR angehoben wird. Alle übrigen Bestimmungen Ihres Arbeitsvertrags bleiben unverändert."
    )
    bill.paragraph(
        "Wir danken Ihnen für Ihren Einsatz und freuen uns auf die weitere Zusammenarbeit."
    )
    bill.signature("Mit freundlichen Grüßen", "Ralf Ostendorf", "Geschäftsführer")
    return doc(
        "salary-change",
        "Mitteilung",
        s,
        day,
        f"Gehaltsanpassung {valid.year}",
        bill,
        fields={"Bruttolohn": money(new)},
        facts=[("personnel_number", MAX_PERSONNEL), ("our_reference", "PA/ost-2503")],
        download=f"Gehaltsanpassung_{valid.year}.pdf",
    )


def reference(
    sender,
    person: Person,
    day: date,
    kind: str,
    text: list[str],
    signer: tuple[str, str],
    seed: int = 0,
) -> Doc:
    """A reference (Arbeitszeugnis or Zwischenzeugnis): a heading, no window address."""
    bill = letter(sender, person, day, [], kind, seed=seed)
    for paragraph in text:
        bill.paragraph(paragraph)
    bill.signature(f"Musterstadt, {german(day)}", *signer)
    return doc(
        "reference",
        "Zeugnis",
        sender,
        day,
        f"{kind} {person.first}",
        bill,
        recipient=person.username,
        download=f"{kind}.pdf",
    )


def termination_confirmation(day: date, letter_day: date, seed: int = 0) -> Doc:
    s = c.BUCHHANDLUNG
    bill = letter(
        s, ERIKA, day, [("Personalnummer", "112")], "Bestätigung Ihrer Kündigung", seed=seed
    )
    bill.paragraph(greeting(ERIKA))
    bill.paragraph(
        f"wir bestätigen den Eingang Ihres Schreibens vom {german(letter_day)}, mit dem Sie Ihr Arbeitsverhältnis fristgerecht zum 28.02.2025 kündigen. Wir bedauern Ihre Entscheidung sehr."
    )
    bill.paragraph(
        "Ihren Resturlaub von 6 Tagen gewähren wir Ihnen vom 17. bis 24.02.2025. Ihre Arbeitspapiere und Ihr Zeugnis erhalten Sie mit der letzten Abrechnung."
    )
    bill.paragraph("Für Ihre Zukunft wünschen wir Ihnen alles Gute.")
    bill.signature("Mit freundlichen Grüßen", "Marlene Kurz", "Geschäftsführerin")
    return doc(
        "termination",
        "Kündigung",
        s,
        day,
        "Kündigungsbestätigung Buchhandlung",
        bill,
        recipient="erika",
        facts=[("letter_date", german(letter_day)), ("personnel_number", "112")],
        download="Kuendigungsbestaetigung.pdf",
    )


def time_sheet(month: date, seed: int) -> Doc:
    """Max's monthly time sheet as the time recording system prints it."""
    rng = random.Random(seed)
    lines = [
        f" Mitarbeiter    : Max Mustermann              Monat    : {month:%m/%Y}",
        f" Personalnummer : {MAX_PERSONNEL}                      Druckdatum: {german(_next_month(month) + timedelta(days=1))}",
        " Kostenstelle   : 4100 Konstruktion           Modell   : Gleitzeit 40h",
        "",
        "-" * 70,
        "|Tag    |Kommen Gehen  Pause |  Ist  | Soll  | Saldo |Bemerkung      |",
        "-" * 70,
    ]
    day = month
    balance = D("0")
    total = D("0")
    while day.month == month.month:
        if day.weekday() < 5:
            start = 7 * 60 + rng.randint(0, 75)
            hours = D(rng.randint(450, 560)) / 60
            end = start + int(hours * 60) + 30
            ist = hours.quantize(CENT)
            saldo = ist - 8
            balance += saldo
            total += ist
            note = rng.choice(["", "", "", "", "Dienstgang", "Homeoffice"])
            lines.append(
                f"|{day:%d} {_WEEKDAYS[day.weekday()]}  |{start // 60:02d}:{start % 60:02d}  {end // 60:02d}:{end % 60:02d}  0:30 | {ist:5.2f} |  8.00 | {saldo:+5.2f} |{note:<15}|"
            )
        day += timedelta(days=1)
    lines += [
        "-" * 70,
        f"|Summe Monat                 |{total:6.2f} |       |{balance:+6.2f} |               |",
        "-" * 70,
        "",
        f" Gleitzeitkonto Vortrag: +12.40   Neu: {balance + D('12.40'):+.2f}",
        "",
        " Unterschrift Mitarbeiter: ______________   Vorgesetzter: ______________",
    ]
    pages = printout(
        f"Zeitnachweis {MONTHS[month.month - 1]} {month.year} - BRÜCKNER Zeitwirtschaft",
        lines,
        size=8.5,
    )
    return doc(
        "time-sheet",
        "Zeitnachweis",
        c.BRUECKNER,
        _next_month(month) + timedelta(days=1),
        f"Zeitnachweis {MONTHS[month.month - 1]} {month.year}",
        pages,
        fields={"Bezugszeitraum": f"{month:%Y-%m}"},
        facts=[("personnel_number", MAX_PERSONNEL)],
        layout="printout",
        download=f"ZEITNACHWEIS_{month:%Y%m}.PDF",
    )


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)
