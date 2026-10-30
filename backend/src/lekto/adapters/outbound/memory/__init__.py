"""In-memory adapters for every port, used in core tests and local development.

They behave like the real adapters, including transactions: nothing is stored without commit.
"""

from lekto.adapters.outbound.memory.classifier import FakeClassifier
from lekto.adapters.outbound.memory.clock import ManualClock
from lekto.adapters.outbound.memory.crypto import (
    FakeCipher,
    FakePasswordHasher,
    FakeRefCipher,
    FakeTotp,
)
from lekto.adapters.outbound.memory.database import MemoryDatabase
from lekto.adapters.outbound.memory.event_bus import MemoryEventBus
from lekto.adapters.outbound.memory.images import FAKE_LOGO, FakeImageNormaliser
from lekto.adapters.outbound.memory.language_model import (
    BagOfWordsEmbeddings,
    FakeEmbeddings,
    FakeLanguageModel,
)
from lekto.adapters.outbound.memory.logos import FakeLogoFetcher
from lekto.adapters.outbound.memory.object_store import MemoryObjectStore
from lekto.adapters.outbound.memory.oidc import FakeOidcProvider
from lekto.adapters.outbound.memory.processing import (
    FAKE_GIRO_CODE,
    FAKE_VISION,
    FakeCodeReader,
    FakeMetadataReader,
    FakeOcr,
    FakePageRenderer,
    FakeParser,
    FakeTextLocator,
)
from lekto.adapters.outbound.memory.search_index import MemorySearchIndex
from lekto.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork, MemoryUnitOfWorkFactory
from lekto.adapters.outbound.memory.wakeup import MemoryWakeup
from lekto.adapters.outbound.memory.webhook_sender import FakeWebhookSender

__all__ = [
    "FAKE_GIRO_CODE",
    "FAKE_LOGO",
    "FAKE_VISION",
    "BagOfWordsEmbeddings",
    "FakeCipher",
    "FakeClassifier",
    "FakeCodeReader",
    "FakeEmbeddings",
    "FakeImageNormaliser",
    "FakeLanguageModel",
    "FakeLogoFetcher",
    "FakeMetadataReader",
    "FakeOcr",
    "FakeOidcProvider",
    "FakePageRenderer",
    "FakeParser",
    "FakePasswordHasher",
    "FakeRefCipher",
    "FakeTextLocator",
    "FakeTotp",
    "FakeWebhookSender",
    "ManualClock",
    "MemoryDatabase",
    "MemoryEventBus",
    "MemoryObjectStore",
    "MemorySearchIndex",
    "MemoryUnitOfWork",
    "MemoryUnitOfWorkFactory",
    "MemoryWakeup",
]
