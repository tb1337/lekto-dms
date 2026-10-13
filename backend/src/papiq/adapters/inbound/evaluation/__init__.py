"""The evaluation set: synthetic documents with expected metadata and a training corpus, run
through the signals, the judge and the fields node to compare models, cold and trained
(`python -m papiq.composition evaluate`)."""

from papiq.adapters.inbound.evaluation.cases import (
    Case,
    EvaluationSet,
    EvaluationSetError,
    FakeAnswer,
    Run,
    TrainingDocument,
    load_set,
)
from papiq.adapters.inbound.evaluation.report import RunInfo, Summary, render, summarise
from papiq.adapters.inbound.evaluation.runner import CaseResult, Environment, evaluate
from papiq.adapters.inbound.evaluation.search import (
    Backend,
    ModelResult,
    QuerySet,
    SearchRun,
    SearchRunInfo,
    SearchServices,
    evaluate_search,
    load_queries,
)
from papiq.adapters.inbound.evaluation.search_report import render_search

__all__ = [
    "Backend",
    "Case",
    "CaseResult",
    "Environment",
    "EvaluationSet",
    "EvaluationSetError",
    "FakeAnswer",
    "ModelResult",
    "QuerySet",
    "Run",
    "RunInfo",
    "SearchRun",
    "SearchRunInfo",
    "SearchServices",
    "Summary",
    "TrainingDocument",
    "evaluate",
    "evaluate_search",
    "load_queries",
    "load_set",
    "render",
    "render_search",
    "summarise",
]
