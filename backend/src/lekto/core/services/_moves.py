"""A person moving a document into another space: what every such move does, whoever starts
it (`DocumentService.move`, deleting a user who leaves documents behind)."""

from datetime import datetime

from lekto.core.domain.documents import Document
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._access import field_definitions
from lekto.core.services.inbox import arrived
from lekto.core.services.rules.changes import ChangeRules
from lekto.core.services.rules.running import Prepared


async def move_by_person(
    uow: UnitOfWork,
    document: Document,
    source: Space,
    target: Space,
    *,
    by: User,
    now: datetime,
    rules: ChangeRules | None,
    prepared: Prepared | None = None,
) -> None:
    """`by` moves `document` out of `source` into `target` (the caller checked they may): the
    space is a person's decision, a green document becomes new for the editors of `target`
    who could not read it before (`inbox.arrived`), the log says a person chose the space, so
    rules leave it there, and a completed document runs the rules of `target` as change rules
    (`ChangeRules.after_arrival`, with the patterns `prepared` outside the transaction from
    `ChangeRules.arrival_rules`). Saves the document and its events."""
    document.move_to(
        target.id, now, by_person=True, handed_over=target.personal_of not in (None, by.id)
    )
    await arrived(uow, document, source, now, by.id)
    if rules is not None:
        await uow.processing_log.append(rules.space_chosen(document, actor=by, now=now))
        await rules.after_arrival(
            uow,
            document=document,
            source=source,
            prepared=prepared or Prepared(),
            definitions=await field_definitions(uow),
            now=now,
            by_person=True,
            applier=by,
        )
    await uow.documents.update(document)
    await uow.outbox.add(document.pull_events())
