"""Search results."""

from pydantic import BaseModel, Field

from lekto.adapters.inbound.rest.schemas.documents import ListedDocument
from lekto.core.ports.search_index import MAX_HITS


class SnippetSegment(BaseModel):
    text: str
    match: bool = Field(description="Whether the words of this piece matched the query.")


class SearchResultItem(BaseModel):
    document: ListedDocument
    score: float | None = Field(
        description="0 to 1, higher is better; only comparable within one result."
    )
    snippet: list[SnippetSegment] = Field(
        description="A piece of the text around the first match, as pieces in order; join "
        "`text` for the plain text. Never markup."
    )


class SearchResultPage(BaseModel):
    items: list[SearchResultItem] = Field(
        description="Best first. A page can hold fewer items than `limit`: hits that the "
        "caller may no longer read, or that are gone, are left out."
    )
    estimated_total: int = Field(
        description=f"An estimate of the hits, not exact. At most {MAX_HITS} hits can be reached."
    )
    next_offset: int | None = Field(
        description="Pass as `offset` for the next page; null on the last page."
    )
    semantic: bool = Field(
        description="Whether the meaning took part. False without embeddings, with "
        "`semantic_ratio=0`, or when the embedding service did not answer in time: the "
        "result is by words only then."
    )
