"""The FastAPI application. All routes of the API live below `/api/v1`; the web UI, if there is
one, below `/ui`."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Protocol

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import BaseRoute

from lekto import __version__
from lekto.adapters.inbound.rest import (
    account,
    automation,
    bulk,
    classifier,
    documents,
    expected,
    external,
    health,
    identifiers,
    jobs,
    lenses,
    master_data,
    outgoing,
    pipeline,
    problems,
    relations,
    rules,
    search,
    spaces,
    stream,
    streams,
    users,
    webhooks,
)
from lekto.adapters.inbound.rest.auth import (
    FILE_SIGNATURE,
    SECURITY,
    SECURITY_SCHEMES,
    SESSION_ONLY,
    TASK_TOKEN,
    authenticate,
    session_principal,
)
from lekto.adapters.inbound.rest.context import ApiContext
from lekto.adapters.inbound.rest.events import EventHub
from lekto.adapters.inbound.rest.middleware import LimitRequestBody, NoStore
from lekto.adapters.inbound.rest.paths import HEALTH_PATH, MCP_PATH, PREFIX
from lekto.adapters.inbound.rest.schemas.events import EventMessage
from lekto.adapters.inbound.rest.schemas.external import TaskAnswer
from lekto.adapters.inbound.rest.ui import ui_routes
from lekto.adapters.inbound.waiting import dispatch_events
from lekto.core.domain.document_facts import ROLES as FACT_ROLES
from lekto.core.domain.identifiers import catalog as identifier_kinds
from lekto.core.domain.reasons import catalog as reasons_catalog
from lekto.core.ports.wakeup import Channel
from lekto.core.services.tasks.desk import CALLBACK_PATH

__all__ = ["PREFIX", "create_app"]

DESCRIPTION = f"""\
Lekto is a headless document management system; this API is the only way in.

Errors are problem details (RFC 9457, `application/problem+json`).

Authentication: a session cookie from `POST /auth/login` (web UI; changing requests also send
the header `X-CSRF-Token`) or a personal API token as `Authorization: Bearer lekto_…`. Every
endpoint needs one of them (401 without), except health, the sign-in endpoints (`POST
/auth/login` and, below `/auth/oidc`, information, start and callback) and the answer to a task
(`/external/tasks/{{id}}/result`, with the task's own token). A `read` token may only
read (403). The own sign-in (password, sessions, TOTP, API tokens, provider links) and
creating users or resetting their sign-in need a session; a token gets 403 there. Documents
and spaces the caller may not see are "not found" (404), the same as ones that do not exist.

The same services are available to AI clients over MCP (Streamable HTTP, stateless) at
`{MCP_PATH}`, with the same API tokens as bearer; it is not part of this OpenAPI document.
Tools: `search`, `get_document`, `get_text`, `update_metadata` (needs a `read_write` token),
`list_tags`.
"""


EVENT_ITEM = {
    "type": "object",
    "required": ["event", "id", "data"],
    "properties": {
        "event": {"type": "string", "description": "The event type, as in `data.type`."},
        "id": {"type": "string", "description": "The event id, as in `data.id`."},
        "data": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/components/schemas/EventMessage"},
        },
    },
}


log = logging.getLogger(__name__)

DISPATCHER_TIMEOUT = 5
"""Seconds the event dispatch may take to end when the app stops, before it is cancelled."""


class Mount(Protocol):
    """Something the app serves besides the API, below its prefix (the MCP endpoint): its
    routes, and `run()` around the app's lifetime."""

    @property
    def routes(self) -> Sequence[BaseRoute]: ...

    def run(self) -> contextlib.AbstractAsyncContextManager[None]: ...


def create_app(context: ApiContext, mounts: Sequence[Mount] = ()) -> FastAPI:
    """The API on the given services, with the mounts after its routes. While the app runs
    (lifespan), it delivers outbox events to its event streams and runs the mounts."""
    hub = EventHub(context.documents)
    hub.attach(context.event_bus)
    if context.search is not None:
        context.search.listen(hub.deliver)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stopping = asyncio.Event()
        dispatcher = asyncio.create_task(
            dispatch_events(
                context.event_bus,
                context.wakeup.subscribe(Channel.EVENTS),
                context.events_poll_interval,
                stopping,
            )
        )
        try:
            async with contextlib.AsyncExitStack() as stack:
                for mount in mounts:
                    await stack.enter_async_context(mount.run())
                yield
        finally:
            hub.close()
            stopping.set()
            try:
                await asyncio.wait_for(dispatcher, timeout=DISPATCHER_TIMEOUT)
            except TimeoutError:
                log.warning("event dispatch did not end in time; cancelling it")
                dispatcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dispatcher

    app = FastAPI(
        title="Lekto DMS API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=f"{PREFIX}/docs",
        redoc_url=None,
    )
    app.state.context = context
    app.state.hub = hub
    problems.install(app)
    app.add_middleware(
        LimitRequestBody,
        limit=context.max_request_size,
        # The uploads and the answers to tasks have their own limits.
        exempt={
            ("POST", f"{PREFIX}/documents"),
            ("PUT", master_data.LOGO_PATH),
            ("POST", CALLBACK_PATH),
        },
    )
    app.add_middleware(
        NoStore,
        prefix=PREFIX,
        public=(HEALTH_PATH, f"{PREFIX}/docs", f"{PREFIX}/openapi.json", f"{PREFIX}/redoc"),
        # A logo is master data every user sees; its URL changes with it.
        cacheable=(master_data.LOGO_PATH,),
    )
    for router in (
        account.public,
        account.router,
        users.router,
        *master_data.ROUTERS,
        identifiers.router,
        spaces.router,
        rules.router,
        rules.applications,
        rules.templates,
        search.router,  # before documents: `/documents/search` is no document id
        bulk.router,  # likewise `/documents/bulk`
        stream.router,  # likewise `/documents/stream`
        classifier.router,
        documents.router,
        documents.inbox,
        pipeline.router,
        streams.router,
        webhooks.router,
        external.router,
        lenses.router,
        relations.router,
        expected.router,
        jobs.router,
        automation.router,
        health.router,
    ):
        app.include_router(router, prefix=PREFIX)
    outgoing.describe(app)
    for mount in mounts:
        app.router.routes.extend(mount.routes)
    # After the API: its paths never reach the UI.
    if context.ui_directory is not None:
        app.router.routes.extend(ui_routes(context.ui_directory))

    original_openapi = app.openapi

    def openapi() -> dict[str, object]:
        schema = original_openapi()
        outgoing.delivered(schema)
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.setdefault("EventMessage", EventMessage.model_json_schema())
        # Read by the route itself (an invalid answer uses the token up); described here.
        components.setdefault("TaskAnswer", TaskAnswer.model_json_schema())
        problem = problems.Problem.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, definition in problem.pop("$defs", {}).items():  # the spaces deleting a user
            components.setdefault(name, definition)
        components.setdefault("Problem", problem)
        # The stream: a string for OpenAPI 3.1 tools, `itemSchema` (OpenAPI 3.2) per event,
        # whose `data` is the JSON of an EventMessage.
        stream = schema["paths"][f"{PREFIX}/events"]["get"]["responses"]["200"]["content"]
        stream["text/event-stream"] = {
            "schema": {"type": "string", "description": "Server-sent events"},
            "itemSchema": EVENT_ITEM,
            "example": stream["text/event-stream"]["example"],
        }
        # Validation errors are problems too; FastAPI's own schemas for them are unused.
        for unused in ("HTTPValidationError", "ValidationError"):
            components.pop(unused, None)
        schema["components"]["securitySchemes"] = SECURITY_SCHEMES
        # The reasons' codes with their parameters and how each is written (`ReasonOut`).
        schema["x-reasons"] = reasons_catalog()
        # The kinds of identifiers and whose they are (clients offer them by these).
        schema["x-identifier-kinds"] = identifier_kinds()
        # The role of a fact of each kind until a source tells (`document_facts.ROLES`).
        schema["x-fact-roles"] = {kind.value: role.value for kind, role in FACT_ROLES.items()}
        for route_context in iter_route_contexts(app.routes):
            route = route_context.original_route
            if isinstance(route, APIRoute) and route.include_in_schema:
                security = security_of(route)
                for method in route_context.methods or ():
                    operation = schema["paths"][route_context.path_format][method.lower()]
                    operation["security"] = security
                    responses = operation["responses"]
                    if "requestBody" in operation and "413" not in responses:
                        responses["413"] = problems.problem_responses(413)[413]
                    # A `read` token or a missing CSRF header is refused on every change; a
                    # token wherever a session is needed.
                    refusable = security == SESSION_ONLY or (
                        security == SECURITY and method != "GET"
                    )
                    if refusable and "403" not in responses:
                        responses["403"] = problems.problem_responses(403)[403]
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


def security_of(route: APIRoute) -> list[dict[str, list[str]]]:
    """From the route's dependencies: public (none), session only, session or token, or a
    task's token."""
    calls = set(_calls(route.dependant))
    if external.task_token in calls:
        return TASK_TOKEN
    if external.file_link in calls:
        return FILE_SIGNATURE
    if session_principal in calls:
        return SESSION_ONLY
    if authenticate in calls:
        return SECURITY
    return []


def _calls(dependant: Dependant) -> Iterator[Callable[..., object] | None]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _calls(dependency)


def close_event_streams(app: FastAPI) -> None:
    """End all open event streams, so that the server can shut down at once."""
    hub: EventHub = app.state.hub
    hub.close()
