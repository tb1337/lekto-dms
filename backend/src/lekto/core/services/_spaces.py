"""The spaces a document may go to: where its uploader may file it (`SpaceCandidates`)."""

from dataclasses import dataclass

from lekto.core.domain.classifier import OWN_SPACE
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.domain.verdict import SpaceChoice, SpaceOption
from lekto.core.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class SpaceCandidates:
    """The spaces `uploader` may file a document into: their personal space (`personal`), the
    other spaces they edit, and the personal spaces of the other active users (handing over).
    Never a space they only read. `people`: the active users, by id (names for reasons and the
    prompt)."""

    uploader: User
    personal: SpaceId
    spaces: dict[SpaceId, Space]
    people: dict[UserId, User]

    def resolve(self, label: str) -> SpaceId | None:
        """The candidate a classifier label stands for (`OWN_SPACE`: the uploader's personal
        space); None for a space that is none of them."""
        if label == OWN_SPACE:
            return self.personal
        found = next((id for id in self.spaces if str(id) == label), None)
        return found

    def label(self, id: SpaceId) -> str:
        """How reasons and the log name a candidate: the uploader's own personal space, another
        user's personal space by its user, a shared space by its name."""
        space = self.spaces[id]
        if space.personal_of is None:
            return space.name
        if space.personal_of == self.uploader.id:
            return "own personal space"
        person = self.people.get(space.personal_of)
        return f"personal space of {person.username if person else space.personal_of}"

    def choice(self, current: Space, *, locked: bool) -> SpaceChoice:
        """What the judge weighs for a document lying in `current`."""
        spaces = {**self.spaces, current.id: current}
        options = {
            id: SpaceOption(
                name=self._kind(space),
                members=frozenset(space.members),
                personal_of=space.personal_of,
            )
            for id, space in spaces.items()
        }
        return SpaceChoice(
            current=current.id, options=options, locked=locked, uploader=self.uploader.id
        )

    def _kind(self, space: Space) -> str:
        """How the judge's candidates name a space: by its kind, not its name (those who read
        the check may not see it; the web names what its viewer sees)."""
        if space.personal_of is None:
            return "a shared space"
        if space.personal_of == self.uploader.id:
            return "the uploader's personal space"
        return "another user's personal space"


async def space_candidates(uow: UnitOfWork, uploader: UserId | None) -> SpaceCandidates | None:
    """The candidates of `uploader`; None if the document has no active uploader (no one's
    spaces to choose from)."""
    if uploader is None:
        return None
    user = await uow.users.find(uploader)
    if user is None or not user.active:
        return None
    people = {item.id: item for item in await uow.users.list_all() if item.active}
    spaces: dict[SpaceId, Space] = {}
    personal: SpaceId | None = None
    for space in await uow.spaces.list_all():
        if space.personal_of == user.id:
            personal = space.id
            spaces[space.id] = space
        elif space.personal_of is not None:
            if space.personal_of in people:
                spaces[space.id] = space
        else:
            role = space.role_of(user.id)
            if role is not None and role.can_edit:
                spaces[space.id] = space
    if personal is None:
        return None
    return SpaceCandidates(uploader=user, personal=personal, spaces=spaces, people=people)
