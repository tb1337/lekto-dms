"""Outbound ports: interfaces the core needs, implemented by outbound adapters."""

from papiq.core.ports.classifier import Classifier, Prediction, TrainedModel, TrainingExample
from papiq.core.ports.clock import Clock
from papiq.core.ports.embeddings import EmbeddingResult, Embeddings
from papiq.core.ports.event_bus import DeliveryRetry, EventBus, EventHandler, Outbox
from papiq.core.ports.identity import (
    ApiTokenRepository,
    CredentialRepository,
    DecryptionError,
    ExternalIdentityRepository,
    LoginFailureRepository,
    OidcProvider,
    PasswordHasher,
    SecretCipher,
    SessionRepository,
    Totp,
)
from papiq.core.ports.job_queue import JobQueue
from papiq.core.ports.llm import LanguageModel, StructuredAnswer, StructuredRequest
from papiq.core.ports.locator import TextLocator
from papiq.core.ports.object_store import ObjectStore
from papiq.core.ports.ocr import Ocr, OcrResult
from papiq.core.ports.pages import PageRenderer
from papiq.core.ports.parser import DocumentParser, ParseResult
from papiq.core.ports.patterns import PatternMatcher
from papiq.core.ports.repository import (
    ClassifierModelRepository,
    ContactRepository,
    DocumentFilter,
    DocumentRepository,
    DocumentTypeRepository,
    DrawerRepository,
    FieldDefinitionRepository,
    NamedRepository,
    ProcessingLog,
    Repository,
    RuleApplicationRepository,
    RuleRepository,
    TagRepository,
    UserRepository,
    WebhookRepository,
)
from papiq.core.ports.search_index import (
    IndexBuild,
    SearchHit,
    SearchIndex,
    SearchQuery,
    SearchResult,
)
from papiq.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from papiq.core.ports.webhook_sender import WebhookRequest, WebhookResponse, WebhookSender

__all__ = [
    "ApiTokenRepository",
    "Classifier",
    "ClassifierModelRepository",
    "Clock",
    "ContactRepository",
    "CredentialRepository",
    "DecryptionError",
    "DeliveryRetry",
    "DocumentFilter",
    "DocumentParser",
    "DocumentRepository",
    "DocumentTypeRepository",
    "DrawerRepository",
    "EmbeddingResult",
    "Embeddings",
    "EventBus",
    "EventHandler",
    "ExternalIdentityRepository",
    "FieldDefinitionRepository",
    "IndexBuild",
    "JobQueue",
    "LanguageModel",
    "LoginFailureRepository",
    "NamedRepository",
    "ObjectStore",
    "Ocr",
    "OcrResult",
    "OidcProvider",
    "Outbox",
    "PageRenderer",
    "ParseResult",
    "PasswordHasher",
    "PatternMatcher",
    "Prediction",
    "ProcessingLog",
    "Repository",
    "RuleApplicationRepository",
    "RuleRepository",
    "SearchHit",
    "SearchIndex",
    "SearchQuery",
    "SearchResult",
    "SecretCipher",
    "SessionRepository",
    "StructuredAnswer",
    "StructuredRequest",
    "TagRepository",
    "TextLocator",
    "Totp",
    "TrainedModel",
    "TrainingExample",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "UserRepository",
    "WebhookRepository",
    "WebhookRequest",
    "WebhookResponse",
    "WebhookSender",
]
