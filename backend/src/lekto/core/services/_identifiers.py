"""Who sees a contact's identifiers and whose they are, for the services of master data and of
profiles (issue #82, `identifiers.seen_by`): admins see all of them; anyone else what is
everyone's, their own numbers and what was learned in their spaces. A conflict names another
contact, or tells that a value is a person's, only to whoever sees that; others learn that the
value is taken, not whose."""

from collections.abc import Sequence
from dataclasses import replace

from lekto.core.domain.errors import ConflictError
from lekto.core.domain.identifiers import (
    Identifier,
    IdentifierKind,
    IdentifierSource,
    of_person,
    related_keys,
    seen_by,
)
from lekto.core.domain.ids import SpaceId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import User
from lekto.core.ports.unit_of_work import UnitOfWork


async def person_identifiers(uow: UnitOfWork) -> set[tuple[IdentifierKind, str]]:
    """The identifiers of every user's profile (with their e-mail addresses): never a
    contact's."""
    return {item.key for profile in await uow.profiles.list_all() for item in profile.evidence()}


async def member_spaces(uow: UnitOfWork, user: User) -> frozenset[SpaceId]:
    """The spaces `user` is a member of, in any role (an admin's own memberships alone)."""
    return frozenset(space.id for space in await uow.spaces.list_accessible(user.id))


def as_seen(contact: Contact, user: User, spaces: frozenset[SpaceId]) -> Contact:
    """`contact` as `user` sees it (`spaces`: those they are a member of): everything for an
    admin, else only the identifiers `seen_by` them."""
    if user.is_active_admin:
        return contact
    shown = [item for item in contact.identifiers if seen_by(item, user.id, spaces)]
    if len(shown) == len(contact.identifiers):
        return contact
    return replace(contact, identifiers=shown)


async def claim_identifiers(
    uow: UnitOfWork, contacts: Sequence[Contact], viewer: User | None = None
) -> None:
    """The identifiers of `contacts`, changed together, are theirs: none is a person's (a
    user's profile, `of_person`) and none one another contact entered by hand (ConflictError);
    another contact's learned or rejected one gives way, in `uow` (a person's choice is the
    newer word). Those of `contacts` that give way to one another are changed in place, for the
    caller to store; the others are updated here. A conflict names the other contact, or the
    person's value, only where `viewer` sees it (None: an admin, who sees everything)."""
    spaces = None
    if viewer is not None and not viewer.is_active_admin:
        spaces = await member_spaces(uow, viewer)
    persons = await person_identifiers(uow)
    own: set[tuple[IdentifierKind, str]] = set()
    if viewer is not None and (profile := await uow.profiles.find(viewer.id)) is not None:
        own = {item.key for item in profile.evidence()}

    def sees(item: Identifier) -> bool:
        return viewer is None or spaces is None or seen_by(item, viewer.id, spaces)

    changing = {contact.id: contact for contact in contacts}
    others = [changing.get(other.id, other) for other in await uow.contacts.list_all()]
    dropped: list[Contact] = []
    for contact in contacts:
        mine = {item.key for item in contact.identifiers}
        same = {related for key in mine for related in related_keys(key)}
        personal = sorted(key for key in mine if of_person(key, persons))
        if personal:
            _, value = personal[0]
            if spaces is not None and not of_person(personal[0], own):
                raise ConflictError(because(ReasonCode.IDENTIFIER_TAKEN, value=value))
            raise ConflictError(because(ReasonCode.IDENTIFIER_OF_PERSON, value=value))
        for other in others:
            if other.id == contact.id:
                continue
            changed = False
            for theirs in [item for item in other.identifiers if item.key in same]:
                if theirs.source is IdentifierSource.MANUAL:
                    if not sees(theirs):
                        raise ConflictError(
                            because(ReasonCode.IDENTIFIER_TAKEN, value=theirs.value)
                        )
                    raise ConflictError(
                        because(
                            ReasonCode.IDENTIFIER_OF_CONTACT,
                            value=theirs.value,
                            contact=other.name,
                        )
                    )
                changed |= other.drop_identifier(theirs.key)
            if changed and other.id not in changing and other not in dropped:
                dropped.append(other)
    for other in dropped:
        await uow.contacts.update(other)
