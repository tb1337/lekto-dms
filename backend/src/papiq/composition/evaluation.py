"""`python -m papiq.composition evaluate`: run the evaluation set against the configured
language model (or the set's fixed answers) and write a Markdown report."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from papiq.adapters.inbound.evaluation import (
    Case,
    CaseResult,
    Environment,
    RunInfo,
    evaluate,
    load_set,
    render,
    summarise,
)
from papiq.adapters.outbound.memory import FakeLanguageModel
from papiq.composition.container import (
    Container,
    build_memory_container,
    build_services,
    openai_language_model,
    policy_of,
)
from papiq.composition.errors import ConfigurationError
from papiq.composition.settings import Settings
from papiq.core.domain.pipeline import PIPELINE, Node
from papiq.core.ports import LanguageModel
from papiq.core.services.classification.nodes import ClassifyNode, ExtractFieldsNode
from papiq.core.services.classification.prompts import CLASSIFY_PROMPT, EXTRACT_PROMPT
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


def build_environment(
    container: Container,
    settings: Settings,
    model_for: Callable[[Case], LanguageModel | None],
) -> Environment:
    """The evaluation's services on the container's adapters. The pipeline of a case runs
    classification and field extraction with `model_for(case)`, the other nodes pass through,
    and there are no automatic retries: a model that cannot be reached ends the case red at
    once."""
    services = build_services(container, settings)
    uow, clock, store = container.unit_of_work, container.clock, container.object_store
    policy = policy_of(settings)

    def pipeline_for(case: Case) -> PipelineService:
        model = model_for(case)
        executors: dict[Node, NodeExecutor] = {node: PlaceholderNode() for node in PIPELINE[1:]}
        executors[Node.CLASSIFY] = ClassifyNode(uow, store, model, clock, policy)
        executors[Node.EXTRACT_FIELDS] = ExtractFieldsNode(uow, store, model, clock, policy)
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
    )


async def run_evaluation(
    settings: Settings,
    *,
    cases: Path,
    fake: bool = False,
    output: Path | None = None,
    progress: bool = False,
) -> Evaluation:
    """Run the set in `cases`; write the report to `output` (default:
    `<cases>/reports/<date>-<model>.md`). Without `fake`, PAPIQ_LLM_BASE_URL is required."""
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
        print(f"{result.case.name}: {lane} ({result.seconds:.1f} s)", flush=True)

    container = build_memory_container()
    environment = build_environment(container, settings, model_for)
    started = datetime.now(UTC)
    try:
        results = await evaluate(
            evaluation, environment, progress=report_progress if progress else None
        )
    finally:
        await container.aclose()
    info = RunInfo(
        model=FAKE_MODEL if model is None else model.model,
        endpoint="memory" if model is None else model.endpoint,
        started=started,
        prompts=f"{CLASSIFY_PROMPT}, {EXTRACT_PROMPT}",
        settings={
            "PAPIQ_LLM_INPUT_BUDGET": settings.llm_input_budget,
            "PAPIQ_LLM_MAX_TAGS": settings.llm_max_tags,
            "PAPIQ_LLM_TEMPERATURE": settings.llm_temperature,
            "PAPIQ_LLM_RESPONSE_FORMAT": settings.llm_response_format,
            "PAPIQ_CONFIDENCE_THRESHOLD": settings.confidence_threshold,
            "PAPIQ_CONTACT_SUGGEST_THRESHOLD": settings.contact_suggest_threshold,
        },
        fake=fake,
    )
    path = output or cases / "reports" / f"{started:%Y-%m-%d}-{_slug(info.model)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(results, info), encoding="utf-8")
    summary = summarise(results, fake=fake)
    return Evaluation(
        path,
        results,
        len(summary.false_green),
        len(summary.green_but_wrong),
        len(summary.violations),
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", name.casefold()).strip("-") or "model"
