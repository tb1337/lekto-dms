"""Where an identifier stands in a document, for showing it on the page: the text around it and
each place the pages show it (`domain.occurrences`)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from lekto.core.domain.document_facts import DocumentFact, FactRole
from lekto.core.domain.errors import NotFoundError
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.occurrences import Occurrence, occurrences
from lekto.core.domain.open_identifiers import Excerpt, excerpt
from lekto.core.ports.object_store import ObjectStore
from lekto.core.services.objects import load_layout, load_text

PLACES = 5
"""Documents a list of places names at most: the newest."""


@dataclass(frozen=True)
class Place:
    """Where an identifier stands in one document: its title and date, the fact's role there,
    the text around it where it first stands (None if the document has no text or the fact no
    position), and each place its pages show it (none without the words of its pages)."""

    document: DocumentId
    title: str
    dated: date
    role: FactRole
    excerpt: Excerpt | None
    occurrences: tuple[Occurrence, ...] = ()


async def place_of(
    store: ObjectStore, document: DocumentId, title: str, dated: date, fact: DocumentFact
) -> Place:
    """Where `fact` stands in `document`."""
    try:
        text = (await load_text(store, document)).decode("utf-8", "replace")
    except NotFoundError:
        return Place(document, title, dated, fact.role, None)
    pages = await load_layout(store, document)
    around = None
    if fact.position is not None:
        around = excerpt(text, fact.position, len(fact.written or fact.value))
    # Matching the words of long pages takes a while: not in the loop.
    found = await asyncio.to_thread(occurrences, text, pages, fact.kind, fact.value, fact.position)
    return Place(document, title, dated, fact.role, around, found)
