"""What the classes share: a letter to the household, sums with VAT, invoice tables."""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from synth.household import ERIKA, MAX, Person, address
from synth.letter import Column, Letter, Sender
from synth.numbers import euro, german

CENT = Decimal("0.01")


def letter(
    sender: Sender,
    to: Person,
    day: date,
    info: Sequence[tuple[str, str]],
    subject: str,
    *,
    both: bool = False,
    reference: str = "",
    seed: int = 0,
    date_label: str = "Datum",
) -> Letter:
    """A letter of `sender` to `to` (or the couple) at their address on `day`."""
    return Letter(
        sender,
        address(to, day, both=both),
        [*info, (date_label, german(day))],
        subject,
        reference=reference,
        seed=seed,
    )


def greeting(to: Person, *, both: bool = False) -> str:
    if both:
        return "Sehr geehrte Frau Musterfrau, sehr geehrter Herr Mustermann,"
    return f"{to.letter},"


def vat(net: Decimal, rate: int = 19) -> Decimal:
    return (net * rate / 100).quantize(CENT, ROUND_HALF_UP)


def lines_table(
    bill: Letter,
    items: Sequence[tuple[str, Decimal, str, Decimal]],
    *,
    rate: int = 19,
    gross_prices: bool = False,
    english: bool = False,
) -> tuple[Decimal, Decimal, Decimal]:
    """A table of items (text, quantity, unit, unit price) and its sums: net, VAT, gross.
    `gross_prices`: the prices include VAT (a shop for consumers)."""
    rows = []
    total = Decimal("0")
    for number, (text, quantity, unit, price) in enumerate(items, start=1):
        amount = (quantity * price).quantize(CENT, ROUND_HALF_UP)
        total += amount
        q = f"{quantity:f}".rstrip("0").rstrip(".") if quantity % 1 else str(int(quantity))
        rows.append((str(number), text, f"{q.replace('.', ',')} {unit}", euro(price), euro(amount)))
    titles = (
        ("Pos.", "Description", "Qty", "Unit price", "Amount")
        if english
        else ("Pos.", "Bezeichnung", "Menge", "Einzelpreis", "Gesamt")
    )
    bill.table(
        [
            Column(titles[0], 12),
            Column(titles[1], 78),
            Column(titles[2], 25, "right"),
            Column(titles[3], 25, "right"),
            Column(titles[4], 25, "right"),
        ],
        rows,
        shade=True,
    )
    if gross_prices:
        gross = total
        net = (gross / (1 + Decimal(rate) / 100)).quantize(CENT, ROUND_HALF_UP)
        tax = gross - net
    else:
        net = total
        tax = vat(net, rate)
        gross = net + tax
    return net, tax, gross


__all__ = ["ERIKA", "MAX", "greeting", "letter", "lines_table", "vat"]


def notice(
    sender: Sender,
    to: Person,
    day: date,
    info: Sequence[tuple[str, str]],
    subject: str,
    paragraphs: Sequence[str],
    *,
    cls: str,
    document_type: str,
    title: str,
    facts: Sequence[tuple[str, ...]] = (),
    fields: dict | None = None,
    pairs: Sequence[tuple[str, str]] = (),
    after: Sequence[str] = (),
    both: bool = False,
    sign: tuple[str, ...] = (),
    closing: str = "",
    seed: int = 0,
    download: str = "",
    language: str = "de",
    codes: Sequence[str] = (),
    pairs_width: float = 55,
    greet: bool = True,
):
    """A letter of paragraphs, optionally label and value pairs and more paragraphs after them,
    signed by hand (`sign`: name and role) or closed with `closing`."""
    from synth.document import doc

    bill = letter(sender, to, day, info, subject, both=both, seed=seed)
    if greet:
        bill.paragraph(greeting(to, both=both))
    for text in paragraphs:
        bill.paragraph(text)
    if pairs:
        bill.pairs(pairs, label_width=pairs_width)
    for text in after:
        bill.paragraph(text)
    if sign:
        bill.signature(closing or "Mit freundlichen Grüßen", *sign)
    else:
        bill.paragraph(closing or f"Mit freundlichen Grüßen\n{sender.head_name}")
    return doc(
        cls,
        document_type,
        sender,
        day,
        title,
        bill,
        recipient="max+erika" if both else to.username,
        facts=facts,
        fields=fields or {},
        download=download or f"{title.replace(' ', '_').replace('/', '-')}.pdf",
        language=language,
        codes=list(codes),
    )
