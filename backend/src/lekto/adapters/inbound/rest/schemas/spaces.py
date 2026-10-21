"""Spaces and their members."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.common import NameIn
from lekto.core.domain.permissions import space_role
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User


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


class SpaceCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Household"}]},
    )

    members: list[SpaceMember] | None = Field(
        default=None,
        description=(
            "Who else is a member, with their role. The caller always edits a space they "
            "create; an admin may give the members alone (one of them must edit)."
        ),
    )


class SpaceOut(BaseModel):
    id: UUID
    name: str = Field(
        examples=["Household"],
        description="A personal space has a fixed name; it is shown by its user's name.",
    )
    personal_of: UUID | None = Field(
        description="The user whose personal space it is: what they upload lands there."
    )
    role: SpaceRole = Field(description="The caller's role; admins edit every space.")
    members: list[MemberOut]
    created_at: datetime
    version: int

    @classmethod
    def of(cls, space: Space, viewer: User) -> "SpaceOut":
        """As `viewer` sees it, who is a member or an admin."""
        role = space_role(viewer, space)
        assert role is not None  # the service returns visible spaces only
        return cls(
            id=space.id,
            name=space.name,
            personal_of=space.personal_of,
            role=role,
            members=[
                MemberOut(user_id=user, role=member)
                for user, member in sorted(space.members.items())
            ],
            created_at=space.created_at,
            version=space.version,
        )
