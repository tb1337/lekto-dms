"""The Liquid renderer passes the contract; its locale shapes dates and amounts."""

from datetime import date
from decimal import Decimal

import pytest

from papiq.adapters.outbound.liquid import LiquidTemplateRenderer
from papiq.core.domain.fields import Money
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


def test_an_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError):
        LiquidTemplateRenderer(locale="xx_YY", currency="EUR")
