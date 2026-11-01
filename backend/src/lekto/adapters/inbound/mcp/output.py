"""What a tool returns: its result as compact JSON, the text a client hands the model.

Every character costs the client tokens, so the text leaves out what says nothing: no
indentation, and no key whose value is null or empty, at any depth (an absent key means "none",
the instructions say so: no tags, no hits, no further page).
"""

import json
from typing import Any

from pydantic import BaseModel


def compact(result: BaseModel) -> str:
    return json.dumps(
        _pruned(result.model_dump(mode="json")), ensure_ascii=False, separators=(",", ":")
    )


def _pruned(value: Any) -> Any:
    if isinstance(value, dict):
        pruned = {key: _pruned(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if not _empty(item)}
    if isinstance(value, list):
        return [_pruned(item) for item in value]
    return value


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, dict | list | str) and not value)
