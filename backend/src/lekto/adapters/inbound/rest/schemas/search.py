"""Search results."""

from pydantic import BaseModel, Field

from lekto.adapters.inbound.rest.schemas.documents import ListedDocument
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.ports.search_index import MAX_HITS
from lekto.core.services.search import SearchMode


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
        description="Whether the meaning took part (`mode` is `hybrid`). False without "
        "embeddings, with `semantic_ratio=0`, or when the embedding service did not answer in "
        "time: the result is by words only then."
    )
    mode: SearchMode = Field(
        description="`hybrid`: by words and meaning; `words`: by words alone, the fallback "
        "that always stays."
    )
    reason: ReasonOut | None = Field(
        description="Why by words alone where the meaning was to take part (not for "
        "`semantic_ratio=0`): `search_no_embeddings`, `search_embed_timeout`, "
        "`search_embed_failed`, `search_embed_dimensions`."
    )
    meaning_pending: bool = Field(
        description="The meaning of the query was not ready in time and is still being made: "
        "the event `search.meaning_ready` with this `query` follows on the caller's event "
        "stream, and the same search then takes the meaning into account."
    )
