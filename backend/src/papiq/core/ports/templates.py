"""Templates of rules and title patterns: Liquid (`{{ contact }}`, `{% if field.x %}`, filters
with `|`).

Templates come from users, rules from any user: a renderer gives a template nothing but the
values passed (no attributes of objects, no other templates, no files) and limits its loops and
its output. First adapter: `python-liquid`.
"""

from collections.abc import Mapping
from typing import Protocol

from papiq.core.domain.templates import TemplateValue


class TemplateRenderer(Protocol):
    def check(self, template: str) -> frozenset[str]:
        """The values the template uses, as paths (`contact`, `field.la_brutto.amount`), not
        those it sets itself. ValidationError, naming line and column, if it is not a valid
        template."""
        ...

    def render(self, template: str, values: Mapping[str, TemplateValue]) -> str:
        """The rendered text. A value that is missing (absent from `values`) can be tested
        (`{% if %}`) and replaced (`| default`); writing it raises MissingValueError naming
        it. ValidationError if the template is invalid or exceeds a limit."""
        ...
