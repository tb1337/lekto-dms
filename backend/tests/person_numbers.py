"""Synthetic numbers of persons with computed check digits, for tests: never real ones."""


def tax_id(first_ten: str = "1234567891") -> str:
    """A tax ID from its first ten digits (one digit twice, the others once)."""
    product = 10
    for digit in first_ten:
        total = (int(digit) + product) % 10 or 10
        product = total * 2 % 11
    return f"{first_ten}{(11 - product) % 10}"


def social_security_number(start: str = "12150680", letter: str = "M", serial: str = "12") -> str:
    """A social security number from area and birth date (8 digits), letter and serial."""
    digits = f"{start}{ord(letter) - ord('A') + 1:02d}{serial}"
    weights = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)
    total = sum(sum(divmod(int(d) * w, 10)) for d, w in zip(digits, weights, strict=True))
    return f"{start}{letter}{serial}{total % 10}"


def health_insurance_number(letter: str = "A", digits: str = "12345678") -> str:
    """A health insurance number from its letter and first eight digits."""
    numbers = f"{ord(letter) - ord('A') + 1:02d}{digits}"
    total = sum(
        sum(divmod(int(d) * (2 if position % 2 else 1), 10)) for position, d in enumerate(numbers)
    )
    return f"{letter}{digits}{total % 10}"
