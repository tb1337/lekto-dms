"""The Liquid renderer passes the contract; its locale shapes dates and amounts."""

from datetime import date
from decimal import Decimal

import pytest

from papiq.adapters.outbound.liquid import LiquidTemplateRenderer
from papiq.core.domain.fields import Money
from papiq.core.domain.periods import Period
from papiq.core.domain.templates import TemplateValue
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


def test_an_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError):
        LiquidTemplateRenderer(locale="xx_YY", currency="EUR")
