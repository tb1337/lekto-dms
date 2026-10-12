"""The health check."""

from typing import Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: Literal["ok", "degraded", "unavailable"] = Field(
        description="`degraded`: only an optional check failed, the API still works (`200`)."
    )
    checks: dict[str, Literal["ok", "failed"]] = Field(
        examples=[{"database": "ok", "object_store": "ok"}]
    )
