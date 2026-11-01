"""The tools of the domains `identifiers`, `rules` and `system`: whose a number is and where it
stands, the rules read (to understand why a document came where it is), and the state of the
system as the caller may see it (Tobi, 01.11.2026, umsetzungsplan "MCP", PR 6b). Rules are made,
changed and applied in the web UI; identifiers are decided there."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names, similar_names
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind, normalise_identifier
from lekto.core.domain.ids import UserId, short_id
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.open_identifiers import OpenSource
from lekto.core.domain.rules import Rule
from lekto.core.domain.rules_json import definition_to_json
from lekto.core.domain.spaces import Space

OPEN_SIZE = 20


class PlaceOut(BaseModel):
    id: str
    title: str
    date: date
    role: str
    text: str | None  # around it


class IdentifierFoundOut(BaseModel):
    kind: str
    value: str
    contacts: list[str]
    documents: list[PlaceOut]


class OpenOut(BaseModel):
    kind: str
    value: str
    source: str
    contacts: list[str]
    person: str | None
    documents: int
    last: date | None
    recommended: str | None
    why: str | None


class OpenListOut(BaseModel):
    total: int
    items: list[OpenOut]
    next_offset: int | None


class RuleOut(BaseModel):
    name: str
    scope: str
    space: str | None
    enabled: bool
    disabled_because: str | None
    triggers: list[str]
    priority: int
    managed: bool | None  # a type's title pattern


class RulesOut(BaseModel):
    rules: list[RuleOut]


class RuleDetailOut(RuleOut):
    version: int
    changed_at: datetime
    definition: JsonValue


class JobKindOut(BaseModel):
    kind: str
    running: int
    due: int
    planned: int
    failed: int


class SearchStatusOut(BaseModel):
    documents: int
    with_meaning: int
    queued: int
    model: str | None


class ClassifierStatusOut(BaseModel):
    model: int | None  # its number
    trained_at: datetime | None
    examples: int | None
    confirmed_since: int


class SystemOut(BaseModel):
    jobs: list[JobKindOut]
    search: SearchStatusOut | None
    classifier: ClassifierStatusOut | None


def add_reference_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "identifiers_find",
        "Whose an identifier is (IBAN, customer number, ...: the kinds as documents_get "
        "include facts names them) and the newest of your documents that show it, with the "
        "text around it.",
    )
    async def identifiers_find(
        ctx: Context, kind: str, value: Annotated[str, Field(min_length=1, max_length=200)]
    ) -> str:
        user = principal_of(ctx).id
        chosen = _kind(kind)
        normal = normalise_identifier(chosen, value)
        holders = [
            contact.name
            for contact in await context.master_data.list_contacts(user)
            if any(item.kind is chosen and item.value == normal for item in contact.identifiers)
        ]
        places = await context.documents.identifier_places(user, chosen, normal)
        return compact(
            IdentifierFoundOut(
                kind=chosen.value,
                value=normal,
                contacts=holders,
                documents=[
                    PlaceOut(
                        id=short_id(place.document),
                        title=place.title,
                        date=place.dated,
                        role=place.role.value,
                        text=(
                            None
                            if place.excerpt is None
                            else f"{place.excerpt.before}{place.excerpt.match}{place.excerpt.after}"
                        ),
                    )
                    for place in places
                ],
            )
        )

    @tools.read(
        "identifiers_open",
        "Identifiers no person confirmed yet: learned by training at a contact, or unknown "
        "(confirmed documents show them, no contact has them); the most documents first, "
        "with Lekto's recommendation. Decided in the web UI.",
        admin=True,
    )
    async def identifiers_open(
        ctx: Context,
        source: Literal["learned", "unknown", "suggested"] | None = None,
        query: Annotated[str | None, Field(max_length=100)] = None,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> str:
        user = principal_of(ctx).id
        page = await context.open_identifiers.page(
            user,
            source=None if source is None else OpenSource(source),
            words=query,
            offset=offset,
            limit=OPEN_SIZE,
        )
        following = offset + OPEN_SIZE
        return compact(
            OpenListOut(
                total=page.total,
                items=[
                    OpenOut(
                        kind=item.kind.value,
                        value=item.written or item.value,
                        source=item.source.value,
                        contacts=[page.names[id] for id in item.contacts if id in page.names],
                        person=None if item.person is None else page.persons.get(item.person),
                        documents=len(item.seen),
                        last=item.last,
                        recommended=(
                            None if item.recommended is None else item.recommended.action.value
                        ),
                        why=None if item.recommended is None else item.recommended.reason.text,
                    )
                    for item in page.items
                ],
                next_offset=following if following < page.total else None,
            )
        )

    @tools.read(
        "rules_list",
        "The rules that act on your documents, in the order they apply: global ones and "
        "those of the spaces you edit, with triggers (ingest, change, ...) and whether they "
        "are enabled. Made and changed in the web UI.",
    )
    async def rules_list(ctx: Context) -> str:
        user = principal_of(ctx).id
        rules = await context.rules.list_rules(user)
        spaces = await _spaces(context, user)
        return compact(RulesOut(rules=[_rule(rule, spaces) for rule in rules]))

    @tools.read(
        "rules_get",
        "A rule by name: its conditions and actions as stored, with names for the ids of "
        "contacts, types, tags, topics, fields and spaces.",
    )
    async def rules_get(ctx: Context, name: str) -> str:
        user = principal_of(ctx).id
        found = _named_rule(await context.rules.list_rules(user), name)
        rule = await context.rules.get(user, found.id)
        spaces = await _spaces(context, user)
        names = await Names.load(context, user)
        lookup: dict[str, str] = {
            str(id): label
            for table in (
                names.contacts,
                names.document_types,
                names.tags,
                names.topics,
                names.groups,
                {id: field.name for id, field in names.fields.items()},
                {space.id: label for space, label in spaces.values()},
            )
            for id, label in table.items()
        }
        base = _rule(rule, spaces)
        return compact(
            RuleDetailOut(
                **base.model_dump(),
                version=rule.current.number,
                changed_at=rule.updated_at,
                definition=_named(definition_to_json(rule.current.definition), lookup),
            )
        )

    @tools.read(
        "system_status",
        "How Lekto is doing: jobs by kind (running, due, planned, failed), the search index "
        "(documents, with meaning) and the classifier's model.",
    )
    async def system_status(ctx: Context) -> str:
        user = principal_of(ctx).id
        jobs = await context.jobs.summary(user)
        search = None
        if context.indexing is not None:
            index = await context.indexing.status(user)
            search = SearchStatusOut(
                documents=index.documents,
                with_meaning=index.stats.embedded,
                queued=index.queued,
                model=index.model,
            )
        classifier = None
        if context.classifier is not None:
            status = await context.classifier.status(user)
            model = status.model
            classifier = ClassifierStatusOut(
                model=None if model is None else model.number,
                trained_at=None if model is None else model.trained_at,
                examples=None if model is None else model.examples,
                confirmed_since=status.since,
            )
        return compact(
            SystemOut(
                jobs=[
                    JobKindOut(
                        kind=item.kind,
                        running=item.running,
                        due=item.due,
                        planned=item.planned,
                        failed=item.failed,
                    )
                    for item in jobs.kinds
                    if item.running or item.due or item.planned or item.failed
                ],
                search=search,
                classifier=classifier,
            )
        )


def _kind(name: str) -> IdentifierKind:
    try:
        return IdentifierKind(name.strip().lower())
    except ValueError:
        alike = similar_names(name, [kind.value for kind in IdentifierKind])
        hint = f"; similar: {', '.join(alike)}" if alike else ""
        raise ValidationError(f"no kind of identifier named '{name}'{hint}") from None


async def _spaces(context: ApiContext, user: UserId) -> dict[UUID, tuple[Space, str]]:
    """The caller's spaces with how they read them (a personal one by its person's name)."""
    spaces = await context.spaces.list_spaces(user)
    people = await context.spaces.members(user, spaces)
    return {
        space.id: (
            space,
            people[space.personal_of].label
            if space.personal_of is not None and space.personal_of in people
            else space.name,
        )
        for space in spaces
    }


def _rule(rule: Rule, spaces: dict[UUID, tuple[Space, str]]) -> RuleOut:
    definition = rule.current.definition
    return RuleOut(
        name=definition.name,
        scope=rule.scope.value,
        space=None if rule.space_id is None else spaces.get(rule.space_id, (None, None))[1],
        enabled=rule.enabled,
        disabled_because=None if rule.disabled_reason is None else rule.disabled_reason.text,
        triggers=sorted(trigger.value for trigger in definition.triggers),
        priority=definition.priority,
        managed=True if rule.managed_by is not None else None,
    )


def _named(value: JsonValue, lookup: dict[str, str]) -> JsonValue:
    """`value` with the ids it holds replaced by their names, where known."""
    if isinstance(value, dict):
        return {key: _named(item, lookup) for key, item in value.items()}
    if isinstance(value, list):
        return [_named(item, lookup) for item in value]
    if isinstance(value, str):
        return lookup.get(value, value)
    return value


def _named_rule(rules: list[Rule], name: str) -> Rule:
    """The rule named `name` (any case); an error with similar names for none."""
    by_name = {rule.current.definition.name: rule for rule in rules}
    for key, rule in by_name.items():
        if key.casefold() == name.casefold():
            return rule
    alike = similar_names(name, by_name)
    hint = f"; similar: {', '.join(alike)}" if alike else ""
    raise ValidationError(f"no rule named '{name}'{hint}")
