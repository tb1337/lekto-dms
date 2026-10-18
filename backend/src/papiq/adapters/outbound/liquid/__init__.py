"""Template renderer adapter: Liquid (`python-liquid`), bounded and without access to Python."""

from papiq.adapters.outbound.liquid.renderer import LiquidTemplateRenderer, parse_locale

__all__ = ["LiquidTemplateRenderer", "parse_locale"]
