"""Numbers as the documents write them: amounts and dates in German, IBANs with their check
digits."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def euro(value: Decimal | float | int, *, sign: bool = False) -> str:
    """`1234.5` as `1.234,50`."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    text = f"{abs(amount):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if amount < 0:
        return f"-{text}"
    return f"+{text}" if sign else text


def plain(value: Decimal | float | int) -> str:
    """`1234.5` as `1234.50`, as a GiroCode writes it."""
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), ROUND_HALF_UP):.2f}"


def german(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def short(day: date) -> str:
    return day.strftime("%d.%m.%y")


def iban(country: str, bban: str) -> str:
    """The IBAN of `bban` in `country`, in groups of four."""
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(digits) % 97
    compact = f"{country}{check:02d}{bban}"
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
