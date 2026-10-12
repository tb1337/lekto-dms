"""The context of the API as a FastAPI dependency."""

from typing import Annotated

from fastapi import Depends, Request

from papiq.adapters.inbound.context import ApiContext, HealthCheck

__all__ = ["ApiContext", "Context", "HealthCheck"]


def _context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


Context = Annotated[ApiContext, Depends(_context)]
