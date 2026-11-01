"""Pages as a program prints them on a line printer or as a text report: Courier lines under a
heading in Helvetica, numbered pages."""

from collections.abc import Sequence

from synth.fonts import MONO, SANS_BOLD
from synth.layout import GREY, Page

LINES_PER_PAGE = 58


def printout(
    heading: str, lines: Sequence[str], *, size: float = 9, footer: str = "", left: float = 18
) -> list[Page]:
    """`lines` in Courier at `size` points, as many pages as they need, each with `heading`
    and its number."""
    step = size * 0.5
    per_page = min(LINES_PER_PAGE, int(250 / step))
    chunks = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    pages = []
    for number, chunk in enumerate(chunks, start=1):
        page = Page()
        page.text(left, 16, heading, SANS_BOLD, 10)
        page.text(192, 16, f"Seite {number}/{len(chunks)}", MONO, 8, "right", GREY)
        page.line((left, 18.5), (192, 18.5), width=0.4)
        y = 26.0
        for line in chunk:
            page.text(left, y, line, MONO, size)
            y += step
        if footer:
            page.text(left, 287, footer, MONO, 7.5, color=GREY)
        pages.append(page)
    return pages
