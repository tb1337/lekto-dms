"""Where a value stands on the pages: each place the text writes it, as its kind may write it,
the one its fact was read at as its own."""

from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.labels import LaidWord, grid_layout, layout_words
from lekto.core.domain.occurrences import occurrences

IBAN = "DE89370400440532013000"
TEXT = """\
Musterbank                 Kontoauszug 3/2021
Saldo -3.590,00 Euro  IBAN DE89 3704 0044 0532 0130 00  BIC MUSTDEFFXXX
\f
Ihre IBAN für Überweisungen: de89370400440532013000"""


def pages() -> dict[int, tuple[LaidWord, ...]]:
    found = layout_words(grid_layout(TEXT))
    assert found is not None
    return found


def test_each_place_on_the_pages_the_own_one_marked() -> None:
    position = TEXT.index("DE89 3704")
    first, second = occurrences(TEXT, pages(), IdentifierKind.IBAN, IBAN, position)
    assert (first.own, second.own) == (True, False)
    assert [location.page for location in first.locations] == [1]
    assert [location.page for location in second.locations] == [2]
    # Written with spaces, the place covers them: one box from the first to the last group.
    (box,) = first.locations[0].boxes
    assert round(box.x * 80) == TEXT.split("\n")[1].index("DE89")


def test_none_without_the_words_of_the_pages_or_without_a_known_position() -> None:
    assert occurrences(TEXT, {}, IdentifierKind.IBAN, IBAN, 0) == ()
    found = occurrences(TEXT, pages(), IdentifierKind.IBAN, IBAN, None)
    assert len(found) == 2 and not any(item.own for item in found)
