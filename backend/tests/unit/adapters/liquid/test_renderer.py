"""The Liquid renderer passes the contract; its locale shapes dates and amounts."""

import re
from datetime import date
from decimal import Decimal

import pytest

from lekto.adapters.outbound.liquid import LiquidTemplateRenderer, parse_locale
from lekto.core.domain.fields import Money
from lekto.core.domain.periods import Period
from lekto.core.domain.templates import TemplateValue
from tests.contracts.templates import TemplateRendererContract


@pytest.fixture
def template_renderer() -> LiquidTemplateRenderer:
    return LiquidTemplateRenderer(locale="de", currency="EUR")


class TestLiquidTemplateRenderer(TemplateRendererContract):
    pass


def test_the_settings_shape_dates_and_amounts() -> None:
    """`PAPIQ_TEMPLATE_LOCALE` writes dates and amounts, `PAPIQ_DEFAULT_CURRENCY` is that of
    `currency` without one."""
    values: dict[str, TemplateValue] = {
        "day": date(2026, 3, 31),
        "amount": Money(Decimal("3650"), "USD"),
    }
    english = LiquidTemplateRenderer(locale="en_US", currency="USD")
    assert english.render("{{ day | datetime: format: 'MMMM yyyy' }}", values) == "March 2026"
    assert english.render("{{ amount }}", values) == "3,650.00 USD"
    austrian = LiquidTemplateRenderer(locale="de-AT", currency="EUR")
    assert austrian.render("{{ amount }}", values) == "3.650,00 USD"
    assert english.render("{{ amount.amount | currency }}", values) == "$3,650.00"
    assert austrian.render("{{ amount.amount | currency }}", values) == "€\xa03.650,00"


@pytest.mark.parametrize(
    ("period", "written"),
    [
        (Period.month(2026, 9), "2026-09"),
        (Period.week(2026, 38), "2026-W38"),
        (Period.week(2026, 1), "2026-W01"),  # starts on 29 December 2025
        (Period.quarter(2026, 3), "2026-Q3"),
        (Period.year(2025), "2025"),
        (Period.day(date(2026, 9, 15)), "2026-09-15"),
        (Period(date(2026, 9, 1), date(2026, 9, 14)), "2026-09-01/2026-09-14"),
    ],
)
def test_a_period_writes_what_it_is_in_iso_8601(period: Period, written: str) -> None:
    values: dict[str, TemplateValue] = {"period": period}
    german = LiquidTemplateRenderer(locale="de", currency="EUR")
    english = LiquidTemplateRenderer(locale="en_US", currency="USD")
    # In any locale; `datetime` on its ends writes it in words.
    assert german.render("{{ period }}", values) == english.render("{{ period }}", values)
    assert german.render("{{ period }}", values) == written
    # Its ends are dates, for `date` and `datetime`.
    template = "{{ period.start | date: '%Y-%m-%d' }}/{{ period.end | date: '%Y-%m-%d' }}"
    assert german.render(template, values) == str(period)


def test_a_period_in_words_through_its_start() -> None:
    values: dict[str, TemplateValue] = {"period": Period.month(2026, 9)}
    german = LiquidTemplateRenderer(locale="de", currency="EUR")
    assert german.render("{{ period.start | datetime: format: 'MMMM yyyy' }}", values) == (
        "September 2026"
    )


@pytest.mark.parametrize(("text", "locale"), [("de", "de"), ("de-AT", "de_AT"), ("en_us", "en_US")])
def test_a_locale_is_named_as_babel_names_it(text: str, locale: str) -> None:
    assert parse_locale(text) == locale


@pytest.mark.parametrize("text", ["xx_YY", "de DE", ""])
def test_an_unknown_locale_is_refused(text: str) -> None:
    """With one message, whether Babel does not know the locale or cannot read the name."""
    message = re.escape(f"unknown locale {text!r}")
    with pytest.raises(ValueError, match=message):
        parse_locale(text)
    with pytest.raises(ValueError, match=message):
        LiquidTemplateRenderer(locale=text, currency="EUR")
