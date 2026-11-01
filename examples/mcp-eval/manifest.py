"""The example documents `seed.py` loads and `tasks.py` asks about: all of the manifest, or a
fixed sample of it (`--documents N`), the same for both, so a small run stays cheap."""

import json
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).resolve().parent.parent / "documents"
KEPT = "strom-2024"
"""A document every sample keeps: a task asks for its invoice number."""


def documents(size: int | None = None) -> list[dict[str, Any]]:
    """The documents of the manifest without its duplicates; with `size`, every k-th of them
    in the order of their files, `KEPT` among them, `size` at most."""
    found = [
        doc
        for doc in json.loads((EXAMPLES / "manifest.json").read_text())["documents"]
        if not doc.get("duplicate_of")
    ]
    if size is None or size >= len(found):
        return found
    ordered = sorted(found, key=lambda doc: doc["file"])
    step = len(ordered) / size
    sample = [ordered[int(index * step)] for index in range(size)]
    if not any(doc.get("key") == KEPT for doc in sample):
        sample[-1] = next(doc for doc in ordered if doc.get("key") == KEPT)
    return sample
