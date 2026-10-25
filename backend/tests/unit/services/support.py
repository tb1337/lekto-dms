"""What the service tests share: `World`, the services on one in-memory unit of work, and
`Raises`. The `world` fixture is in `conftest.py`."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from lekto.adapters.outbound.memory import (
    FakeCipher,
    FakeImageNormaliser,
    FakeOidcProvider,
    FakePasswordHasher,
    FakeTotp,
    FakeWebhookSender,
    ManualClock,
    MemoryDatabase,
    MemoryObjectStore,
    MemoryUnitOfWorkFactory,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.events import DomainEvent
from lekto.core.domain.pipeline import NODES, Node, NodeResult
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import Role, User
from lekto.core.ports.logos import LogoFetcher
from lekto.core.ports.ocr import VisionModel
from lekto.core.services.auth import AuthService
from lekto.core.services.documents import DocumentService
from lekto.core.services.inbox import InboxService
from lekto.core.services.lenses import LensService
from lekto.core.services.logos import LogoService
from lekto.core.services.master_data import NORMALISE_BATCH, MasterDataService
from lekto.core.services.oidc import OidcService
from lekto.core.services.pipeline import NodeExecutor, PipelineService
from lekto.core.services.spaces import SpaceService
from lekto.core.services.tasks.desk import TaskDesk
from lekto.core.services.tasks.service import TaskService
from lekto.core.services.users import UserService
from lekto.core.services.webhooks import WebhookDeliveryService, WebhookPolicy, WebhookService
from tests import builders
from tests.builders import PlaceholderNode

LINK_BASE = "https://lekto.example.org"
"""`LEKTO_PUBLIC_URL` of the services that need it."""


class Raises:
    """Node executor that raises `times` times, then returns OK."""

    def __init__(self, times: int) -> None:
        self.times = times
        self.calls = 0

    async def run(self, document: Document) -> NodeResult:
        self.calls += 1
        if self.calls <= self.times:
            raise OSError("scanner glitch")
        return builders.OK


@dataclass
class World:
    """Services on in-memory adapters, plus helpers to seed and inspect state."""

    clock: ManualClock = field(default_factory=lambda: ManualClock(builders.NOW))
    database: MemoryDatabase = field(default_factory=MemoryDatabase)
    object_store: MemoryObjectStore = field(default_factory=MemoryObjectStore)
    executors: dict[Node, NodeExecutor] = field(
        default_factory=lambda: {
            node: PlaceholderNode() for node in NODES if node is not Node.RECEIVE
        }
    )
    hasher: FakePasswordHasher = field(default_factory=FakePasswordHasher)
    cipher: FakeCipher = field(default_factory=FakeCipher)
    totp: FakeTotp = field(default_factory=FakeTotp)
    idp: FakeOidcProvider = field(default_factory=FakeOidcProvider)
    sender: FakeWebhookSender = field(default_factory=FakeWebhookSender)
    images: FakeImageNormaliser = field(default_factory=FakeImageNormaliser)
    normalise_batch: int = NORMALISE_BATCH

    @property
    def uow(self) -> MemoryUnitOfWorkFactory:
        return MemoryUnitOfWorkFactory(self.database)

    @property
    def users(self) -> UserService:
        return UserService(self.uow, self.clock, self.hasher)

    @property
    def auth(self) -> AuthService:
        return AuthService(
            self.uow,
            self.clock,
            hasher=self.hasher,
            cipher=self.cipher,
            totp=self.totp,
            sessions=builders.SESSIONS,
        )

    def oidc(self, *, auto_create: bool = False) -> OidcService:
        return OidcService(
            self.uow,
            self.clock,
            self.auth,
            self.idp,
            self.cipher,
            display_name="Test IdP",
            auto_create=auto_create,
        )

    @property
    def spaces(self) -> SpaceService:
        return SpaceService(self.uow, self.clock)

    @property
    def master_data(self) -> MasterDataService:
        return MasterDataService(
            self.uow,
            self.clock,
            builders.TEMPLATES,
            store=self.object_store,
            normalise_batch=self.normalise_batch,
        )

    @property
    def logos(self) -> LogoService:
        return LogoService(self.uow, self.clock, self.object_store, self.images)

    def fetching(self, fetcher: LogoFetcher) -> tuple[MasterDataService, LogoService]:
        """Master data and logos with fetching on."""
        master = MasterDataService(
            self.uow, self.clock, builders.TEMPLATES, store=self.object_store, fetch_logos=True
        )
        return master, LogoService(self.uow, self.clock, self.object_store, self.images, fetcher)

    @property
    def documents(self) -> DocumentService:
        return DocumentService(self.uow, self.clock, self.object_store)

    @property
    def inbox(self) -> InboxService:
        return InboxService(self.uow, self.clock)

    @property
    def webhooks(self) -> WebhookService:
        return WebhookService(
            self.uow, self.clock, self.cipher, builders.WEBHOOKS, builders.TEMPLATES
        )

    @property
    def lenses(self) -> LensService:
        return LensService(self.uow, self.clock)

    def webhook_delivery(self, policy: WebhookPolicy | None = None) -> WebhookDeliveryService:
        return WebhookDeliveryService(
            self.uow,
            self.clock,
            self.cipher,
            self.sender,
            policy or builders.WEBHOOKS,
            builders.TEMPLATES,
            link_base=LINK_BASE,
        )

    @property
    def tasks(self) -> TaskService:
        return TaskService(self.uow, self.clock)

    def desk(self, link_base: str | None = None) -> TaskDesk:
        """Places tasks; without `link_base` at `LINK_BASE`."""
        return TaskDesk(self.cipher, builders.TEMPLATES, link_base=link_base or LINK_BASE)

    def pipeline(
        self,
        executors: Mapping[Node, NodeExecutor] | None = None,
        *,
        vision: VisionModel | None = None,
        vision_lease: timedelta | None = None,
        facts: NodeExecutor | None = None,
    ) -> PipelineService:
        return builders.pipeline_service(
            self.uow,
            self.clock,
            self.object_store,
            {**self.executors, **(executors or {})},
            vision=vision,
            vision_lease=vision_lease,
            facts=facts,
        )

    async def user(self, name: str | None = None, role: Role = Role.USER) -> User:
        """A user with their personal space, seeded directly."""
        return await builders.seed_user(self.uow, name, role=role)

    async def account(
        self, name: str | None = None, role: Role = Role.USER, password: str = builders.PASSWORD
    ) -> User:
        """A user with their personal space and password."""
        return await builders.seed_account(
            self.uow, self.hasher, name, role=role, password=password
        )

    async def personal_space(self, user: User) -> Space:
        async with self.uow() as uow:
            return await uow.spaces.get_personal(user.id)

    async def drain(self, pipeline: PipelineService | None = None) -> int:
        """Run due jobs until none is left; returns how many ran."""
        return await builders.drain(pipeline or self.pipeline())

    def events(self) -> list[DomainEvent]:
        return list(self.database.outbox)

    def event_types(self) -> list[str]:
        return [event.type for event in self.database.outbox]
