"""Keeping the facts of processing as they happen (`domain.first_runs`): the first run when it
stops, and a person's verdicts when they decide, in the transaction of the change itself."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from lekto.core.domain.classification import SPACE, FieldCheck, field_key
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.first_runs import (
    JUDGED_FIELDS,
    Decision,
    FirstRun,
    decided_fields,
    early_verdicts,
    judge_fields,
    values_of,
)
from lekto.core.domain.ids import FieldId, TagId
from lekto.core.domain.master_data import Assignment
from lekto.core.domain.pipeline import Lane, NodeRun
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services.inbox import field_checks


async def keep_first_run(
    uow: UnitOfWork, document: Document, first_lane: Lane | None, now: datetime
) -> None:
    """Keep the document's first run if it just stopped: its first lane was `first_lane`
    (None) before the result now stored, and is set now. The log holds the run's entries,
    the one just appended included."""
    if first_lane is not None or document.first_lane is None:
        return
    log = await uow.processing_log.list_for(document.id)
    await uow.processing_facts.add_first_run(FirstRun.of(document.id, log, now))


async def keep_verdicts(
    uow: UnitOfWork,
    decision: Decision,
    *,
    before: Document,
    after: Document,
    given: Collection[str],
    definitions: Mapping[FieldId, FieldDefinition],
    now: datetime,
    log: Sequence[NodeRun] | None = None,
    space_decided: bool | None = None,
) -> None:
    """Keep a person's verdicts on the fields their decision covers (`decided_fields`):
    `before` and `after` it, `given` the fields they set (named as in checks). A field judged
    before keeps its verdict. A person who decides before the first run stopped gets `EARLY`
    for the fields they set. The space is not judged if a person (or the source system)
    decided it before (`space_decided`; None: as `before` tells, `space_confirmed_at`), such as
    on upload. `log`: the document's log, if read already."""
    manual = await _manual_tags(uow, before.tag_ids | after.tag_ids)
    applying = {
        field_key(id)
        for id, definition in definitions.items()
        if definition.applies_to(after.document_type_id)
    }
    if before.processing.run == 1 and before.first_lane is None:
        named = {*given, *([SPACE] if decision is Decision.MOVE else [])}
        early = named & {*JUDGED_FIELDS, *applying}
        await uow.processing_facts.add_verdicts(early_verdicts(after.id, decision, early, now))
        return
    values = values_of(before, manual)
    fields = decided_fields(decision, before=values, given=given, applying=applying)
    decided = before.space_confirmed_at is not None if space_decided is None else space_decided
    if decided:
        fields -= {SPACE}
    if not fields:
        return
    checks: Mapping[str, FieldCheck] = field_checks(
        await uow.processing_log.list_for(after.id) if log is None else log
    )
    verdicts = judge_fields(
        after.id,
        decision,
        fields=fields,
        before=values,
        after=values_of(after, manual),
        checks=checks,
        decided_at=now,
    )
    await uow.processing_facts.add_verdicts(verdicts)


async def _manual_tags(uow: UnitOfWork, tags: Collection[TagId]) -> frozenset[TagId]:
    """Those of `tags` that are set by hand only."""
    manual = set()
    for id in tags:
        tag = await uow.tags.find(id)
        if tag is not None and tag.assignment is Assignment.MANUAL:
            manual.add(id)
    return frozenset(manual)
