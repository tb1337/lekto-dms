"""Where a value stands on a document's pages: each place its text writes it (as its kind may
write it, `identifier_spans`), on the pages of the parsed text (`TextPlaces`); the one a fact was
read at is its own."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lekto.core.domain.facts import identifier_spans
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.labels import LaidWord
from lekto.core.domain.locations import Location
from lekto.core.domain.text_places import TextPlaces


@dataclass(frozen=True)
class Occurrence:
    """One place a value stands, by page a box per line; `own`: where its fact was read."""

    locations: tuple[Location, ...]
    own: bool = False


def occurrences(
    text: str,
    pages: Mapping[int, Sequence[LaidWord]],
    kind: IdentifierKind,
    value: str,
    position: int | None,
) -> tuple[Occurrence, ...]:
    """Each place `text` writes `value` of `kind` that stands on `pages`, in the order of the
    text; the one starting at `position` (the fact's) is its own. None without pages (a document
    parsed before its words were kept)."""
    if not pages:
        return ()
    places = TextPlaces(text, pages)
    found = []
    for span in identifier_spans(text, kind, value):
        located = places.locations(span.start, span.end)
        if located:
            found.append(Occurrence(located, own=span.start == position))
    return tuple(found)
