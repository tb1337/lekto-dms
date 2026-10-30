"""Where a rule's text conditions hit a document's text, as characters of the text as stored,
for showing them on its pages: `contains` as the rules read it (`evidence.contains`: whole
words, any case, any whitespace between them, or, for a long value, any spaces within it),
`matches` where its pattern hits the text with whitespace collapsed (as `pattern_text` reads
it), mapped back."""

import re
from dataclasses import dataclass

from lekto.core.domain.evidence import normalise

MAX_HITS = 20
"""Places of one condition at most."""

_SHORTEST_SPACELESS = 8  # as `evidence.contains`
_BEFORE = r"(?<![^\W_])(?<![^\W_][-./,])"
_AFTER = r"(?![^\W_])(?![-./,][^\W_])"
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Collapsed:
    """A text with each run of whitespace as one space, and for each of its characters the
    one of the text it stands for (`at`, one more at the end)."""

    text: str
    at: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Characters `start` to `end` of the collapsed text, in the text."""
        return self.at[start], self.at[end - 1] + 1


def collapsed(text: str) -> Collapsed:
    parts: list[str] = []
    at: list[int] = []
    last = 0
    for match in _WHITESPACE.finditer(text):
        parts.append(text[last : match.start()])
        at.extend(range(last, match.start()))
        parts.append(" ")
        at.append(match.start())
        last = match.end()
    parts.append(text[last:])
    at.extend(range(last, len(text) + 1))
    return Collapsed("".join(parts), tuple(at))


def contained(text: str, value: str) -> tuple[tuple[int, int], ...]:
    """Where `text` contains `value` as `contains` finds it: as whole words, else, for a long
    value, ignoring spaces."""
    words = normalise(value).split()
    if not words:
        return ()
    exact = _BEFORE + r"\s+".join(re.escape(word) for word in words) + _AFTER
    found = _spans(exact, text)
    spaceless = "".join(words)
    if not found and len(spaceless) >= _SHORTEST_SPACELESS:
        found = _spans(r"\s*".join(re.escape(char) for char in spaceless), text)
    return found


def _spans(pattern: str, text: str) -> tuple[tuple[int, int], ...]:
    found = re.finditer(pattern, text, re.IGNORECASE)
    return tuple(match.span() for _, match in zip(range(MAX_HITS), found, strict=False))
