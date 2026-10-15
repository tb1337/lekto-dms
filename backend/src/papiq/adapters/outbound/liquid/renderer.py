"""Templates in Liquid (`python-liquid`), for users: no other templates (`include`, `render`
are not tags here), no attributes of Python objects (Liquid looks up keys only), bounded loops
and output.

Values come as the domain has them and are given to Liquid in forms its filters understand: a
number is a float that writes itself as its exact decimal text (Liquid's arithmetic filters
know no `Decimal`), an amount a mapping of `amount` and `currency` that writes itself in the
locale (`3.650,00 EUR` in `de`), a date stays a date. The filters `datetime`, `currency` and
`decimal` format in the locale (Babel); `datetime` takes a date without shifting it into a time
zone.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from babel import Locale, UnknownLocaleError
from babel.dates import format_date
from babel.numbers import format_currency
from liquid import BoundTemplate, Environment, FalsyStrictUndefined
from liquid.exceptions import LiquidError, UndefinedError
from liquid.extra import Currency, DateTime, Number

from papiq.core.domain.errors import MissingValueError, ValidationError
from papiq.core.domain.fields import Money, Period, PeriodKind
from papiq.core.domain.templates import TemplateValue

_UNDEFINED = re.compile(r"^'?(?P<path>.+?)'? is undefined$")
_LOCATION = re.compile(r"' (?P<line>\d+):(?P<column>\d+)\n")
_FORBIDDEN_TAGS = ("include", "render")


class _Environment(Environment):
    context_depth_limit = 10
    local_namespace_limit = 10_000
    loop_iteration_limit = 1_000
    output_stream_limit = 10_000


class _DateTime(DateTime):
    """Babel's `datetime`, with a date as a date (Liquid's would make it midnight, UTC)."""

    def __init__(self, locale: str) -> None:
        super().__init__(default_locale=locale, default_timezone="UTC")
        self._locale = locale

    def __call__(self, left: object, *args: Any, **kwargs: Any) -> str:
        if isinstance(left, date) and not isinstance(left, datetime):
            format = str(kwargs.get("format") or "medium")
            return format_date(left, format=format, locale=self._locale)
        return str(super().__call__(left, *args, **kwargs))


class LiquidTemplateRenderer:
    def __init__(self, *, locale: str, currency: str) -> None:
        """`locale` writes dates and amounts (`PAPIQ_TEMPLATE_LOCALE`); `currency` is that
        of the `currency` filter where a template names none (`PAPIQ_DEFAULT_CURRENCY`)."""
        try:
            self._locale = str(Locale.parse(locale.replace("-", "_")))
        except UnknownLocaleError:
            raise ValueError(f"unknown locale {locale!r}") from None
        environment = _Environment(undefined=FalsyStrictUndefined)
        for tag in _FORBIDDEN_TAGS:
            del environment.tags[tag]
        environment.filters["datetime"] = _DateTime(self._locale)
        environment.filters["currency"] = Currency(
            default_locale=self._locale, default_currency_code=currency
        )
        environment.filters["decimal"] = Number(default_locale=self._locale)
        self._environment = environment
        self._parse = lru_cache(maxsize=512)(self._parsed)

    def check(self, template: str) -> frozenset[str]:
        parsed = self._parse(template)
        unknown = sorted(set(parsed.filter_names()) - set(self._environment.filters))
        if unknown:
            raise ValidationError(f"invalid template: unknown filter {unknown[0]!r}")
        return frozenset(parsed.global_variable_paths())

    def render(self, template: str, values: Mapping[str, TemplateValue]) -> str:
        parsed = self._parse(template)
        try:
            return parsed.render(**_mapping(values, self._locale))
        except UndefinedError as error:
            found = _UNDEFINED.match(str(error.message or ""))
            raise MissingValueError(found.group("path") if found else "a value") from None
        except LiquidError as error:
            raise _invalid(error) from None

    def _parsed(self, template: str) -> BoundTemplate:
        try:
            return self._environment.parse(template)
        except LiquidError as error:
            raise _invalid(error) from None


def _invalid(error: LiquidError) -> ValidationError:
    found = _LOCATION.search(error.detailed_message())
    where = f" (line {found.group('line')}, column {found.group('column')})" if found else ""
    return ValidationError(f"invalid template: {error.message}{where}")


class _Number(float):
    """A number for Liquid's filters that writes itself as its exact decimal text."""

    _text: str

    def __new__(cls, value: Decimal) -> "_Number":
        number = super().__new__(cls, value)
        number._text = format(value, "f")
        return number

    def __str__(self) -> str:
        return self._text

    __repr__ = __str__


class _Amount(Mapping[str, object]):
    """An amount: `amount` and `currency`, written as `3.650,00 EUR` in the locale."""

    def __init__(self, money: Money, locale: str) -> None:
        self._values: dict[str, object] = {
            "amount": _Number(money.amount),
            "currency": money.currency,
        }
        self._text = format_currency(
            money.amount, money.currency, "#,##0.00 ¤¤", locale=locale, currency_digits=True
        )

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __str__(self) -> str:
        return self._text


class _Period(Mapping[str, object]):
    """A period: `start` and `end` (dates for `date` and `datetime`), written by what it is in
    the locale: `September 2026`, `KW 38 2026`, `Q3 2026`, `2026`, a day as a date, else its
    ends joined by an en dash (`01.09.2026` to `14.09.2026`)."""

    def __init__(self, period: Period, locale: str) -> None:
        self._values: dict[str, object] = {"start": period.start, "end": period.end}
        self._text = _period_text(period, locale)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __str__(self) -> str:
        return self._text


_WEEK = {"de": "KW {week} {year}"}  # else `week 38 2026`


def _period_text(period: Period, locale: str) -> str:
    start, end = period.start, period.end
    match period.kind:
        case PeriodKind.DAY:
            return format_date(start, "medium", locale=locale)
        case PeriodKind.WEEK:
            year, week, _ = start.isocalendar()
            words = _WEEK.get(Locale.parse(locale).language, "week {week} {year}")
            return words.format(week=week, year=year)
        case PeriodKind.MONTH:
            return format_date(start, "LLLL yyyy", locale=locale)
        case PeriodKind.QUARTER:
            return format_date(start, "QQQ yyyy", locale=locale)
        case PeriodKind.YEAR:
            return format_date(start, "yyyy", locale=locale)
    first, last = (format_date(day, "medium", locale=locale) for day in (start, end))
    return f"{first}\u2013{last}"


def _mapping(values: Mapping[str, TemplateValue], locale: str) -> dict[str, object]:
    return {key: _value(value, locale) for key, value in values.items() if value is not None}


def _value(value: TemplateValue, locale: str) -> object:
    match value:
        case bool() | str() | int() | date():
            return value
        case Decimal():
            return _Number(value)
        case Money():
            return _Amount(value, locale)
        case Period():
            return _Period(value, locale)
        case Mapping():
            return _mapping(value, locale)
        case Sequence():
            return [_value(item, locale) for item in value if item is not None]
    raise TypeError(f"not a template value: {type(value).__name__}")
