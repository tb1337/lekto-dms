"""Search results."""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from lekto.adapters.inbound.rest.schemas.documents import ListedDocument
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.ports.search_index import MAX_HITS
from lekto.core.services.indexing import IndexCheck, IndexStatus, JobTimes
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


def _ms(value: timedelta) -> float:
    return round(value.total_seconds() * 1000, 1)


class IndexStatsOut(BaseModel):
    documents: int = Field(description="Documents in the index.")
    embedded: int = Field(description="Of them, those with vectors (of any model).")
    vectors: int = Field(description="Vectors in all, one per section of a text.")
    indexing: bool = Field(description="Whether the index is writing right now.")
    size_bytes: int | None = Field(description="Its size on disk, if the index tells.")


class JobTimesOut(BaseModel):
    count: int = Field(description="Index jobs done in the period.")
    median_ms: float
    p90_ms: float

    @classmethod
    def of(cls, times: JobTimes | None) -> "JobTimesOut | None":
        if times is None:
            return None
        return cls(count=times.count, median_ms=_ms(times.median), p90_ms=_ms(times.p90))


class SearchStatusOut(BaseModel):
    documents: int = Field(description="Documents in the database.")
    index: IndexStatsOut
    running: int = Field(description="Index jobs running now.")
    queued: int = Field(description="Index jobs waiting (due or planned).")
    remaining_ms: float | None = Field(
        description="When the waiting index jobs are through, estimated from those done in "
        "the last ten minutes; 0 without any waiting, null without a recent one to go by."
    )
    embedded_jobs: JobTimesOut | None = Field(
        description="How long the index jobs ran that embedded sections (since `since`)."
    )
    plain_jobs: JobTimesOut | None = Field(
        description="How long the index jobs ran that only wrote (the text was the same)."
    )
    per_section_ms: float | None = Field(
        description="Time of the jobs that embedded, per section they embedded."
    )
    model: str | None = Field(description="The embedding model; null without embeddings.")
    dimensions: int | None = Field(description="The length of its vectors, if configured.")
    since: datetime = Field(description="The durations count the jobs done from then on.")

    @classmethod
    def of(cls, status: IndexStatus) -> "SearchStatusOut":
        stats = status.stats
        return cls(
            documents=status.documents,
            index=IndexStatsOut(
                documents=stats.documents,
                embedded=stats.embedded,
                vectors=stats.vectors,
                indexing=stats.indexing,
                size_bytes=stats.size_bytes,
            ),
            running=status.running,
            queued=status.queued,
            remaining_ms=None if status.remaining is None else _ms(status.remaining),
            embedded_jobs=JobTimesOut.of(status.embedded),
            plain_jobs=JobTimesOut.of(status.plain),
            per_section_ms=None if status.per_section is None else _ms(status.per_section),
            model=status.model,
            dimensions=status.dimensions,
            since=status.since,
        )


class IndexCheckOut(BaseModel):
    current: int = Field(description="Documents indexed as they are.")
    missing: int = Field(description="Documents not in the index.")
    outdated: int = Field(description="Indexed in another version or an older layout.")
    other_model: int = Field(description="Indexed with vectors of no or another model.")
    extra: int = Field(description="Entries of documents that no longer exist.")
    took_ms: float

    @classmethod
    def of(cls, check: IndexCheck) -> "IndexCheckOut":
        found = check.comparison
        return cls(
            current=found.current,
            missing=len(found.missing),
            outdated=len(found.outdated),
            other_model=len(found.other_model),
            extra=len(found.extra),
            took_ms=_ms(check.took),
        )
