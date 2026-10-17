"""Logos of contacts: uploaded by admins, read by everyone, gone with their contact; the file
and the contact always tell the same logo."""

import asyncio

import pytest

from papiq.adapters.outbound.memory import FAKE_LOGO
from papiq.core.domain.appearance import LogoSource
from papiq.core.domain.errors import (
    ImageError,
    NotFoundError,
    PermissionDeniedError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from papiq.core.domain.ids import ContactId, new_id
from papiq.core.domain.users import Role
from papiq.core.services.logos import LOGO_MAX_SIZE
from papiq.core.services.objects import logo_key
from tests.builders import NOW
from tests.contracts.images import SVG, image
from tests.unit.services.conftest import World

PNG = image((200, 100))


async def test_an_admin_uploads_a_logo_everyone_reads(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    contact = await world.master_data.create_contact(admin.id, "Nord")
    stored = await world.logos.upload(admin.id, contact.id, PNG)
    assert stored.logo is not None
    assert (stored.logo.source, stored.logo.stored_at, stored.logo.domain) == (
        LogoSource.UPLOADED,
        NOW,
        None,
    )
    assert await world.object_store.get(logo_key(contact.id)) == FAKE_LOGO
    read = await world.logos.logo(user.id, contact.id)
    assert (read.data, read.logo) == (FAKE_LOGO, stored.logo)
    with pytest.raises(PermissionDeniedError):
        await world.logos.upload(user.id, contact.id, PNG)
    with pytest.raises(PermissionDeniedError):
        await world.logos.remove(user.id, contact.id)

    removed = await world.logos.remove(admin.id, contact.id)
    assert removed.logo is None
    assert not await world.object_store.exists(logo_key(contact.id))
    with pytest.raises(NotFoundError):
        await world.logos.logo(user.id, contact.id)


async def test_what_is_no_logo_changes_nothing(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    contact = await world.master_data.create_contact(admin.id, "Nord")
    for data, error in (
        (SVG, UnsupportedMediaTypeError),
        (image((40, 40), "ICO"), UnsupportedMediaTypeError),
        (PNG[:30], ImageError),
        (b"\x89PNG\r\n\x1a\n" + bytes(LOGO_MAX_SIZE), ValidationError),
    ):
        with pytest.raises(error):
            await world.logos.upload(admin.id, contact.id, data)
    async with world.uow() as uow:
        assert (await uow.contacts.get(contact.id)).logo is None
    assert not await world.object_store.exists(logo_key(contact.id))
    with pytest.raises(NotFoundError):
        await world.logos.upload(admin.id, ContactId(new_id()), PNG)


async def test_a_logo_goes_with_its_contact_also_while_one_is_stored(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    contact = await world.master_data.create_contact(admin.id, "Nord")
    # An upload and the deletion at once: whichever comes second sees the first's result, so
    # no file stays behind without its contact.
    upload, deletion = await asyncio.gather(
        world.logos.upload(admin.id, contact.id, PNG),
        world.master_data.delete_contact(admin.id, contact.id),
        return_exceptions=True,
    )
    assert deletion is None
    assert not isinstance(upload, Exception) or isinstance(upload, NotFoundError)
    assert not await world.object_store.exists(logo_key(contact.id))
    async with world.uow() as uow:
        assert await uow.contacts.find(contact.id) is None
