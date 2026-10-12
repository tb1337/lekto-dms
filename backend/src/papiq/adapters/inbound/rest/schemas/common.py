"""Pieces more than one area of the API uses."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Name = Annotated[str, Field(min_length=1, max_length=200, examples=["ACME Energy"])]


class NameIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "ACME Energy"}]},
    )

    name: Name
