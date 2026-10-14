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
    return LiquidTemplateRenderer("de")


class TestLiquidTemplateRenderer(TemplateRendererContract):
    pass


def test_the_locale_shapes_dates_and_amounts() -> None:
    values: dict[str, TemplateValue] = {
        "day": date(2026, 3, 31),
        "amount": Money(Decimal("3650"), "USD"),
    }
    english = LiquidTemplateRenderer("en_US")
    assert english.render("{{ day | datetime: format: 'MMMM yyyy' }}", values) == "March 2026"
    assert english.render("{{ amount }}", values) == "3,650.00 USD"
    assert LiquidTemplateRenderer("de-AT").render("{{ amount }}", values) == "3.650,00 USD"


def test_an_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError):
        LiquidTemplateRenderer("xx_YY")
