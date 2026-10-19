"""Work over all documents reads them a page at a time."""

from lekto.core.ports.repository import DocumentFilter
from lekto.core.services._pages import document_pages
from tests import builders
from tests.unit.services.support import World


async def test_every_document_once_a_page_at_a_time(world: World) -> None:
    owner = await world.user()
    space = await world.default_space(owner)
    documents = [builders.document(owner, space) for _ in range(5)]
    async with world.uow() as uow:
        for document in documents:
            await uow.documents.add(document)
        await uow.commit()

    pages = [page async for page in document_pages(world.uow, size=2)]

    assert [len(page) for page in pages] == [2, 2, 1]
    assert {document.id for page in pages for document in page} == {d.id for d in documents}


async def test_only_what_the_filter_matches(world: World) -> None:
    owner = await world.user()
    space = await world.default_space(owner)
    async with world.uow() as uow:
        await uow.documents.add(builders.document(owner, space))
        await uow.commit()

    confirmed = [page async for page in document_pages(world.uow, DocumentFilter(confirmed=True))]

    assert confirmed == []
