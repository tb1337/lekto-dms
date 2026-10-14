"""Templates in Liquid (`python-liquid`), for users: no other templates (`include`, `render`
are not tags here), no attributes of Python objects (Liquid looks up keys only), bounded loops
and output.

Values come as the domain has them and are given to Liquid in forms its filters understand: a
number is a float that writes itself as its exact decimal text (Liquid's arithmetic filters
know no `Decimal`), an amount a mapping of `amount` and `currency` that writes itself in the
locale (`3.650,00 EUR`), a date stays a date. The filters `datetime`, `currency` and `decimal`
format in `locale` (Babel); `datetime` takes a date without shifting it into a time zone.
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
from papiq.core.domain.fields import Money
from papiq.core.domain.templates import TemplateValue

DEFAULT_LOCALE = "de"
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
    def __init__(self, locale: str = DEFAULT_LOCALE) -> None:
        try:
            self._locale = str(Locale.parse(locale.replace("-", "_")))
        except UnknownLocaleError:
            raise ValueError(f"unknown locale {locale!r}") from None
        environment = _Environment(undefined=FalsyStrictUndefined)
        for tag in _FORBIDDEN_TAGS:
            del environment.tags[tag]
        environment.filters["datetime"] = _DateTime(self._locale)
        environment.filters["currency"] = Currency(
            default_locale=self._locale, default_currency_code="EUR"
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
        case Mapping():
            return _mapping(value, locale)
        case Sequence():
            return [_value(item, locale) for item in value if item is not None]
    raise TypeError(f"not a template value: {type(value).__name__}")
