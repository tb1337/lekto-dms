"""The stream of documents (`.idea/bezuege.md`, decisions 13 to 17; issue #145 PR 13): the
documents a filter finds, in lanes. A series is a lane, the relation target its documents refer
to (the contract) at its start and its expected document at its end; a branch is the chain of
documents that refer to a document of a series without belonging to it; documents related only
among themselves make a lane of their own; the rest stand in one lane "single".

Derived on each call over the documents the caller reads; at most `LIMIT` documents (the newest)
and `MAX_LANES` lanes of series and chains: a stream wider than that says so, and a narrower
filter shows it whole."""

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum

from lekto.core.domain.document_facts import DocumentFact
from lekto.core.domain.documents import Document
from lekto.core.domain.ids import DocumentId, DocumentTypeId, UserId
from lekto.core.domain.reasons import Action
from lekto.core.domain.relations import Relation, RelationState
from lekto.core.domain.series import Dated, Series, SeriesState, series_of
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._access import check_fact_filter, load_lister
from lekto.core.services._tags import expanded
from lekto.core.services.expected import period_of, series_groups

LIMIT = 500
"""The most documents a stream shows: the newest."""

MAX_LANES = 24
"""The most lanes of series and chains a stream shows; a wider one asks for a narrower filter."""


class LaneKind(StrEnum):
    SERIES = "series"
    BRANCH = "branch"  # documents that refer to one of a series, with the chain of theirs
    CHAIN = "chain"  # documents related only among themselves
    SINGLE = "single"  # documents without series and relation


@dataclass(frozen=True)
class Lane:
    """`documents`: oldest first. `series` and `state`: of a series lane. `target`: the
    relation target at the start of a series. `parent`: the index of the series lane a branch
    comes off, `joins` the document of that lane it refers to."""

    kind: LaneKind
    documents: tuple[Document, ...]
    series: Series | None = None
    state: SeriesState | None = None
    target: Document | None = None
    parent: int | None = None
    joins: DocumentId | None = None


@dataclass(frozen=True)
class Stream:
    lanes: tuple[Lane, ...]
    relations: tuple[Relation, ...]  # the set relations among its documents
    truncated: bool  # more documents than `LIMIT`, or more lanes than `MAX_LANES`


class StreamService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def stream(
        self, actor: UserId, filter: DocumentFilter, *, all_users: bool = False
    ) -> Stream:
        """The stream of the documents `filter` finds among those the caller reads (with
        `all_users`, an admin's, every user's)."""
        async with self._uow() as uow:
            user = await load_lister(uow, actor, all_users, Action.LIST_ALL_DOCUMENTS)
            check_fact_filter(user, filter)
            filter = await expanded(uow, filter)
            if all_users:
                found = await uow.documents.query(filter, limit=LIMIT + 1)
            else:
                found = await uow.documents.query_visible(actor, filter, limit=LIMIT + 1)
            documents = [item for item in found[:LIMIT] if item.lane is not None]
            ids = [item.id for item in documents]
            facts = await uow.document_facts.of_documents(ids)
            present = set(ids)
            relations = [
                relation
                for relation in await uow.document_relations.of_documents(ids)
                if relation.state is RelationState.SET
                and relation.newer in present
                and relation.older in present
            ]
            targets = frozenset(
                item.id for item in await uow.document_types.list_all() if item.relation_target
            )
        today = self._clock.now().date()
        lanes, wide = _lanes(documents, facts, relations, targets, today)
        unique = {relation.key: relation for relation in relations}
        return Stream(tuple(lanes), tuple(unique.values()), len(found) > LIMIT or wide)


def _lanes(
    documents: list[Document],
    facts: Mapping[DocumentId, list[DocumentFact]],
    relations: list[Relation],
    targets: frozenset[DocumentTypeId],
    today: date,
) -> tuple[list[Lane], bool]:
    by_id = {item.id: item for item in documents}
    linked: dict[DocumentId, set[DocumentId]] = {item.id: set() for item in documents}
    for relation in relations:
        linked[relation.newer].add(relation.older)
        linked[relation.older].add(relation.newer)
    # Series.
    # The series as "Erwartet" sees them (`expected.series_groups`).
    groups = {
        key: [by_id[item.id] for item in dated]
        for key, dated in series_groups(documents, facts).items()
    }
    used: set[DocumentId] = set()
    series_lanes: list[Lane] = []
    for key, members in groups.items():
        series = series_of(key, [_dated(item) for item in members])
        if series is None:
            continue
        ordered = tuple(sorted(members, key=_when))
        used.update(item.id for item in ordered)
        series_lanes.append(
            Lane(LaneKind.SERIES, ordered, series=series, state=series.state(today))
        )
    # The relation target at the start of a series: the oldest one its documents refer to.
    with_targets = []
    for lane in series_lanes:
        candidates = sorted(
            (
                by_id[other]
                for item in lane.documents
                for other in linked[item.id]
                if other not in used and by_id[other].document_type_id in targets
            ),
            key=_when,
        )
        target = candidates[0] if candidates else None
        if target is not None:
            used.add(target.id)
        with_targets.append(replace(lane, target=target))
    series_lanes = sorted(with_targets, key=lambda lane: _when(lane.documents[-1]), reverse=True)
    # Branches off the series, then chains among the rest.
    lanes: list[Lane] = []
    for lane in series_lanes:
        index = len(lanes)
        lanes.append(lane)
        own = {item.id for item in _all(lane)}
        for item in lane.documents:
            for other in sorted(linked[item.id], key=lambda id: _when(by_id[id])):
                if other in used or other in own:
                    continue
                chain = _chain(other, linked, used)
                lanes.append(
                    Lane(
                        LaneKind.BRANCH,
                        tuple(sorted((by_id[id] for id in chain), key=_when)),
                        parent=index,
                        joins=item.id,
                    )
                )
    for document in sorted(documents, key=_when, reverse=True):
        if document.id in used or not linked[document.id]:
            continue
        chain = _chain(document.id, linked, used)
        lanes.append(Lane(LaneKind.CHAIN, tuple(sorted((by_id[id] for id in chain), key=_when))))
    wide = len(lanes) > MAX_LANES
    if wide:
        lanes = [
            lane for lane in lanes[:MAX_LANES] if lane.parent is None or lane.parent < MAX_LANES
        ]
        used = {item.id for lane in lanes for item in _all(lane)}
    single = tuple(sorted((item for item in documents if item.id not in used), key=_when))
    if single and not wide:
        lanes.append(Lane(LaneKind.SINGLE, single))
    return lanes, wide


def _chain(
    start: DocumentId, linked: Mapping[DocumentId, set[DocumentId]], used: set[DocumentId]
) -> list[DocumentId]:
    """The documents reached from `start` over relations, none used yet; they are used then."""
    found = [start]
    used.add(start)
    queue = deque([start])
    while queue:
        for other in sorted(linked[queue.popleft()]):
            if other not in used:
                used.add(other)
                found.append(other)
                queue.append(other)
    return found


def _all(lane: Lane) -> Iterable[Document]:
    yield from lane.documents
    if lane.target is not None:
        yield lane.target


def _dated(document: Document) -> Dated:
    assert document.document_date is not None
    return Dated(document.id, document.document_date, period_of(document))


def _when(document: Document) -> tuple[date, datetime, str]:
    """Oldest first: by document date, else by when it came in."""
    day = document.document_date or document.created_at.date()
    return (day, document.created_at, str(document.id))
