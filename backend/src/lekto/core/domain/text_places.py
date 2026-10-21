"""Where a stretch of a document's text stands on its pages, for showing a fact found in the
text on the page it came from.

The parser writes the text from the words of its structure (`labels.layout_words`), line by
line and page by page, with spaces, the columns of a line and the breaks of lines and pages
between them. So the words stand in the text in their order, each as a run of characters
between spaces: a word is matched with the next such run that spells it, looked for among the
`REACH` runs after the one matched before. A word not found there (a block in fixed pitch
spells a hyphen its own way) is left out, and the next one is looked for from the same run, so
one such word does not put the rest out of step. A stretch stands where the words it touches
stand, a box per line (`line_boxes`).
"""

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lekto.core.domain.labels import LaidWord
from lekto.core.domain.locations import Box, Location, line_boxes

REACH = 20
"""How many runs of the text after the last one matched a word is looked for in."""

_RUN = re.compile(r"\S+")


@dataclass(frozen=True)
class _Placed:
    start: int
    end: int
    page: int
    box: Box


class TextPlaces:
    """The words of the parsed text, by page in reading order, with where each stands in
    `text` and on its page."""

    def __init__(self, text: str, pages: Mapping[int, Sequence[LaidWord]]) -> None:
        runs = [(match.group(), match.start(), match.end()) for match in _RUN.finditer(text)]
        placed: list[_Placed] = []
        at = 0
        for number in sorted(pages):
            for word in pages[number]:
                for index in range(at, min(at + REACH, len(runs))):
                    spelt, start, end = runs[index]
                    if spelt == word.text:
                        placed.append(_Placed(start, end, number, word.box))
                        at = index + 1
                        break
        self._placed = placed
        self._ends = [item.end for item in placed]

    def locations(self, start: int, end: int) -> tuple[Location, ...]:
        """Where characters `start` to `end` (exclusive) of the text stand: by page, a box per
        line of the words they touch; none where no word of them was found."""
        boxes: dict[int, list[Box]] = {}
        index = bisect_right(self._ends, start)
        while index < len(self._placed) and self._placed[index].start < end:
            item = self._placed[index]
            boxes.setdefault(item.page, []).append(item.box)
            index += 1
        return tuple(Location(page, line_boxes(found)) for page, found in sorted(boxes.items()))
