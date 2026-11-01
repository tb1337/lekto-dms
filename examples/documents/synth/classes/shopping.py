"""Till receipts of shops, petrol stations, a bakery, a café and a pharmacy; a receipt for cash
paid (Quittung) and a private sale, filled in by hand."""

import random
from datetime import date, datetime
from decimal import Decimal

from synth import contacts as c
from synth import ids
from synth.codes import code
from synth.document import Doc, doc, money
from synth.fonts import HAND, SANS, SANS_BOLD, SERIF, Font
from synth.household import MAX, street
from synth.layout import GREY, Page
from synth.letter import Sender
from synth.numbers import euro, german
from synth.receipt import Item, receipt

D = Decimal

_GROCERIES = [
    ("Vollmilch 3,5% 1l", "1,19", "B"),
    ("Bio Bauernbrot 750g", "3,49", "B"),
    ("Äpfel Elstar", "2,49", "B"),
    ("Butter 250g", "2,29", "B"),
    ("Gouda jung Scheiben", "1,89", "B"),
    ("Kaffee Bohne 1kg", "13,99", "B"),
    ("Apfelsaft naturtrüb 1l", "1,79", "A"),
    ("Spülmittel Zitrone", "1,25", "A"),
    ("Nudeln Fusilli 500g", "0,99", "B"),
    ("Tomaten passiert", "0,89", "B"),
    ("Bananen", "1,69", "B"),
    ("Joghurt Natur 500g", "0,79", "B"),
    ("Mineralwasser 6x1,5l", "3,54", "A"),
    ("Pfand", "1,50", "A"),
    ("Küchenrolle 4er", "3,29", "A"),
    ("Hähnchenbrust 400g", "5,99", "B"),
    ("Eier Freiland 10er", "3,19", "B"),
    ("Schokolade Vollmilch", "1,49", "B"),
]
_HARDWARE = [
    ("Farbrolle 18cm", "4,29", "A"),
    ("Schrauben 4x40 200St", "7,99", "A"),
    ("Wandfarbe weiß 10l", "39,95", "A"),
    ("Abdeckfolie 4x5m", "3,49", "A"),
    ("Dübel 6mm 100St", "4,99", "A"),
    ("Akku-Bohrschrauber 18V", "89,00", "A"),
    ("Silikon transparent", "6,49", "A"),
    ("Blumenerde 40l", "5,99", "A"),
    ("Glühbirne LED E27", "3,99", "A"),
]
_DRUGSTORE = [
    ("Zahnpasta Kräuter", "1,45", "A"),
    ("Shampoo Mild 300ml", "2,95", "A"),
    ("Duschgel Sport", "1,25", "A"),
    ("Sonnencreme LSF 50", "8,95", "A"),
    ("Taschentücher 30x10", "2,75", "A"),
    ("Babyöl", "3,45", "A"),
    ("Pflaster Sortiment", "2,99", "A"),
    ("Waschmittel 20 WL", "5,95", "A"),
]
_BAKERY = [
    ("Brötchen", "0,45", "B"),
    ("Croissant", "1,30", "B"),
    ("Roggenmischbrot", "3,80", "B"),
    ("Butterbrezel", "1,60", "B"),
    ("Kaffee to go", "2,60", "A"),
]
_CAFE = [
    ("Cappuccino", "3,80", "A"),
    ("Milchkaffee", "4,20", "A"),
    ("Käsekuchen", "4,50", "A"),
    ("Apfelstrudel", "4,90", "A"),
    ("Mineralwasser 0,25", "2,90", "A"),
    ("Kinderkakao", "2,80", "A"),
]

_SHOPS: dict[str, tuple[Sender, list[str], list[tuple[str, str, str]]]] = {
    "grocery": (
        c.FRISCHMARKT,
        [
            "FRISCHMARKT",
            "Hauptstraße 50",
            "12345 Musterstadt",
            "Tel. 01234 66 77 88",
            "St.-Nr. 21/300/40001",
        ],
        _GROCERIES,
    ),
    "hardware": (
        c.BAUMARKT,
        [
            "Baumarkt HAMMER",
            "Gewerbestraße 3",
            "12349 Musterstadt",
            f"USt-IdNr. {ids.vat_id('30122344')}",
        ],
        _HARDWARE,
    ),
    "drugstore": (
        c.DROGERIE,
        ["Drogerie Sonne", "Bahnhofstraße 12", "12345 Musterstadt", "Inh. Sonja Albers e.K."],
        _DRUGSTORE,
    ),
    "bakery": (c.BAECKEREI, ["Bäckerei Krume", "Kirchplatz 3 · Musterstadt", "seit 1952"], _BAKERY),
    "cafe": (
        c.CAFE,
        ["Café Lindenblüte", "Lindenallee 2", "12345 Musterstadt", "Tisch 4 · Bedienung: Julia"],
        _CAFE,
    ),
}


def _price(text: str) -> Decimal:
    return D(text.replace(",", "."))


def shop_receipt(kind: str, when: datetime, seed: int) -> Doc:
    """A till receipt of `kind` (grocery, hardware, drugstore, bakery, cafe)."""
    rng = random.Random(seed)
    sender, head, stock = _SHOPS[kind]
    count = {
        "grocery": rng.randint(5, 14),
        "hardware": rng.randint(2, 5),
        "drugstore": rng.randint(2, 6),
        "bakery": rng.randint(2, 4),
        "cafe": rng.randint(2, 4),
    }[kind]
    items = []
    for name, price, rate in rng.sample(stock, min(count, len(stock))):
        quantity = rng.choice((1, 1, 1, 2, 3)) if kind in ("grocery", "bakery") else 1
        unit = _price(price)
        detail = f"{quantity} x {euro(unit)}" if quantity > 1 else ""
        if name.startswith("Äpfel") or name.startswith("Bananen"):
            weight = D(rng.randint(600, 1900)) / 1000
            detail, line = (
                f"{weight:.3f} kg x {euro(unit)} EUR/kg".replace(".", ","),
                (weight * unit).quantize(D("0.01")),
            )
        else:
            line = unit * quantity
        items.append(Item(name, line, rate, detail))
    card = rng.random() < 0.55
    total = sum((item.price for item in items), D("0"))
    given = None if card else (total // 5 + 1) * 5
    footer = (
        ["Vielen Dank für Ihren Besuch!"]
        if kind == "cafe"
        else ["Vielen Dank für Ihren Einkauf!", "Umtausch nur mit Kassenbon."]
    )
    extra = []
    if kind == "cafe":
        extra = ["Bewirtungsbeleg: Anlass ______________", "Personen: ___  Trinkgeld: ______"]
    symbol = None
    codes = []
    if kind == "grocery" and rng.random() < 0.6:
        symbol = code(f"V0;{sender.name};Kasse2;{when:%Y%m%d%H%M%S};{total}", "QR Code")
        codes = ["QR Code"]
    elif kind == "hardware":
        symbol = code(f"2{seed:011d}"[:12], "EAN-13")
        codes = ["EAN-13"]
    page, total = receipt(
        head,
        items,
        when,
        payment="Kartenzahlung" if card else "Bar",
        given=given,
        register=f"Kasse {rng.randint(1, 6)}",
        number=rng.randint(1000, 9999),
        tse_serial=f"{seed * 7919:016x}"[-16:],
        code=symbol,
        footer=footer,
        extra=extra,
        font=Font("mono") if kind != "cafe" else Font("sans"),
    )
    return doc(
        "till-receipt",
        "Kassenbon",
        sender,
        when.date(),
        f"Kassenbon {sender.name.split(' ')[0]} {german(when.date())}",
        [page],
        fields={"Betrag": money(total), "Zahlungsart": "Karte" if card else "Bar"},
        codes=codes,
        layout="receipt",
        download=f"eBon_{when:%Y%m%d_%H%M}.pdf",
    )


def fuel_receipt(when: datetime, seed: int) -> Doc:
    rng = random.Random(seed)
    litres = D(rng.randint(2800, 5200)) / 100
    price = D(rng.randint(1659, 1889)) / 1000
    fuel = (litres * price).quantize(D("0.01"))
    items = [
        Item(
            "Super E10",
            fuel,
            "A",
            f"Säule {rng.randint(1, 8)}  {litres:.2f} l x {price:.3f}".replace(".", ","),
        )
    ]
    if rng.random() < 0.4:
        items.append(Item("Kaffee groß", D("2.99"), "A"))
    page, total = receipt(
        [
            "Tankstelle NORD",
            "Ringstraße 2",
            "12359 Musterstadt",
            "Tel. 01234 22 44 66",
            f"USt-IdNr. {ids.vat_id('22446688')}",
        ],
        items,
        when,
        payment="Kartenzahlung",
        register="Kasse 1",
        number=rng.randint(10000, 99999),
        tse_serial=f"{seed * 104729:016x}"[-16:],
        footer=["Gute Fahrt!"],
    )
    return doc(
        "till-receipt",
        "Kassenbon",
        c.TANKSTELLE,
        when.date(),
        f"Tankbeleg {german(when.date())}",
        [page],
        fields={"Betrag": money(total), "Zahlungsart": "Karte"},
        layout="receipt",
        download=f"Tankbeleg_{when:%Y%m%d}.pdf",
    )


def pharmacy_receipt(when: datetime, seed: int) -> Doc:
    rng = random.Random(seed)
    items = [
        Item("Ibuprofen 400mg 20 St.", D("3.95"), "A"),
        Item("Zuzahlung Rezept", D("5.00"), "A", "PZN 01234567"),
    ]
    if rng.random() < 0.5:
        items.append(Item("Nasenspray 10ml", D("4.49"), "A"))
    page, total = receipt(
        [
            "Apotheke am Markt",
            "Marktplatz 6 · 12345 Musterstadt",
            "Apothekerin Dr. Ulla Brandt",
            "Tel. 01234 21 21 21",
        ],
        items,
        when,
        payment="Bar",
        given=D("20.00"),
        register="Kasse 1",
        number=rng.randint(100, 999),
        tse_serial=f"{seed * 31337:016x}"[-16:],
        footer=["Gute Besserung!", "Beleg für Ihre Steuererklärung aufbewahren."],
    )
    return doc(
        "till-receipt",
        "Kassenbon",
        c.APOTHEKE,
        when.date(),
        f"Apotheke {german(when.date())}",
        [page],
        fields={"Betrag": money(total), "Zahlungsart": "Bar"},
        layout="receipt",
        download=f"Beleg_{when:%Y%m%d}.pdf",
    )


def cash_receipt(
    sender: Sender,
    day: date,
    amount: Decimal,
    purpose: str,
    number: str,
    received_from: str = "Max Mustermann",
    *,
    signer: str = "",
) -> Doc:
    """A receipt (Quittung) from a pad, filled in by hand: amount, from whom, for what."""
    page = Page(148, 105)
    page.rect(5, 5, 138, 95, stroke=(60, 60, 60), width=0.8)
    page.text(10, 16, "Quittung", SANS_BOLD, 16)
    page.text(140, 12, "Nr.", SANS, 8, "right", GREY)
    page.text(140, 18, number, HAND, 13, "right", (20, 40, 120))
    lines = [
        ("EUR", f"{euro(amount)}"),
        ("in Worten", _words(amount)),
        ("von", received_from),
        ("für", purpose),
        ("dankend erhalten", f"Musterstadt, {german(day)}"),
    ]
    y = 32.0
    for label, value in lines:
        page.text(10, y, label, SANS, 8, color=GREY)
        page.line((38, y + 1), (138, y + 1), width=0.3, color=(150, 150, 150))
        page.text(40, y, value, HAND, 13, color=(20, 40, 120))
        y += 11
    page.text(10, 92, f"Stempel / Unterschrift {sender.name}", SANS, 7, color=GREY)
    page.text(95, 90, signer or sender.name.split(" ")[0], HAND, 15, color=(20, 40, 120))
    return doc(
        "cash-receipt",
        "Quittung",
        sender,
        day,
        f"Quittung {purpose}",
        [page],
        fields={"Betrag": money(amount), "Zahlungsart": "Bar"},
        layout="form",
        download=f"Quittung_{number}.pdf",
    )


_ONES = [
    "null",
    "ein",
    "zwei",
    "drei",
    "vier",
    "fünf",
    "sechs",
    "sieben",
    "acht",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
    "vierzehn",
    "fünfzehn",
    "sechzehn",
    "siebzehn",
    "achtzehn",
    "neunzehn",
]
_TENS = [
    "",
    "",
    "zwanzig",
    "dreißig",
    "vierzig",
    "fünfzig",
    "sechzig",
    "siebzig",
    "achtzig",
    "neunzig",
]


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    text = f"{_ONES[hundreds]}hundert" if hundreds else ""
    if rest < 20:
        return text + (_ONES[rest] if rest or not text else "")
    tens, ones = divmod(rest, 10)
    return text + (f"{_ONES[ones]}und" if ones else "") + _TENS[tens]


def _words(amount: Decimal) -> str:
    euros = int(amount)
    cents = int((amount - euros) * 100)
    thousands, rest = divmod(euros, 1000)
    text = (f"{_below_thousand(thousands)}tausend" if thousands else "") + (
        _below_thousand(rest) if rest or not thousands else ""
    )
    return f"{text.capitalize()} Euro" + (f" {cents}/100" if cents else "")


def private_sale(day: date, price: Decimal) -> Doc:
    """A purchase contract between private persons for a used bicycle, a printed form filled in
    by hand."""
    seller = c.PRIVATE_SELLER
    page = Page()
    page.text(25, 30, "Kaufvertrag für ein gebrauchtes Fahrrad", SANS_BOLD, 15)
    page.text(
        25,
        37,
        "zwischen Privatpersonen – unter Ausschluss der Sachmängelhaftung",
        SANS,
        9,
        color=GREY,
    )
    road, city = street(day)
    blocks = [
        (
            "Verkäufer",
            [
                ("Name", seller.name),
                ("Anschrift", f"{seller.street}, {seller.city}"),
                ("Telefon", "0170 5544332"),
            ],
        ),
        (
            "Käufer",
            [("Name", MAX.name), ("Anschrift", f"{road}, {city}"), ("Ausweis-Nr.", "geprüft")],
        ),
        (
            "Fahrrad",
            [
                ("Marke / Modell", "Velotrek City 7"),
                ("Rahmennummer", "VT7-2291-AB-3304"),
                ("Farbe", "dunkelgrün"),
                ("Zubehör", "Schloss, Gepäckträger, Licht"),
            ],
        ),
    ]
    y = 52.0
    for title, rows in blocks:
        page.text(25, y, title, SANS_BOLD, 11)
        y += 7
        for label, value in rows:
            page.text(25, y, label, SANS, 9, color=GREY)
            page.line((62, y + 1), (185, y + 1), width=0.3, color=(160, 160, 160))
            page.text(64, y, value, HAND, 14, color=(20, 40, 120))
            y += 8.5
        y += 5
    page.text(25, y, "Kaufpreis", SANS_BOLD, 11)
    page.text(64, y, f"{euro(price)} EUR, in bar erhalten", HAND, 14, color=(20, 40, 120))
    y += 12
    for line in [
        "Der Verkäufer versichert, dass das Fahrrad sein Eigentum ist, nicht gestohlen ist und frei",
        "von Rechten Dritter. Das Fahrrad wird verkauft wie besichtigt, unter Ausschluss jeder",
        "Gewährleistung, soweit nicht Vorsatz oder Arglist vorliegt.",
    ]:
        page.text(25, y, line, SANS, 9)
        y += 5
    y += 12
    page.text(25, y, f"Musterstadt, {german(day)}", HAND, 14, color=(20, 40, 120))
    page.text(120, y, f"Musterstadt, {german(day)}", HAND, 14, color=(20, 40, 120))
    y += 14
    page.text(30, y, "T. Schreiber", HAND, 17, color=(20, 40, 120))
    page.text(125, y, "M. Mustermann", HAND, 17, color=(20, 40, 120))
    page.line((25, y + 2), (95, y + 2), width=0.3)
    page.line((120, y + 2), (185, y + 2), width=0.3)
    page.text(25, y + 6, "Verkäufer", SERIF, 8, color=GREY)
    page.text(120, y + 6, "Käufer", SERIF, 8, color=GREY)
    return doc(
        "private-sale",
        "Vertrag",
        seller,
        day,
        "Kaufvertrag Fahrrad",
        [page],
        fields={"Betrag": money(price)},
        layout="form",
        download="Kaufvertrag_Fahrrad.pdf",
    )
