"""`python -m lekto.composition evaluate-search`: index the evaluation set with one or more
embedding models and measure which queries find which documents; write a Markdown report."""

import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lekto.adapters.inbound.evaluation import (
    Backend,
    Case,
    ModelResult,
    SearchRun,
    SearchRunInfo,
    SearchServices,
    evaluate_search,
    load_queries,
    load_set,
    render_search,
)
from lekto.adapters.outbound.http_client import endpoint_of
from lekto.adapters.outbound.meilisearch import MeilisearchIndex
from lekto.adapters.outbound.memory import (
    BagOfWordsEmbeddings,
    MemorySearchIndex,
)
from lekto.composition.container import (
    build_memory_container,
    indexing_policy_of,
    openai_embeddings,
    search_policy_of,
)
from lekto.composition.errors import ConfigurationError
from lekto.composition.evaluation import build_environment, fake_model_for, slug
from lekto.composition.settings import Settings, reported
from lekto.core.ports.llm import LanguageModel
from lekto.core.ports.search_index import SearchIndex
from lekto.core.services.indexing import IndexingService
from lekto.core.services.search import SearchService

DEFAULT_RATIOS = (0.0, 0.5, 1.0)
QUERY_TIMEOUT = timedelta(minutes=2)  # a model may be loaded into memory on the first query


@dataclass(frozen=True)
class SearchEvaluation:
    report: Path
    run: SearchRun

    @property
    def models(self) -> list[ModelResult]:
        return self.run.models


def parse_ratios(text: str) -> tuple[float, ...]:
    try:
        ratios = tuple(float(part) for part in text.split(",") if part.strip())
    except ValueError:
        raise ConfigurationError(f"--ratios is not a list of numbers: {text!r}") from None
    if not ratios or any(not 0 <= ratio <= 1 for ratio in ratios):
        raise ConfigurationError("--ratios needs numbers between 0 and 1, like 0,0.5,1")
    return tuple(dict.fromkeys(ratios))


async def run_search_evaluation(
    settings: Settings,
    *,
    cases: Path,
    queries: Path | None = None,
    fake: bool = False,
    models: Sequence[str] = (),
    ratios: Sequence[float] = DEFAULT_RATIOS,
    output: Path | None = None,
    progress: bool = False,
) -> SearchEvaluation:
    """Run the queries of `queries` (default: `<cases>/search/queries.json`) on the set in
    `cases` for each model; write the report to `output` (default:
    `<cases>/search/reports/<date>-<models>.md`).

    Without `fake`, LEKTO_MEILISEARCH_URL and LEKTO_EMBEDDING_BASE_URL are required; every model
    gets a temporary Meilisearch index, removed afterwards. With `fake`, bag-of-words vectors and
    the in-memory index take their place.
    """
    evaluation = load_set(cases)
    query_set = load_queries(
        queries or cases / "search" / "queries.json",
        frozenset(case.name for case in evaluation.cases),
    )
    if fake and models:
        raise ConfigurationError("--models does not go with --fake")
    backends, endpoint, index = _backends(settings, fake=fake, models=models)

    def model_for(case: Case) -> LanguageModel | None:
        # The documents are classified with the fixed answers: the metadata is not what is
        # measured here, and the same documents go to every model.
        return fake_model_for(case)

    def say(message: str) -> None:
        print(message, flush=True)

    container = build_memory_container()
    environment = build_environment(container, settings, model_for)
    uow, clock, store = container.unit_of_work, container.clock, container.object_store
    # The length of the vectors is measured per model, not the configured one.
    indexing_policy = replace(indexing_policy_of(settings), dimensions=None)
    search_policy = replace(
        search_policy_of(settings), embed_timeout=QUERY_TIMEOUT, dimensions=None
    )
    services = SearchServices(
        indexing=lambda index, embeddings: IndexingService(
            uow, clock, store, index, indexing_policy, embeddings=embeddings
        ),
        search=lambda index, embeddings: SearchService(
            uow, index, search_policy, embeddings=embeddings
        ),
    )
    started = datetime.now(UTC)
    try:
        run = await evaluate_search(
            evaluation,
            query_set,
            environment,
            services,
            backends,
            ratios,
            progress=say if progress else None,
        )
    finally:
        await container.aclose()
    info = SearchRunInfo(
        endpoint=endpoint,
        index=index,
        started=started,
        settings=reported(
            settings,
            "search_chunk_size",
            "search_max_chunks",
            "search_max_text",
            "search_semantic_ratio",
            "embedding_document_prefix",
            "embedding_query_prefix",
        ),
        fake=fake,
        default_ratio=settings.search_semantic_ratio,
    )
    names = "-".join(slug(model.name) for model in run.models)
    path = output or cases / "search" / "reports" / f"{started:%Y-%m-%d}-{names}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_search(run, query_set, info), encoding="utf-8")
    return SearchEvaluation(path, run)


def _backends(
    settings: Settings, *, fake: bool, models: Sequence[str]
) -> tuple[list[Backend], str, str]:
    """The backends, the endpoint and the kind of index for the report."""
    if fake:
        embeddings = BagOfWordsEmbeddings()

        @asynccontextmanager
        async def memory(dimensions: int | None) -> AsyncIterator[SearchIndex]:
            yield MemorySearchIndex(dimensions=dimensions)

        return [Backend(embeddings.model, embeddings, memory)], "memory", "in memory"
    if settings.meilisearch_url is None:
        raise ConfigurationError("LEKTO_MEILISEARCH_URL is not set; use --fake or configure it")
    if settings.embedding_base_url is None:
        raise ConfigurationError("LEKTO_EMBEDDING_BASE_URL is not set; use --fake or configure it")
    names = list(
        dict.fromkeys(models or ([settings.embedding_model] if settings.embedding_model else []))
    )
    if not names:
        raise ConfigurationError("no model: pass --models or set LEKTO_EMBEDDING_MODEL")

    @asynccontextmanager
    async def meilisearch(dimensions: int | None) -> AsyncIterator[SearchIndex]:
        assert settings.meilisearch_url is not None
        key = settings.meilisearch_api_key
        index = MeilisearchIndex(
            url=str(settings.meilisearch_url),
            api_key=None if key is None else key.get_secret_value(),
            index=f"lekto-eval-{secrets.token_hex(4)}",
            dimensions=dimensions,
            locales=settings.search_locales.split("+"),
            timeout=settings.meilisearch_timeout.total_seconds(),
            task_timeout=settings.meilisearch_task_timeout.total_seconds(),
        )
        try:
            await index.check()
            yield index
        finally:
            try:
                await index.drop()
            finally:
                await index.aclose()

    backends = [
        Backend(
            name,
            openai_embeddings(settings.model_copy(update={"embedding_model": name})),
            meilisearch,
        )
        for name in names
    ]
    return (
        backends,
        endpoint_of(str(settings.embedding_base_url)),
        f"Meilisearch at {endpoint_of(str(settings.meilisearch_url))}, a temporary index per model",
    )
