"""Field definitions (Paperless-ngx: custom fields) and the values they accept."""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import fold_umlauts
from lekto.core.domain.ids import DocumentTypeId, FieldId, new_id
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.master_data import Assignment, MasterData, checked_description
from lekto.core.domain.periods import Period
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.sorting import strip_accents
from lekto.core.domain.validation import require_name

_CURRENCY = re.compile(r"[A-Z]{3}")


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    AMOUNT = "amount"
    DATE = "date"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    LINK = "link"
    PERIOD = "period"


@dataclass(frozen=True)
class Money:
    """An amount with its ISO 4217 currency code, e.g. `Money(Decimal("12.50"), "EUR")`."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValidationError(f"amount must be a finite Decimal, got {self.amount!r}")
        if not isinstance(self.currency, str) or not _CURRENCY.fullmatch(self.currency):
            raise ValidationError(f"currency must be an ISO 4217 code, got {self.currency!r}")


@dataclass(frozen=True)
class Url:
    """An absolute http or https URL."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or any(char.isspace() for char in self.value):
            raise ValidationError(because(ReasonCode.NOT_A_URL, value=self.value))
        try:
            parts = urlsplit(self.value)
            host = parts.hostname
        except ValueError:
            raise ValidationError(because(ReasonCode.NOT_A_URL, value=self.value)) from None
        if parts.scheme not in {"http", "https"} or not host:
            raise ValidationError(because(ReasonCode.URL_NOT_HTTP, value=self.value))


type FieldValue = str | Decimal | Money | date | bool | Url | Period

SORTABLE_TYPES = frozenset({FieldType.DATE, FieldType.PERIOD, FieldType.NUMBER, FieldType.AMOUNT})
"""The types whose values a list sorts by (`sort_value`)."""


def sort_value(value: FieldValue | None) -> date | Decimal | None:
    """What a value sorts by: a date as it is, a period by its first day, a number as it is, an
    amount by its value whatever its currency; None for other types and no value."""
    match value:
        case Money():
            return value.amount
        case Period():
            return value.start
        case bool():
            return None
        case Decimal() | date():
            return value
    return None


@dataclass(kw_only=True)
class FieldDefinition(MasterData):
    """A freely definable field with a fixed data type.

    Scope: `document_type_ids is None` means global (every document); otherwise the field
    applies only to documents of one of the listed types. `choices` is used by CHOICE only.

    A field is required or optional where it applies: a global one as `required` says, a
    typed one for the types in `required_types` (a part of its types). Extraction must find
    a required field; an optional one may stay empty.

    `description` tells the language model what belongs in the field (its name is often an
    internal one no document shows): it goes into the prompts.

    `assignment`: a `manual` field is never asked of the language model; a person or a rule
    sets it. Required, it keeps the document open until a person has set it (issue #52).
    """

    id: FieldId
    data_type: FieldType
    document_type_ids: frozenset[DocumentTypeId] | None = None
    choices: tuple[str, ...] = ()
    required: bool = False
    required_types: frozenset[DocumentTypeId] = frozenset()
    description: str | None = None
    assignment: Assignment = Assignment.AUTO

    def __post_init__(self) -> None:
        super().__post_init__()
        self.required_types = frozenset(self.required_types)
        self.description = checked_description(self.description)
        if self.document_type_ids is None:
            if self.required_types:
                raise ValidationError(because(ReasonCode.FIELD_GLOBAL_REQUIRED))
        else:
            if self.required:
                raise ValidationError(because(ReasonCode.FIELD_TYPED_REQUIRED))
            if not self.required_types <= self.document_type_ids:
                raise ValidationError(because(ReasonCode.FIELD_REQUIRED_OWN_TYPES))
        if self.data_type is FieldType.CHOICE:
            choices = tuple(require_name(choice, "choice") for choice in self.choices)
            if not choices:
                raise ValidationError(because(ReasonCode.CHOICE_NEEDS_CHOICES))
            if len(set(choices)) != len(choices):
                raise ValidationError(because(ReasonCode.CHOICES_NOT_UNIQUE))
            self.choices = choices
        elif self.choices:
            raise ValidationError(because(ReasonCode.ONLY_CHOICE_FIELDS_CHOICES))

    @classmethod
    def create(
        cls,
        *,
        name: str,
        data_type: FieldType,
        now: datetime,
        document_type_ids: Collection[DocumentTypeId] | None = None,
        choices: Collection[str] = (),
        required: bool = False,
        required_types: Collection[DocumentTypeId] = (),
        description: str | None = None,
        assignment: Assignment = Assignment.AUTO,
    ) -> Self:
        return cls(
            id=FieldId(new_id()),
            name=name,
            data_type=data_type,
            document_type_ids=None if document_type_ids is None else frozenset(document_type_ids),
            choices=tuple(choices),
            required=required,
            required_types=frozenset(required_types),
            description=description,
            assignment=assignment,
            created_at=now,
        )

    def describe(self, description: str | None) -> None:
        """What belongs in the field, for the language model; None or empty removes it."""
        self.description = checked_description(description)

    def change_choices(self, choices: Collection[str]) -> frozenset[str]:
        """New choices for a choice field; returns the choices that are gone. Values in
        use are the caller's to check."""
        if self.data_type is not FieldType.CHOICE:
            raise ValidationError(because(ReasonCode.ONLY_CHOICE_FIELDS_CHOICES))
        old = set(self.choices)
        changed = replace(self, choices=tuple(choices))
        self.choices = changed.choices
        return frozenset(old - set(self.choices))

    def change_scope(self, document_type_ids: Collection[DocumentTypeId] | None) -> bool:
        """Global (None) or for these document types; returns whether the scope got narrower
        (then values of documents outside it are the caller's to check)."""
        new = None if document_type_ids is None else frozenset(document_type_ids)
        if new is not None and not new:
            raise ValidationError(because(ReasonCode.FIELD_NEEDS_TYPE))
        old, self.document_type_ids = self.document_type_ids, new
        if new is None:
            self.required_types = frozenset()
        else:
            self.required, self.required_types = False, self.required_types & new
        return new is not None and (old is None or not old <= new)

    def require(
        self, *, required: bool | None = None, types: Collection[DocumentTypeId] | None = None
    ) -> None:
        """Required or optional: `required` while global, `types` the types it is required
        for (of its own); None leaves a part as it is."""
        if required is not None:
            if required and self.document_type_ids is not None:
                raise ValidationError(because(ReasonCode.FIELD_TYPED_REQUIRED))
            self.required = required
        if types is not None:
            types = frozenset(types)
            if types and self.document_type_ids is None:
                raise ValidationError(because(ReasonCode.FIELD_GLOBAL_REQUIRED))
            if not types <= (self.document_type_ids or frozenset()):
                raise ValidationError(because(ReasonCode.FIELD_REQUIRED_OWN_TYPES))
            self.required_types = types

    def is_required_for(self, document_type_id: DocumentTypeId | None) -> bool:
        """Whether extraction must find it in a document of that type (it applies to it)."""
        if self.document_type_ids is None:
            return self.required
        return document_type_id in self.required_types

    @property
    def is_global(self) -> bool:
        return self.document_type_ids is None

    @property
    def is_read(self) -> bool:
        """Whether the language model reads it (not a field set by hand)."""
        return self.assignment is Assignment.AUTO

    @property
    def key(self) -> str:
        """The field in templates: `field.la_brutto` (`template_key` of its name)."""
        return template_key(self.name)

    def applies_to(self, document_type_id: DocumentTypeId | None) -> bool:
        if self.document_type_ids is None:
            return True
        return document_type_id in self.document_type_ids

    def validate(self, value: object) -> FieldValue:
        """Return the value if it fits the data type, else raise ValidationError."""
        match self.data_type:
            case FieldType.TEXT if isinstance(value, str) and value.strip():
                return value
            case FieldType.NUMBER if isinstance(value, Decimal) and value.is_finite():
                return value
            case FieldType.NUMBER if isinstance(value, int) and not isinstance(value, bool):
                return Decimal(value)
            case FieldType.AMOUNT if isinstance(value, Money):
                return value
            case FieldType.DATE if isinstance(value, date) and not isinstance(value, datetime):
                return value
            case FieldType.BOOLEAN if isinstance(value, bool):
                return value
            case FieldType.CHOICE if isinstance(value, str) and value in self.choices:
                return value
            case FieldType.LINK if isinstance(value, Url):
                return value
            case FieldType.PERIOD if isinstance(value, Period):
                return value
        raise self.refusal(value)

    def refusal(self, value: object) -> ValidationError:
        """The error for a value that does not fit (shortened: it may come from anyone)."""
        return ValidationError(
            f"field '{self.name}' ({self.data_type}) does not accept {value!r:.100}"
        )


# --- values as JSON ----------------------------------------------------------------------


def decimal_text(value: Decimal) -> str:
    """A decimal in plain notation (`53350000`, `12.50`), never `5.335E+7`: `str(Decimal)` keeps
    the exponent a value arrived with."""
    return format(value, "f")


def field_to_json(value: FieldValue) -> JsonValue:
    """The JSON form of a value, the one the API, rules and the processing log use: text, choice
    and link as text; number as decimal text; amount as `{amount, currency}`; date as ISO text;
    period as `{start, end}` in ISO text; yes/no as boolean."""
    match value:
        case bool() | str():
            return value
        case Decimal():
            return decimal_text(value)
        case Money():
            return {"amount": decimal_text(value.amount), "currency": value.currency}
        case date():
            return value.isoformat()
        case Url():
            return value.value
        case Period():
            return {"start": value.start.isoformat(), "end": value.end.isoformat()}


def field_from_json(definition: FieldDefinition, data: object) -> FieldValue:
    """The value of `definition` from its JSON form (as `field_to_json` writes it; a number may
    also be a JSON number), checked against the definition. ValidationError if it does not
    fit."""
    value: object = data
    try:
        match definition.data_type:
            case FieldType.NUMBER if _numeric(data):
                value = Decimal(str(data))
            case FieldType.AMOUNT if isinstance(data, dict) and set(data) == _AMOUNT_KEYS:
                if _numeric(data["amount"]):
                    value = Money(Decimal(str(data["amount"])), data["currency"])
            case FieldType.DATE if isinstance(data, str):
                value = date.fromisoformat(data)
            case FieldType.LINK if isinstance(data, str):
                value = Url(data)
            case FieldType.PERIOD if isinstance(data, dict) and set(data) == _PERIOD_KEYS:
                start, end = data["start"], data["end"]
                if isinstance(start, str) and isinstance(end, str):
                    value = Period(date.fromisoformat(start), date.fromisoformat(end))
    except (InvalidOperation, ValueError, ValidationError):
        raise definition.refusal(data) from None
    return definition.validate(value)


_AMOUNT_KEYS = {"amount", "currency"}
_PERIOD_KEYS = {"start", "end"}


def _numeric(value: object) -> bool:
    return isinstance(value, int | float | str) and not isinstance(value, bool)


_NOT_KEY = re.compile(r"[^a-z0-9]+")


def template_key(name: str) -> str:
    """A field's name as templates write it: lower case, umlauts as `ae`, `oe`, `ue`, `ß` as
    `ss`, other accents dropped, anything else an underscore (`LA_Brutto` → `la_brutto`,
    `Fällig am` → `faellig_am`); `f_` before a leading digit."""
    folded = fold_umlauts(unicodedata.normalize("NFKC", name).casefold())
    key = _NOT_KEY.sub("_", strip_accents(folded)).strip("_") or "field"
    return f"f_{key}" if key[0].isdigit() else key
