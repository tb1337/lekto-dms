"""What the inbound adapters over HTTP (REST API, MCP server) need from the rest of the
application, handed over by the composition root."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from papiq.core.domain.errors import (
    ClassifierUnavailableError,
    NotFoundError,
    SearchUnavailableError,
)
from papiq.core.ports.event_bus import EventBus
from papiq.core.services.auth import AuthService
from papiq.core.services.classifier import ClassifierService
from papiq.core.services.documents import DocumentService
from papiq.core.services.indexing import IndexingService
from papiq.core.services.logos import LogoService
from papiq.core.services.master_data import MasterDataService
from papiq.core.services.oidc import OidcService
from papiq.core.services.pipeline import PipelineService
from papiq.core.services.rules import RuleService
from papiq.core.services.rules.retroactive import RuleApplicationService
from papiq.core.services.search import SearchService
from papiq.core.services.spaces import SpaceService
from papiq.core.services.users import UserService
from papiq.core.services.webhooks import WebhookDeliveryService, WebhookService

type HealthCheck = Callable[[], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class ApiContext:
    """What the REST and MCP adapters work with (`composition.api.api_context`); the tuning
    comes from the settings, which hold its defaults."""

    auth: AuthService
    users: UserService
    spaces: SpaceService
    master_data: MasterDataService
    logos: LogoService
    pipeline: PipelineService
    documents: DocumentService
    rules: RuleService
    rule_applications: RuleApplicationService
    webhooks: WebhookService
    webhook_delivery: WebhookDeliveryService
    event_bus: EventBus
    health_checks: Mapping[str, HealthCheck]
    max_upload_size: int
    max_request_size: int  # every other request body
    # Checks of parts the API works without (the search): a failure is `degraded`, not `503`.
    optional_checks: frozenset[str] = frozenset()
    oidc: OidcService | None = None
    # Both with a search index; without, the search endpoints answer 503.
    search: SearchService | None = None
    indexing: IndexingService | None = None
    # With a classifier; without, its endpoints answer 503.
    classifier: ClassifierService | None = None
    events_poll_interval: timedelta
    # Characters of a document's text one answer holds at most (REST `/text`, MCP `get_text`).
    text_max: int
    # `False` only for development over plain HTTP: cookies without `Secure`.
    cookie_secure: bool
    # Event streams check every so often that their session or token is still valid.
    stream_recheck_interval: timedelta = timedelta(seconds=30)
    # The built web UI, served below `/ui`; None: the API only.
    ui_directory: Path | None = None

    # The services the API works without, for an endpoint or tool that needs them: REST answers
    # the errors with 503 (search, classifier) or 404 (identity provider), MCP with its text.

    def require_search(self) -> SearchService:
        if self.search is None:
            raise SearchUnavailableError("search is not configured")
        return self.search

    def require_indexing(self) -> IndexingService:
        if self.indexing is None:
            raise SearchUnavailableError("search is not configured")
        return self.indexing

    def require_classifier(self) -> ClassifierService:
        if self.classifier is None:
            raise ClassifierUnavailableError("no classifier is configured")
        return self.classifier

    def require_oidc(self) -> OidcService:
        if self.oidc is None:
            raise NotFoundError("identity provider", "oidc")
        return self.oidc
