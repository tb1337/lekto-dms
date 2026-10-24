"""Metadata that comes with a document taken over from another system (channel `migration`)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from dataclasses import field as dataclass_field
from datetime import date, datetime
from uuid import UUID

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    TAGS,
    TITLE,
    TOPIC,
    field_id_of,
)
from lekto.core.domain.documents import UNSET, DocumentChanges
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition, FieldValue, field_from_json, field_to_json
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId
from lekto.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_list,
    as_object,
    as_text,
    require_date,
    require_object,
    require_uuid,
)
from lekto.core.domain.reasons import Reason, ReasonCode, written
from lekto.core.domain.validation import require_utc

IMPORTED = "imported"
"""Key of the receive log entry's output that holds the metadata, and the `model_version` of
the nodes that applied it."""

MAX_REVIEWS = 50
MAX_REVIEW_REASON = 500  # characters
REVIEWABLE: frozenset[str] = frozenset({CONTACT, DOCUMENT_TYPE, TOPIC, TAGS, DOCUMENT_DATE, TITLE})
"""The fields of the judge a review can name; a custom field is named `field:<id>`."""
PAPERLESS_REVIEWS: frozenset[ReasonCode] = frozenset(
    {
        ReasonCode.PAPERLESS_USER_REVIEW,
        ReasonCode.PAPERLESS_CORRESPONDENT_REVIEW,
        ReasonCode.PAPERLESS_DOCUMENT_TYPE_REVIEW,
        ReasonCode.PAPERLESS_TAG_REVIEW,
        ReasonCode.PAPERLESS_CUSTOM_FIELD_REVIEW,
        ReasonCode.PAPERLESS_STORAGE_PATH_REVIEW,
        ReasonCode.PAPERLESS_ASN_REVIEW,
    }
)
"""The codes a migration may give its own reasons: a Paperless object the plan asks a person to
check (`review: true`), by its name (`name`)."""


@dataclass(frozen=True, kw_only=True)
class ImportedReview:
    """Why a person should look at a document taken over from another system before it is
    filed: the reason, and the field it is about (`contact`, ..., `field:<id>`), or None for the
    document as a whole. A named field is open in the inbox: without a value, the person
    decides one. A reason the migration gives of its own may come with its code (`code`,
    `params`: one of `PAPERLESS_REVIEWS`, issue #83); a reason a person wrote has none."""

    reason: str
    field: str | None = None
    code: ReasonCode | None = None
    params: Mapping[str, JsonValue] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip() or len(self.reason) > MAX_REVIEW_REASON:
            raise ValidationError(f"review: a reason of 1 to {MAX_REVIEW_REASON} characters")
        named = self.field is None or self.field in REVIEWABLE
        if not named and field_id_of(self.field or "") is None:
            raise ValidationError(f"review: {self.field!r} is no field of a document")
        if self.code is not None and self.code not in PAPERLESS_REVIEWS:
            raise ValidationError(f"review: {self.code!r} is no code of a migration's reason")
        if self.code is None and self.params:
            raise ValidationError("review: parameters need a code")
        self.as_reason()  # ValidationError for parameters that do not fit the code

    def as_reason(self) -> Reason:
        """The reason with its code, or as written."""
        return written(self.reason) if self.code is None else Reason(self.code, self.params)

    def to_json(self) -> JsonObject:
        data: JsonObject = {"reason": self.reason, "field": self.field}
        if self.code is not None:
            data["code"] = self.code.value
            data["params"] = dict(self.params)
        return data

    @classmethod
    def from_json(cls, data: JsonValue) -> "ImportedReview":
        data = require_object(data, "review")
        code = as_text(data.get("code"))
        try:
            known = None if code is None else ReasonCode(code)
        except ValueError:
            raise ValidationError(f"review: unknown code {code!r}") from None
        return cls(
            reason=as_text(data.get("reason")) or "",
            field=as_text(data.get("field")),
            code=known,
            params=dict(as_object(data.get("params")) or {}),
        )


@dataclass(frozen=True, kw_only=True)
class ImportedMetadata:
    """What the source system knew about a document. The classification nodes apply it instead
    of asking the language model. `None` leaves a field unset. With `review`, the judge (or for
    a custom field the fields node) is uncertain for those reasons: the document waits in the
    inbox, with the values applied."""

    title: str | None = None
    contact_id: ContactId | None = None
    document_type_id: DocumentTypeId | None = None
    tag_ids: frozenset[TagId] = frozenset()
    document_date: date | None = None
    fields: Mapping[FieldId, FieldValue] = field(default_factory=dict)
    # When it came in at the source system (Paperless-ngx: `added`); the document keeps it as
    # its `created_at`. In UTC.
    created_at: datetime | None = None
    review: tuple[ImportedReview, ...] = ()

    def __post_init__(self) -> None:
        if len(self.review) > MAX_REVIEWS:
            raise ValidationError(f"review: at most {MAX_REVIEWS} reasons")

    def classification(self) -> DocumentChanges:
        """Title, contact, type and date as a change; the tags are added separately."""
        return DocumentChanges(
            title=UNSET if self.title is None else self.title,
            contact_id=UNSET if self.contact_id is None else self.contact_id,
            document_type_id=UNSET if self.document_type_id is None else self.document_type_id,
            document_date=UNSET if self.document_date is None else self.document_date,
        )

    def to_json(self) -> JsonObject:
        return {
            "title": self.title,
            "contact_id": None if self.contact_id is None else str(self.contact_id),
            "document_type_id": (
                None if self.document_type_id is None else str(self.document_type_id)
            ),
            "tag_ids": [str(tag) for tag in sorted(self.tag_ids)],
            "document_date": None if self.document_date is None else self.document_date.isoformat(),
            "fields": {str(key): field_to_json(value) for key, value in self.fields.items()},
            "created_at": None if self.created_at is None else self.created_at.isoformat(),
            "review": [item.to_json() for item in self.review],
        }

    @classmethod
    def from_json(
        cls, data: JsonValue, definitions: Mapping[FieldId, FieldDefinition]
    ) -> "ImportedMetadata":
        """Read what `to_json` wrote; the field values are checked against `definitions`."""
        data = require_object(data, "imported metadata")
        try:
            fields: dict[FieldId, FieldValue] = {}
            for key, value in (as_object(data.get("fields")) or {}).items():
                field_id = FieldId(require_uuid(key, "fields"))
                if field_id not in definitions:
                    raise ValidationError(f"field {key} no longer exists")
                fields[field_id] = field_from_json(definitions[field_id], value)
            return cls(
                title=as_text(data.get("title")),
                contact_id=_optional_id(data.get("contact_id"), ContactId, "contact_id"),
                document_type_id=_optional_id(
                    data.get("document_type_id"), DocumentTypeId, "document_type_id"
                ),
                tag_ids=frozenset(
                    TagId(require_uuid(tag, "tag_ids")) for tag in as_list(data.get("tag_ids"))
                ),
                document_date=(
                    None
                    if (day := data.get("document_date")) is None
                    else require_date(day, "document_date")
                ),
                fields=fields,
                created_at=(
                    None
                    if (at := data.get("created_at")) is None
                    else require_utc(datetime.fromisoformat(as_text(at) or ""), "created_at")
                ),
                review=tuple(map(ImportedReview.from_json, as_list(data.get("review")))),
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise ValidationError(f"imported metadata: {error}") from None


def _optional_id[I](value: JsonValue, kind: Callable[[UUID], I], where: str) -> I | None:
    return None if value is None else kind(require_uuid(value, where))
