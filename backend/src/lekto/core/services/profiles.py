"""Profiles: a user's display name (public) and what is private about them as a person.

A user changes their own profile, signed in with a session; admins change anyone's, with a
session, and with an API token only the display name and e-mail address (a migration fills
them: a leaked token must not read or rewrite what is private). Others see only the display
name (`UserService`). A display name is unique across users regardless of case and never
another user's username (`USER_NAMES_LOCK`); aliases are private and need not be unique. An
identifier of a person is never a contact's (`of_person`, also a customer number that stands in
a social security number): one a contact entered by hand is a conflict, a learned one gives way
(a person's own number was learned by mistake, as an employer's from the pay slips that all
carry it).
"""

import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.errors import ConflictError, PermissionDeniedError, ValidationError
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource, of_person
from lekto.core.domain.ids import UserId
from lekto.core.domain.profiles import Person, Profile
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import User, display_name_of
from lekto.core.domain.validation import name_key
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor

log = logging.getLogger(__name__)

USER_NAMES_LOCK = "user-names"
"""The lock (`UnitOfWork.lock`) a unit takes, before its writes, when it adds a username or sets
a display name: a display name is never another user's username, which no index keeps across the
two columns."""


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

    async def get(self, actor: UserId, id: UserId, *, session: bool = True) -> UserProfile:
        """The user themself or an active admin (PermissionDeniedError otherwise), with a
        session; an admin with an API token gets the display name and e-mail address alone
        (the rest stays empty), a user with one nothing."""
        async with self._uow() as uow:
            token_admin = await _allowed(uow, actor, id, session)
            user = await uow.users.get(id)
            profile = await uow.profiles.find(id) or Profile.empty(id)
        if token_admin:
            profile = Profile(id=id, email=profile.email, version=profile.version)
        return UserProfile(user, profile)

    async def update(
        self, actor: UserId, id: UserId, changes: ProfileChanges, *, session: bool = True
    ) -> UserProfile:
        """Change the profile (`ProfileChanges`); the user themself or an active admin, with a
        session; an admin with an API token only the display name and e-mail address
        (PermissionDeniedError for the rest). ConflictError if the display name is another
        user's name or an identifier a contact's entered by hand; ValidationError for a birth
        date in the future."""
        async with self._uow() as uow:
            token_admin = await _allowed(uow, actor, id, session)
            if token_admin and not (
                isinstance(changes.aliases, Unset)
                and isinstance(changes.birth_date, Unset)
                and isinstance(changes.identifiers, Unset)
            ):
                raise PermissionDeniedError(because(ReasonCode.SESSION_NEEDED_PROFILE))
            if not isinstance(changes.display_name, Unset):
                await uow.lock(USER_NAMES_LOCK)
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
                raise ValidationError(because(ReasonCode.BIRTH_DATE_IN_FUTURE))
            if display_name != user.display_name or not isinstance(changes.aliases, Unset):
                await check_display_name(uow, id, display_name, profile.aliases)
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


async def _allowed(uow: UnitOfWork, actor: UserId, id: UserId, session: bool) -> bool:
    """Whether the caller may see and change the profile of `id` only in part: an admin with an
    API token (True); the user themself and admins with a session wholly (False);
    PermissionDeniedError for anyone else, and for a user's own token."""
    user = await load_actor(uow, actor)
    if user.id != id and not user.is_active_admin:
        raise PermissionDeniedError(because(ReasonCode.PROFILE_OWN_ONLY))
    if session:
        return False
    if user.id == id and not user.is_active_admin:
        raise PermissionDeniedError(because(ReasonCode.SESSION_NEEDED))
    return True


async def check_display_name(
    uow: UnitOfWork, user: UserId, display_name: str | None, aliases: Iterable[str] = ()
) -> None:
    """ConflictError if the display name is another user's display name or username
    (regardless of case); ValidationError if it is one of the user's own `aliases`. Aliases are
    not compared with other users' names: they are private, and a conflict would tell whose one
    is. The unit holds `USER_NAMES_LOCK`."""
    if display_name is None:
        return
    key = name_key(display_name)
    if key in {name_key(alias) for alias in aliases}:
        raise ValidationError(because(ReasonCode.DISPLAY_NAME_IS_ALIAS, name=display_name))
    for other in await uow.users.list_all():
        if other.id == user:
            continue
        theirs = (other.username, other.display_name)
        if any(name is not None and name_key(name) == key for name in theirs):
            raise ConflictError(because(ReasonCode.DISPLAY_NAME_TAKEN, name=display_name))


async def check_username(uow: UnitOfWork, username: str) -> None:
    """ConflictError if `username` is another user's display name (regardless of case). The
    unit holds `USER_NAMES_LOCK`."""
    key = name_key(username)
    for other in await uow.users.list_all():
        if other.display_name is not None and name_key(other.display_name) == key:
            raise ConflictError(because(ReasonCode.USERNAME_OF_OTHER, username=username))


async def check_person_identifiers(uow: UnitOfWork, identifiers: Iterable[Identifier]) -> None:
    """No identifier of the person is one a contact entered by hand, nor a contact's customer or
    personnel number that is one of the person's values (`of_person`) (ConflictError naming the
    contact); a contact's learned one gives way, in `uow`. Several users may share one (the IBAN
    of a joint account)."""
    mine = {item.key for item in identifiers}
    if not mine:
        return
    for contact in await uow.contacts.list_all():
        changed = False
        for theirs in [item for item in contact.identifiers if of_person(item.key, mine)]:
            if theirs.source is IdentifierSource.MANUAL:
                raise ConflictError(
                    because(
                        ReasonCode.PROFILE_IDENTIFIER_OF_CONTACT,
                        value=theirs.value,
                        contact=contact.name,
                    )
                )
            changed |= contact.drop_identifier(theirs.key)
        if changed:
            await uow.contacts.update(contact)


async def person_identifiers(uow: UnitOfWork) -> set[tuple[IdentifierKind, str]]:
    """The identifiers of every user's profile (with their e-mail addresses): never a
    contact's."""
    return {item.key for profile in await uow.profiles.list_all() for item in profile.evidence()}


async def matching_persons(uow: UnitOfWork, viewer: User | None = None) -> list[Person]:
    """What finds the active users in a document (`domain.facts`); for a `viewer` who is no
    admin, every other user in their public form (`Person.public`: by display name alone)."""
    profiles = {item.id: item for item in await uow.profiles.list_all()}
    persons = [
        Person.of(user, profiles.get(user.id)) for user in await uow.users.list_all() if user.active
    ]
    if viewer is None or viewer.is_active_admin:
        return persons
    return [person if person.user_id == viewer.id else person.public() for person in persons]


async def new_profile_hints(
    uow: UnitOfWork, user: User, display_name: str | None, email: str | None
) -> None:
    """Fill a new user's display name and e-mail from hints (an identity provider's claims,
    a migration): only what is free and valid; nothing else is touched. The unit holds
    `USER_NAMES_LOCK` (`users.add_user` takes it)."""
    name = None
    try:
        name = display_name_of(display_name)
        if name is not None:
            await check_display_name(uow, user.id, name)
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
