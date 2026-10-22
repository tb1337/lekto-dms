"""Profiles: a user's display name (public) and what is private about them as a person.

A user changes their own profile; admins change anyone's (a migration fills them). Others see
only the display name (`UserService`). Display names and aliases are unique across users
regardless of case; an identifier of a person is never a contact's: one a contact entered by
hand is a conflict, a learned one gives way (a person's own number was learned by mistake, as an
employer's from the pay slips that all carry it).
"""

import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.errors import ConflictError, PermissionDeniedError, ValidationError
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.ids import UserId
from lekto.core.domain.profiles import Person, Profile
from lekto.core.domain.users import User, display_name_of
from lekto.core.domain.validation import name_key
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserProfile:
    user: User
    profile: Profile


@dataclass(frozen=True)
class ProfileChanges:
    """UNSET leaves a part as it is; None removes the display name, birth date or e-mail.
    `aliases` and `identifiers` replace all of them."""

    display_name: str | Unset | None = UNSET
    aliases: Collection[str] | Unset = UNSET
    birth_date: date | Unset | None = UNSET
    email: str | Unset | None = UNSET
    identifiers: Collection[Identifier] | Unset = UNSET


class ProfileService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def get(self, actor: UserId, id: UserId) -> UserProfile:
        """The user themself or an active admin (PermissionDeniedError otherwise)."""
        async with self._uow() as uow:
            await _allowed(uow, actor, id)
            user = await uow.users.get(id)
            profile = await uow.profiles.find(id) or Profile.empty(id)
        return UserProfile(user, profile)

    async def update(self, actor: UserId, id: UserId, changes: ProfileChanges) -> UserProfile:
        """Change the profile (`ProfileChanges`); the user themself or an active admin.
        ConflictError if a name is another user's or an identifier a contact's entered by hand;
        ValidationError for a birth date in the future."""
        async with self._uow() as uow:
            await _allowed(uow, actor, id)
            user = await uow.users.get(id)
            stored = await uow.profiles.find(id)
            old = stored or Profile.empty(id)
            display_name = (
                user.display_name
                if isinstance(changes.display_name, Unset)
                else display_name_of(changes.display_name)
            )
            profile = Profile(
                id=id,
                aliases=list(_kept(changes.aliases, old.aliases)),
                birth_date=_kept(changes.birth_date, old.birth_date),
                email=_kept(changes.email, old.email),
                identifiers=list(_kept(changes.identifiers, old.identifiers)),
                version=old.version,
            )
            if profile.birth_date is not None and profile.birth_date > self._clock.now().date():
                raise ValidationError("a birth date in the future")
            await check_person_names(uow, id, display_name, profile.aliases)
            await check_person_identifiers(uow, profile.evidence())
            if display_name != user.display_name:
                user.display_name = display_name
                await uow.users.update(user)
            if stored is None:
                profile.version = 1
                await uow.profiles.add(profile)
            else:
                await uow.profiles.update(profile)
            await uow.commit()
        log.info("profile changed", extra={"user_id": str(id), "by": str(actor)})
        return UserProfile(user, profile)


def _kept[T](change: T | Unset, old: T) -> T:
    return old if isinstance(change, Unset) else change


async def _allowed(uow: UnitOfWork, actor: UserId, id: UserId) -> None:
    user = await load_actor(uow, actor)
    if user.id != id and not user.is_active_admin:
        raise PermissionDeniedError("only the user and admins see and change a profile")


async def check_person_names(
    uow: UnitOfWork, user: UserId, display_name: str | None, aliases: Iterable[str]
) -> None:
    """ConflictError if the display name or an alias is one of another user's names (display
    name or alias, regardless of case), or the display name one of the user's own aliases."""
    mine = [name for name in (display_name, *aliases) if name]
    keys = [name_key(name) for name in mine]
    if display_name is not None and name_key(display_name) in keys[1:]:
        raise ValidationError(f"'{display_name}' is the display name and an alias")
    wanted = dict(zip(keys, mine, strict=True))
    if not wanted:
        return
    profiles = {item.id: item for item in await uow.profiles.list_all()}
    for other in await uow.users.list_all():
        if other.id == user:
            continue
        profile = profiles.get(other.id)
        theirs = [other.display_name, *(profile.aliases if profile else ())]
        for name in theirs:
            if name and name_key(name) in wanted:
                raise ConflictError(f"'{wanted[name_key(name)]}' is the name of another user")


async def check_person_identifiers(uow: UnitOfWork, identifiers: Iterable[Identifier]) -> None:
    """No identifier of the person is one a contact entered by hand (ConflictError naming the
    contact); a contact's learned one gives way, in `uow`. Several users may share one (the IBAN
    of a joint account)."""
    mine = {item.key for item in identifiers}
    if not mine:
        return
    for contact in await uow.contacts.list_all():
        changed = False
        for theirs in [item for item in contact.identifiers if item.key in mine]:
            if theirs.source is IdentifierSource.MANUAL:
                raise ConflictError(
                    f"'{theirs.value}' is an identifier of the contact '{contact.name}'"
                )
            changed |= contact.drop_identifier(theirs.key)
        if changed:
            await uow.contacts.update(contact)


async def person_identifiers(uow: UnitOfWork) -> set[tuple[IdentifierKind, str]]:
    """The identifiers of every user's profile (with their e-mail addresses): never a
    contact's."""
    return {item.key for profile in await uow.profiles.list_all() for item in profile.evidence()}


async def matching_persons(uow: UnitOfWork) -> list[Person]:
    """What finds the active users in a document (`domain.facts`)."""
    profiles = {item.id: item for item in await uow.profiles.list_all()}
    return [
        Person.of(user, profiles.get(user.id)) for user in await uow.users.list_all() if user.active
    ]


async def new_profile_hints(
    uow: UnitOfWork, user: User, display_name: str | None, email: str | None
) -> None:
    """Fill a new user's display name and e-mail from hints (an identity provider's claims,
    a migration): only what is free and valid; nothing else is touched."""
    name = None
    try:
        name = display_name_of(display_name)
        if name is not None:
            await check_person_names(uow, user.id, name, ())
    except (ValidationError, ConflictError):
        name = None
    if name is not None:
        user.display_name = name
        await uow.users.update(user)
    if email is None:
        return
    try:
        profile = Profile(id=user.id, email=email, version=1)
        await check_person_identifiers(uow, profile.evidence())
    except (ValidationError, ConflictError):
        return
    await uow.profiles.add(profile)
