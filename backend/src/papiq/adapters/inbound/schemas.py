"""Response bodies that more than one inbound adapter (REST, MCP) returns."""

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from papiq.core.domain.fields import FieldValue, Money, Url
from papiq.core.domain.rule_engine import RuleReport
from papiq.core.domain.rules import RuleScope


class MoneyValue(BaseModel):
    amount: str = Field(examples=["12.50"], description="Decimal number as text, exact.")
    currency: str = Field(examples=["EUR"], description="ISO 4217 code.")


FieldJson = Annotated[
    str | bool | MoneyValue,
    Field(
        description=(
            "By data type: text, choice and link: string; number: decimal as string; date: "
            "`YYYY-MM-DD`; boolean: true/false; amount: `{amount, currency}`."
        )
    ),
]


def decimal_text(value: Decimal) -> str:
    """A decimal in plain notation (`53350000`, `12.50`), never `5.335E+7`: `str(Decimal)` keeps
    the exponent a value arrived with."""
    return format(value, "f")


def field_json(value: FieldValue) -> str | bool | MoneyValue:
    match value:
        case bool() | str():
            return value
        case Money(amount=amount, currency=currency):
            return MoneyValue(amount=decimal_text(amount), currency=currency)
        case Decimal():
            return decimal_text(value)
        case Url(value=url):
            return url
        case _:  # date
            return value.isoformat()


class RuleEffectOut(BaseModel):
    field: str = Field(description="`drawer`, `contact`, `document_type`, `title`, `tags`, ...")
    old: Any
    new: Any


class RuleNoteOut(BaseModel):
    field: str
    kind: Literal["skipped", "overruled", "refused", "conflict", "review", "yielded"] = Field(
        description=(
            "`overruled`: a person decided the field; `refused`: not allowed (rights, scope, "
            "unconfirmed values); `conflict`: rules or values disagree; `skipped`: something "
            "it refers to is gone or does not apply, or a template writes a missing value; "
            "`review`: the rule holds the document for a review; `yielded`: a document type's "
            "title pattern gave way to another rule that sets the title."
        )
    )
    reason: str


class RuleReportOut(BaseModel):
    """What one rule did."""

    rule_id: UUID
    version: int
    name: str
    scope: RuleScope
    applied: list[RuleEffectOut]
    notes: list[RuleNoteOut] = Field(description="Actions that were not applied, and why.")

    @classmethod
    def of(cls, report: RuleReport) -> "RuleReportOut":
        return cls.model_validate(report.to_json())
