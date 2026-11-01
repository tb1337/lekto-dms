"""What the inbound adapters over HTTP (REST API, MCP server) need from the rest of the
application, handed over by the composition root."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from lekto.core.domain.errors import (
    ClassifierUnavailableError,
    NotFoundError,
    SearchUnavailableError,
)
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.ports.event_bus import EventBus
from lekto.core.ports.identity import RefCipher
from lekto.core.ports.wakeup import Wakeup
from lekto.core.services.auth import AuthService
from lekto.core.services.automation import AutomationService
from lekto.core.services.bulk import BulkService
from lekto.core.services.classifier import ClassifierService
from lekto.core.services.documents import DocumentService
from lekto.core.services.expected import ExpectedService
from lekto.core.services.inbox import InboxService
from lekto.core.services.indexing import IndexingService
from lekto.core.services.jobs import JobsService
from lekto.core.services.lenses import LensService
from lekto.core.services.logos import LogoService
from lekto.core.services.master_data import MasterDataService
from lekto.core.services.oidc import OidcService
from lekto.core.services.open_identifiers import OpenIdentifierService
from lekto.core.services.pipeline import PipelineService
from lekto.core.services.profiles import ProfileService
from lekto.core.services.relations import RelationService
from lekto.core.services.rules import RuleService
from lekto.core.services.rules.retroactive import RuleApplicationService
from lekto.core.services.search import SearchService
from lekto.core.services.spaces import SpaceService
from lekto.core.services.stream import StreamService
from lekto.core.services.tasks.service import TaskService
from lekto.core.services.users import UserService
from lekto.core.services.webhooks import WebhookDeliveryService, WebhookService

type HealthCheck = Callable[[], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class ApiContext:
    """What the REST and MCP adapters work with (`composition.api.api_context`); the tuning
    comes from the settings, which hold its defaults."""

    auth: AuthService
    users: UserService
    profiles: ProfileService
    spaces: SpaceService
    master_data: MasterDataService
    open_identifiers: OpenIdentifierService
    logos: LogoService
    pipeline: PipelineService
    documents: DocumentService
    inbox: InboxService
    rules: RuleService
    rule_applications: RuleApplicationService
    bulk: BulkService
    webhooks: WebhookService
    webhook_delivery: WebhookDeliveryService
    tasks: TaskService
    lenses: LensService
    relations: RelationService
    expected: ExpectedService
    stream: StreamService
    jobs: JobsService
    automation: AutomationService
    event_bus: EventBus
    wakeup: Wakeup
    # Opaque references to values (an IBAN, an invoice number) in addresses.
    refs: RefCipher
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
    # Characters of a document's text one answer holds at most (REST `/text`, MCP
    # `documents_text`).
    text_max: int
    # Where browsers reach the web UI (`LEKTO_PUBLIC_URL` and `/ui`), for links MCP clients give
    # the user; None without `LEKTO_PUBLIC_URL`.
    ui_url: str | None = None
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
            raise SearchUnavailableError(because(ReasonCode.SEARCH_NOT_CONFIGURED))
        return self.search

    def require_indexing(self) -> IndexingService:
        if self.indexing is None:
            raise SearchUnavailableError(because(ReasonCode.SEARCH_NOT_CONFIGURED))
        return self.indexing

    def require_classifier(self) -> ClassifierService:
        if self.classifier is None:
            raise ClassifierUnavailableError("no classifier is configured")
        return self.classifier

    def require_oidc(self) -> OidcService:
        if self.oidc is None:
            raise NotFoundError("identity provider", "oidc")
        return self.oidc
