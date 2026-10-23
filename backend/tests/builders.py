"""Test data builders shared by unit tests and contract suites."""

import itertools
import tempfile
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from lekto.adapters.outbound.liquid import LiquidTemplateRenderer
from lekto.composition.container import (
    classifier_policy_of,
    event_retry_of,
    indexing_policy_of,
    neighbours_policy_of,
    policy_of,
    retry_policy_of,
    search_policy_of,
    session_policy_of,
    thresholds_of,
    webhook_policy_of,
)
from lekto.composition.settings import Settings
from lekto.core.domain.documents import Document, Sha256
from lekto.core.domain.identity import Credential, check_new_password
from lekto.core.domain.ids import DocumentId, SpaceId, UserId, new_id
from lekto.core.domain.pipeline import Lane, Node, NodeResult, Outcome
from lekto.core.domain.search import IndexDocument, Visibility
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.ports.clock import Clock
from lekto.core.ports.identity import PasswordHasher
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.ocr import VisionModel
from lekto.core.ports.search_index import SearchQuery
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services.pipeline import (
    DeferredResult,
    IncomingFile,
    NodeExecutor,
    PipelineService,
)

DEFAULT_SETTINGS = Settings.model_construct()
"""The shipped defaults (`backend/README.md`, Configuration): tests take thresholds and
limits from here, so the one source of a default is `composition/settings.py`."""
# Templates of rules and title patterns, as the memory container renders them.
TEMPLATES = LiquidTemplateRenderer(
    locale=DEFAULT_SETTINGS.template_locale, currency=DEFAULT_SETTINGS.default_currency
)
THRESHOLDS = thresholds_of(DEFAULT_SETTINGS)
CLASSIFICATION = policy_of(DEFAULT_SETTINGS)
CLASSIFIER = classifier_policy_of(DEFAULT_SETTINGS)
INDEXING = indexing_policy_of(DEFAULT_SETTINGS)
NEIGHBOURS = neighbours_policy_of(DEFAULT_SETTINGS)
SEARCH = search_policy_of(DEFAULT_SETTINGS)
WEBHOOKS = webhook_policy_of(DEFAULT_SETTINGS)
RETRY = retry_policy_of(DEFAULT_SETTINGS)
SESSIONS = session_policy_of(DEFAULT_SETTINGS)
EVENT_RETRY = event_retry_of(DEFAULT_SETTINGS)


def pipeline_service(
    uow: UnitOfWorkFactory,
    clock: Clock,
    store: ObjectStore,
    executors: Mapping[Node, NodeExecutor],
    *,
    vision: VisionModel | None = None,
    vision_lease: timedelta | None = None,
    facts: NodeExecutor | None = None,
) -> PipelineService:
    """A pipeline with the shipped defaults for its tuning."""
    return PipelineService(
        uow,
        clock,
        store,
        executors,
        pipeline_version="test",
        suggest_contact=DEFAULT_SETTINGS.contact_suggest_threshold,
        retry=RETRY,
        poor_reading=DEFAULT_SETTINGS.poor_reading_threshold,
        vision=vision,
        vision_lease=vision_lease,
        facts=facts,
    )


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)

# The sample files of the tests (made by `samples/make_samples.py`).
SAMPLES = Path(__file__).parent / "samples"

# LEKTO_SECRET_KEY for tests (32 bytes, base64); never use it elsewhere.
SECRET_KEY = "dGVzdC1rZXktdGVzdC1rZXktdGVzdC1rZXktdGVzdC0="
PASSWORD = "correct horse battery"
# LEKTO_FORWARDED_ALLOW_IPS for tests: required with secure cookies.
TRUSTED_PROXY = "127.0.0.1"

OK = NodeResult(outcome=Outcome.OK)
UNCERTAIN = NodeResult(outcome=Outcome.UNCERTAIN, reason="new contact", confidence=0.4)
FAILED = NodeResult(outcome=Outcome.FAILED, reason="OCR crashed")


class PlaceholderNode:
    """Node executor that does nothing and passes."""

    async def run(self, document: Document) -> NodeResult:
        return NodeResult(outcome=Outcome.OK)


class Returns:
    """Node executor that returns a fixed result (one to complete when stored, too)."""

    def __init__(self, result: NodeResult | DeferredResult) -> None:
        self.result = result
        self.calls = 0

    async def run(self, document: Document) -> NodeResult | DeferredResult:
        self.calls += 1
        return self.result


_numbers = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_numbers)}"


def user(name: str | None = None, *, role: Role = Role.USER) -> User:
    return User.create(username=name or _unique("user"), role=role, now=NOW)


def admin(name: str | None = None) -> User:
    return user(name, role=Role.ADMIN)


def space(
    editor: User,
    name: str | None = None,
    *,
    readers: Iterable[User] = (),
    editors: Iterable[User] = (),
) -> Space:
    """A space `editor` edits (as its creator), shared with `readers` and further `editors`."""
    members = {
        **{reader.id: SpaceRole.READ for reader in readers},
        **{other.id: SpaceRole.EDIT for other in editors},
        editor.id: SpaceRole.EDIT,
    }
    return Space.create(name=name or _unique("space"), members=members, now=NOW)


async def seed_user(
    uow: UnitOfWorkFactory, name: str | None = None, *, role: Role = Role.USER
) -> User:
    """A user with their personal space, stored directly."""
    seeded = user(name, role=role)
    async with uow() as unit:
        await unit.users.add(seeded)
        await unit.spaces.add(personal_space(seeded))
        await unit.commit()
    return seeded


async def seed_account(
    uow: UnitOfWorkFactory,
    hasher: PasswordHasher,
    name: str | None = None,
    *,
    role: Role = Role.USER,
    password: str = PASSWORD,
) -> User:
    """A user with their personal space and `password`, stored directly."""
    seeded = await seed_user(uow, name, role=role)
    async with uow() as unit:
        await unit.credentials.add(
            Credential(
                user_id=seeded.id,
                password_hash=await hasher.hash(check_new_password(password, seeded.username)),
            )
        )
        await unit.commit()
    return seeded


def personal_space(user: User) -> Space:
    return Space.create_personal(user=user.id, now=NOW)


def sha256(content: str | None = None) -> Sha256:
    return Sha256.of((content or _unique("content")).encode())


def document(
    uploader: User | UserId | None,
    in_space: Space | SpaceId,
    *,
    content: str | None = None,
    filename: str = "scan.pdf",
) -> Document:
    """A freshly received document `uploader` uploaded; OCR is due."""
    document = Document.receive(
        uploaded_by=uploader.id if isinstance(uploader, User) else uploader,
        space_id=in_space.id if isinstance(in_space, Space) else in_space,
        sha256=sha256(content),
        original_filename=filename,
        media_type="application/pdf",
        result=OK,
        now=NOW,
    )
    document.pull_events()
    return document


def received() -> Document:
    """A freshly received document of a new user, in their personal space."""
    uploader = user()
    return document(uploader, personal_space(uploader))


def run_pipeline(
    document: Document,
    results: dict[Node, NodeResult] | None = None,
    *,
    now: datetime = NOW,
    before: Callable[[Node], object] | None = None,
) -> Document:
    """Run the due nodes with OK (or the given results) at `now`, one at a time in graph order,
    until processing stops; `before` is called with each node before its result is stored
    (to change the document as the node would)."""
    results = results or {}
    while True:
        run = document.processing.run
        due = [node for node in document.processing.due() if document.is_awaiting(node, run)]
        if not due:
            return document
        if before is not None:
            before(due[0])
        document.record_result(due[0], run, results.get(due[0], OK), now)


def processed(
    owner: User | None,
    in_space: Space,
    results: dict[Node, NodeResult] | None = None,
    *,
    content: str | None = None,
) -> Document:
    """A document whose pipeline has run; green unless `results` say otherwise."""
    result = run_pipeline(document(owner, in_space, content=content), results)
    result.pull_events()
    return result


# Received files of the tests; the directory is removed when the test process ends.
_INCOMING = tempfile.TemporaryDirectory(prefix="lekto-tests-")


def incoming(data: bytes) -> IncomingFile:
    """`data` as a received file, ready for `PipelineService.receive`."""
    path = Path(_INCOMING.name) / uuid.uuid4().hex
    path.write_bytes(data)
    return IncomingFile.of(path)


def skip_classification(pipeline: PipelineService) -> PipelineService:
    """Let classification and field extraction pass as OK, for tests about other things
    (without a language model, they would make every document yellow)."""
    for node in (Node.JUDGE, Node.FIELDS):
        pipeline.replace_executor(node, PlaceholderNode())
    return pipeline


def index_document(**fields: Any) -> IndexDocument:
    """A green document in a random space, for the search index; `fields` override any of its
    fields."""
    values: dict[str, Any] = {
        "id": DocumentId(new_id()),
        "version": 1,
        "space_id": SpaceId(new_id()),
        "lane": Lane.GREEN,
        "title": _unique("title"),
        "filename": "scan.pdf",
        "created_at": NOW,
    }
    values.update(fields)
    return IndexDocument(**values)


def search_query(text: str, visibility: Visibility, **fields: Any) -> SearchQuery:
    """A query of the index with the shipped semantic ratio unless `fields` give one."""
    fields.setdefault("semantic_ratio", SEARCH.semantic_ratio)
    return SearchQuery(text=text, visibility=visibility, **fields)


class RunsJobs(Protocol):
    async def run_next_job(self) -> bool: ...


async def drain(runner: RunsJobs) -> int:
    """Run `runner`'s due jobs until none is left; returns how many ran."""
    count = 0
    while await runner.run_next_job():
        count += 1
    return count
