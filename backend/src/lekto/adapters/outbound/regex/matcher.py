"""Searches run in a worker thread with the GIL released (`concurrent=True`), so a slow pattern
blocks neither the event loop nor other threads until its time limit stops it."""

import asyncio
from functools import lru_cache

import regex

from lekto.core.domain.errors import PatternTimeoutError, ValidationError
from lekto.core.domain.reasons import ReasonCode, because


@lru_cache(maxsize=512)
def _compile(pattern: str, case_sensitive: bool) -> "regex.Pattern[str]":
    flags = regex.VERSION0 if case_sensitive else regex.VERSION0 | regex.IGNORECASE
    try:
        return regex.compile(pattern, flags)
    except regex.error as error:
        raise ValidationError(
            because(ReasonCode.PATTERN_INVALID, pattern=pattern, detail=str(error))
        ) from None


class RegexPatternMatcher:
    def __init__(self, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._timeout = timeout

    def validate(self, pattern: str) -> None:
        _compile(pattern, True)

    async def search(self, pattern: str, text: str, *, case_sensitive: bool) -> bool:
        compiled = _compile(pattern, case_sensitive)
        return await asyncio.to_thread(self._search, compiled, text)

    async def find(
        self, pattern: str, text: str, *, case_sensitive: bool, limit: int
    ) -> tuple[tuple[int, int], ...]:
        compiled = _compile(pattern, case_sensitive)
        return await asyncio.to_thread(self._find, compiled, text, limit)

    def _find(
        self, compiled: "regex.Pattern[str]", text: str, limit: int
    ) -> tuple[tuple[int, int], ...]:
        found: list[tuple[int, int]] = []
        try:
            for match in compiled.finditer(text, concurrent=True, timeout=self._timeout):
                if match.end() > match.start():
                    found.append((match.start(), match.end()))
                if len(found) >= limit:
                    break
        except TimeoutError:
            raise PatternTimeoutError(
                f"pattern {compiled.pattern!r} took longer than {self._timeout} s"
            ) from None
        return tuple(found)

    def _search(self, compiled: "regex.Pattern[str]", text: str) -> bool:
        try:
            return compiled.search(text, concurrent=True, timeout=self._timeout) is not None
        except TimeoutError:
            raise PatternTimeoutError(
                f"pattern {compiled.pattern!r} took longer than {self._timeout} s"
            ) from None
