"""The open identifiers (`domain.open_identifiers`) for admins: the list across all contacts and
documents, where one stands in its documents, and a person's decisions about them, one at a
time or many at once. Confirming one enters it at a contact (the learned one's own, or the one
its documents name); rejecting one takes it out there or notes it rejected, so training does not
learn it again. A suggestion for a person goes into their profile, or is noted there as
declined (`Profile.declined`); that needs a session, as other changes of a profile do. Each
decision is a change of its contact or profile on its own: one that fails (another contact
entered the value meanwhile) leaves the others done."""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.identifiers import (
    CONTACT_KINDS,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    Key,
)
from lekto.core.domain.ids import ContactId, DocumentId, UserId
from lekto.core.domain.open_identifiers import (
    Excerpt,
    OpenIdentifier,
    OpenSource,
    Recommendation,
    Sighting,
    excerpt,
    open_identifiers,
)
from lekto.core.domain.profiles import Profile
from lekto.core.domain.reasons import Action, Reason, ReasonCode, because
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import require_admin
from lekto.core.services._identifiers import person_identifiers
from lekto.core.services.master_data import MasterDataService
from lekto.core.services.objects import load_text
from lekto.core.services.profiles import (
    check_person_identifiers,
    matching_persons,
    save_profile,
)

PLACES = 5
"""Documents whose places a detail shows, the newest first."""


class OpenAction(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


@dataclass(frozen=True, kw_only=True)
class OpenDecision:
    """What a person decides about the open identifier of `kind` and `value`. `contact`: where;
    without one, the learned one's contact, or the one contact an unknown one's documents
    name (confirming one whose documents name several needs it; rejecting it notes it at the
    one with most documents)."""

    kind: IdentifierKind
    value: str
    action: OpenAction
    contact: ContactId | None = None

    @property
    def key(self) -> Key:
        return self.kind, self.value


@dataclass(frozen=True)
class DecisionOutcome:
    """How a decision went: `error` why it was not done, None if it was."""

    kind: IdentifierKind
    value: str
    error: Reason | None = None


@dataclass(frozen=True)
class OpenPage:
    """A page of the open identifiers after the filters (`total` of them), how many are open
    under each source and of each kind with the other filters, how many have a recommendation
    (`recommended`, counted as the sources are), how many of all have one to confirm
    (`to_confirm`: what `confirm_recommended` confirms), and the names of the contacts and the
    persons the page names."""

    items: list[OpenIdentifier]
    total: int
    counts: Mapping[OpenSource, int]
    kinds: Mapping[IdentifierKind, int]
    names: Mapping[ContactId, str]
    persons: Mapping[UserId, str]
    recommended: int = 0
    to_confirm: int = 0


@dataclass(frozen=True)
class Place:
    """Where an open identifier stands in one of its documents: the document's title and date,
    the fact's role there, and the text around it (None if the document has no text or the
    fact no position)."""

    document: DocumentId
    title: str
    dated: date
    role: FactRole
    excerpt: Excerpt | None


@dataclass(frozen=True)
class OpenDetail:
    item: OpenIdentifier
    places: list[Place]
    names: Mapping[ContactId, str]
    persons: Mapping[UserId, str]


class OpenIdentifierService:
    def __init__(
        self, uow: UnitOfWorkFactory, store: ObjectStore, master_data: MasterDataService
    ) -> None:
        self._uow = uow
        self._store = store
        self._master_data = master_data

    async def page(
        self,
        actor: UserId,
        *,
        source: OpenSource | None = None,
        kind: IdentifierKind | None = None,
        words: str | None = None,
        recommended: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> OpenPage:
        """The open identifiers (admins), the most documents first: of `source` and `kind` if
        given, with `words` in the value (with or without spaces), as written or in the name
        of a contact or a person, and with `recommended` only those with a recommendation."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            found, names, persons, _ = await _open(uow)
        to_confirm = len([item for item in found if _to_confirm(item)])
        if words is not None and words.strip():
            found = [item for item in found if _matches(item, words, names, persons)]
        counts = Counter(item.source for item in found if kind is None or item.kind is kind)
        kinds = Counter(item.kind for item in found if source is None or item.source is source)
        chosen = [
            item
            for item in found
            if (source is None or item.source is source) and (kind is None or item.kind is kind)
        ]
        # Counted as the sources are, without the choice of a source.
        advised = sum(
            1
            for item in found
            if item.recommended is not None and (kind is None or item.kind is kind)
        )
        if recommended:
            chosen = [item for item in chosen if item.recommended is not None]
        page = chosen[offset : offset + limit]
        shown = {contact for item in page for contact in item.contacts}
        users = {item.person for item in page if item.person is not None}
        return OpenPage(
            items=page,
            total=len(chosen),
            counts={each: counts.get(each, 0) for each in OpenSource},
            kinds=dict(sorted(kinds.items())),
            names={id: name for id, name in names.items() if id in shown},
            persons={id: name for id, name in persons.items() if id in users},
            recommended=advised,
            to_confirm=to_confirm,
        )

    async def summary(self, actor: UserId) -> Mapping[OpenSource, int]:
        """How many identifiers are open under each source (admins)."""
        page = await self.page(actor, limit=0)
        return page.counts

    async def detail(self, actor: UserId, kind: IdentifierKind, value: str) -> OpenDetail:
        """The open identifier of `kind` and `value` (admins) and where it stands in its newest
        documents; NotFoundError if it is not open."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            found, names, persons, _ = await _open(uow)
            item = next((each for each in found if each.key == (kind, value)), None)
            if item is None:
                raise NotFoundError(
                    "identifier", value, because(ReasonCode.IDENTIFIER_NOT_OPEN, value=value)
                )
            newest = item.seen[:PLACES]
            documents = {each.document: await uow.documents.find(each.document) for each in newest}
        places = []
        for seen in newest:
            document = documents.get(seen.document)
            if document is None:
                continue
            places.append(
                Place(
                    document=seen.document,
                    title=document.title,
                    dated=seen.dated,
                    role=seen.fact.role,
                    excerpt=await self._excerpt(seen),
                )
            )
        return OpenDetail(
            item,
            places,
            {id: names[id] for id in item.contacts if id in names},
            {} if item.person is None else {item.person: persons.get(item.person, "")},
        )

    async def _excerpt(self, seen: Sighting) -> Excerpt | None:
        """The text around the fact where it first stands in its document."""
        fact = seen.fact
        if fact.position is None:
            return None
        try:
            text = (await load_text(self._store, seen.document)).decode("utf-8", "replace")
        except NotFoundError:
            return None
        return excerpt(text, fact.position, len(fact.written or fact.value))

    async def decide(
        self, actor: UserId, decisions: Sequence[OpenDecision], *, session: bool = True
    ) -> list[DecisionOutcome]:
        """Keep each of `decisions` (admins), each a change of its contact or profile on its
        own; one that cannot be done says why, and the others are done all the same. A
        decision about a person's suggestion needs a `session`."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            found, _, _, learned = await _open(uow)
        open = {item.key: item for item in found}
        outcomes = []
        for decision in decisions:
            kind, value = decision.key
            try:
                await self._decide(actor, decision, open.get(decision.key), learned, session)
            except (
                ConflictError,
                NotFoundError,
                PermissionDeniedError,
                ValidationError,
            ) as error:
                outcomes.append(DecisionOutcome(kind, value, error.reason))
            else:
                outcomes.append(DecisionOutcome(kind, value))
        return outcomes

    async def confirm_recommended(
        self, actor: UserId, *, session: bool = True
    ) -> list[DecisionOutcome]:
        """Confirm every open identifier whose documents recommend it (admins, Tobi
        28.10.2026), each as `decide` confirms one: at its contact by hand, a suggested one at
        the contact or the person its documents name. One that cannot be done says why. Never
        rejects: a rejected one is never learned again and leaves the list unseen."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            found, _, _, _ = await _open(uow)
        decisions = [
            OpenDecision(kind=item.kind, value=item.value, action=OpenAction.CONFIRM)
            for item in found
            if _to_confirm(item)
        ]
        if not decisions:
            return []
        return await self.decide(actor, decisions, session=session)

    async def _decide(
        self,
        actor: UserId,
        decision: OpenDecision,
        item: OpenIdentifier | None,
        learned: Mapping[Key, Identifier],
        session: bool,
    ) -> None:
        kind, value = decision.key
        if item is None:
            raise NotFoundError(
                "identifier", value, because(ReasonCode.IDENTIFIER_NOT_OPEN, value=value)
            )
        if item.person is not None:
            if not session:
                raise PermissionDeniedError(because(ReasonCode.SESSION_NEEDED_PROFILE))
            await self._at_person(actor, item.person, decision)
            return
        contact = decision.contact
        if contact is None:
            if decision.action is OpenAction.CONFIRM and len(item.contacts) != 1:
                raise ValidationError(because(ReasonCode.IDENTIFIER_CONTACT_UNCLEAR, value=value))
            contact = item.contacts[0]
        if decision.action is OpenAction.REJECT:
            await self._master_data.reject_identifier(actor, contact, decision.key)
            return
        # A learned one keeps its topic and user at its own contact; another contact's topics
        # and users are not its.
        held = learned.get(decision.key) if contact in item.contacts else None
        entered = Identifier(
            kind,
            value,
            topic_id=None if held is None else held.topic_id,
            user_id=None if held is None else held.user_id,
        )
        await self._master_data.add_identifier(actor, contact, entered)

    async def _at_person(self, actor: UserId, user: UserId, decision: OpenDecision) -> None:
        """Enter a suggested identifier in the profile of `user`, or note it declined there."""
        async with self._uow() as uow:
            viewer = await uow.users.get(actor)
            stored = await uow.profiles.find(user)
            old = stored or Profile.empty(user)
            entered = Identifier(*decision.key)
            if decision.action is OpenAction.CONFIRM:
                profile = replace(old, identifiers=[*old.identifiers, entered])
                await check_person_identifiers(uow, profile.evidence(), viewer)
            else:
                profile = replace(old, declined=[*old.declined, entered])
            await save_profile(uow, stored, profile)
            await uow.commit()


async def _open(
    uow: UnitOfWork,
) -> tuple[list[OpenIdentifier], dict[ContactId, str], dict[UserId, str], dict[Key, Identifier]]:
    """The open identifiers, the names of the contacts and the persons, and the identifiers
    training learned by key (each at one contact)."""
    contacts = await uow.contacts.list_all()
    sightings = await uow.document_facts.sightings(CONTACT_KINDS)
    personal = await person_identifiers(uow)
    persons = await matching_persons(uow)
    declined = {
        profile.id: [item.key for item in profile.declined]
        for profile in await uow.profiles.list_all()
    }
    names = {contact.id: contact.name for contact in contacts}
    learned = {
        item.key: item
        for contact in contacts
        for item in contact.identifiers
        if item.source is IdentifierSource.LEARNED
    }
    found = open_identifiers(contacts, sightings, personal, persons, declined)
    return found, names, {person.user_id: person.display_name or "" for person in persons}, learned


def _to_confirm(item: OpenIdentifier) -> bool:
    """Whether the documents recommend confirming `item`."""
    return item.recommended is not None and item.recommended.action is Recommendation.CONFIRM


def _compact(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def _matches(
    item: OpenIdentifier,
    words: str,
    names: Mapping[ContactId, str],
    persons: Mapping[UserId, str],
) -> bool:
    wanted = words.strip().casefold()
    compact = _compact(words)
    texts: Collection[str] = [
        item.value,
        item.written,
        *(names.get(id, "") for id in item.contacts),
        "" if item.person is None else persons.get(item.person, ""),
    ]
    return any(wanted in text.casefold() for text in texts) or (
        bool(compact) and compact in _compact(item.value)
    )
