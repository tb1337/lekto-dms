"""`python -m papiq.composition evaluate`: run the evaluation set against the configured
language model (or the set's fixed answers) and write a Markdown report."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from papiq.adapters.inbound.evaluation import (
    Case,
    CaseResult,
    Environment,
    Run,
    RunInfo,
    evaluate,
    load_set,
    render,
    summarise,
)
from papiq.adapters.outbound.memory import (
    BagOfWordsEmbeddings,
    FakeLanguageModel,
    MemorySearchIndex,
)
from papiq.adapters.outbound.sklearn import SklearnClassifier
from papiq.composition.container import (
    Container,
    build_memory_container,
    build_services,
    neighbours_policy_of,
    openai_language_model,
    policy_of,
)
from papiq.composition.errors import ConfigurationError
from papiq.composition.settings import Settings
from papiq.core.domain.pipeline import NODES, Node
from papiq.core.ports import LanguageModel
from papiq.core.services.classification.nodes import FieldsNode, JudgeNode, LlmSignal
from papiq.core.services.classification.prompts import EXTRACT_PROMPT, PROPOSE_PROMPT
from papiq.core.services.classification.signals import (
    ClassifierSignal,
    FactsSignal,
    NeighboursSignal,
)
from papiq.core.services.imports import ImportedFieldsNode, ImportedJudgeNode, ImportedSignal
from papiq.core.services.pipeline import NodeExecutor, PipelineService, PlaceholderNode, RetryPolicy

FAKE_MODEL = "fixed answers"
PIPELINE_VERSION = "evaluation"


@dataclass(frozen=True)
class Evaluation:
    report: Path
    results: list[CaseResult]
    false_green: int
    green_but_wrong: int
    violations: int


EMBEDDING_DIMENSIONS = 256
"""Length of the bag-of-words vectors the trained run indexes with."""


def evaluation_container(run: Run) -> Container:
    """The adapters of a run, all in memory: for the trained one a search index with
    bag-of-words vectors and the scikit-learn classifier."""
    container = build_memory_container()
    if run is Run.COLD:
        return container
    return replace(
        container,
        search_index=MemorySearchIndex(dimensions=EMBEDDING_DIMENSIONS),
        embeddings=BagOfWordsEmbeddings(dimensions=EMBEDDING_DIMENSIONS),
        classifier=SklearnClassifier(),
    )


def build_environment(
    container: Container,
    settings: Settings,
    model_for: Callable[[Case], LanguageModel | None],
    run: Run = Run.COLD,
) -> Environment:
    """The evaluation's services on the container's adapters. The pipeline of a case runs the
    signals, the judge and the fields node with `model_for(case)`, the other nodes pass through,
    and there are no automatic retries: a model that cannot be reached ends the case red at
    once. Taken-over documents (the training corpus) pass the signals, the judge and the
    fields node as in the container. In the cold run the classifier and the similar documents
    abstain."""
    if run is Run.TRAINED:
        settings = settings.model_copy(
            update={
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "embedding_document_prefix": None,
                "embedding_query_prefix": None,
            }
        )
    services = build_services(container, settings)
    uow, clock, store = container.unit_of_work, container.clock, container.object_store
    policy = policy_of(settings)
    trained = run is Run.TRAINED
    classifier = services.classifier if trained else None
    index = container.search_index if trained else None
    embeddings = container.embeddings if trained else None

    def pipeline_for(case: Case | None) -> PipelineService:
        model = None if case is None else model_for(case)
        executors: dict[Node, NodeExecutor] = {
            node: PlaceholderNode() for node in NODES if node is not Node.RECEIVE
        }
        signals: dict[Node, NodeExecutor] = {
            Node.SIGNAL_LLM: LlmSignal(uow, store, model, clock, policy),
            Node.SIGNAL_FACTS: FactsSignal(uow, store),
            Node.SIGNAL_CLASSIFIER: ClassifierSignal(store, classifier),
            Node.SIGNAL_NEIGHBOURS: NeighboursSignal(
                uow, store, index, embeddings, neighbours_policy_of(settings)
            ),
        }
        executors |= {node: ImportedSignal(uow, signal) for node, signal in signals.items()}
        executors[Node.JUDGE] = ImportedJudgeNode(
            uow,
            JudgeNode(
                uow, store, clock, policy, classifier_threshold=settings.classifier_threshold
            ),
        )
        executors[Node.FIELDS] = ImportedFieldsNode(
            uow, FieldsNode(uow, store, model, clock, policy)
        )
        return PipelineService(
            uow,
            clock,
            store,
            executors,
            pipeline_version=PIPELINE_VERSION,
            retry=RetryPolicy(max_attempts=1),
        )

    return Environment(
        store=store,
        users=services.users,
        master_data=services.master_data,
        documents=services.documents,
        pipeline_for=pipeline_for,
        run=run,
        indexing=services.indexing if trained else None,
        classifier=classifier,
    )


async def run_evaluation(
    settings: Settings,
    *,
    cases: Path,
    fake: bool = False,
    output: Path | None = None,
    progress: bool = False,
    runs: Sequence[Run] = tuple(Run),
) -> Evaluation:
    """Run the set in `cases`, cold and trained (or the `runs` given); write the report to
    `output` (default: `<cases>/reports/<date>-<model>.md`). Without `fake`,
    PAPIQ_LLM_BASE_URL is required."""
    evaluation = load_set(cases)
    model: LanguageModel | None = None
    if not fake:
        if settings.llm_base_url is None:
            raise ConfigurationError(
                "PAPIQ_LLM_BASE_URL is not set; configure a model or use --fake"
            )
        model = openai_language_model(settings)

    def model_for(case: Case) -> LanguageModel | None:
        if not fake:
            return model
        if case.fake is None:
            raise ConfigurationError(f"case {case.name} has no fixed answer for --fake")
        return FakeLanguageModel(case.fake.respond, model=FAKE_MODEL)

    def report_progress(result: CaseResult) -> None:
        lane = "none" if result.lane is None else result.lane.value
        print(f"{result.run}: {result.case.name}: {lane} ({result.seconds:.1f} s)", flush=True)

    started = datetime.now(UTC)
    results: dict[Run, list[CaseResult]] = {}
    for run in runs:
        container = evaluation_container(run)
        environment = build_environment(container, settings, model_for, run)
        try:
            results[run] = await evaluate(
                evaluation, environment, progress=report_progress if progress else None
            )
        finally:
            await container.aclose()
    info = RunInfo(
        model=FAKE_MODEL if model is None else model.model,
        endpoint="memory" if model is None else model.endpoint,
        started=started,
        prompts=f"{PROPOSE_PROMPT}, {EXTRACT_PROMPT}",
        settings={
            "PAPIQ_LLM_INPUT_BUDGET": settings.llm_input_budget,
            "PAPIQ_LLM_MAX_TAGS": settings.llm_max_tags,
            "PAPIQ_LLM_TEMPERATURE": settings.llm_temperature,
            "PAPIQ_LLM_RESPONSE_FORMAT": settings.llm_response_format,
            "PAPIQ_CONFIDENCE_THRESHOLD": settings.confidence_threshold,
            "PAPIQ_CONTACT_SUGGEST_THRESHOLD": settings.contact_suggest_threshold,
            "PAPIQ_DEFAULT_CURRENCY": settings.default_currency,
            "PAPIQ_CLASSIFIER_THRESHOLD": settings.classifier_threshold,
            "PAPIQ_NEIGHBOURS": settings.neighbours,
        },
        fake=fake,
        training=len(evaluation.training),
    )
    path = output or cases / "reports" / f"{started:%Y-%m-%d}-{_slug(info.model)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(results, info), encoding="utf-8")
    summaries = [summarise(items, fake=fake) for items in results.values()]
    return Evaluation(
        path,
        [result for items in results.values() for result in items],
        sum(len(summary.false_green) for summary in summaries),
        sum(len(summary.green_but_wrong) for summary in summaries),
        sum(len(summary.violations) for summary in summaries),
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", name.casefold()).strip("-") or "model"
