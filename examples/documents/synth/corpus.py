"""The corpus: every document of the household, when it was captured, in which quality stage,
what was done to its paper, and how it relates to the others. The stages follow how such a
document arrives: portals give PDFs, letters come on paper and are scanned or photographed,
receipts are photographed, a few come by fax."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from synth import contacts as c
from synth import ids
from synth.classes import authorities as au
from synth.classes import bank as bk
from synth.classes import billing as bi
from synth.classes import health as he
from synth.classes import housing as ho
from synth.classes import insurance as ins
from synth.classes import misc as mi
from synth.classes import shopping as sh
from synth.classes import work as wk
from synth.document import Doc, doc
from synth.household import ERIKA, LENA, MAX
from synth.layout import Page
from synth.paper import NO_MARKS, Marks

D = Decimal
TODAY = date(2026, 10, 31)


@dataclass
class Entry:
    key: str
    make: Callable[[], Doc]
    stage: str
    marks: Marks = NO_MARKS
    duplex: bool = False
    turned: frozenset[int] = frozenset()
    tiff: bool = False
    exif_turned: bool = False
    refers: tuple[str, ...] = ()
    series: str | None = None
    duplicate_of: str | None = None
    fax_from: str = ""
    delay: int | None = None  # days from the document's date to its capture
    day: date | None = None  # when it was captured, for a document without a date
    notes: list[str] = field(default_factory=list)


# How a letter that came by post reaches Lekto, and a receipt.
LETTER_STAGES = {
    "scan-clean": 25,
    "scan-office": 30,
    "scan-bw": 14,
    "scanner-ocr": 12,
    "scan-poor": 8,
    "photo": 8,
    "photo-poor": 3,
}
RECEIPT_STAGES = {
    "photo": 40,
    "scan-office": 15,
    "scan-clean": 10,
    "photo-poor": 12,
    "scan-poor": 8,
    "digital": 15,
}


def _months(start: date, end: date) -> list[date]:
    months, month = [], start
    while month <= end:
        months.append(month)
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return months


def entries() -> list[Entry]:
    rng = random.Random(4711)
    out: list[Entry] = []

    def add(key: str, make: Callable[[], Doc], stage: str | None = None, **rest: object) -> Entry:
        chosen = stage or _pick(rng, LETTER_STAGES)
        entry = Entry(key, make, chosen, **rest)  # type: ignore[arg-type]
        if (
            stage is None
            and chosen
            in (
                "scan-clean",
                "scan-office",
                "scan-bw",
                "scanner-ocr",
                "scan-poor",
                "photo",
                "photo-poor",
            )
            and "marks" not in rest
        ):
            entry.marks = _letter_marks(rng)
        out.append(entry)
        return entry

    # Stadtwerke: bills, the move, a correction, a price change, a meter card.
    add(
        "strom-2024",
        lambda: bi.utility_bill_printout(
            "R-2024-0277",
            date(2024, 3, 18),
            date(2023, 3, 1),
            date(2024, 2, 29),
            "1ESY 1160 4471 23",
            D("1297.42"),
        ),
        "scan-bw",
        marks=Marks(holes=True, folds=True),
    )
    add(
        "strom-2025",
        lambda: bi.utility_bill(
            "R-2025-0311",
            date(2025, 3, 20),
            date(2024, 3, 1),
            date(2025, 2, 28),
            "1ESY 1160 4471 23",
            2905,
            12,
            D("98.00"),
            new_advance=D("101.00"),
            seed=1,
        ),
        "digital",
    )
    add(
        "strom-2025-scan",
        lambda: bi.utility_bill(
            "R-2025-0311",
            date(2025, 3, 20),
            date(2024, 3, 1),
            date(2025, 2, 28),
            "1ESY 1160 4471 23",
            2905,
            12,
            D("98.00"),
            new_advance=D("101.00"),
            seed=1,
        ),
        "scan-clean",
        marks=Marks(stamp="BEZAHLT", stamp_date="02.04.2025", folds=True, holes=True),
        duplicate_of="strom-2025",
    )
    add(
        "strom-schluss",
        lambda: bi.utility_bill(
            "R-2025-0884",
            date(2025, 8, 14),
            date(2025, 3, 1),
            date(2025, 7, 31),
            "1ESY 1160 4471 23",
            1083,
            5,
            D("101.00"),
            final=True,
            seed=2,
        ),
        "scanner-ocr",
        marks=Marks(folds=True),
    )
    add(
        "strom-vertrag",
        lambda: bi.utility_contract(
            date(2025, 7, 10), date(2025, 8, 1), "1EMH 0081 2290 41", D("95.00"), "SV-2025-207718"
        ),
        "digital",
    )
    add(
        "strom-preis",
        lambda: bi.price_change(date(2025, 11, 15), date(2026, 1, 1), "SV-2025-207718"),
        "scan-office",
        marks=Marks(folds=True, note="kein Handlungsbedarf"),
    )
    add(
        "strom-ablesung",
        lambda: bi.meter_card(date(2026, 7, 10), "1EMH 0081 2290 41", date(2026, 7, 31)),
        "photo",
        marks=Marks(folds=True),
    )
    add(
        "strom-2026",
        lambda: bi.utility_bill(
            "R-2026-0815",
            date(2026, 8, 18),
            date(2025, 8, 1),
            date(2026, 7, 31),
            "1EMH 0081 2290 41",
            2814,
            11,
            D("95.00"),
            new_advance=D("112.00"),
            seed=3,
        ),
        "digital",
        refers=("strom-vertrag",),
    )
    add(
        "strom-korrektur",
        lambda: bi.utility_correction(
            "R-2026-0902",
            "R-2026-0815",
            date(2026, 8, 18),
            date(2026, 9, 2),
            "1EMH 0081 2290 41",
            D("1281.38"),
            D("1214.73"),
        ),
        "digital",
        refers=("strom-2026",),
    )

    # FernNetz: every month, from the portal; two printed and scanned, one seen in the viewer.
    for n, month in enumerate(_months(date(2024, 1, 1), date(2026, 9, 1))):
        stage = "digital"
        if month in (date(2024, 5, 1), date(2025, 12, 1)):
            stage = "scan-office"
        elif month in (date(2025, 8, 1), date(2026, 6, 1)):
            stage = "screenshot"
        add(
            f"fernnetz-{month:%Y-%m}",
            lambda m=month, s=n: bi.phone_bill(m, 100 + s),
            stage,
            series="fernnetz",
            marks=Marks(highlight="Rechnungsbetrag") if stage == "scan-office" else NO_MARKS,
        )

    # Craftsmen around the move.
    krause_items = [
        ("Arbeitszeit Elektromeister", D("6.5"), "Std.", D("68.00")),
        ("Arbeitszeit Geselle", D("8"), "Std.", D("54.00")),
        ("Steckdose doppelt, Unterputz", D("6"), "Stück", D("18.90")),
        ("Herdanschlussdose", D("1"), "Stück", D("24.50")),
        ("FI-Schutzschalter 40A", D("1"), "Stück", D("89.00")),
    ]
    add(
        "krause-angebot",
        lambda: bi.offer(
            c.ELEKTRO_KRAUSE,
            "AN-2025-118",
            date(2025, 8, 20),
            "Elektroinstallation Küche und Flur",
            krause_items,
            seed=11,
        ),
        "fax",
        fax_from="+49 1234 909091",
    )
    add(
        "krause-rechnung",
        lambda: bi.craft_invoice(
            c.ELEKTRO_KRAUSE,
            "RE-2025-0412",
            date(2025, 9, 30),
            "Elektroinstallation Küche und Flur",
            krause_items,
            offer_ref=("AN-2025-118", date(2025, 8, 20)),
            site="Lindenallee 12, 12345 Musterstadt",
            seed=12,
        ),
        "scan-office",
        marks=Marks(stamp="BEZAHLT", stamp_date="10.11.2025", folds=True),
        refers=("krause-angebot",),
    )
    add(
        "krause-mahnung",
        lambda: bi.reminder(
            c.ELEKTRO_KRAUSE,
            "RE-2025-0412",
            date(2025, 9, 30),
            D("1295.80"),
            date(2025, 11, 3),
            customer="K1012",
            seed=13,
        ),
        "scan-clean",
        marks=Marks(folds=True, note="überwiesen 10.11."),
        refers=("krause-rechnung",),
    )
    maler_items = [
        ("Wände und Decken streichen, 3 Zimmer", D("78"), "m²", D("8.40")),
        ("Spachtelarbeiten", D("4"), "Std.", D("52.00")),
        ("Material Farbe, Abdeckung", D("1"), "pauschal", D("186.00")),
    ]
    add(
        "maler-quittung",
        lambda: sh.cash_receipt(
            c.MALER,
            date(2025, 7, 20),
            D("500.00"),
            "Anzahlung Malerarbeiten Birkenweg",
            "0815",
            signer="Sonnenschein",
        ),
        "photo",
    )
    add(
        "maler-rechnung",
        lambda: bi.craft_invoice(
            c.MALER,
            "2025-147",
            date(2025, 8, 5),
            "Malerarbeiten Birkenweg 5 (Auszug)",
            maler_items,
            site="Birkenweg 5, 12347 Musterstadt",
            seed=14,
            giro=False,
        ),
        "scan-poor",
        marks=Marks(folds=True),
        refers=("maler-quittung",),
    )
    umzug_items = [
        ("Umzug 3-Zimmer-Wohnung, 4 Packer", D("1"), "pauschal", D("1650.00")),
        ("Halteverbotszone beantragen", D("2"), "Stück", D("85.00")),
        ("Umzugskartons", D("40"), "Stück", D("2.50")),
        ("Küchenmontage", D("5"), "Std.", D("58.00")),
    ]
    add(
        "umzug-angebot",
        lambda: bi.offer(
            c.UMZUG,
            "UE-25-0630",
            date(2025, 6, 20),
            "Umzug Birkenweg 5 – Lindenallee 12",
            umzug_items,
            seed=15,
        ),
        "digital",
    )
    add(
        "umzug-rechnung",
        lambda: bi.craft_invoice(
            c.UMZUG,
            "UE-R-25-1102",
            date(2025, 8, 4),
            "Umzug am 31.07.2025",
            umzug_items,
            offer_ref=("UE-25-0630", date(2025, 6, 20)),
            order="UE-25-0630",
            seed=16,
        ),
        "digital",
        refers=("umzug-angebot",),
    )

    # Doctors.
    add(
        "arzt-max",
        lambda: bi.doctor_invoice(
            c.DR_BEISPIEL,
            "2025-0419",
            date(2025, 4, 22),
            MAX,
            [
                (date(2025, 4, 3), "1", "Beratung", "2,3", D("10.72")),
                (date(2025, 4, 3), "29", "Gesundheitsuntersuchung", "2,3", D("58.99")),
                (date(2025, 4, 3), "3550", "Blutbild", "1,15", D("4.02")),
                (date(2025, 4, 3), "250", "Blutentnahme", "1,8", D("4.20")),
            ],
            seed=21,
        ),
        "scan-clean",
        marks=Marks(folds=True, stamp="BEZAHLT", stamp_date="30.04.2025"),
    )
    add(
        "arzt-erika",
        lambda: bi.doctor_invoice(
            c.DR_BEISPIEL,
            "2026-0212",
            date(2026, 2, 17),
            ERIKA,
            [
                (date(2026, 2, 2), "1", "Beratung", "2,3", D("10.72")),
                (date(2026, 2, 2), "5", "Symptombezogene Untersuchung", "2,3", D("10.72")),
                (date(2026, 2, 2), "375", "Schutzimpfung Reise", "2,3", D("10.72")),
            ],
            seed=22,
        ),
        "scanner-ocr",
        marks=Marks(folds=True),
    )
    add(
        "zahnarzt-hkp",
        lambda: bi.treatment_plan(date(2026, 1, 12), "HKP-2026-031", MAX),
        "fax",
        fax_from="+49 1234 676768",
    )
    add(
        "zahnarzt-rechnung",
        lambda: bi.doctor_invoice(
            c.ZAHNARZT,
            "Z-2026-0318",
            date(2026, 3, 20),
            MAX,
            [
                (date(2026, 3, 2), "2210", "Vollkeramikkrone Zahn 36", "2,3", D("780.00")),
                (date(2026, 2, 16), "2270", "Provisorium", "2,3", D("65.40")),
                (date(2026, 3, 2), "", "Material- und Laborkosten", "", D("298.60")),
                (date(2026, 3, 2), "", "abzgl. Festzuschuss Krankenkasse", "", D("-412.30")),
            ],
            seed=23,
            dental=True,
            plan=("HKP-2026-031", date(2026, 1, 12)),
        ),
        "scan-bw",
        marks=Marks(folds=True, holes=True),
        refers=("zahnarzt-hkp",),
    )
    add(
        "physio",
        lambda: bi.craft_invoice(
            c.PHYSIO,
            "P-25-0917",
            date(2025, 11, 20),
            "Krankengymnastik, 6 Behandlungen (Rezept vom 22.09.2025)",
            [
                ("Krankengymnastik Zuzahlung", D("6"), "Beh.", D("2.71")),
                ("Verordnungsblattgebühr", D("1"), "Stück", D("10.00")),
            ],
            seed=24,
            giro=False,
            labour_note=False,
        ),
        "photo",
    )

    # The car.
    add(
        "werkstatt-2025",
        lambda: bi.garage_invoice(
            "WE-25-04412",
            date(2025, 5, 16),
            61420,
            [
                ("Inspektion nach Herstellervorgabe", D("1"), "pauschal", D("189.00")),
                ("Motoröl 5W-30", D("4.5"), "l", D("16.90")),
                ("Ölfilter", D("1"), "Stück", D("14.80")),
                ("Pollenfilter", D("1"), "Stück", D("29.90")),
                ("Scheibenwischer vorn", D("1"), "Satz", D("34.50")),
            ],
            "A-25-1187",
            seed=31,
        ),
        "scan-office",
        marks=Marks(folds=True),
    )
    add(
        "werkstatt-2026",
        lambda: bi.garage_invoice(
            "WE-26-03980",
            date(2026, 5, 12),
            73905,
            [
                ("Inspektion nach Herstellervorgabe", D("1"), "pauschal", D("195.00")),
                ("Motoröl 5W-30", D("4.5"), "l", D("17.40")),
                ("Bremsscheiben und -beläge vorn", D("1"), "Satz", D("289.00")),
                ("Arbeitszeit Bremsen", D("1.5"), "Std.", D("118.00")),
            ],
            "A-26-0991",
            seed=32,
        ),
        "photo-poor",
        marks=Marks(folds=True),
    )
    add(
        "hu-2026",
        lambda: bi.inspection_report(date(2026, 5, 12), "PN-26-118204", 73905),
        "scan-clean",
        marks=Marks(staple=True),
    )

    # Shopping chains.
    bergmann_items = [
        ("Gartenstuhl Teak, 2 Stück", D("1"), "Satz", D("189.98")),
        ("Sonnenschirm 3 m", D("1"), "Stück", D("79.99")),
        ("Pflanzkübel Terrakotta", D("2"), "Stück", D("24.95")),
    ]
    add(
        "bergmann-bestellung",
        lambda: bi.shop_order_letter(
            c.BERGMANN,
            "BG-7781234",
            date(2026, 2, 2),
            [(n, q * p) for n, q, _, p in bergmann_items],
            customer=bi.BERGMANN_CUSTOMER,
        ),
        "digital",
    )
    add(
        "bergmann-lieferschein",
        lambda: bi.delivery_note(
            c.BERGMANN,
            "LS-8820311",
            "BG-7781234",
            date(2026, 2, 5),
            [(n, int(q)) for n, q, _, _ in bergmann_items],
            customer=bi.BERGMANN_CUSTOMER,
            printout_style=True,
        ),
        "scan-bw",
        refers=("bergmann-bestellung",),
    )
    add(
        "bergmann-rechnung",
        lambda: bi.shop_invoice(
            c.BERGMANN,
            "RG-2026-118842",
            "BG-7781234",
            date(2026, 2, 5),
            bergmann_items,
            customer=bi.BERGMANN_CUSTOMER,
        ),
        "digital",
        refers=("bergmann-bestellung",),
    )
    add(
        "bergmann-gutschrift",
        lambda: bi.credit_note(
            c.BERGMANN,
            "GS-2026-004417",
            "RG-2026-118842",
            date(2026, 2, 5),
            date(2026, 2, 19),
            [("Sonnenschirm 3 m (Rücksendung)", D("1"), "Stück", D("79.99"))],
            customer=bi.BERGMANN_CUSTOMER,
        ),
        "digital",
        refers=("bergmann-rechnung",),
    )
    add(
        "bergmann-mahnung-1",
        lambda: bi.reminder(
            c.BERGMANN,
            "RG-2026-118842",
            date(2026, 2, 5),
            D("239.88"),
            date(2026, 3, 6),
            customer=bi.BERGMANN_CUSTOMER,
        ),
        "scan-office",
        marks=Marks(folds=True, highlight="239,88"),
        refers=("bergmann-rechnung",),
    )
    add(
        "bergmann-mahnung-2",
        lambda: bi.reminder(
            c.BERGMANN,
            "RG-2026-118842",
            date(2026, 2, 5),
            D("239.88"),
            date(2026, 3, 20),
            level=2,
            fee=D("5.00"),
            customer=bi.BERGMANN_CUSTOMER,
        ),
        "scan-poor",
        marks=Marks(folds=True, note="bezahlt 23.3.!"),
        refers=("bergmann-mahnung-1", "bergmann-rechnung"),
    )
    tw_items = [
        ("Notebook ProBook 14, 16 GB, 512 GB SSD", D("1"), "Stück", D("899.00")),
        ("Garantie-Plus 3 Jahre", D("1"), "Stück", D("79.00")),
        ("Notebook-Tasche 14 Zoll", D("1"), "Stück", D("29.99")),
    ]
    add(
        "technik-bestellung",
        lambda: bi.shop_order_screen(
            c.TECHNIKWELT,
            "TW-2025-5531190",
            date(2025, 11, 28),
            [(n, p) for n, _, _, p in tw_items],
            "https://www.technikwelt.example/checkout/danke?order=TW-2025-5531190",
        ),
        "screenshot",
    )
    add(
        "technik-rechnung",
        lambda: bi.shop_invoice(
            c.TECHNIKWELT,
            "TWR-25-8812047",
            "TW-2025-5531190",
            date(2025, 11, 29),
            tw_items,
            customer="TW-K-210334",
        ),
        "digital",
        refers=("technik-bestellung",),
    )
    add(
        "technik-garantie",
        lambda: bi.warranty(date(2025, 12, 2), "PB14-5CD3418XYZ", "TWR-25-8812047"),
        "photo",
        refers=("technik-rechnung",),
    )
    moebel_items = [
        ("Sofa „Lindau“ 3-Sitzer, Stoff anthrazit", D("1"), "Stück", D("1299.00")),
        ("Sessel „Lindau“", D("1"), "Stück", D("549.00")),
        ("Lieferung und Montage", D("1"), "pauschal", D("89.00")),
    ]
    add(
        "moebel-auftrag",
        lambda: bi.furniture_order(date(2025, 7, 5), "WF-25-07-0419", moebel_items, D("500.00")),
        "scan-clean",
        marks=Marks(staple=True),
    )
    add(
        "moebel-quittung",
        lambda: sh.cash_receipt(
            c.MOEBEL,
            date(2025, 7, 5),
            D("500.00"),
            "Anzahlung Auftrag WF-25-07-0419",
            "A-2207",
            signer="Sander",
        ),
        "photo",
        refers=("moebel-auftrag",),
    )
    add(
        "moebel-lieferschein",
        lambda: bi.delivery_note(
            c.MOEBEL,
            "WF-LS-25-3381",
            "WF-25-07-0419",
            date(2025, 8, 14),
            [(n, int(q)) for n, q, _, _ in moebel_items[:2]],
            customer="WF-30455",
        ),
        "scan-office",
        marks=Marks(note="vollständig, M."),
        refers=("moebel-auftrag",),
    )
    add(
        "moebel-rechnung",
        lambda: bi.shop_invoice(
            c.MOEBEL,
            "WF-R-25-2290",
            "WF-25-07-0419",
            date(2025, 8, 14),
            moebel_items,
            customer="WF-30455",
        ),
        "scanner-ocr",
        marks=Marks(folds=True),
        refers=("moebel-auftrag",),
    )

    # English invoices.
    for n, month in enumerate(_months(date(2025, 8, 1), date(2026, 9, 1))):
        add(
            f"cloudberry-{month:%Y-%m}",
            lambda m=month, s=n: bi.hosting_invoice(m, 300 + s),
            "digital",
            series="cloudberry",
        )
    add("northwind-rechnung", lambda: mi.software_invoice(date(2025, 6, 3)), "digital")
    add(
        "northwind-lizenz",
        lambda: mi.licence_certificate(date(2025, 6, 3)),
        "digital",
        refers=("northwind-rechnung",),
    )
    add(
        "hotel-bristol",
        lambda: mi.hotel_invoice(date(2026, 8, 14)),
        "photo",
        marks=Marks(folds=True),
    )

    # Receipts.
    kinds = ["grocery"] * 16 + ["hardware"] * 5 + ["drugstore"] * 4 + ["bakery"] * 2 + ["cafe"] * 2
    for n, kind in enumerate(kinds):
        when = datetime(2024, 1, 1) + (datetime(2026, 10, 25) - datetime(2024, 1, 1)) * rng.random()
        when = when.replace(
            hour=rng.randint(8, 19), minute=rng.randint(0, 59), second=0, microsecond=0
        )
        add(
            f"bon-{kind}-{n:02d}",
            lambda k=kind, w=when, s=n: sh.shop_receipt(k, w, 500 + s),
            _pick(rng, RECEIPT_STAGES),
            exif_turned=n in (3, 17),
            delay=rng.randint(0, 3),
        )
    for n in range(6):
        when = datetime(2024, 3, 1) + (datetime(2026, 10, 20) - datetime(2024, 3, 1)) * rng.random()
        when = when.replace(microsecond=0, second=0)
        add(
            f"tanken-{n}",
            lambda w=when, s=n: sh.fuel_receipt(w, 600 + s),
            _pick(rng, RECEIPT_STAGES),
            delay=rng.randint(0, 5),
        )
    for n, when in enumerate(
        [datetime(2025, 2, 11, 9, 40), datetime(2025, 9, 23, 17, 5), datetime(2026, 1, 13, 18, 22)]
    ):
        add(
            f"apotheke-{n}",
            lambda w=when, s=n: sh.pharmacy_receipt(w, 700 + s),
            _pick(rng, RECEIPT_STAGES),
            delay=rng.randint(0, 4),
        )
    add("fahrrad-kaufvertrag", lambda: sh.private_sale(date(2026, 7, 10), D("280.00")), "photo")
    add(
        "fahrrad-quittung",
        lambda: sh.cash_receipt(
            c.PRIVATE_SELLER,
            date(2026, 7, 10),
            D("280.00"),
            "Fahrrad Velotrek City 7",
            "1",
            signer="T. Schreiber",
        ),
        "scan-office",
        refers=("fahrrad-kaufvertrag",),
    )

    # Bank.
    balance = D("1842.17")
    for n, month in enumerate(_months(date(2024, 1, 1), date(2026, 9, 1))):
        printer = month.year == 2024
        stage = "digital" if not printer else ("scan-bw" if month.month % 3 else "scanner-ocr")
        made = bk.account_statement(month, month.month, balance, 800 + n, printer=printer)
        balance = made[1]
        add(
            f"konto-{month:%Y-%m}",
            lambda d=made[0]: d,
            stage,
            series="sparkasse",
            tiff=printer and month.month in (2, 7),
        )
    for n, month in enumerate(_months(date(2025, 10, 1), date(2026, 9, 1))):
        add(
            f"kreditkarte-{month:%Y-%m}",
            lambda m=month, s=n: bk.card_statement(m, 900 + s),
            "digital",
            series="hansebank",
        )
    balance = D("3120.40")
    for n, (year, quarter) in enumerate(
        [(y, q) for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)][:11]
    ):
        made = bk.quarter_statement(year, quarter, balance, 950 + n)
        balance = made[1]
        add(f"direktbank-{year}-q{quarter}", lambda d=made[0]: d, "digital", series="direktbank")
    add(
        "darlehen-vertrag",
        lambda: bk.loan_contract(date(2024, 2, 26), "AF-24-0203318", D("14500.00"), "3,49", 48),
        "scan-clean",
        marks=Marks(staple=True, holes=True),
    )
    add(
        "darlehen-2024",
        lambda: bk.loan_statement(2024, "AF-24-0203318", D("14500.00"), D("321.68")),
        "scan-office",
        refers=("darlehen-vertrag",),
        marks=Marks(folds=True),
    )
    add(
        "darlehen-2025",
        lambda: bk.loan_statement(2025, "AF-24-0203318", D("11080.00"), D("321.68")),
        "digital",
        refers=("darlehen-vertrag",),
    )
    add(
        "bauspar-vertrag",
        lambda: bk.building_savings(date(2024, 5, 10), "BS 4471 1984 00"),
        "scan-office",
        marks=Marks(folds=True, holes=True),
    )
    add(
        "bauspar-2024",
        lambda: bk.building_savings(date(2025, 1, 20), "BS 4471 1984 00", annual=2024),
        "scan-bw",
        refers=("bauspar-vertrag",),
    )
    add(
        "bauspar-2025",
        lambda: bk.building_savings(date(2026, 1, 19), "BS 4471 1984 00", annual=2025),
        "scanner-ocr",
        refers=("bauspar-vertrag",),
    )
    add(
        "ueberweisung-tierheim",
        lambda: bk.transfer_screen(date(2025, 12, 20), D("100.00"), c.TIERHEIM, "Spende Tierheim"),
        "screenshot",
    )
    add("sparkasse-steuer-2025", lambda: bk.tax_certificate(2025), "digital")
    add("sparkasse-entgelte", lambda: bk.fees_notice(date(2026, 1, 28)), "digital")
    add(
        "freistellungsauftrag",
        lambda: bk.exemption_order(date(2025, 1, 15)),
        "scan-clean",
        marks=Marks(folds=True),
    )
    add(
        "sepa-tsv",
        lambda: bk.sepa_mandate(
            c.TSV, mi.TSV_CREDITOR, "TSV-3317", date(2025, 9, 1), "Mitgliedsbeitrag TSV, jährlich"
        ),
        "scan-office",
    )
    add(
        "sepa-musikschule",
        lambda: bk.sepa_mandate(
            c.MUSIKSCHULE,
            ids.creditor_id("00000912012"),
            "MSK-0912",
            date(2025, 9, 5),
            "Unterrichtsgebühr Lena, vierteljährlich",
        ),
        "photo",
    )

    # Work.
    for n, month in enumerate(_months(date(2024, 1, 1), date(2026, 9, 1))):
        if month.year == 2024:
            stage = "scan-bw" if month.month % 2 else "scan-office"
            marks = Marks(holes=True, folds=month.month % 4 == 0)
        else:
            stage, marks = "digital", NO_MARKS
        add(
            f"lohn-max-{month:%Y-%m}",
            lambda m=month, s=n: wk.payslip(m, seed=s),
            stage,
            marks=marks,
            series="lohn-max",
            turned=frozenset({0}) if month == date(2024, 8, 1) else frozenset(),
        )
    for n, month in enumerate(_months(date(2025, 3, 1), date(2026, 9, 1))):
        if n % 3 == 2:
            continue  # not every notice of pay was filed
        add(
            f"lohn-erika-{month:%Y-%m}",
            lambda m=month, s=n: wk.payslip_public(m, seed=s),
            "digital",
            series="lohn-erika",
        )
    add(
        "lstb-max-2024",
        lambda: wk.wage_tax_certificate(2024, MAX, c.BRUECKNER, wk.MAX_PERSONNEL, D("58940.00")),
        "scan-office",
        marks=Marks(holes=True, note="Steuer 2024"),
    )
    add(
        "lstb-max-2025",
        lambda: wk.wage_tax_certificate(2025, MAX, c.BRUECKNER, wk.MAX_PERSONNEL, D("62180.00")),
        "digital",
    )
    add(
        "lstb-erika-2025",
        lambda: wk.wage_tax_certificate(
            2025, ERIKA, c.STADT_PERSONAL, wk.ERIKA_PERSONNEL, D("33750.00")
        ),
        "scan-clean",
        marks=Marks(holes=True),
    )
    add(
        "arbeitsvertrag-erika",
        lambda: wk.employment_contract(date(2025, 2, 10)),
        "scan-clean",
        marks=Marks(staple=True, holes=True),
    )
    add(
        "arbeitsvertrag-erika-foto",
        lambda: wk.employment_contract(date(2025, 2, 10)),
        "photo",
        duplicate_of="arbeitsvertrag-erika",
    )
    add(
        "gehalt-2025",
        lambda: wk.salary_letter(date(2025, 3, 20), D("5020.00"), date(2025, 4, 1)),
        "scan-office",
        marks=Marks(holes=True),
    )
    add(
        "gehalt-2026",
        lambda: wk.salary_letter(date(2026, 3, 18), D("5180.00"), date(2026, 4, 1)),
        "scanner-ocr",
        refers=("gehalt-2025",),
    )
    add(
        "zwischenzeugnis-max",
        lambda: wk.reference(
            c.BRUECKNER,
            MAX,
            date(2025, 11, 28),
            "Zwischenzeugnis",
            [
                f"Herr Max Mustermann, geboren am {MAX.born:%d.%m.%Y}, ist seit dem 01.04.2019 in unserem Unternehmen als Konstrukteur in der Abteilung Konstruktion tätig.",
                "Zu seinen Aufgaben gehören die Konstruktion von Baugruppen für Verpackungsmaschinen mit CAD, die Erstellung von Stücklisten und technischen Zeichnungen sowie die Abstimmung mit Fertigung und Einkauf. Seit 2023 leitet er das Teilprojekt Antriebstechnik.",
                "Herr Mustermann verfügt über ein umfassendes und fundiertes Fachwissen, das er stets sicher und zielgerichtet einsetzt. Er arbeitet sehr selbständig, äußerst sorgfältig und zuverlässig. Seine Arbeitsergebnisse sind von hervorragender Qualität.",
                "Sein Verhalten gegenüber Vorgesetzten, Kollegen und Kunden ist stets einwandfrei. Dieses Zwischenzeugnis wird auf seinen Wunsch wegen eines Wechsels des Vorgesetzten erteilt.",
            ],
            ("Anja Brückner", "Geschäftsführerin"),
        ),
        "scan-clean",
    )
    add(
        "zeugnis-erika",
        lambda: wk.reference(
            c.BUCHHANDLUNG,
            ERIKA,
            date(2025, 2, 28),
            "Arbeitszeugnis",
            [
                f"Frau Erika Musterfrau, geboren am {ERIKA.born:%d.%m.%Y}, war vom 01.09.2016 bis zum 28.02.2025 in unserer Buchhandlung als Buchhändlerin beschäftigt.",
                "Sie beriet unsere Kundinnen und Kunden, betreute das Sortiment Kinder- und Jugendbuch, organisierte Lesungen und bildete Auszubildende aus.",
                "Frau Musterfrau erledigte die ihr übertragenen Aufgaben stets zu unserer vollsten Zufriedenheit. Ihr Verhalten war jederzeit vorbildlich.",
                "Frau Musterfrau verlässt uns auf eigenen Wunsch. Wir bedauern dies sehr, danken ihr für die stets gute Zusammenarbeit und wünschen ihr für die Zukunft alles Gute.",
            ],
            ("Marlene Kurz", "Geschäftsführerin"),
        ),
        "scan-clean",
        marks=Marks(holes=True),
    )
    add(
        "kuendigung-erika",
        lambda: wk.termination_confirmation(date(2024, 12, 20), date(2024, 12, 16)),
        "scan-office",
        marks=Marks(folds=True),
    )
    for n, month in enumerate(_months(date(2026, 1, 1), date(2026, 9, 1))):
        stage = "printout" if month.month not in (3, 7) else "scan-bw"
        add(
            f"zeitnachweis-{month:%Y-%m}",
            lambda m=month, s=n: wk.time_sheet(m, 1100 + s),
            stage,
            series="zeitnachweis",
            marks=Marks(note="geprüft, M.M.") if stage == "scan-bw" else NO_MARKS,
        )

    # Housing.
    add(
        "mietvertrag",
        lambda: ho.lease(date(2025, 6, 15)),
        "scan-clean",
        marks=Marks(staple=True, holes=True),
    )
    add(
        "genossenschaft",
        lambda: ho.membership(date(2025, 6, 20)),
        "scan-office",
        marks=Marks(folds=True, holes=True),
    )
    add("wohnungsgeber", lambda: ho.landlord_confirmation(date(2025, 7, 25)), "scan-bw")
    add(
        "nebenkosten-2025",
        lambda: ho.utility_statement(
            c.WOHNBAU,
            date(2026, 5, 20),
            date(2025, 8, 1),
            date(2025, 12, 31),
            ho.COSTS_2025,
            D("1416.40"),
            contract=ho.LEASE,
        ),
        "scan-office",
        marks=Marks(folds=True, highlight="Guthaben"),
        refers=("mietvertrag",),
    )
    add(
        "mieterhoehung",
        lambda: ho.rent_increase(date(2026, 9, 15)),
        "scanner-ocr",
        marks=Marks(folds=True),
        refers=("mietvertrag",),
    )
    add(
        "kuendigung-birkenweg",
        lambda: ho.notice_confirmation(date(2025, 4, 30), date(2025, 4, 28)),
        "fax",
        fax_from="+49 1234 332110",
    )
    add(
        "kaution",
        lambda: ho.deposit_statement(date(2025, 10, 15)),
        "scan-poor",
        marks=Marks(folds=True),
        refers=("kuendigung-birkenweg",),
    )
    add(
        "nebenkosten-2024",
        lambda: ho.utility_statement(
            c.HAUSVERWALTUNG,
            date(2025, 6, 10),
            date(2024, 1, 1),
            date(2024, 12, 31),
            ho.COSTS_2024,
            D("2160.00"),
            contract=ho.OLD_TENANT,
        ),
        "photo",
        marks=Marks(folds=True),
    )

    # Insurance.
    add(
        "hausrat-police",
        lambda: ins.policy(
            date(2025, 7, 28),
            ins.HOUSEHOLD_POLICY,
            "Hausratversicherung",
            date(2025, 8, 1),
            D("142.80"),
            [
                ("Versicherungssumme", "62.000,00 EUR"),
                ("Wohnfläche", "92,4 m²"),
                ("Fahrraddiebstahl", "bis 1.000,00 EUR, Selbstbeteiligung 150,00 EUR"),
            ],
            seed=41,
        ),
        "digital",
    )
    add(
        "haftpflicht-police",
        lambda: ins.policy(
            date(2024, 1, 10),
            ins.LIABILITY_POLICY,
            "Privathaftpflichtversicherung",
            date(2024, 2, 1),
            D("78.54"),
            [
                ("Deckungssumme", "10 Mio. EUR pauschal"),
                ("Mitversichert", "Ehepartnerin und Kind"),
                ("Hundehalterhaftpflicht", "eingeschlossen (1 Hund)"),
            ],
            seed=42,
        ),
        "scan-clean",
        marks=Marks(holes=True),
    )
    add(
        "hanse-beitrag-2025",
        lambda: ins.premium_invoice(
            c.HANSE_VERS,
            date(2024, 12, 2),
            ins.LIABILITY_POLICY,
            [
                ("Privathaftpflicht PH-2019-0083317", D("78.54")),
                ("Hausrat (Birkenweg) HV-2019-1130027", D("118.20")),
            ],
            (date(2025, 1, 1), date(2025, 12, 31)),
            customer=ins.HANSE_CUSTOMER,
        ),
        "scan-bw",
        marks=Marks(folds=True),
    )
    add(
        "hanse-beitrag-2026",
        lambda: ins.premium_invoice(
            c.HANSE_VERS,
            date(2025, 12, 1),
            ins.HOUSEHOLD_POLICY,
            [
                ("Privathaftpflicht PH-2019-0083317", D("84.20")),
                ("Hausrat HV-2025-4471182", D("142.80")),
            ],
            (date(2026, 1, 1), date(2026, 12, 31)),
            customer=ins.HANSE_CUSTOMER,
        ),
        "scan-office",
        marks=Marks(folds=True),
        refers=("hausrat-police",),
    )
    add(
        "haftpflicht-anpassung",
        lambda: ins.premium_adjustment(date(2025, 11, 15)),
        "scan-clean",
        marks=Marks(folds=True, highlight="84,20 EUR"),
        refers=("haftpflicht-police",),
    )
    add(
        "schaden-anzeige",
        lambda: ins.claim_report(date(2026, 6, 3)),
        "scan-office",
        refers=("hausrat-police",),
    )
    add(
        "schaden-eingang",
        lambda: ins.claim_receipt(date(2026, 6, 10), date(2026, 6, 3)),
        "digital",
        refers=("schaden-anzeige",),
    )
    add(
        "schaden-regulierung",
        lambda: ins.claim_settlement(date(2026, 7, 2)),
        "scanner-ocr",
        marks=Marks(folds=True),
        refers=("schaden-eingang",),
    )
    add(
        "kfz-police",
        lambda: ins.car_policy(date(2024, 11, 20)),
        "scan-office",
        marks=Marks(folds=True, holes=True),
    )
    add(
        "kfz-beitrag-2026",
        lambda: ins.premium_invoice(
            c.KRAFTSCHUTZ,
            date(2025, 11, 25),
            ins.CAR_POLICY,
            [("Kfz-Haftpflicht MU-MM 1984", D("244.10")), ("Vollkasko MU-MM 1984", D("227.10"))],
            (date(2026, 1, 1), date(2026, 12, 31)),
            customer="KS-K-118204",
        ),
        "digital",
        refers=("kfz-police",),
    )
    add(
        "kfz-sf",
        lambda: ins.no_claims_notice(date(2026, 1, 5)),
        "photo",
        marks=Marks(folds=True),
        refers=("kfz-police",),
    )
    add("kasse-mitglied", lambda: ins.health_membership(date(2025, 1, 8)), "scan-poor")
    add(
        "kasse-zusatzbeitrag",
        lambda: ins.health_contribution(date(2025, 12, 1)),
        "scan-poor",
        marks=Marks(folds=True),
    )
    add(
        "kasse-familie",
        lambda: ins.family_insurance(date(2025, 3, 12)),
        "scan-office",
        marks=Marks(folds=True),
    )
    add("rentenversicherung-erika", lambda: ins.pension_statement(date(2026, 2, 15)), "digital")

    # Authorities.
    add(
        "steuer-2024",
        lambda: au.income_tax(2024, date(2025, 7, 18), D("1412.00"), D("57710.00"), D("21480.00")),
        "scan-clean",
        duplex=True,
        marks=Marks(folds=True, holes=True, highlight="Erstattungsbetrag"),
    )
    add(
        "finanzamt-anforderung",
        lambda: au.tax_request(date(2026, 6, 2), date(2026, 5, 20)),
        "scan-office",
        marks=Marks(folds=True, note="Belege bis 1.7.!"),
    )
    add(
        "steuer-2025",
        lambda: au.income_tax(2025, date(2026, 8, 12), D("1688.00"), D("60950.00"), D("32520.00")),
        "scanner-ocr",
        marks=Marks(folds=True),
        refers=("finanzamt-anforderung",),
    )
    add("kfz-steuer", lambda: au.vehicle_tax(date(2024, 3, 5)), "scan-bw", marks=Marks(holes=True))
    add(
        "kfz-steuer-aenderung",
        lambda: au.vehicle_tax(date(2025, 8, 20), change=True),
        "scan-office",
        marks=Marks(folds=True),
        refers=("kfz-steuer",),
    )
    add("meldebestaetigung", lambda: au.registration(date(2025, 8, 5)), "photo")
    add(
        "hundesteuer-2025",
        lambda: au.dog_tax(2025, date(2025, 2, 1)),
        "scan-clean",
        marks=Marks(folds=True),
    )
    add(
        "hundesteuer-2026",
        lambda: au.dog_tax(2026, date(2026, 1, 20)),
        "scan-poor",
        marks=Marks(folds=True),
        refers=("hundesteuer-2025",),
    )
    add(
        "kindergeld-2025",
        lambda: au.child_benefit(date(2025, 1, 15), D("255.00"), date(2025, 1, 1)),
        "scan-office",
        marks=Marks(folds=True),
    )
    add(
        "kindergeld-2026",
        lambda: au.child_benefit(date(2025, 12, 10), D("259.00"), date(2026, 1, 1)),
        "scan-bw",
        refers=("kindergeld-2025",),
    )
    add(
        "rente-max-2025",
        lambda: au.pension_info(MAX, date(2025, 7, 1), D("1018.40"), D("2104.70")),
        "scan-office",
        marks=Marks(folds=True),
    )
    add(
        "rente-max-2026",
        lambda: au.pension_info(MAX, date(2026, 7, 1), D("1092.15"), D("2131.20")),
        "digital",
        refers=("rente-max-2025",),
    )
    add(
        "rente-erika-2026",
        lambda: au.pension_info(ERIKA, date(2026, 6, 15), D("612.80"), D("1288.40")),
        "scan-clean",
        marks=Marks(folds=True),
    )
    add(
        "bussgeld-anhoerung",
        lambda: au.hearing(date(2026, 3, 10)),
        "scan-office",
        marks=Marks(folds=True),
    )
    add(
        "bussgeld-bescheid",
        lambda: au.fine(date(2026, 4, 14)),
        "photo-poor",
        marks=Marks(folds=True, stamp="BEZAHLT", stamp_date="20.04.2026"),
        refers=("bussgeld-anhoerung",),
    )

    # Health.
    add(
        "klinik-lena",
        lambda: he.discharge_letter(date(2025, 10, 20)),
        "scan-clean",
        marks=Marks(folds=True),
    )
    add("befund-max", lambda: he.findings(date(2026, 2, 5)), "scan-poor", marks=Marks(folds=True))
    add("au-max", lambda: he.sick_note(date(2026, 1, 13)), "photo")

    # Everyday life.
    add(
        "tsv-mitglied",
        lambda: mi.club_membership(date(2025, 9, 1)),
        "scan-office",
        marks=Marks(folds=True),
        refers=("sepa-tsv",),
    )
    add(
        "tsv-beitrag-2026",
        lambda: mi.club_fee(date(2026, 1, 10)),
        "digital",
        refers=("tsv-mitglied",),
    )
    add(
        "spende-2024",
        lambda: mi.donation_receipt(2024, date(2025, 1, 20), D("100.00")),
        "scan-bw",
        marks=Marks(holes=True),
    )
    add(
        "spende-2025",
        lambda: mi.donation_receipt(2025, date(2026, 1, 22), D("150.00")),
        "scanner-ocr",
    )
    add(
        "bahn-weihnachten",
        lambda: mi.train_ticket(
            date(2025, 12, 18),
            datetime(2025, 12, 23, 9, 12),
            "Musterstadt Hbf",
            "Hafenstadt Hbf",
            D("38.90"),
            "RB-7G4K2Q",
        ),
        "digital",
    )
    add(
        "bahn-ostern",
        lambda: mi.train_ticket(
            date(2026, 4, 1),
            datetime(2026, 4, 3, 10, 41),
            "Musterstadt Hbf",
            "Förderstadt",
            D("24.50"),
            "RB-9X1M7P",
        ),
        "digital",
    )
    add(
        "bahn-sommer",
        lambda: mi.train_ticket(
            date(2026, 6, 28),
            datetime(2026, 7, 1, 7, 55),
            "Musterstadt Hbf",
            "Domstadt Hbf",
            D("49.90"),
            "RB-3T8W5L",
        ),
        "photo-poor",
        marks=Marks(folds=True),
    )
    add(
        "bahn-buchung",
        lambda: mi.train_ticket_screen(
            date(2026, 5, 10),
            datetime(2026, 5, 23, 8, 30),
            "Musterstadt Hbf",
            "Sonnental",
            D("31.80"),
            "RB-5Q2N8R",
        ),
        "screenshot",
    )
    add(
        "flug-buchung",
        lambda: mi.flight_booking(date(2026, 7, 20), "SNX4QK", "176-2400118834"),
        "digital",
    )
    add(
        "flug-bordkarte",
        lambda: mi.boarding_pass(date(2026, 8, 9), "176-2400118834", "SNX4QK"),
        "digital",
        refers=("flug-buchung",),
    )
    add(
        "anwalt-1",
        lambda: mi.lawyer_letter(date(2025, 11, 5)),
        "fax",
        fax_from="+49 1234 515253",
        refers=("kaution",),
    )
    add(
        "anwalt-2",
        lambda: mi.lawyer_letter(date(2025, 12, 1), second=True),
        "scan-clean",
        marks=Marks(folds=True),
        refers=("anwalt-1",),
    )
    add(
        "musikschule-vertrag",
        lambda: mi.music_contract(date(2025, 9, 5)),
        "scan-office",
        marks=Marks(folds=True),
        refers=("sepa-musikschule",),
    )
    add(
        "musikschule-gebuehr",
        lambda: mi.music_fee(date(2026, 7, 1)),
        "digital",
        refers=("musikschule-vertrag",),
    )
    add(
        "schule-klassenfahrt",
        lambda: mi.school_letter(
            date(2025, 9, 15),
            "Klassenfahrt ins Schullandheim",
            [
                "vom 13. bis 15. Mai fährt unsere Klasse ins Schullandheim am Waldsee. Die Kosten betragen 145 EUR pro Kind (Unterkunft, Vollpension, Programm).",
                "Bitte geben Sie den Betrag bis zum 31. Oktober im Umschlag mit dem Namen Ihres Kindes ab.",
            ],
        ),
        "photo",
    )
    add(
        "schule-elternabend",
        lambda: mi.school_letter(
            date(2026, 2, 20),
            "Einladung zum Elternabend",
            [
                "herzlich lade ich Sie zum Elternabend am Dienstag, 10. März, um 19:30 Uhr in den Klassenraum der 4b ein.",
                "Themen: Übergang auf die weiterführende Schule, Projektwoche, Verschiedenes.",
            ],
        ),
        "scan-poor",
    )
    add("vhs-spanisch", lambda: mi.course_confirmation(date(2026, 1, 10)), "digital")
    add("werbung-solar", lambda: mi.advert_solar(date(2026, 4, 8)), "scan-office")
    add(
        "werbung-gewinn",
        lambda: mi.advert_prize(date(2025, 10, 14)),
        "photo-poor",
        marks=Marks(folds=True),
    )
    add("leerseite", _blank, "scan-office", delay=0, day=date(2025, 11, 2))
    return out


def _blank() -> Doc:
    """An empty sheet, scanned by mistake."""
    return doc("blank", "", "", None, "Leere Seite", [Page()], download="Scan.pdf")


def _pick(rng: random.Random, weights: dict[str, int]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


_NOTES = (
    "erledigt",
    "überwiesen",
    "an Erika",
    "Steuer!",
    "abgeheftet",
    "Frist notiert",
    "bezahlt",
    "Kopie an Steuerberater",
)


def _letter_marks(rng: random.Random) -> Marks:
    return Marks(
        folds=rng.random() < 0.7,
        holes=rng.random() < 0.4,
        note=rng.choice(_NOTES) if rng.random() < 0.12 else None,
        stain=rng.random() < 0.03,
    )


__all__ = ["LENA", "TODAY", "Entry", "entries"]
