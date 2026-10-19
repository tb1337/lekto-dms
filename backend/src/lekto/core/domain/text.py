"""Long texts shortened to a budget: the beginning and the end are kept, where letterhead,
date, subject and totals usually stand."""

import re
from dataclasses import dataclass

_SPACES = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True)
class Shortened:
    text: str
    omitted: int  # characters left out; 0 if the text fits


def shorten(text: str, budget: int) -> Shortened:
    """At most about `budget` characters, a run of spaces counted once (the columns of a text
    as it is set cost a model little): two thirds from the beginning and one third from the
    end, cut at line breaks where one is near, with a note on what was left out."""
    if weight(text) <= budget:
        return Shortened(text, 0)
    head = _cut_back(text[: _reach(text, budget * 2 // 3)])
    tail = text[len(text) - _reach(text[::-1], budget - budget * 2 // 3) :]
    tail = _cut_forward(tail)
    omitted = len(text) - len(head) - len(tail)
    return Shortened(f"{head}\n\n[... {omitted} characters left out ...]\n\n{tail}", omitted)


def weight(text: str) -> int:
    """The characters of `text` against the budget: a run of spaces or tabs counts once."""
    return len(_SPACES.sub(" ", text))


def _reach(text: str, most: int) -> int:
    """The length of the longest beginning of `text` that weighs at most `most`."""
    counted = 0
    after_space = False
    for index, char in enumerate(text):
        space = char in " \t"
        if not (space and after_space):
            counted += 1
            if counted > most:
                return index
        after_space = space
    return len(text)


def _cut_back(part: str) -> str:
    position = part.rfind("\n")
    return part[:position] if position >= len(part) * 4 // 5 else part


def _cut_forward(part: str) -> str:
    position = part.find("\n")
    return part[position + 1 :] if 0 <= position <= len(part) // 5 else part
