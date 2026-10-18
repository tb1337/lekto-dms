"""Every document, or those a filter matches, a page at a time: for work over all documents
without holding them in memory at once or one transaction open."""

from collections.abc import AsyncIterator

from papiq.core.domain.documents import Document
from papiq.core.ports import UnitOfWorkFactory
from papiq.core.ports.repository import DocumentFilter, DocumentPosition

PAGE = 500
"""Documents read in one transaction."""


async def document_pages(
    uow: UnitOfWorkFactory, filter: DocumentFilter | None = None, *, size: int = PAGE
) -> AsyncIterator[list[Document]]:
    """The documents `filter` matches (all without one), newest first, `size` at a time; each
    page is read in a transaction of its own."""
    after: DocumentPosition | None = None
    while True:
        async with uow() as unit:
            page = await unit.documents.query(filter or DocumentFilter(), after=after, limit=size)
        if page:
            yield page
        if len(page) < size:
            return
        after = DocumentPosition.after(page[-1].id)
