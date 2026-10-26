"""Templates of rules, title patterns and webhook bodies: Liquid (`{{ contact }}`,
`{% if field.x %}`, filters with `|`; `json` writes a value as JSON in the API's form, for the
bodies of webhooks).

Templates come from users, rules from any user: a renderer gives a template nothing but the
values passed (no attributes of objects, no other templates, no files) and limits its loops and
its output. First adapter: `python-liquid`.
"""

from collections.abc import Mapping
from typing import Protocol

from lekto.core.domain.fields import Writing
from lekto.core.domain.templates import TemplateValue


class TemplateRenderer(Protocol):
    @property
    def writing(self) -> Writing:
        """How it writes values (the language of its locale, its currency), so that what a
        template rendered for a field can be read back (`fields.read_written`)."""
        ...

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
