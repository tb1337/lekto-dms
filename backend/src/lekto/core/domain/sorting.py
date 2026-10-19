"""How lists sort text: case and accents aside, an umlaut as its letter (DIN 5007-1), so that
`Ärztebrief` stands with `Arzt` and `straße` with `strasse`."""

import unicodedata


def sort_key(text: str) -> str:
    return strip_accents(text).casefold().strip()


def strip_accents(text: str) -> str:
    """`text` without accents and umlaut dots: `é` → `e`, `ä` → `a`."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))
