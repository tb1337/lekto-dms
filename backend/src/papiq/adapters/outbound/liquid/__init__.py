"""Template renderer adapter: Liquid (`python-liquid`), bounded and without access to Python."""

from papiq.adapters.outbound.liquid.renderer import DEFAULT_LOCALE, LiquidTemplateRenderer

__all__ = ["DEFAULT_LOCALE", "LiquidTemplateRenderer"]
