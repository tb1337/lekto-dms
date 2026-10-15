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
    ("period", "german", "english"),
    [
        (Period.month(2026, 9), "September 2026", "September 2026"),
        (Period.week(2026, 38), "KW 38 2026", "week 38 2026"),
        (Period.quarter(2026, 3), "Q3 2026", "Q3 2026"),
        (Period.year(2025), "2025", "2025"),
        (Period.day(date(2026, 9, 15)), "15.09.2026", "Sep 15, 2026"),
        (
            Period(date(2026, 9, 1), date(2026, 9, 14)),
            "01.09.2026\u201314.09.2026",
            "Sep 1, 2026\u2013Sep 14, 2026",
        ),
    ],
)
def test_a_period_writes_what_it_is(period: Period, german: str, english: str) -> None:
    values: dict[str, TemplateValue] = {"period": period}
    german_renderer = LiquidTemplateRenderer(locale="de", currency="EUR")
    assert german_renderer.render("{{ period }}", values) == german
    assert (
        LiquidTemplateRenderer(locale="en_US", currency="USD").render("{{ period }}", values)
        == english
    )
    # Its ends are dates, for `date` and `datetime`.
    template = "{{ period.start | date: '%Y-%m-%d' }}/{{ period.end | date: '%Y-%m-%d' }}"
    assert german_renderer.render(template, values) == str(period)


def test_an_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError):
        LiquidTemplateRenderer(locale="xx_YY", currency="EUR")
