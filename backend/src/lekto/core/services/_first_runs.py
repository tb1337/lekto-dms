"""Keeping the facts of processing as they happen (`domain.first_runs`): the first run when it
stops, and a person's verdicts when they decide, in the transaction of the change itself."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from lekto.core.domain.classification import SPACE, FieldCheck, field_key
from lekto.core.domain.document_facts import FactState
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.first_runs import (
    FACTS,
    JUDGED_FIELDS,
    RELATIONS,
    Decision,
    FieldVerdict,
    FirstRun,
    Verdict,
    decided_fields,
    early_verdicts,
    judge_fields,
    values_of,
)
from lekto.core.domain.ids import FieldId, TagId
from lekto.core.domain.master_data import Assignment
from lekto.core.domain.pipeline import Lane, NodeRun
from lekto.core.domain.relations import RelationOrigin, RelationState
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
    on upload, unless the automation asked about it since (its check is open): the person's
    answer to that is their first decision on what the automation proposed. `log`: the
    document's log, if read already."""
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
    if not fields:
        return
    checks: Mapping[str, FieldCheck] = field_checks(
        await uow.processing_log.list_for(after.id) if log is None else log
    )
    decided = before.space_confirmed_at is not None if space_decided is None else space_decided
    space = checks.get(SPACE)
    if decided and (space is None or space.ok):
        fields -= {SPACE}
        if not fields:
            return
    verdicts = judge_fields(
        after.id,
        decision,
        fields=fields,
        before=values,
        after=values_of(after, manual),
        checks=checks,
        decided_at=now,
    )
    if decision is Decision.INBOX and any(
        fact.state is not FactState.REJECTED
        for fact in await uow.document_facts.of_document(after.id)
    ):
        # Confirmed with its facts: the person took what the sources found, unless they
        # decided about them before (the first decision stands).
        verdicts.append(
            FieldVerdict(
                document_id=after.id,
                field=FACTS,
                verdict=Verdict.TAKEN,
                decided_at=now,
                decision=decision,
            )
        )
    if decision is Decision.INBOX and any(
        relation.origin is RelationOrigin.LEKTO
        and relation.state is not RelationState.REJECTED
        and relation.newer == after.id
        for relation in await uow.document_relations.of_document(after.id)
    ):
        # Confirmed with the relations Lekto found for it: taken likewise.
        verdicts.append(
            FieldVerdict(
                document_id=after.id,
                field=RELATIONS,
                verdict=Verdict.TAKEN,
                decided_at=now,
                decision=decision,
            )
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
