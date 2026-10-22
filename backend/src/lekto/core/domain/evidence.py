"""Finding values in a document's text: the facts behind a classification's confidence.

A value counts as found only if the text shows it, in one of the usual ways of writing it:
dates in German, English and ISO notation, periods (a month, a calendar week, a quarter, a
year, a span of dates), numbers with German or English separators, currencies as code, symbol
or word. Everything works on a normalised text (see `normalise`).
"""

import html
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cached_property
from itertools import pairwise

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.periods import MONTH_NAMES, Period

# Markdown markup that may sit inside a value (`**84,20 €**`, table pipes).
_MARKUP = re.compile(r"[*_#|`>~]+")
# A word broken at the end of a line: `Rech-\nnung`.
_HYPHENATION = re.compile(r"(?<=[^\W\d_])-[ \t]*\n[ \t]*(?=[^\W\d_])")
_WHITESPACE = re.compile(r"\s+")
UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue"}
"""Umlauts (case folded) and how they are written without them."""
_UMLAUTS = str.maketrans(UMLAUTS)


def normalise(text: str) -> str:
    """HTML entities as characters (texts parsed before 0.2.0 have `&amp;` and `&#124;`),
    compatibility forms unified (NFKC), lower case (case folding, so `ß` is `ss`),
    hyphenation at line ends and Markdown markup removed, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", html.unescape(text)).replace("­", "")
    text = _HYPHENATION.sub("", text)
    text = _MARKUP.sub(" ", text)
    return _WHITESPACE.sub(" ", text.casefold()).strip()


def without_markup(text: str) -> str:
    """Markdown markup removed and whitespace collapsed; case kept."""
    return _WHITESPACE.sub(" ", _MARKUP.sub(" ", text)).strip()


def fold_umlauts(text: str) -> str:
    """`ä` as `ae` and so on, for names written either way; expects normalised text."""
    return text.translate(_UMLAUTS)


# --- dates ------------------------------------------------------------------------------------

# Other ways to write the months than their names: Austrian, without umlauts, abbreviated.
_OTHER_SPELLINGS = (
    ("jänner", "jaenner", "jan"),
    ("feb",),
    ("maerz", "mär", "mrz", "mar"),
    ("apr",),
    (),
    ("jun",),
    ("jul",),
    ("aug",),
    ("sept", "sep"),
    ("okt", "oct"),
    ("nov",),
    ("dez", "dec"),
)
_MONTHS = {
    **{
        name.casefold(): number
        for names in MONTH_NAMES.values()
        for number, name in enumerate(names, 1)
    },
    **{
        spelling: number
        for number, spellings in enumerate(_OTHER_SPELLINGS, 1)
        for spelling in spellings
    },
}
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th|\.)?"
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, str, str]], ...] = (
    # 31.03.2026, 31.3.26, 31/03/2026, 31-03-2026
    (re.compile(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?![\d])"), ("d", "m", "y")),
    # 2026-03-31, 2026/03/31
    (re.compile(r"(?<![\d.])(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?![\d])"), ("y", "m", "d")),
    # 31. März 2026, 31 Mar. 2026, 31st March 2026
    (re.compile(rf"(?<!\d){_DAY}\s*{_MONTH}\s*(\d{{4}})(?!\d)"), ("d", "m", "y")),
    # March 31, 2026; Mar 31st 2026
    (re.compile(rf"\b{_MONTH}\s*{_DAY},?\s*(\d{{4}})(?!\d)"), ("m", "d", "y")),
)


def dates_in(text: str) -> set[date]:
    """All dates written in the normalised `text`. A two-digit year gives both its readings
    (`12.03.24`: 1924 and 2024): a date is compared, not guessed (`_years`)."""
    return {day for _, _, days in _dated(text) for day in days}


def _dated(text: str) -> Iterator[tuple[int, int, tuple[date, ...]]]:
    """The dates of `dates_in` with where they stand in `text`, each place with its readings."""
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            parts = dict(zip(order, match.groups(), strict=True))
            month = int(parts["m"]) if parts["m"].isdigit() else _MONTHS[parts["m"]]
            days = tuple(_days(_years(parts["y"]), month, int(parts["d"])))
            if days:
                yield match.start(), match.end(), days


def _days(years: tuple[int, ...], month: int, day: int) -> Iterator[date]:
    for year in years:
        try:
            yield date(year, month, day)
        except ValueError:
            continue


def _years(text: str) -> tuple[int, ...]:
    """The years `text` may mean: two digits mean either century. No fixed year divides them
    (Tobi, 22.10.2026: ISO 8601 writes four digits; where a choice is needed, the reading
    nearest to when the document came in counts, `nearest`)."""
    year = int(text)
    return (1900 + year, 2000 + year) if len(text) == 2 else (year,)


def nearest(days: Iterable[date], received: date) -> date:
    """Of the readings of one written date, the one nearest to `received`, the day the
    document came in (of two as near, the later)."""
    return min(days, key=lambda day: (abs((day - received).days), -day.toordinal()))


# --- periods ------------------------------------------------------------------------------------

# Between the ends of a span: `01.09.2026 - 30.09.2026`, `1. bis 30. September 2026`.
_TO = r"\s*(?:-|\u2013|\u2014|bis(?: zum| einschl(?:ießlich|\.)?)?|to|until|through)\s*"
_YEAR = r"((?:19|20)\d{2})"
_WEEK_WORD = r"(?:kw|kalenderwoche|calendar week|week|wk)\.?"
# A month, week or quarter with its year, or without one (`für September`, `KW 38`).
_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # September 2026, Sept. 2026, september, 2026
    (re.compile(rf"(?<![\d.]\s)(?<![\d.]){_MONTH}(?:,?\s*{_YEAR})?(?![\d])"), "month name"),
    # 09/2026, 9.2026 (not inside a date: 01.09.2026)
    (re.compile(rf"(?<![\d./-])(\d{{1,2}})[./]{_YEAR}(?![\d./])"), "month number"),
    # 2026-09 (not a date: 2026-09-30)
    (re.compile(rf"(?<![\d./-]){_YEAR}-(\d{{1,2}})(?![\d]|[-/]\d)"), "iso month"),
    # KW 38/2026, KW 38 2026, Kalenderwoche 38, week 38, 2026
    (re.compile(rf"\b{_WEEK_WORD}\s*(\d{{1,2}})(?:\s*[/,]?\s*{_YEAR})?(?![\d])"), "week"),
    # 38. KW 2026
    (re.compile(rf"(?<![\d.])(\d{{1,2}})\.\s*{_WEEK_WORD}(?:\s*[/,]?\s*{_YEAR})?(?![\d])"), "week"),
    # Q3 2026, Q3/2026, 3. Quartal 2026, quarter 3 2026
    (re.compile(rf"\bq([1-4])(?:\s*[/ ]?\s*{_YEAR})?(?![\d])"), "quarter"),
    (re.compile(rf"(?<![\d.])([1-4])\.\s*quartal(?:\s*{_YEAR})?(?![\d])"), "quarter"),
    (re.compile(rf"\b(?:quarter|quartal)\s*([1-4])(?:\s*[/,]?\s*{_YEAR})?(?![\d])"), "quarter"),
    # a year on its own: Lohnsteuerbescheinigung 2025 (not inside a date or a number)
    (re.compile(rf"(?<![\d.,/-]){_YEAR}(?![\d]|[.,/-]\d)"), "year"),
)
# Spans whose start leaves out what the end gives: `01.09.-30.09.2026`, `1.-30.09.2026`,
# `1. bis 30. September 2026`.
_SPAN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"(?<![\d.])(\d{{1,2}})\.(\d{{1,2}})\.?{_TO}(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}}|\d{{2}})(?!\d)"
    ),
    re.compile(rf"(?<![\d.])(\d{{1,2}})\.?{_TO}(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}}|\d{{2}})(?!\d)"),
    re.compile(rf"(?<![\d.])(\d{{1,2}})\.?{_TO}(\d{{1,2}})\.?\s*{_MONTH}\s*(\d{{4}})(?!\d)"),
)
_GAP = re.compile(_TO)


@dataclass(frozen=True)
class _Found:
    """A period written in a text, where it stands, and whether its year was assumed."""

    start: int
    end: int
    period: Period
    yearless: bool = False

    @property
    def length(self) -> int:
        return self.end - self.start


def _periods(text: str, reference: date | None = None) -> list[_Found]:
    """The periods written in the normalised `text`: spans of dates, months, calendar weeks,
    quarters, years, single dates as days. One without a year takes that of `reference` (the
    year before if it would lie after it); without `reference` it is left out."""
    found: list[_Found] = []
    dates = sorted(_dated(text))
    for start, end, days in dates:
        found.extend(_Found(start, end, Period.day(day)) for day in days)
    for first, second in pairwise(dates):
        if not _GAP.fullmatch(text[first[1] : second[0]]):
            continue
        # The readings of two-digit years never span a century: `01.12.24 - 31.01.25` is
        # 1924 to 1925 or 2024 to 2025, not 1924 to 2025.
        ambiguous = len(first[2]) > 1 or len(second[2]) > 1
        found.extend(
            _Found(first[0], second[1], Period(start_day, end_day))
            for start_day in first[2]
            for end_day in second[2]
            if start_day <= end_day and not (ambiguous and end_day.year - start_day.year >= 100)
        )
    for pattern in _SPAN_PATTERNS:
        for match in pattern.finditer(text):
            found.extend(
                _Found(match.start(), match.end(), span) for span in _spans(match.groups())
            )
    for pattern, kind in _PERIOD_PATTERNS:
        for match in pattern.finditer(text):
            item = _period(kind, match.groups(), reference)
            if item is not None:
                found.append(_Found(match.start(), match.end(), *item))
    return found


def _spans(groups: tuple[str | None, ...]) -> list[Period]:
    """A span from `_SPAN_PATTERNS`, in each reading of its year: the start takes the month and
    year of the end it leaves out."""
    parts = [part for part in groups if part is not None]
    if len(parts) == 5:  # d.m. - d.m.y
        day, month, end_day, end_month, year = parts
    elif parts[-2].isdigit():  # d. - d.m.y
        day, end_day, end_month, year = parts
        month = end_month
    elif parts[-2] in _MONTHS:  # d. - d. month y
        day, end_day, name, year = parts
        month = end_month = str(_MONTHS[name])
    else:
        return []
    spans = []
    for reading in _years(year):
        try:
            spans.append(
                Period(
                    date(reading, int(month), int(day)),
                    date(reading, int(end_month), int(end_day)),
                )
            )
        except (ValueError, ValidationError):
            continue
    return spans


def _period(
    kind: str, groups: tuple[str | None, ...], reference: date | None
) -> tuple[Period, bool] | None:
    try:
        match kind:
            case "month name":
                name, year = groups
                return _dated_by(lambda y: Period.month(y, _MONTHS[str(name)]), year, reference)
            case "month number":
                month, year = groups
                return Period.month(int(str(year)), int(str(month))), False
            case "iso month":
                year, month = groups
                return Period.month(int(str(year)), int(str(month))), False
            case "week":
                week, year = groups
                return _dated_by(lambda y: Period.week(y, int(str(week))), year, reference)
            case "quarter":
                quarter, year = groups
                return _dated_by(lambda y: Period.quarter(y, int(str(quarter))), year, reference)
            case "year":
                (year,) = groups
                return Period.year(int(str(year))), False
    except (ValueError, ValidationError, KeyError):
        return None
    return None


def _dated_by(
    make: Callable[[int], Period], year: str | None, reference: date | None
) -> tuple[Period, bool] | None:
    """The period of `year`; without one, that of `reference`'s year, or the year before if
    it would start after `reference`."""
    if year is not None:
        return make(int(year)), False
    if reference is None:
        return None
    period = make(reference.year)
    if period.start > reference:
        period = make(reference.year - 1)
    return period, True


def periods_in(text: str) -> set[Period]:
    """All periods written in the normalised `text`, each with its year."""
    return {item.period for item in _periods(text) if not item.yearless}


def read_period(
    raw: str, reference: date | None = None, *, received: date | None = None
) -> tuple[Period, bool] | None:
    """The period `raw` writes (`September 2026`, `KW 38/2026`, `Q3 2026`, `2025`,
    `01.09.-30.09.2026`, `1. bis 30. September 2026`, one date as that day), and whether its
    year was assumed: a month, week or quarter without one takes the year of `reference` (the
    document date). Readings inside another one do not count (the days of a span, the year of
    a month); None if there is none, or more than one is left. A two-digit year
    (`01.09.-30.09.26`) leaves its two readings at one place: of those, the one nearest to
    `received` (the day the document came in) counts; without `received`, none."""
    found = _periods(normalise(raw), reference)
    outer = [
        item
        for item in found
        if not any(
            other is not item
            and other.start <= item.start
            and item.end <= other.end
            and other.length > item.length
            for other in found
        )
    ]
    readings = {(item.period, item.yearless) for item in outer}
    if len(readings) == 1:
        return next(iter(readings))
    if readings and received is not None and len({(item.start, item.end) for item in outer}) == 1:
        start = nearest((period.start for period, _ in readings), received)
        return next(reading for reading in readings if reading[0].start == start)
    return None


# --- numbers ----------------------------------------------------------------------------------

# Digits with separators between them: `1.234,56`, `1,234.56`, `1 234,56`, `1'234.56`, `84,20`.
_TRUTH = {"true": True, "yes": True, "ja": True, "false": False, "no": False, "nein": False}


def truth_value(text: str) -> bool | None:
    """Yes or no as a document or a model writes it (German, English); None for other text."""
    return _TRUTH.get(text.strip().casefold())


_NUMBER = re.compile(r"(?<![\d])\d(?:[\d]|[.,'](?=\d)| (?=\d{3}(?!\d)))*")


def numbers_in(text: str) -> set[Decimal]:
    """All numbers written in the normalised `text`, as absolute values. An ambiguous
    notation (`1.234`: thousand or one point two three four) yields both readings."""
    found: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        found.update(_readings(match.group()))
    return found


def _readings(token: str) -> set[Decimal]:
    readings: set[Decimal] = set()
    for decimal_mark, groups in ((",", ".' "), (".", ",' ")):
        number = _reading(token, decimal_mark, groups)
        if number is not None:
            readings.add(number)
    # Any prefix that ends before a space may be a number of its own (`Seite 1 234`).
    if " " in token:
        for part in token.split(" "):
            readings.update(_readings(part))
    return readings


def _reading(token: str, decimal_mark: str, groups: str) -> Decimal | None:
    """`token` read with `decimal_mark` and thousands grouped by one of `groups`; None if it
    does not fit that notation."""
    whole, mark, fraction = token.rpartition(decimal_mark)
    if not mark:
        whole = fraction
    elif decimal_mark in whole or not fraction.isdigit():
        return None
    parts = re.split(f"[{re.escape(groups)}]", whole)
    if len(parts) > 1:
        if not 1 <= len(parts[0]) <= 3 or any(len(part) != 3 for part in parts[1:]):
            return None
        if len({separator for separator in whole if separator in groups}) > 1:
            return None
    if not all(part.isdigit() for part in parts):
        return None
    try:
        return Decimal("".join(parts) + ("." + fraction if mark else ""))
    except InvalidOperation:
        return None


def amounts_in(text: str) -> set[Decimal]:
    """The numbers the normalised `text` writes as amounts: with two decimal places
    (`620,00`, `1,234.56`), or with a currency or a dash beside them (`620 €`, `eur 620`,
    `620,-`). A bare number (`620`) is none: on a scan it may be any fragment."""
    found: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        readings = _readings(match.group())
        if _beside_currency(text, match.start(), match.end()):
            found.update(readings)
        else:
            found.update(number for number in readings if number.as_tuple().exponent == -2)
    return found


_BEFORE = re.compile(r"(?:[^\W\d_]+\.?|[€$£¥]) ?$")
_AFTER = re.compile(r" ?(?:[^\W\d_]+\.?|[€$£¥])")
_DASH_AFTER = re.compile(r"[.,][-\u2013]")


def _beside_currency(text: str, start: int, end: int) -> bool:
    if _DASH_AFTER.match(text, end):
        return True
    before = _BEFORE.search(text[max(0, start - 12) : start])
    after = _AFTER.match(text, end)
    return any(
        currencies_in(found.group().strip()) for found in (before, after) if found is not None
    )


# --- currencies -------------------------------------------------------------------------------

_CURRENCY_SIGNS = {
    "€": {"EUR"},
    "euro": {"EUR"},
    "euros": {"EUR"},
    "$": {"USD"},
    "us$": {"USD"},
    "dollar": {"USD"},
    "dollars": {"USD"},
    "£": {"GBP"},
    "pfund": {"GBP"},
    "¥": {"JPY", "CNY"},
    "fr.": {"CHF"},
    "sfr.": {"CHF"},
    "sfr": {"CHF"},
    "franken": {"CHF"},
    "kč": {"CZK"},
    "zł": {"PLN"},
    "kr": {"SEK", "NOK", "DKK"},
    "kr.": {"SEK", "NOK", "DKK"},
}
# Active ISO 4217 codes; other three-letter words (BIS, DEN, SIE) are no currency.
_ISO_4217_CODES = """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL
    BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP
    ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR
    IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL
    LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
    NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD
    SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX
    USD UYU UZS VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG
"""
_ISO_4217 = frozenset(_ISO_4217_CODES.split())
_WORD = re.compile(r"[^\W\d_]+\.?|[€$£¥]")


def currencies_in(text: str) -> set[str]:
    """ISO 4217 codes the normalised `text` shows: as code (`EUR`), sign (`€`) or word
    (`Euro`)."""
    found: set[str] = set()
    for match in _WORD.finditer(text):
        word = match.group()
        found.update(_CURRENCY_SIGNS.get(word, ()))
        bare = word.rstrip(".")
        found.update(_CURRENCY_SIGNS.get(bare, ()))
        if bare.upper() in _ISO_4217:
            found.add(bare.upper())
    if "us$" in text:
        found.add("USD")
    return found


# --- values as a person or a model writes them ------------------------------------------------

_SIGNS = "-\u2212\u2013"  # hyphen-minus, minus sign, en dash
# A minus standing on its own before or after the number (`-12,50`, `€ -5`, `12,50-`), not
# joined to a word (`R-2026`).
_SIGN_BEFORE = re.compile(rf"(?:^|[\s(:€$£¥])[{_SIGNS}]\s*$")
_SIGN_AFTER = re.compile(rf"\s*[{_SIGNS}](?:$|[\s)€$£¥])")


def read_number(
    raw: str, facts: "DocumentText | None" = None, *, language: str | None = None
) -> Decimal | None:
    """The one number in `raw`, as written: `2.111,68`, `1,234.56`, `84,20`, `-12,50`,
    `12,50-`, `1 234`. None unless `raw` holds exactly one. An ambiguous notation (`1.234`) is
    read the way `facts` shows it; where the text shows both readings (or no text is given),
    the German one, unless `language` is English."""
    text = normalise(raw)
    tokens = list(_NUMBER.finditer(text))
    if len(tokens) != 1:
        return None
    token = tokens[0]
    german = _reading(token.group(), ",", ".' ")
    english = _reading(token.group(), ".", ",' ")
    if german is None or english is None or german == english:
        number = german if german is not None else english
        if number is None:
            return None
    elif facts is not None and facts.has_number(german) != facts.has_number(english):
        number = german if facts.has_number(german) else english
    else:
        number = english if language == "en" else german
    if _SIGN_BEFORE.search(text[: token.start()]) or _SIGN_AFTER.match(text[token.end() :]):
        number = -number
    return number


def read_date(
    raw: str, facts: "DocumentText | None" = None, *, received: date | None = None
) -> date | None:
    """The one date in `raw`, in any notation `dates_in` reads (`2026-03-12`, `12.03.2026`,
    `12. März 2026`). Of several, the one `facts` shows, if it is just one; else None. A
    two-digit year (`12.03.24`) is one date with two readings: the one `facts` shows, else
    the one nearest to `received` (the day the document came in); without `received`, none."""
    places = [days for _, _, days in _dated(normalise(raw))]
    found = {day for days in places for day in days}
    if len(found) > 1 and facts is not None:
        found = {value for value in found if facts.has_date(value)} or found
    if len(found) == 1:
        return next(iter(found))
    if found and received is not None and len(places) == 1:
        return nearest(found, received)
    return None


def read_amount(
    raw: str,
    facts: "DocumentText | None" = None,
    *,
    language: str | None = None,
    default: str | None = None,
) -> tuple[Decimal, str] | None:
    """The amount and its currency (ISO 4217) in `raw`, read as `read_number` does: `2.111,68
    EUR`, `€ 84,20`. Without a currency in `raw` (or with one standing for several, `kr`),
    the one currency `facts` shows, or `default` where the text shows none (a pay slip prints
    bare numbers); None if that does not settle it."""
    number = read_number(raw, facts, language=language)
    if number is None:
        return None
    codes = currencies_in(normalise(raw))
    if len(codes) != 1 and facts is not None:
        narrowed = codes & facts.currencies if codes else facts.currencies
        if len(narrowed) == 1:
            codes = narrowed
    if not codes and default is not None and (facts is None or not facts.currencies):
        codes = {default}
    if len(codes) != 1:
        return None
    return number, next(iter(codes))


# --- text -------------------------------------------------------------------------------------

_SHORTEST_SPACELESS = 8  # characters; shorter values compared without spaces match too easily


def contains(text: str, value: str) -> bool:
    """Whether the normalised `text` contains `value` (normalised here) as whole words: as is,
    with umlauts written as `ae`/`oe`/`ue`, or, for longer values, ignoring spaces (an IBAN in
    groups). `Z-3` is not in `Z-3141`."""
    needle = normalise(value)
    if not needle:
        return False
    if _whole(needle, text) or _whole(fold_umlauts(needle), fold_umlauts(text)):
        return True
    spaceless = needle.replace(" ", "")
    return len(spaceless) >= _SHORTEST_SPACELESS and spaceless in text.replace(" ", "")


def _whole(needle: str, text: str) -> bool:
    """`needle` occurs in `text` as whole words: not next to a letter or digit, nor joined to
    one by `-`, `.`, `/` or `,` (`R-2026` is not in `R-2026-0815`, `31` not in `31.03.2026`)."""
    pattern = r"(?<![^\W_])(?<![^\W_][-./,])" + re.escape(needle) + r"(?![^\W_])(?![-./,][^\W_])"
    return re.search(pattern, text) is not None


@dataclass(frozen=True)
class DocumentText:
    """A document's text with what has been found in it, computed once."""

    raw: str

    @classmethod
    def read(cls, raw: str) -> "DocumentText":
        """The text with everything in it found at once: for a worker thread, so that the
        event loop does not wait for long texts."""
        text = cls(raw)
        for name, member in vars(cls).items():
            if isinstance(member, cached_property):
                getattr(text, name)
        return text

    @cached_property
    def normalised(self) -> str:
        return normalise(self.raw)

    @cached_property
    def dates(self) -> set[date]:
        return dates_in(self.normalised)

    @cached_property
    def periods(self) -> set[Period]:
        return periods_in(self.normalised)

    @cached_property
    def numbers(self) -> set[Decimal]:
        return numbers_in(self.normalised)

    @cached_property
    def amounts(self) -> set[Decimal]:
        return amounts_in(self.normalised)

    @cached_property
    def currencies(self) -> set[str]:
        return currencies_in(self.normalised)

    def contains(self, value: str) -> bool:
        return contains(self.normalised, value)

    def has_date(self, value: date) -> bool:
        return value in self.dates

    def has_period(self, value: Period, reference: date | None = None) -> bool:
        """Whether the text writes the period (`September 2026`, `01.09.-30.09.2026`; with
        `reference`, also without its year), or shows its first and last day as dates."""
        if value in self.periods or (self.has_date(value.start) and self.has_date(value.end)):
            return True
        return reference is not None and any(
            item.period == value for item in _periods(self.normalised, reference)
        )

    def has_number(self, value: Decimal) -> bool:
        return abs(value) in self.numbers

    def has_amount(self, value: Decimal) -> bool:
        """Whether the text writes `value` as an amount (`amounts_in`), not only as a
        number."""
        return abs(value) in self.amounts

    def has_currency(self, code: str) -> bool:
        return code in self.currencies
