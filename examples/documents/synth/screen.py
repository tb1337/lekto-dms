"""Web pages as a browser shows them, for screenshots: a confirmation page of a shop, a bank or
a railway, 1440 by 900 pixels at 96 dpi."""

from collections.abc import Sequence

from synth.fonts import Font
from synth.layout import GREY, WHITE, Page
from synth.letter import Sender, _tint, logo

PX = 25.4 / 96
WIDTH, HEIGHT = 1440 * PX, 900 * PX


def confirmation(
    sender: Sender,
    heading: str,
    intro: str,
    pairs: Sequence[tuple[str, str]],
    rows: Sequence[tuple[str, str]] = (),
    note: str = "",
    nav: Sequence[str] = ("Start", "Angebote", "Service", "Mein Konto"),
) -> Page:
    """A page under the site's bar: a heading, a sentence, a card of label and value, an
    optional list of lines with amounts and a note below."""
    style = sender.style
    font, bold = Font(style.family), Font(style.family, bold=True)
    page = Page(WIDTH, HEIGHT)
    page.rect(0, 0, WIDTH, 18, fill=style.accent)
    if style.logo != "none":
        logo(page, style.logo, 12, 3.5, 11, WHITE, sender.head_name)
    page.text(27, 11.5, sender.head_name, bold, 15, color=WHITE)
    x = WIDTH - 20
    for item in reversed(nav):
        page.text(x, 11, item, font, 10, "right", WHITE)
        x -= 30
    page.rect(0, 18, WIDTH, HEIGHT - 18, fill=(246, 247, 249))
    left = 70.0
    page.rect(
        left - 10,
        28,
        WIDTH - 2 * (left - 10),
        HEIGHT - 48,
        fill=WHITE,
        stroke=(225, 228, 232),
        width=0.6,
    )
    page.ellipse(left, 38, 9, 9, fill=(40, 160, 90))
    page.line((left + 2.4, 42.8), (left + 4, 44.5), (left + 6.8, 40.6), width=1.6, color=WHITE)
    page.text(left + 14, 45, heading, bold, 18)
    page.text(left, 56, intro, font, 10.5, color=GREY)
    y = 68.0
    page.rect(left, y, 150, 8 + 7 * len(pairs), fill=_tint(style.accent, 0.92))
    y += 9
    for label, value in pairs:
        page.text(left + 5, y, label, font, 10, color=GREY)
        page.text(left + 60, y, value, bold, 10)
        y += 7
    if rows:
        top = 68.0
        x0 = left + 165
        page.text(x0, top + 6, "Ihre Auswahl", bold, 11)
        yy = top + 14
        for name, amount in rows:
            page.text(x0, yy, name, font, 10)
            page.text(x0 + 125, yy, amount, font, 10, "right")
            page.line((x0, yy + 2.2), (x0 + 125, yy + 2.2), width=0.3, color=(220, 220, 220))
            yy += 7
    if note:
        page.text(left, y + 10, note, font, 9.5, color=GREY)
    page.rect(left, HEIGHT - 42, 52, 10, fill=style.accent)
    page.text(
        left + 26,
        HEIGHT - 35.3,
        "Weiter einkaufen" if rows else "Zur Übersicht",
        bold,
        10,
        "center",
        WHITE,
    )
    page.text(
        WIDTH / 2,
        HEIGHT - 8,
        f"© 2026 {sender.name} · Impressum · Datenschutz · AGB",
        font,
        8,
        "center",
        GREY,
    )
    return page
