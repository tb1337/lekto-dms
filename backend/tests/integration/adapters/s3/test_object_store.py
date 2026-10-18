"""The S3 object store passes the contract against the configured server (Garage in the
devcontainer). Every test works below a key prefix of its own, removed afterwards."""

import secrets
from collections.abc import AsyncIterator

import pytest

from papiq.adapters.outbound.s3 import S3ObjectStore
from papiq.composition.settings import Settings
from tests.contracts.object_store import ObjectStoreContract
from tests.integration.services import s3_client, s3_store, s3_test_store


@pytest.fixture
async def object_store(s3_settings: Settings) -> AsyncIterator[S3ObjectStore]:
    async with s3_test_store(s3_settings) as store:
        yield store


class TestS3ObjectStore(ObjectStoreContract):
    pass


async def test_the_content_type_is_stored(s3_settings: Settings) -> None:
    """As a client of its own sees the object, below the store's prefix."""
    prefix = f"tests/{secrets.token_hex(8)}/"
    async with s3_test_store(s3_settings, prefix) as store, s3_client(s3_settings) as s3:
        await store.put("a.pdf", b"%PDF", content_type="application/pdf")
        head = await s3.head_object(Bucket=s3_settings.s3_bucket, Key=prefix + "a.pdf")
    assert head["ContentType"] == "application/pdf"


async def test_the_store_can_be_closed_and_reused(object_store: S3ObjectStore) -> None:
    await object_store.put("a", b"x", content_type="text/plain")
    await object_store.aclose()
    assert await object_store.get("a") == b"x"


async def test_check_needs_the_bucket(object_store: S3ObjectStore, s3_settings: Settings) -> None:
    await object_store.check()
    missing = s3_store(s3_settings.model_copy(update={"s3_bucket": "papiq-missing"}), "")
    try:
        with pytest.raises(Exception, match=r"404|NoSuchBucket|Not Found"):
            await missing.check()
    finally:
        await missing.aclose()
