"""A business letter after DIN 5008 (form B): letterhead, return address and recipient in the
window, an information block, subject, body and a footer with the sender's legal details; the
body flows over as many pages as it needs, each after the first with a short header.

The body is a list of blocks (paragraphs, tables, totals, boxes, codes, a signature) that
`Letter.pages` sets from top to bottom. A sender's `Style` gives its letters one look: family,
colour, logo and the arrangement of the head."""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PIL import Image

from synth.fonts import Font, width, wrap
from synth.layout import BLACK, GREY, RGB, WHITE, Page

LEFT = 25.0
RIGHT = 190.0
BODY_BOTTOM = 262.0
NEXT_TOP = 34.0


@dataclass(frozen=True)
class Style:
    family: str = "sans"
    accent: RGB = (0, 90, 140)
    logo: str = "circle"  # circle, diamond, bars, triangle, rings, monogram, none
    head: str = "right"  # right, left, band, center
    tagline: str = ""


@dataclass(frozen=True)
class Sender:
    """Who writes: name and address, how to reach them, bank and legal details."""

    name: str
    street: str
    city: str  # postcode and city
    style: Style = field(default_factory=Style)
    short: str = ""  # the name in the head, if shorter
    phone: str = ""
    email: str = ""
    web: str = ""
    bank: str = ""
    iban: str = ""
    bic: str = ""
    register: str = ""  # court and number
    vat_id: str = ""
    tax_number: str = ""
    managers: str = ""  # managing directors, board
    extra: tuple[str, ...] = ()  # further footer lines

    @property
    def head_name(self) -> str:
        return self.short or self.name


@dataclass(frozen=True)
class Column:
    title: str
    width: float  # millimetres
    align: str = "left"


@dataclass
class Letter:
    sender: Sender
    recipient: Sequence[str]
    info: Sequence[tuple[str, str]]
    subject: str
    reference: str = ""  # on the following pages' header, e.g. "Rechnung R-1"
    page_word: str = "Seite"
    of_word: str = "von"
    blocks: list[Callable[["_Flow"], None]] = field(default_factory=list)
    footer: bool = True
    seed: int = 0

    @property
    def font(self) -> Font:
        return Font(self.sender.style.family)

    # Blocks of the body, in the order they stand.

    def paragraph(
        self,
        text: str,
        *,
        size: float = 10,
        bold: bool = False,
        color: RGB = BLACK,
        indent: float = 0,
        after: float = 3,
    ) -> None:
        def place(flow: _Flow) -> None:
            font = self.font.bolder() if bold else self.font
            lines = wrap(text, font, size, RIGHT - LEFT - indent)
            step = size * 0.46
            for line in lines:
                flow.need(step)
                flow.y += step
                flow.page.text(LEFT + indent, flow.y, line, font, size, color=color)
            flow.y += after

        self.blocks.append(place)

    def heading(self, text: str, *, size: float = 11, after: float = 2) -> None:
        def place(flow: _Flow) -> None:
            flow.need(size * 0.46 + 20)
            flow.y += size * 0.5
            flow.page.text(
                LEFT, flow.y, text, self.font.bolder(), size, color=self.sender.style.accent
            )
            flow.y += after

        self.blocks.append(place)

    def space(self, mm: float) -> None:
        def place(flow: _Flow) -> None:
            flow.y += mm

        self.blocks.append(place)

    def pairs(
        self,
        rows: Sequence[tuple[str, str]],
        *,
        label_width: float = 55,
        size: float = 10,
        after: float = 3,
    ) -> None:
        """Label and value, one pair a line."""

        def place(flow: _Flow) -> None:
            step = size * 0.48
            for label, value in rows:
                lines = wrap(value, self.font, size, RIGHT - LEFT - label_width)
                flow.need(step * len(lines))
                flow.y += step
                flow.page.text(LEFT, flow.y, label, self.font, size, color=GREY)
                for number, line in enumerate(lines):
                    if number:
                        flow.y += step
                    flow.page.text(LEFT + label_width, flow.y, line, self.font, size)
            flow.y += after

        self.blocks.append(place)

    def table(
        self,
        columns: Sequence[Column],
        rows: Sequence[Sequence[str]],
        *,
        size: float = 9,
        bold_rows: Sequence[int] = (),
        rules: bool = True,
        shade: bool = False,
        after: float = 4,
    ) -> None:
        """A table across the body; its head again on each page it continues on."""

        def head(flow: _Flow) -> None:
            accent = self.sender.style.accent
            flow.need(12)
            if shade:
                flow.page.rect(LEFT, flow.y, RIGHT - LEFT, 5.6, fill=_tint(accent, 0.85))
            flow.y += 4
            _row(flow, [column.title for column in columns], self.font.bolder(), size * 0.95)
            flow.y += 1.6
            flow.page.line((LEFT, flow.y), (RIGHT, flow.y), width=0.8, color=accent)

        def place(flow: _Flow) -> None:
            step = size * 0.5
            head(flow)
            for number, cells in enumerate(rows):
                if flow.y + step > BODY_BOTTOM:
                    flow.new_page()
                    head(flow)
                flow.y += step
                font = self.font.bolder() if number in bold_rows else self.font
                _row(flow, cells, font, size)
                if rules:
                    flow.page.line(
                        (LEFT, flow.y + 1.6), (RIGHT, flow.y + 1.6), width=0.2, color=(190,) * 3
                    )
            flow.y += after

        def _row(flow: _Flow, cells: Sequence[str], font: Font, cell_size: float) -> None:
            x = LEFT
            for column, cell in zip(columns, cells, strict=False):
                if column.align == "right":
                    flow.page.text(x + column.width - 1, flow.y, cell, font, cell_size, "right")
                elif column.align == "center":
                    flow.page.text(x + column.width / 2, flow.y, cell, font, cell_size, "center")
                else:
                    flow.page.text(x + 1, flow.y, cell, font, cell_size)
                x += column.width

        self.blocks.append(place)

    def totals(
        self, rows: Sequence[tuple[str, str]], *, size: float = 10, strong_last: bool = True
    ) -> None:
        """Sums on the right, the last one bold over a line."""

        def place(flow: _Flow) -> None:
            step = size * 0.5
            flow.need(step * len(rows) + 4)
            for number, (label, value) in enumerate(rows):
                last = strong_last and number == len(rows) - 1
                font = self.font.bolder() if last else self.font
                if last:
                    flow.y += 1
                    flow.page.line((112, flow.y), (RIGHT, flow.y), width=0.6)
                flow.y += step
                flow.page.text(115, flow.y, label, font, size)
                flow.page.text(RIGHT - 1, flow.y, value, font, size, "right")
            flow.y += 4

        self.blocks.append(place)

    def box(self, lines: Sequence[str], *, size: float = 10, after: float = 4) -> None:
        """A tinted box in the sender's colour, the first line bold."""

        def place(flow: _Flow) -> None:
            step = size * 0.5
            height = step * len(lines) + 4
            flow.need(height)
            accent = self.sender.style.accent
            flow.page.rect(LEFT, flow.y, RIGHT - LEFT, height, fill=_tint(accent, 0.88))
            flow.page.rect(LEFT, flow.y, 1.4, height, fill=accent)
            y = flow.y + 1.2
            for number, line in enumerate(lines):
                y += step
                font = self.font.bolder() if number == 0 else self.font
                flow.page.text(LEFT + 5, y, line, font, size)
            flow.y += height + after

        self.blocks.append(place)

    def code(
        self, image: Image.Image, lines: Sequence[str], *, side: float = 28, after: float = 4
    ) -> None:
        """A code on the right with text beside it (a GiroCode and how to use it)."""

        def place(flow: _Flow) -> None:
            flow.need(side + 2)
            flow.page.picture(RIGHT - side, flow.y + 1, side, side, image)
            y = flow.y + 1
            for number, line in enumerate(lines):
                y += 4.6
                font = self.font.bolder() if number == 0 else self.font
                flow.page.text(RIGHT - side - 4, y, line, font, 9, "right")
            flow.y += side + 2 + after

        self.blocks.append(place)

    def chart(
        self, bars: Sequence[tuple[str, float]], *, unit: str, height: float = 30, after: float = 4
    ) -> None:
        """Bars with their labels below and values above, in the sender's colour."""

        def place(flow: _Flow) -> None:
            flow.need(height + 10)
            top = flow.y + 4
            peak = max(value for _, value in bars) or 1
            for number, (label, value) in enumerate(bars):
                x = LEFT + 8 + number * 24
                h = (height - 6) * value / peak
                color = self.sender.style.accent if number == len(bars) - 1 else (170,) * 3
                flow.page.rect(x, top + height - h, 14, h, fill=color)
                flow.page.text(
                    x + 7,
                    top + height - h - 1.5,
                    f"{value:,.0f} {unit}".replace(",", "."),
                    self.font,
                    7,
                    "center",
                )
                flow.page.text(x + 7, top + height + 4, label, self.font, 7.5, "center")
            flow.page.line(
                (LEFT, top + height), (LEFT + 16 + len(bars) * 24, top + height), width=0.4
            )
            flow.y = top + height + 6 + after

        self.blocks.append(place)

    def signature(self, closing: str, name: str, role: str = "") -> None:
        """The closing, a written signature and the name below."""

        def place(flow: _Flow) -> None:
            flow.need(32)
            flow.y += 5
            flow.page.text(LEFT, flow.y, closing, self.font, 10)
            rng = random.Random(f"{self.seed}-{name}")
            _scribble(flow.page, LEFT + 2, flow.y + 14, rng)
            flow.y += 22
            flow.page.text(LEFT, flow.y, name, self.font, 10)
            if role:
                flow.y += 4.6
                flow.page.text(LEFT, flow.y, role, self.font, 9, color=GREY)
            flow.y += 4

        self.blocks.append(place)

    # Setting it on pages.

    def pages(self) -> list[Page]:
        flow = _Flow(self)
        flow.first_page()
        for block in self.blocks:
            block(flow)
        total = len(flow.pages)
        for number, page in enumerate(flow.pages, start=1):
            if self.footer:
                _footer(page, self.sender)
            if total > 1:
                page.text(
                    RIGHT,
                    268,
                    f"{self.page_word} {number} {self.of_word} {total}",
                    self.font,
                    8,
                    "right",
                    GREY,
                )
            if number > 1:
                _continuation(page, self, number, total)
        return flow.pages


class _Flow:
    """Where the body stands: the page and the height on it."""

    def __init__(self, letter: Letter) -> None:
        self.letter = letter
        self.pages: list[Page] = []
        self.page = Page()
        self.y = 0.0

    def first_page(self) -> None:
        self.page = Page()
        self.pages.append(self.page)
        self.y = _first_page(self.page, self.letter)

    def new_page(self) -> None:
        self.page = Page()
        self.pages.append(self.page)
        self.y = NEXT_TOP

    def need(self, height: float) -> None:
        if self.y + height > BODY_BOTTOM:
            self.new_page()


def _tint(color: RGB, amount: float) -> RGB:
    r, g, b = color
    return (
        round(r + (255 - r) * amount),
        round(g + (255 - g) * amount),
        round(b + (255 - b) * amount),
    )


def logo(page: Page, kind: str, x: float, y: float, size: float, color: RGB, text: str) -> None:
    """A sender's mark in the square (`x`, `y`, `size`)."""
    s = size
    match kind:
        case "circle":
            page.ellipse(x, y, s, s, fill=color)
            page.ellipse(x + s * 0.32, y + s * 0.18, s * 0.5, s * 0.5, fill=WHITE)
        case "diamond":
            page.polygon(
                (x + s / 2, y), (x + s, y + s / 2), (x + s / 2, y + s), (x, y + s / 2), fill=color
            )
            page.polygon(
                (x + s / 2, y + s * 0.3),
                (x + s * 0.7, y + s / 2),
                (x + s / 2, y + s * 0.7),
                (x + s * 0.3, y + s / 2),
                fill=WHITE,
            )
        case "bars":
            for number, height in enumerate((0.55, 0.8, 1.0, 0.7)):
                bx = x + number * s * 0.26
                page.rect(bx, y + s * (1 - height), s * 0.18, s * height, fill=color)
        case "triangle":
            page.polygon((x, y + s), (x + s / 2, y), (x + s, y + s), fill=color)
            page.polygon(
                (x + s * 0.3, y + s), (x + s / 2, y + s * 0.55), (x + s * 0.7, y + s), fill=WHITE
            )
        case "rings":
            for number in range(3):
                page.ellipse(
                    x + number * s * 0.28, y + s * 0.2, s * 0.44, s * 0.44, stroke=color, width=2.2
                )
        case "monogram":
            page.rect(x, y, s, s, fill=color)
            initials = "".join(part[0] for part in text.split()[:2]).upper()
            page.text(
                x + s / 2,
                y + s * 0.68,
                initials,
                Font("serif", bold=True),
                s * 1.3,
                "center",
                WHITE,
            )
        case "wave":
            points = [
                (x + s * t / 20, y + s * 0.5 - s * 0.3 * math.sin(t / 20 * 2 * math.pi))
                for t in range(21)
            ]
            page.polygon(*points, (x + s, y + s), (x, y + s), fill=color)


def _first_page(page: Page, letter: Letter) -> float:
    """The head, the window and the information block; the height where the body begins."""
    sender, style = letter.sender, letter.sender.style
    font, bold = Font(style.family), Font(style.family, bold=True)
    accent = style.accent
    match style.head:
        case "band":
            page.rect(0, 0, page.width, 30, fill=accent)
            page.text(LEFT, 19, sender.head_name, bold, 20, color=WHITE)
            if style.tagline:
                page.text(LEFT, 25.5, style.tagline, font, 9, color=WHITE)
            if style.logo != "none":
                logo(page, style.logo, RIGHT - 16, 7, 16, WHITE, sender.head_name)
        case "left":
            if style.logo != "none":
                logo(page, style.logo, LEFT, 12, 17, accent, sender.head_name)
            x = LEFT + (22 if style.logo != "none" else 0)
            page.text(x, 22, sender.head_name, bold, 17, color=accent)
            if style.tagline:
                page.text(x, 28, style.tagline, font, 9, color=GREY)
        case "center":
            page.text(page.width / 2, 20, sender.head_name, bold, 18, "center", accent)
            page.line((LEFT + 30, 24.5), (RIGHT - 30, 24.5), width=0.6, color=accent)
            sub = style.tagline or f"{sender.street} · {sender.city}"
            page.text(page.width / 2, 30, sub, font, 8.5, "center", GREY)
        case _:
            if style.logo != "none":
                logo(page, style.logo, RIGHT - 18, 12, 18, accent, sender.head_name)
            x = RIGHT - (23 if style.logo != "none" else 0)
            page.text(x, 22, sender.head_name, bold, 16, "right", accent)
            if style.tagline:
                page.text(x, 28, style.tagline, font, 9, "right", GREY)
    # Fold and hole marks.
    for y in (105, 210):
        page.line((4, y), (8, y), width=0.3, color=GREY)
    page.line((4, 148.5), (9, 148.5), width=0.3, color=GREY)
    # The window: return address, recipient.
    back = f"{sender.name} · {sender.street} · {sender.city}"
    size = 7
    while width(back, font, size) > 80 and size > 5.5:
        size -= 0.25
    page.text(LEFT, 57, back, font, size)
    page.line((LEFT, 58.2), (LEFT + width(back, font, size), 58.2), width=0.3)
    y = 66
    for line in letter.recipient:
        page.text(LEFT, y, line, font, 10)
        y += 4.5
    # The information block.
    y = 52
    for label, value in letter.info:
        page.text(125, y, label, font, 8, color=GREY)
        page.text(RIGHT, y, value, font, 8.5, "right")
        y += 4.4
    # The subject.
    lines = wrap(letter.subject, bold, 11, RIGHT - LEFT)
    y = max(103.0, y + 6)
    for line in lines:
        page.text(LEFT, y, line, bold, 11)
        y += 5
    return y + 4


def _continuation(page: Page, letter: Letter, number: int, total: int) -> None:
    font = Font(letter.sender.style.family)
    page.text(LEFT, 18, letter.sender.head_name, font.bolder(), 9, color=letter.sender.style.accent)
    right = f"{letter.reference} · " if letter.reference else ""
    page.text(
        RIGHT,
        18,
        f"{right}{letter.page_word} {number} {letter.of_word} {total}",
        font,
        8,
        "right",
        GREY,
    )
    page.line((LEFT, 21), (RIGHT, 21), width=0.3, color=GREY)


def _footer(page: Page, sender: Sender) -> None:
    font = Font(sender.style.family)
    columns: list[list[str]] = [
        [sender.name, sender.street, sender.city],
        [line for line in (sender.phone, sender.email, sender.web) if line],
        [
            line
            for line in (
                sender.bank,
                sender.iban and f"IBAN {sender.iban}",
                sender.bic and f"BIC {sender.bic}",
            )
            if line
        ],
        [
            line
            for line in (
                sender.register,
                sender.vat_id and f"USt-IdNr. {sender.vat_id}",
                sender.tax_number and f"St.-Nr. {sender.tax_number}",
                sender.managers,
                *sender.extra,
            )
            if line
        ],
    ]
    columns = [column for column in columns if column]
    page.line((LEFT, 272), (RIGHT, 272), width=0.3, color=sender.style.accent)
    # Each column as wide as its longest line, the gaps shared out; smaller type if they don't fit.
    size = 6.5
    widths = [max(width(line, font, size) for line in column) for column in columns]
    room = RIGHT - LEFT
    while sum(widths) + 3 * (len(columns) - 1) > room and size > 4.5:
        size -= 0.25
        widths = [max(width(line, font, size) for line in column) for column in columns]
    gap = (room - sum(widths)) / max(1, len(columns) - 1)
    x = LEFT
    for column, column_width in zip(columns, widths, strict=True):
        for number, line in enumerate(column):
            page.text(x, 276 + number * 3, line, font, size, color=GREY)
        x += column_width + gap


def _scribble(page: Page, x: float, y: float, rng: random.Random) -> None:
    """A signature: a few loops, written in one stroke, in blue."""
    points = []
    t = 0.0
    loops = rng.randint(3, 6)
    length = rng.uniform(30, 45)
    for step in range(120):
        t = step / 119
        px = x + t * length + 2.5 * math.sin(t * loops * 2 * math.pi + rng.random() * 0.2)
        py = y - 4 * math.sin(t * loops * math.pi) * (1 - t * 0.5) + rng.uniform(-0.2, 0.2)
        points.append((px, py))
    page.line(*points, width=0.9, color=(20, 40, 120))
