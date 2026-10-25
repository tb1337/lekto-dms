"""Finding identifiers: readers take values for identifiers (`Candidate`: the patterns of each
kind in a text, a GiroCode's IBAN), Lekto checks each against its kind and weighs them together
(`identifiers_from`). A customer or personnel number that is one of a person's numbers, stands
in one or overlaps it is theirs only (a pension fund writes "Versicherungsnummer" before the
social security number, `65 170839 J 003`)."""

import re
from collections.abc import Iterable, Iterator
from contextlib import suppress

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import normalise
from lekto.core.domain.identifiers.base import Candidate, Key
from lekto.core.domain.identifiers.registry import NAMING_KINDS, OWN_KINDS, TYPES

_CONTAINED = 6
"""Characters a customer or personnel number has at least to count as part of a person's number
it stands in."""


def candidates_in(text: str) -> Iterator[Candidate]:
    """What the patterns of every kind find in `text`."""
    normalised = normalise(text)
    for item in TYPES.values():
        yield from item.find(normalised)


def identifiers_in(text: str) -> set[Key]:
    """The identifiers `text` shows, normalised: IBANs and German VAT numbers anywhere, other
    VAT numbers, customer and personnel numbers after their label ("USt-IdNr.", "Kundennummer",
    "Vertragsnummer", "Personalnummer", ...), the domains of e-mail and web addresses (free
    mail aside) and the addresses themselves; a person's numbers with a valid check digit: the
    tax ID after its label ("Steuer-ID", "IdNr.") or in its groups (`12 345 678 901`), the social
    security number anywhere, the health insurance number after its label
    ("Versichertennummer", "Krankenversicherungsnummer"). Weighed as `identifiers_from`
    weighs them."""
    return identifiers_from(candidates_in(text))


def places_in(text: str) -> dict[Key, int]:
    """Where each value its reader took for an identifier stands first in the normalised `text`
    (after its label, not a number of the same digits before it)."""
    places: dict[Key, int] = {}
    for candidate in candidates_in(text):
        if candidate.span is None:
            continue
        with suppress(ValidationError):
            key = (candidate.kind, TYPES[candidate.kind].normalise(candidate.raw))
            places[key] = min(places.get(key, candidate.span[0]), candidate.span[0])
    return places


def identifiers_from(candidates: Iterable[Candidate]) -> set[Key]:
    """The identifiers among `candidates`, normalised: those of their kind (the others are left
    out); a customer or personnel number only if it is none of the person's numbers found, does
    not stand in one (`of_person`) and does not overlap one where both tell their place."""
    found: set[Key] = set()
    naming: list[tuple[Key, tuple[int, int] | None]] = []
    own_spans: list[tuple[int, int]] = []
    for candidate in candidates:
        with suppress(ValidationError):
            key = (candidate.kind, TYPES[candidate.kind].normalise(candidate.raw))
            if candidate.kind in NAMING_KINDS:
                naming.append((key, candidate.span))
                continue
            found.add(key)
            if candidate.kind in OWN_KINDS and candidate.span is not None:
                own_spans.append(candidate.span)
    personal = [key for key in found if key[0] in OWN_KINDS]
    for key, span in naming:
        overlaps = span is not None and any(
            span[0] < theirs_end and theirs_start < span[1]
            for theirs_start, theirs_end in own_spans
        )
        if not overlaps and not of_person(key, personal):
            found.add(key)
    return found


def of_person(key: Key, personal: Iterable[Key]) -> bool:
    """Whether an identifier is one of a person's values `personal`: the same, or a customer or
    personnel number with the value of one of them (of any kind: the IBAN as an "account
    number"), or one that stands in a tax ID, social security or health insurance number (a
    pension fund's "Versicherungsnummer" is the start of the social security number)."""
    kind, value = key
    for theirs in personal:
        if theirs == key:
            return True
        if kind not in NAMING_KINDS:
            continue
        their_kind, their_value = theirs
        compact = re.sub(r"[^A-Z0-9]", "", their_value.upper())
        if value == compact:
            return True
        if their_kind in OWN_KINDS and len(value) >= _CONTAINED and value in compact:
            return True
    return False
