"""Till receipts: 80 mm thermal paper as long as its lines, the shop's name on top, items and
sum, the VAT table, the payment and the data of the cash register's security module (TSE),
a code at the end."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from PIL import Image

from synth.fonts import MONO, Font, width
from synth.layout import Page
from synth.numbers import euro

WIDTH = 80.0
LEFT = 4.0
RIGHT = 76.0


@dataclass(frozen=True)
class Item:
    name: str
    price: Decimal  # the line's total
    vat: str = "A"  # A: 19 %, B: 7 %
    detail: str = ""  # e.g. "2 x 1,29"


RATES = {"A": Decimal("0.19"), "B": Decimal("0.07")}


def receipt(
    shop: Sequence[str],
    items: Sequence[Item],
    when: datetime,
    *,
    payment: str = "Bar",
    given: Decimal | None = None,
    register: str = "Kasse 2",
    number: int = 4711,
    tse_serial: str = "a3f9c21e5b7d4f60",
    font: Font = MONO,
    code: Image.Image | None = None,
    footer: Sequence[str] = ("Vielen Dank für Ihren Einkauf!",),
    extra: Sequence[str] = (),
) -> tuple[Page, Decimal]:
    """The receipt and its sum."""
    bold = font.bolder()
    lines: list[tuple[str, str, Font, float, str]] = []  # left, right, font, size, align

    def add(
        left: str = "", right: str = "", f: Font = font, size: float = 8, align: str = "left"
    ) -> None:
        lines.append((left, right, f, size, align))

    for number_of_line, line in enumerate(shop):
        add(
            line,
            "",
            bold if number_of_line == 0 else font,
            12 if number_of_line == 0 else 8,
            "center",
        )
    add()
    add("EUR", "", font, 8, "right")
    total = Decimal("0")
    for item in items:
        if item.detail:
            add(f"  {item.detail}")
        add(item.name, f"{euro(item.price)} {item.vat}")
        total += item.price
    add("-" * 42)
    add("SUMME EUR", euro(total), bold, 11)
    add("-" * 42)
    if payment == "Bar":
        paid = given if given is not None else total
        add("Gegeben Bar", euro(paid))
        add("Rückgeld", euro(paid - total))
    else:
        add(payment, euro(total))
        add("Kartenzahlung kontaktlos")
        add(f"Terminal-ID 6{number:07d}  Beleg {number % 1000:04d}")
    add()
    add("MwSt      Netto     Steuer    Brutto")
    for rate in ("A", "B"):
        gross = sum((item.price for item in items if item.vat == rate), Decimal("0"))
        if gross:
            net = (gross / (1 + RATES[rate])).quantize(Decimal("0.01"))
            add(
                f"{rate} {int(RATES[rate] * 100):>2} %  {euro(net):>8}  {euro(gross - net):>8}  {euro(gross):>8}"
            )
    add()
    for line in extra:
        add(line)
    add(f"{when:%d.%m.%Y %H:%M}   {register}   Bon {number}")
    add(f"TSE-Transaktion: {number * 7 + 1000}")
    add(f"TSE-Signaturzähler: {number * 15 + 20000}")
    add(f"TSE-Start: {when:%Y-%m-%dT%H:%M:%S}")
    add(f"TSE-Seriennr.: {tse_serial}")
    add()
    for line in footer:
        add(line, "", font, 8, "center")
    step = 3.9
    height = 12 + len(lines) * step + (34 if code else 8)
    page = Page(WIDTH, height)
    y = 10.0
    for left, right, f, size, align in lines:
        if align == "center":
            page.text(WIDTH / 2, y, left, f, size, "center")
        elif align == "right":
            page.text(RIGHT, y, left, f, size, "right")
        else:
            text = left
            while text and width(text, f, size) > RIGHT - LEFT:
                text = text[:-1]
            page.text(LEFT, y, text, f, size)
            if right:
                page.text(RIGHT, y, right, f, size, "right")
        y += step * (1.5 if size > 10 else 1)
    if code is not None:
        side = 26
        page.picture((WIDTH - side) / 2, y + 2, side, side * code.height / code.width, code)
    return page, total
