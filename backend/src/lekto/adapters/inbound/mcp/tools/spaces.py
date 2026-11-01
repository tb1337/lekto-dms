"""The tools of the domains `spaces` and `lenses`: where documents lie and who sees them, and
the caller's saved views, read only (Tobi, 01.11.2026, umsetzungsplan "MCP": managing Lekto
stays in the web UI)."""

from collections.abc import Iterable, Mapping
from uuid import UUID

from mcp.server.mcpserver import Context
from pydantic import BaseModel

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.lenses import Lens
from lekto.core.domain.spaces import Space


class MemberOut(BaseModel):
    name: str
    role: str


class SpaceOut(BaseModel):
    name: str
    personal: bool | None
    description: str | None
    role: str | None  # yours
    members: list[MemberOut]


class SpacesOut(BaseModel):
    spaces: list[SpaceOut]


class LensOut(BaseModel):
    name: str
    query: str | None
    contacts: list[str]
    document_types: list[str]
    tags: list[str]
    topics: list[str]
    document_period: str | None
    document_date_from: str | None
    document_date_to: str | None


class LensesOut(BaseModel):
    lenses: list[LensOut]


def add_space_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "spaces_list",
        "The spaces you are a member of: a personal space by its person's name, your role "
        "(read or edit) and who else sees its documents.",
    )
    async def spaces_list(ctx: Context) -> str:
        user = principal_of(ctx).id
        spaces = await context.spaces.list_spaces(user)
        people = {
            id: person.label for id, person in (await context.spaces.members(user, spaces)).items()
        }
        return compact(
            SpacesOut(
                spaces=[
                    SpaceOut(
                        name=_label(space, people),
                        personal=True if space.personal_of is not None else None,
                        description=space.description,
                        role=None if (role := space.role_of(user)) is None else role.value,
                        members=[
                            MemberOut(name=people.get(id, "a former account"), role=role.value)
                            for id, role in space.members.items()
                            if id != user
                        ],
                    )
                    for space in sorted(spaces, key=lambda space: _label(space, people))
                ]
            )
        )

    @tools.read(
        "lenses_list",
        "Your lenses (saved views of the documents) with their words and filters; "
        "documents_list takes one by name.",
    )
    async def lenses_list(ctx: Context) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        lenses = await context.lenses.list_lenses(user)
        return compact(LensesOut(lenses=[_lens(lens, names) for lens in lenses]))


async def space_name(context: ApiContext, user: UserId, id: SpaceId) -> str:
    """How the caller reads the space `id`: a personal one by its person's name."""
    space = await context.spaces.get(user, id)
    people = {
        person: item.label for person, item in (await context.spaces.members(user, [space])).items()
    }
    return _label(space, people)


def _label(space: Space, people: dict[UserId, str]) -> str:
    if space.personal_of is not None and space.personal_of in people:
        return people[space.personal_of]
    return space.name


def _lens(lens: Lens, names: Names) -> LensOut:
    chosen = lens.filter

    def named(ids: Iterable[UUID], table: Mapping[UUID, str]) -> list[str]:
        return [table[id] for id in ids if id in table]

    return LensOut(
        name=lens.name,
        query=lens.query,
        contacts=named(chosen.contact_ids, names.contacts),
        document_types=named(chosen.document_type_ids, names.document_types),
        tags=named(chosen.tag_ids, names.tags),
        topics=named(chosen.topic_ids, names.topics),
        document_period=None if chosen.relative_period is None else chosen.relative_period.value,
        document_date_from=None if chosen.date_from is None else chosen.date_from.isoformat(),
        document_date_to=None if chosen.date_to is None else chosen.date_to.isoformat(),
    )
