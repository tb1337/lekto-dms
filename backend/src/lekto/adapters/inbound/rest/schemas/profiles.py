"""Profiles: the display name, and what is private about a user as a person."""

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.documents import UNSET
from lekto.core.domain.identifiers import (
    MAX_IDENTIFIERS,
    Identifier,
    IdentifierKind,
    IdentifierSource,
)
from lekto.core.domain.ids import ContactId, TagId
from lekto.core.domain.profiles import MAX_ALIASES, MAX_PERSON_IDENTIFIERS
from lekto.core.domain.users import MAX_DISPLAY_NAME
from lekto.core.services.profiles import ContactNumber, ProfileChanges, UserProfile

PERSON_NOTE = (
    " Only the user and admins see the profile; others see the display name. Of the profile "
    "nothing goes to the language model or the search index (the display name does: it labels "
    "the user's personal space in the prompt); the processing log keeps only which users a "
    "document names and the kinds of evidence, never the values, and shows them to admins and "
    "to the user named."
)


class PersonIdentifierIn(BaseModel):
    """Written as in documents; Lekto stores it normalised."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"kind": "tax_id", "value": "..."}]}
    )

    kind: IdentifierKind = Field(
        description=(
            "`iban`, `tax_id` (11 digits with check digit), `social_security_number`, "
            "`health_insurance_number` (a letter and nine digits) or `email_address`; other "
            "kinds are a contact's (422)."
        )
    )
    value: str = Field(min_length=1, max_length=100)


class PersonIdentifierOut(BaseModel):
    kind: IdentifierKind
    value: str = Field(description="Normalised.")


class ContactNumberIn(BaseModel):
    """A customer or personnel number of the user at a contact, written as in documents."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "contact_id": "6f1c2a4e-0000-4000-8000-000000000001",
                    "kind": "personnel_number",
                    "value": "12345",
                }
            ]
        },
    )

    contact_id: UUID
    kind: IdentifierKind = Field(
        description="`customer_number` (also a contract or policy number) or `personnel_number`; "
        "other kinds name nobody (422)."
    )
    value: str = Field(min_length=1, max_length=100)
    topic_id: UUID | None = Field(
        default=None,
        description="One of the contact's topics it points to (a personnel number to work).",
    )

    def number(self) -> ContactNumber:
        return ContactNumber(
            ContactId(self.contact_id),
            Identifier.parse(
                self.kind,
                self.value,
                topic_id=None if self.topic_id is None else TagId(self.topic_id),
            ),
        )


class ContactNumberOut(BaseModel):
    contact_id: UUID
    kind: IdentifierKind
    value: str = Field(description="Normalised.")
    source: IdentifierSource = Field(
        description="`manual`: entered by hand (by the user or an admin); `learned`: training "
        "found it in confirmed documents that are surely the user's alone (in their personal "
        "space, or naming them by more than their name)."
    )
    topic_id: UUID | None

    @classmethod
    def of(cls, number: ContactNumber) -> "ContactNumberOut":
        item = number.identifier
        return cls(
            contact_id=number.contact_id,
            kind=item.kind,
            value=item.value,
            source=item.source,
            topic_id=item.topic_id,
        )


Alias = Annotated[str, Field(min_length=1, max_length=MAX_DISPLAY_NAME)]


class ProfileOut(BaseModel):
    user_id: UUID
    display_name: str | None = Field(description="Public; null: the username is shown.")
    aliases: list[str] = Field(description="Other names (a maiden name), to find the person.")
    birth_date: date | None
    email: str | None = Field(description="Also counts as an identifier.")
    identifiers: list[PersonIdentifierOut]
    numbers: list[ContactNumberOut] = Field(
        description="The user's customer and personnel numbers at contacts, by contact: found "
        "in a document, they are evidence for the contact and for the user. Only the user and "
        "admins see them, here and at the contact."
    )

    @classmethod
    def of(cls, found: UserProfile) -> "ProfileOut":
        profile = found.profile
        return cls(
            user_id=found.user.id,
            display_name=found.user.display_name,
            aliases=list(profile.aliases),
            birth_date=profile.birth_date,
            email=profile.email,
            identifiers=[
                PersonIdentifierOut(kind=item.kind, value=item.value)
                for item in profile.identifiers
            ],
            numbers=[ContactNumberOut.of(number) for number in found.numbers],
        )


class ProfilePatch(BaseModel):
    """What is given changes; null removes the display name, birth date or e-mail; `aliases`,
    `identifiers` and `numbers` replace all of them."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "display_name": "Anna Example",
                    "aliases": ["Anna Sample"],
                    "birth_date": "1980-06-15",
                }
            ]
        },
    )

    display_name: str | None = Field(
        default=None,
        max_length=MAX_DISPLAY_NAME,
        description="Unique across users regardless of case, also against their aliases (409).",
    )
    aliases: list[Alias] = Field(default_factory=list, max_length=MAX_ALIASES)
    birth_date: date | None = None
    email: str | None = Field(default=None, max_length=254)
    identifiers: list[PersonIdentifierIn] = Field(
        default_factory=list,
        max_length=MAX_PERSON_IDENTIFIERS,
        description=(
            "The person's own numbers; found in a document, they tell whose it is. Several users "
            "may share one (a joint account), a contact may not have it (409 if a contact "
            "entered it by hand; a learned one gives way)."
        ),
    )
    numbers: list[ContactNumberIn] = Field(
        default_factory=list,
        max_length=MAX_IDENTIFIERS,
        description=(
            "The user's numbers at contacts entered by hand (a learned one given is then entered "
            "by hand); learned ones left out stay. Unique across contacts: 409 if another "
            "contact has it entered by hand (naming that contact only if the caller sees the "
            "number there), 404 for a contact that does not exist."
        ),
    )
    declined_numbers: list[ContactNumberIn] = Field(
        default_factory=list,
        max_length=MAX_IDENTIFIERS,
        description=(
            "Learned numbers that are not the user's: they are rejected at their contact, and "
            "training does not learn them again. Others are left as they are."
        ),
    )

    def changes(self) -> ProfileChanges:
        given = self.model_fields_set
        return ProfileChanges(
            display_name=self.display_name if "display_name" in given else UNSET,
            aliases=self.aliases if "aliases" in given else UNSET,
            birth_date=self.birth_date if "birth_date" in given else UNSET,
            email=self.email if "email" in given else UNSET,
            identifiers=(
                [Identifier.parse(item.kind, item.value) for item in self.identifiers]
                if "identifiers" in given
                else UNSET
            ),
            numbers=[item.number() for item in self.numbers] if "numbers" in given else UNSET,
            declined_numbers=(
                [item.number() for item in self.declined_numbers]
                if "declined_numbers" in given
                else UNSET
            ),
        )
