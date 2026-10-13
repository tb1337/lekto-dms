"""Field definitions (Paperless-ngx: custom fields) and the values they accept."""

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.ids import DocumentTypeId, FieldId, new_id
from papiq.core.domain.master_data import MasterData
from papiq.core.domain.validation import require_name

_CURRENCY = re.compile(r"[A-Z]{3}")


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    AMOUNT = "amount"
    DATE = "date"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    LINK = "link"


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
            raise ValidationError(f"invalid URL {self.value!r}")
        try:
            parts = urlsplit(self.value)
            host = parts.hostname
        except ValueError:
            raise ValidationError(f"invalid URL {self.value!r}") from None
        if parts.scheme not in {"http", "https"} or not host:
            raise ValidationError(f"URL must be absolute http(s), got {self.value!r}")


type FieldValue = str | Decimal | Money | date | bool | Url


@dataclass(kw_only=True)
class FieldDefinition(MasterData):
    """A freely definable field with a fixed data type.

    Scope: `document_type_ids is None` means global (every document); otherwise the field
    applies only to documents of one of the listed types. `choices` is used by CHOICE only.

    A field is required or optional where it applies: a global one as `required` says, a
    typed one for the types in `required_types` (a part of its types). Extraction must find
    a required field; an optional one may stay empty.
    """

    id: FieldId
    data_type: FieldType
    document_type_ids: frozenset[DocumentTypeId] | None = None
    choices: tuple[str, ...] = ()
    required: bool = False
    required_types: frozenset[DocumentTypeId] = frozenset()

    def __post_init__(self) -> None:
        super().__post_init__()
        self.required_types = frozenset(self.required_types)
        if self.document_type_ids is None:
            if self.required_types:
                raise ValidationError("a global field is required by `required`, not per type")
        else:
            if self.required:
                raise ValidationError("a typed field is required per type")
            if not self.required_types <= self.document_type_ids:
                raise ValidationError("a field can only be required for its own types")
        if self.data_type is FieldType.CHOICE:
            choices = tuple(require_name(choice, "choice") for choice in self.choices)
            if not choices:
                raise ValidationError("a choice field needs at least one choice")
            if len(set(choices)) != len(choices):
                raise ValidationError("choices must be unique")
            self.choices = choices
        elif self.choices:
            raise ValidationError("only choice fields have choices")

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
    ) -> Self:
        return cls(
            id=FieldId(new_id()),
            name=name,
            data_type=data_type,
            document_type_ids=None if document_type_ids is None else frozenset(document_type_ids),
            choices=tuple(choices),
            required=required,
            required_types=frozenset(required_types),
            created_at=now,
        )

    def change_choices(self, choices: Collection[str]) -> frozenset[str]:
        """New choices for a choice field; returns the choices that are gone. Values in
        use are the caller's to check."""
        if self.data_type is not FieldType.CHOICE:
            raise ValidationError("only choice fields have choices")
        old = set(self.choices)
        changed = FieldDefinition(**{**self.__dict__, "choices": tuple(choices)})
        self.choices = changed.choices
        return frozenset(old - set(self.choices))

    def change_scope(self, document_type_ids: Collection[DocumentTypeId] | None) -> bool:
        """Global (None) or for these document types; returns whether the scope got narrower
        (then values of documents outside it are the caller's to check)."""
        new = None if document_type_ids is None else frozenset(document_type_ids)
        if new is not None and not new:
            raise ValidationError("give at least one document type, or null for global")
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
                raise ValidationError("a typed field is required per type")
            self.required = required
        if types is not None:
            types = frozenset(types)
            if types and self.document_type_ids is None:
                raise ValidationError("a global field is required by `required`, not per type")
            if not types <= (self.document_type_ids or frozenset()):
                raise ValidationError("a field can only be required for its own types")
            self.required_types = types

    def is_required_for(self, document_type_id: DocumentTypeId | None) -> bool:
        """Whether extraction must find it in a document of that type (it applies to it)."""
        if self.document_type_ids is None:
            return self.required
        return document_type_id in self.required_types

    @property
    def is_global(self) -> bool:
        return self.document_type_ids is None

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
        raise ValidationError(f"field '{self.name}' ({self.data_type}) does not accept {value!r}")
