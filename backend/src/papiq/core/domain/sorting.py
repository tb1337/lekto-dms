"""How lists sort text: case and accents aside, an umlaut as its letter (DIN 5007-1), so that
`Ärztebrief` stands with `Arzt` and `straße` with `strasse`."""

import unicodedata


def sort_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return letters.casefold().strip()
