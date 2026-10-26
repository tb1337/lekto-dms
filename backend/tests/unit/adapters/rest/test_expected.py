"""`GET /expected` (#145 PR 12)."""

from datetime import date, datetime

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.master_data import Contact, DocumentType
from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import Api


async def test_the_expected_documents_of_the_caller(api: Api) -> None:
    owner = await api.user()
    found = await api.client.get(f"{PREFIX}/expected", headers=auth(owner))
    assert (found.status_code, found.json()) == (200, [])
    others = await api.client.get(f"{PREFIX}/expected?all_users=true", headers=auth(owner))
    assert others.status_code == 403
    admin = await api.admin()
    every = await api.client.get(f"{PREFIX}/expected?all_users=true", headers=auth(admin))
    assert every.status_code == 200


async def test_a_series_as_the_api_gives_it(api: Api) -> None:
    owner = await api.user()
    uow = api.container.unit_of_work
    contact = Contact.create(name="Stadtwerke", now=builders.NOW)
    kind = DocumentType.create(name="Abschlag", now=builders.NOW)
    async with uow() as unit:
        await unit.contacts.add(contact)
        await unit.document_types.add(kind)
        space = await unit.spaces.get_personal(owner.id)
        for month in (7, 8, 9):
            document = builders.processed(owner, space)
            document.apply_changes(
                DocumentChanges(
                    contact_id=contact.id,
                    document_type_id=kind.id,
                    document_date=date(2026, month, 15),
                ),
                {},
                builders.NOW,
            )
            await unit.documents.add(document)
        await unit.commit()
    api.clock.set(datetime(2026, 10, 1, 12, tzinfo=builders.NOW.tzinfo))
    found = await api.client.get(f"{PREFIX}/expected?tz=Europe/Berlin", headers=auth(owner))
    (series,) = found.json()
    assert {
        key: series[key]
        for key in ("contact", "cadence", "spread_days", "documents", "next_date", "state")
    } == {
        "contact": {"id": str(contact.id), "name": "Stadtwerke"},
        "cadence": "monthly",
        "spread_days": 2,
        "documents": 3,
        "next_date": "2026-10-15",
        "state": "soon",
    }
    unknown = await api.client.get(f"{PREFIX}/expected?tz=Mars/Base", headers=auth(owner))
    assert unknown.status_code == 422
