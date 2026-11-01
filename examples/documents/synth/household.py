"""The household the documents belong to: Max Mustermann, Erika Musterfrau and their daughter
Lena in Musterstadt, who moved on 1 August 2025. All names, addresses and numbers are made up."""

from dataclasses import dataclass
from datetime import date

from synth import ids

MOVED = date(2025, 8, 1)


@dataclass(frozen=True)
class Person:
    username: str
    first: str
    last: str
    salutation: str  # Herrn, Frau
    letter: str  # Sehr geehrter Herr Mustermann
    born: date
    tax_id: str = ""
    social_security_number: str = ""
    health_insurance_number: str = ""

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


MAX = Person(
    "max",
    "Max",
    "Mustermann",
    "Herrn",
    "Sehr geehrter Herr Mustermann",
    date(1984, 6, 14),
    tax_id=ids.tax_id("4719283561"),
    social_security_number=ids.social_security_number("65140684", "M", "51"),
    health_insurance_number=ids.health_insurance_number("M", "28371946"),
)
ERIKA = Person(
    "erika",
    "Erika",
    "Musterfrau",
    "Frau",
    "Sehr geehrte Frau Musterfrau",
    date(1986, 11, 2),
    tax_id=ids.tax_id("8326154973"),
    social_security_number=ids.social_security_number("65021186", "S", "52"),
    health_insurance_number=ids.health_insurance_number("M", "61829374"),
)
LENA = Person(
    "lena",
    "Lena",
    "Mustermann",
    "",
    "Liebe Lena",
    date(2017, 5, 9),
    health_insurance_number=ids.health_insurance_number("M", "73920481"),
)

CHILD_BENEFIT_NUMBER = "245FK112233"
LICENSE_PLATE = "MU-MM 1984"
MAX_IBAN = ids.iban("DE", "250500000123456789")
ERIKA_IBAN = ids.iban("DE", "430600002233445566")
MAX_EMAIL = "max.mustermann@posteo-beispiel.example"


def street(day: date) -> tuple[str, str]:
    """The household's address on `day`: street and city."""
    if day < MOVED:
        return ("Birkenweg 5", "12347 Musterstadt")
    return ("Lindenallee 12", "12345 Musterstadt")


def address(person: Person, day: date, *, both: bool = False) -> tuple[str, ...]:
    """The lines of the window for `person` (and, `both`, for the couple) on `day`."""
    road, city = street(day)
    if both:
        return ("Herrn Max Mustermann", "Frau Erika Musterfrau", road, city)
    if person.salutation:
        return (person.salutation, person.name, road, city)
    return (person.name, road, city)
