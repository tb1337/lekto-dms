"""Pieces more than one area of the API uses."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from papiq.core.domain.validation import MAX_NAME

Name = Annotated[str, Field(min_length=1, max_length=MAX_NAME, examples=["ACME Energy"])]


class NameIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "ACME Energy"}]},
    )

    name: Name
