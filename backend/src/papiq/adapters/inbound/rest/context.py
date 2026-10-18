"""The context of the API as a FastAPI dependency, and the services the API works without as
dependencies that answer 503 while they are not configured."""

from typing import Annotated

from fastapi import Depends, Request

from papiq.adapters.inbound.context import ApiContext, HealthCheck
from papiq.core.domain.errors import ClassifierUnavailableError, SearchUnavailableError
from papiq.core.services.classifier import ClassifierService
from papiq.core.services.indexing import IndexingService
from papiq.core.services.search import SearchService

__all__ = ["ApiContext", "Classifier", "Context", "HealthCheck", "Indexing", "Search"]


def _context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


Context = Annotated[ApiContext, Depends(_context)]


def _search(context: Context) -> SearchService:
    if context.search is None:
        raise SearchUnavailableError("search is not configured")
    return context.search


def _indexing(context: Context) -> IndexingService:
    if context.indexing is None:
        raise SearchUnavailableError("search is not configured")
    return context.indexing


def _classifier(context: Context) -> ClassifierService:
    if context.classifier is None:
        raise ClassifierUnavailableError("no classifier is configured")
    return context.classifier


Search = Annotated[SearchService, Depends(_search)]
Indexing = Annotated[IndexingService, Depends(_indexing)]
Classifier = Annotated[ClassifierService, Depends(_classifier)]
