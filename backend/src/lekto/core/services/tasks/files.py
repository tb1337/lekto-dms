"""The files the consumer of a model call may fetch: the structure of the document's text
(`content.json`, its words with their boxes) and its page images (`pages/<n>.webp`).

Each link is signed with `LEKTO_SECRET_KEY` (by `SecretCipher`: an authenticated encryption
of nothing, bound to the task, its document, its run, the file and the end of the link) and
holds until the task's deadline, as long as the run is the document's current one. The task's
token is apart from them: a link answers nothing.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from lekto.core.domain import media_types
from lekto.core.domain.encoding import base64url, from_base64url
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.tasks import Task
from lekto.core.ports.identity import DecryptionError, SecretCipher
from lekto.core.services.objects import page_key, structure_key

EXTERNAL_TASKS_PATH = "/api/v1/external/tasks/"
FILES_PATH = EXTERNAL_TASKS_PATH + "{id}/files/{name}"
STRUCTURE = "content.json"
_PAGE = re.compile(r"pages/([1-9][0-9]{0,4})\.webp")


def page_file(number: int) -> str:
    """The name of the image of page `number` (from 1)."""
    return f"pages/{number}.webp"


def file_link(
    link_base: str, cipher: SecretCipher, task: Task, name: str, expires: datetime
) -> str:
    """The signed link to the file `name` of `task`'s document, valid until `expires`."""
    stamp = int(expires.timestamp())
    signature = base64url(cipher.encrypt(b"", context=_context(task, name, stamp)))
    query = urlencode({"expires": stamp, "signature": signature})
    return link_base.rstrip("/") + FILES_PATH.format(id=task.id, name=name) + "?" + query


def signed(cipher: SecretCipher, task: Task, name: str, expires: int, signature: str) -> bool:
    """Whether `signature` is Lekto's for the file `name` of `task` until `expires`."""
    try:
        cipher.decrypt(from_base64url(signature), context=_context(task, name, expires))
    except (DecryptionError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class TaskFile:
    key: str
    media_type: str


def task_file(document: DocumentId, name: str, pages: int | None) -> TaskFile | None:
    """Where the file `name` of the document lies; None for no such file (a page beyond
    `pages`, the document's page count)."""
    if name == STRUCTURE:
        return TaskFile(structure_key(document), media_types.JSON)
    match = _PAGE.fullmatch(name)
    if match is None or int(match.group(1)) > (pages or 0):
        return None
    return TaskFile(page_key(document, int(match.group(1))), media_types.WEBP)


def _context(task: Task, name: str, expires: int) -> bytes:
    return f"task-file:{task.id}:{task.document_id}:{task.run}:{name}:{expires}".encode()
