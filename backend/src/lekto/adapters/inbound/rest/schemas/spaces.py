"""Spaces and their members."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.common import Name, NameIn
from lekto.core.domain.ids import UserId
from lekto.core.domain.master_data import MAX_DESCRIPTION
from lekto.core.domain.permissions import space_role
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User

SpaceDescription = Annotated[
    str,
    Field(
        max_length=MAX_DESCRIPTION,
        description=(
            "What belongs in the space, for the language model when it suggests where a "
            "document goes; empty removes it. Never sent with other users' personal spaces."
        ),
        examples=["Wohnung, Nebenkosten, Versorger, Versicherungen fürs Haus, Kinder"],
    ),
]


class MemberIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"role": "read"}]},
    )

    role: SpaceRole = Field(
        description="`read`: the space's green documents; `edit`: every document in it in every "
        "lane, changing, confirming, moving and deleting them, the space's rules, members and name."
    )


class MemberOut(BaseModel):
    user_id: UUID
    role: SpaceRole


class SpaceMember(MemberOut):
    model_config = ConfigDict(extra="forbid")


class MemberDetails(MemberOut):
    username: str
    active: bool = Field(
        description="A deactivated member keeps their place until an editor removes them."
    )


class SpaceCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Household"}]},
    )

    description: SpaceDescription | None = None
    members: list[SpaceMember] | None = Field(
        default=None,
        description=(
            "Who else is a member, with their role. The caller always edits a space they "
            "create; an admin may give the members alone (one of them must edit)."
        ),
    )


class SpacePatch(BaseModel):
    """Fields left out stay; a `description` of null or empty removes it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"description": "Wohnung, Nebenkosten, Versorger"}]},
    )

    name: Name | None = Field(default=None, description="Not for a personal space (422).")
    description: SpaceDescription | None = None


class SpaceOut(BaseModel):
    id: UUID
    name: str = Field(
        examples=["Household"],
        description="A personal space has a fixed name; it is shown by its user's name.",
    )
    personal_of: UUID | None = Field(
        description="The user whose personal space it is: what they upload lands there."
    )
    description: str | None = Field(
        description="What belongs in the space, for the language model."
    )
    role: SpaceRole = Field(description="The caller's role; admins edit every space.")
    members: list[MemberDetails]
    created_at: datetime
    version: int

    @classmethod
    def of(cls, space: Space, viewer: User, people: Mapping[UserId, User]) -> "SpaceOut":
        """As `viewer` sees it, who is a member or an admin; `people`: its members."""
        role = space_role(viewer, space)
        assert role is not None  # the service returns visible spaces only
        return cls(
            id=space.id,
            name=space.name,
            personal_of=space.personal_of,
            description=space.description,
            role=role,
            members=[
                MemberDetails(
                    user_id=user,
                    role=member,
                    username=people[user].username,
                    active=people[user].active,
                )
                for user, member in sorted(space.members.items())
            ],
            created_at=space.created_at,
            version=space.version,
        )
