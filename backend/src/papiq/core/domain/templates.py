"""The values a template sees: plain data, nested in mappings and lists. A value a document
does not have is left out, not given as None: the template tests it with `{% if %}` or
`| default`, and writing it is a missing value (`MissingValueError`)."""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from papiq.core.domain.fields import Money

type TemplateValue = (
    str
    | int
    | bool
    | Decimal
    | date
    | Money
    | Sequence[TemplateValue]
    | Mapping[str, TemplateValue]
)
