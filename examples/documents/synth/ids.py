"""Synthetic identifiers with computed check digits, so that Lekto recognises them: never real
ones (`tests/person_numbers.py` computes them the same way)."""

from synth.numbers import iban

__all__ = [
    "creditor_id",
    "health_insurance_number",
    "iban",
    "social_security_number",
    "tax_id",
    "vat_id",
]


def _mod97_check(body: str, country: str) -> int:
    digits = "".join(str(int(c, 36)) for c in body + country + "00")
    return 98 - int(digits) % 97


def creditor_id(national: str, country: str = "DE", business: str = "ZZZ") -> str:
    """A SEPA creditor identifier (`DE98ZZZ09999999999`): check digits over the national part."""
    return f"{country}{_mod97_check(national, country):02d}{business}{national}"


def vat_id(eight: str) -> str:
    """A German VAT ID from its first eight digits, with its check digit (ISO 7064 MOD 11,10),
    written as `DE 123 456 789`."""
    product = 10
    for digit in eight:
        total = (int(digit) + product) % 10 or 10
        product = total * 2 % 11
    check = (11 - product) % 10
    digits = f"{eight}{check}"
    return f"DE {digits[:3]} {digits[3:6]} {digits[6:]}"


def tax_id(first_ten: str) -> str:
    """A tax ID from its first ten digits (one digit twice, the others once), in its groups."""
    product = 10
    for digit in first_ten:
        total = (int(digit) + product) % 10 or 10
        product = total * 2 % 11
    value = f"{first_ten}{(11 - product) % 10}"
    return f"{value[:2]} {value[2:5]} {value[5:8]} {value[8:]}"


def social_security_number(start: str, letter: str, serial: str) -> str:
    """A social security number from area and birth date (8 digits), letter and serial, as
    `65 140684 M 512`."""
    digits = f"{start}{ord(letter) - ord('A') + 1:02d}{serial}"
    weights = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)
    total = sum(sum(divmod(int(d) * w, 10)) for d, w in zip(digits, weights, strict=True))
    return f"{start[:2]} {start[2:]} {letter} {serial}{total % 10}"


def health_insurance_number(letter: str, digits: str) -> str:
    """A health insurance number from its letter and first eight digits."""
    numbers = f"{ord(letter) - ord('A') + 1:02d}{digits}"
    total = sum(
        sum(divmod(int(d) * (2 if position % 2 else 1), 10)) for position, d in enumerate(numbers)
    )
    return f"{letter}{digits}{total % 10}"
