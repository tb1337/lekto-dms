"""Logos of contacts: uploaded by admins, read by every signed-in user (master data is global).

The logo is stored as a small WebP at `objects.logo_key`; the contact names where it came from
and when (`Contact.logo`). Storing and removing the file and the contact's change happen under
one lock per contact (`logo_lock`), so that the file and the contact always tell the same
logo, also when an upload, a removal, a deletion of the contact and a fetch meet.
"""

from dataclasses import dataclass

from papiq.core.domain import media_types
from papiq.core.domain.appearance import ContactLogo, LogoSource
from papiq.core.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from papiq.core.domain.ids import ContactId, UserId
from papiq.core.domain.master_data import Contact
from papiq.core.domain.permissions import can_manage_master_data
from papiq.core.ports import Clock, ImageNormaliser, ObjectStore, UnitOfWork, UnitOfWorkFactory
from papiq.core.services._access import load_actor
from papiq.core.services.objects import logo_key

LOGO_MAX_SIZE = 1024 * 1024
"""Bytes of an uploaded image."""
LOGO_TYPE = "image/webp"


def logo_lock(contact: ContactId) -> str:
    """The lock (`UnitOfWork.lock`) a unit takes before it stores or removes the logo of a
    contact, or deletes the contact."""
    return f"contact-logo:{contact}"


@dataclass(frozen=True)
class StoredLogo:
    data: bytes  # WebP
    logo: ContactLogo


class LogoService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        store: ObjectStore,
        images: ImageNormaliser,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._store = store
        self._images = images

    async def upload(self, actor: UserId, id: ContactId, data: bytes) -> Contact:
        """Admins only. `data`, a PNG, JPEG or WebP image of at most `LOGO_MAX_SIZE` bytes,
        becomes the contact's logo, in place of any other; a fetched one never replaces it.
        UnsupportedMediaTypeError for another kind (SVG: it can carry scripts),
        ValidationError if it is too large, ImageError if it cannot be read."""
        async with self._uow() as uow:
            await _require_admin(uow, actor)
            await uow.contacts.get(id)
        if len(data) > LOGO_MAX_SIZE:
            raise ValidationError(f"a logo is at most {LOGO_MAX_SIZE} bytes")
        if media_types.detect_image(data[: media_types.SNIFF_SIZE]) not in media_types.LOGO_UPLOADS:
            raise UnsupportedMediaTypeError("a logo is a PNG, JPEG or WebP image")
        image = await self._images.normalise(data)
        async with self._uow() as uow:
            await uow.lock(logo_lock(id))
            await _require_admin(uow, actor)
            contact = await uow.contacts.get(id)
            await self._store.put(logo_key(id), image, content_type=LOGO_TYPE)
            contact.set_logo(ContactLogo(source=LogoSource.UPLOADED, stored_at=self._clock.now()))
            await uow.contacts.update(contact)
            await uow.commit()
        return contact

    async def remove(self, actor: UserId, id: ContactId) -> Contact:
        """Admins only: the contact shows its initials again; a failed fetch noted is
        forgotten."""
        async with self._uow() as uow:
            await uow.lock(logo_lock(id))
            await _require_admin(uow, actor)
            contact = await uow.contacts.get(id)
            if contact.logo is None and contact.logo_failure is None:
                return contact
            contact.remove_logo()
            await uow.contacts.update(contact)
            await self._store.delete(logo_key(id))
            await uow.commit()
        return contact

    async def logo(self, actor: UserId, id: ContactId) -> StoredLogo:
        """Every signed-in user. NotFoundError if the contact has no logo."""
        async with self._uow() as uow:
            await load_actor(uow, actor)
            contact = await uow.contacts.get(id)
        if contact.logo is None:
            raise NotFoundError("logo of contact", id)
        return StoredLogo(await self._store.get(logo_key(id)), contact.logo)


async def drop_logo(uow: UnitOfWork, store: ObjectStore, contact: ContactId) -> None:
    """Before a contact is deleted, in `uow`: its logo goes with it. Takes the contact's logo
    lock (the unit's only one), so that no logo is stored for it meanwhile."""
    await uow.lock(logo_lock(contact))
    await store.delete(logo_key(contact))


async def _require_admin(uow: UnitOfWork, actor: UserId) -> None:
    if not can_manage_master_data(await load_actor(uow, actor)):
        raise PermissionDeniedError("only admins change master data")
