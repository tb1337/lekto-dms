"""The title the machine gives a document: the language model's proposal. A type's title
pattern is a rule (`rules.title_rule`), which replaces it as any rule's title does.

A title is the machine's as long as the document has it and the log shows the machine gave
it (or it is the file name): the fields node may replace it, and a rule may set another one
without the document becoming uncertain. A title a person or a rule gave stays.
"""

from collections.abc import Sequence

from papiq.core.domain.classification import CHECKS, TITLE, checks_from_json
from papiq.core.domain.documents import Document
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.pipeline import Node, NodeRun

RENDERED_TITLE = "rendered_title"
"""Key in the output of a confirmation before 0.2.0: the title the pattern gave with the decided
values (patterns are rules now; the key is still read)."""


def machine_title(log: Sequence[NodeRun]) -> str | None:
    """The title the machine gave last: the fields node's title check, or the title rendered
    when a person confirmed the document."""
    for entry in reversed(log):
        rendered = entry.result.output.get(RENDERED_TITLE)
        if isinstance(rendered, str):
            return rendered
        if entry.node is not Node.FIELDS:
            continue
        try:
            checks = checks_from_json(entry.result.output.get(CHECKS))
        except ValidationError:
            continue
        for check in checks:
            if check.field == TITLE and isinstance(check.value, str):
                return check.value
    return None


def has_machine_title(document: Document, log: Sequence[NodeRun]) -> bool:
    """Whether the document's title is the file name or the one the machine gave last."""
    return document.title in (document.file_title, machine_title(log))
