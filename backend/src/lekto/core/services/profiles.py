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

A user's numbers at contacts (a customer or personnel number that names them, issue #82) are
private like the profile and kept with it (`UserProfile.numbers`): the user enters them, takes
over or declines those training found for them (`ProfileChanges.numbers`, `declined_numbers`);
they are stored at their contacts (`Contact.set_numbers_of`).
"""

import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.identifiers import (
    Identifier,
    IdentifierKind,
    IdentifierSource,
    of_person,
    seen_by,
)
from lekto.core.domain.ids import ContactId, UserId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.profiles import Person, Profile
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import User, display_name_of
from lekto.core.domain.validation import name_key
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor
from lekto.core.services._identifiers import claim_identifiers, member_spaces

log = logging.getLogger(__name__)

USER_NAMES_LOCK = "user-names"
"""The lock (`UnitOfWork.lock`) a unit takes, before its writes, when it adds a username or sets
a display name: a display name is never another user's username, which no index keeps across the
two columns."""


@dataclass(frozen=True)
class ContactNumber:
    """A customer or personnel number at a contact that names the user: entered by hand or
    learned (`identifier.source`)."""

    contact_id: ContactId
    identifier: Identifier


@dataclass(frozen=True)
class UserProfile:
    user: User
    profile: Profile
    numbers: tuple[ContactNumber, ...] = ()


@dataclass(frozen=True)
class ProfileChanges:
    """UNSET leaves a part as it is; None removes the display name, birth date or e-mail.
    `aliases` and `identifiers` replace all of them; `numbers` replaces the user's numbers at
    contacts entered by hand (a learned one given is then entered by hand); `declined_numbers`
    are learned ones the user says are not theirs (they are rejected)."""

    display_name: str | Unset | None = UNSET
    aliases: Collection[str] | Unset = UNSET
    birth_date: date | Unset | None = UNSET
    email: str | Unset | None = UNSET
    identifiers: Collection[Identifier] | Unset = UNSET
    numbers: Collection[ContactNumber] | Unset = UNSET
    declined_numbers: Collection[ContactNumber] | Unset = UNSET

    @property
    def private(self) -> bool:
        """Whether it changes more than the display name and the e-mail address."""
        return not (
            isinstance(self.aliases, Unset)
            and isinstance(self.birth_date, Unset)
            and isinstance(self.identifiers, Unset)
            and isinstance(self.numbers, Unset)
            and isinstance(self.declined_numbers, Unset)
        )


class ProfileService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def get(self, actor: UserId, id: UserId, *, session: bool = True) -> UserProfile:
        """The user themself or an active admin (PermissionDeniedError otherwise), with a
        session; an admin with an API token gets the display name and e-mail address alone
        (the rest stays empty), a user with one nothing."""
        async with self._uow() as uow:
            _, token_admin = await _allowed(uow, actor, id, session)
            user = await uow.users.get(id)
            profile = await uow.profiles.find(id) or Profile.empty(id)
            if token_admin:
                return UserProfile(
                    user, Profile(id=id, email=profile.email, version=profile.version)
                )
            numbers = numbers_of(await uow.contacts.list_all(), id)
        return UserProfile(user, profile, numbers)

    async def update(
        self, actor: UserId, id: UserId, changes: ProfileChanges, *, session: bool = True
    ) -> UserProfile:
        """Change the profile (`ProfileChanges`); the user themself or an active admin, with a
        session; an admin with an API token only the display name and e-mail address
        (PermissionDeniedError for the rest). ConflictError if the display name is another
        user's name or an identifier a contact's entered by hand (naming the contact only to
        whoever sees its identifier there); ValidationError for a birth date in the future;
        NotFoundError for a number at a contact that does not exist."""
        async with self._uow() as uow:
            viewer, token_admin = await _allowed(uow, actor, id, session)
            if token_admin and changes.private:
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
            await check_person_identifiers(uow, profile.evidence(), viewer)
            if display_name != user.display_name:
                user.display_name = display_name
                await uow.users.update(user)
            if stored is None:
                profile.version = 1
                await uow.profiles.add(profile)
            else:
                await uow.profiles.update(profile)
            contacts = await uow.contacts.list_all()
            if not (
                isinstance(changes.numbers, Unset) and isinstance(changes.declined_numbers, Unset)
            ):
                contacts = await _set_numbers(uow, viewer, id, contacts, changes)
            await uow.commit()
        log.info("profile changed", extra={"user_id": str(id), "by": str(actor)})
        return UserProfile(user, profile, numbers_of(contacts, id))


def _kept[T](change: T | Unset, old: T) -> T:
    return old if isinstance(change, Unset) else change


def numbers_of(contacts: Iterable[Contact], user: UserId) -> tuple[ContactNumber, ...]:
    """The numbers at `contacts` that name `user`, entered by hand or learned, by contact."""
    return tuple(
        ContactNumber(contact.id, item)
        for contact in sorted(contacts, key=lambda contact: name_key(contact.name))
        for item in contact.identifiers
        if item.user_id == user and item.counts
    )


async def _set_numbers(
    uow: UnitOfWork,
    viewer: User,
    user: UserId,
    contacts: Sequence[Contact],
    changes: ProfileChanges,
) -> list[Contact]:
    """Store the user's numbers at contacts as `changes` give them (`Contact.set_numbers_of`),
    in `uow`; all contacts as they are afterwards. A value moving from one contact to another
    is given up first: kind and value are unique across contacts."""
    known = {contact.id for contact in contacts}
    entered: dict[ContactId, list[Identifier]] = defaultdict(list)
    declined: dict[ContactId, list[tuple[IdentifierKind, str]]] = defaultdict(list)
    given = [] if isinstance(changes.numbers, Unset) else list(changes.numbers)
    refused = [] if isinstance(changes.declined_numbers, Unset) else list(changes.declined_numbers)
    for number in (*given, *refused):
        if number.contact_id not in known:
            raise NotFoundError("contact", number.contact_id)
    for number in given:
        entered[number.contact_id].append(number.identifier)
    for number in refused:
        declined[number.contact_id].append(number.identifier.key)
    touched = [
        contact
        for contact in contacts
        if contact.id in entered
        or contact.id in declined
        or any(item.user_id == user for item in contact.identifiers)
    ]
    before = {contact.id: list(contact.identifiers) for contact in touched}
    for contact in touched:
        mine = entered[contact.id]
        if isinstance(changes.numbers, Unset):
            mine = [item for item in contact.identifiers if item.user_id == user and item.manual]
        contact.set_numbers_of(user, mine, declined[contact.id])
    changed = [contact for contact in touched if contact.identifiers != before[contact.id]]
    await claim_identifiers(uow, changed, viewer)
    after = {contact.id: list(contact.identifiers) for contact in changed}
    for contact in changed:
        keys = {item.key for item in after[contact.id]}
        if any(item.key not in keys for item in before[contact.id]):
            contact.identifiers = [item for item in before[contact.id] if item.key in keys]
            await uow.contacts.update(contact)
    for contact in changed:
        contact.identifiers = after[contact.id]
        await uow.contacts.update(contact)
    return await uow.contacts.list_all()


async def _allowed(uow: UnitOfWork, actor: UserId, id: UserId, session: bool) -> tuple[User, bool]:
    """The caller, and whether they may see and change the profile of `id` only in part: an
    admin with an API token (True); the user themself and admins with a session wholly
    (False); PermissionDeniedError for anyone else, and for a user's own token."""
    user = await load_actor(uow, actor)
    if user.id != id and not user.is_active_admin:
        raise PermissionDeniedError(because(ReasonCode.PROFILE_OWN_ONLY))
    if session:
        return user, False
    if user.id == id and not user.is_active_admin:
        raise PermissionDeniedError(because(ReasonCode.SESSION_NEEDED))
    return user, True


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


async def check_person_identifiers(
    uow: UnitOfWork, identifiers: Iterable[Identifier], viewer: User | None = None
) -> None:
    """No identifier of the person is one a contact entered by hand, nor a contact's customer or
    personnel number that is one of the person's values (`of_person`) (ConflictError naming the
    contact, if `viewer` sees that identifier: None, an admin, sees all); a contact's learned
    one gives way, in `uow`. Several users may share one (the IBAN of a joint account)."""
    mine = {item.key for item in identifiers}
    if not mine:
        return
    spaces = None
    if viewer is not None and not viewer.is_active_admin:
        spaces = await member_spaces(uow, viewer)
    for contact in await uow.contacts.list_all():
        changed = False
        for theirs in [item for item in contact.identifiers if of_person(item.key, mine)]:
            if theirs.source is IdentifierSource.MANUAL:
                if (
                    viewer is not None
                    and spaces is not None
                    and not seen_by(theirs, viewer.id, spaces)
                ):
                    raise ConflictError(because(ReasonCode.IDENTIFIER_TAKEN, value=theirs.value))
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
