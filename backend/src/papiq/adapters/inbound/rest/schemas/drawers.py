"""Drawers and their shares."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from papiq.adapters.inbound.rest.schemas.common import NameIn
from papiq.core.domain.drawers import Drawer, ShareLevel
from papiq.core.domain.permissions import can_manage_drawer, drawer_access
from papiq.core.domain.users import User


class DrawerCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Household"}]},
    )

    owner_id: UUID | None = Field(
        default=None,
        description="Admins only: the user who will own the drawer. Default: the caller.",
    )


class ShareOut(BaseModel):
    user_id: UUID
    level: ShareLevel


class DrawerOut(BaseModel):
    id: UUID
    name: str = Field(examples=["Household"])
    owner_id: UUID
    is_default: bool
    access: ShareLevel = Field(
        description="The caller's access: owner and admins (read_write), or the share."
    )
    shares: list[ShareOut] | None = Field(description="Only for the owner and admins.")
    created_at: datetime

    @classmethod
    def of(cls, drawer: Drawer, viewer: User) -> "DrawerOut":
        """As `viewer` sees it, who owns it, has a share or is an admin."""
        access = drawer_access(viewer, drawer)
        assert access is not None  # the service returns visible drawers only
        manager = can_manage_drawer(viewer, drawer)
        shares = sorted(drawer.shares.items())
        return cls(
            id=drawer.id,
            name=drawer.name,
            owner_id=drawer.owner_id,
            is_default=drawer.is_default,
            access=access,
            shares=[ShareOut(user_id=u, level=level) for u, level in shares] if manager else None,
            created_at=drawer.created_at,
        )


class ShareIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"level": "read"}]},
    )

    level: ShareLevel
