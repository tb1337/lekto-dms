"""The text a tool returns: compact, without what says nothing."""

import json

from pydantic import BaseModel

from lekto.adapters.inbound.mcp.output import compact


class Inner(BaseModel):
    name: str
    tags: list[str]
    note: str | None = None


class Outer(BaseModel):
    items: list[Inner]
    next_offset: int | None
    semantic: bool
    fields: dict[str, str]
    title: str


def test_null_and_empty_values_are_left_out_at_any_depth() -> None:
    result = Outer(
        items=[Inner(name="Größe", tags=[]), Inner(name="b", tags=["x"], note="n")],
        next_offset=None,
        semantic=False,
        fields={},
        title="",
    )
    text = compact(result)
    assert json.loads(text) == {
        "items": [{"name": "Größe"}, {"name": "b", "tags": ["x"], "note": "n"}],
        "semantic": False,
    }
    assert " " not in text and "Größe" in text  # no indentation, no escapes for umlauts


def test_a_result_without_values_is_an_empty_object() -> None:
    assert compact(Outer(items=[], next_offset=None, semantic=True, fields={}, title="")) == (
        '{"semantic":true}'
    )
