"""The services of the integration tests, made from the settings: Postgres databases, S3 stores
and Meilisearch indexes of their own, and what removes them again. The conftests hold only
fixtures."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
import httpx2

from lekto.adapters.outbound.meilisearch import MeilisearchIndex
from lekto.adapters.outbound.s3 import S3ObjectStore
from lekto.adapters.outbound.sql import Database
from lekto.composition.settings import Settings
from tests.builders import DEFAULT_SETTINGS
from tests.contracts.search_index import DIMENSIONS

# --- Postgres -----------------------------------------------------------------------------------


def postgres(settings: Settings, name: str | None = None) -> Database:
    assert settings.db_host and settings.db_name and settings.db_user and settings.db_password
    return Database.postgres(
        host=settings.db_host,
        port=settings.db_port,
        name=name or settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
    )


async def create_database(settings: Settings, name: str) -> None:
    admin = postgres(settings)
    try:
        async with admin.engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        await admin.dispose()


async def drop_database(settings: Settings, name: str) -> None:
    admin = postgres(settings)
    try:
        async with admin.engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.dispose()


# --- S3 -----------------------------------------------------------------------------------------


def s3_store(settings: Settings, prefix: str) -> S3ObjectStore:
    assert settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key
    return S3ObjectStore(
        endpoint_url=str(settings.s3_endpoint_url),
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id.get_secret_value(),
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        path_style=settings.s3_path_style,
        prefix=prefix,
    )


@asynccontextmanager
async def s3_client(settings: Settings) -> AsyncIterator[Any]:
    """A client of the S3 service, beside the stores."""
    assert settings.s3_access_key_id and settings.s3_secret_access_key
    session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        region_name=settings.s3_region,
    )
    async with session.client("s3", endpoint_url=str(settings.s3_endpoint_url)) as s3:
        yield s3


async def remove_prefix(settings: Settings, prefix: str) -> None:
    async with s3_client(settings) as s3:
        listing = await s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix=prefix)
        for item in listing.get("Contents", []):
            await s3.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])


@asynccontextmanager
async def s3_test_store(
    settings: Settings, prefix: str | None = None
) -> AsyncIterator[S3ObjectStore]:
    """A store below a key prefix of its own (`prefix`, or a new one), removed afterwards."""
    prefix = prefix or f"tests/{secrets.token_hex(8)}/"
    store = s3_store(settings, prefix)
    try:
        yield store
    finally:
        await store.aclose()
        await remove_prefix(settings, prefix)


# --- Meilisearch --------------------------------------------------------------------------------


def new_index(
    settings: Settings, name: str, *, dimensions: int | None = DIMENSIONS
) -> MeilisearchIndex:
    assert settings.meilisearch_url is not None
    key = settings.meilisearch_api_key
    return MeilisearchIndex(
        url=str(settings.meilisearch_url),
        api_key=None if key is None else key.get_secret_value(),
        index=name,
        dimensions=dimensions,
        locales=DEFAULT_SETTINGS.search_locales.split("+"),
        timeout=DEFAULT_SETTINGS.meilisearch_timeout.total_seconds(),
        task_timeout=DEFAULT_SETTINGS.meilisearch_task_timeout.total_seconds(),
    )


async def drop(settings: Settings, *names: str) -> None:
    """Delete test indexes, whatever state they are in."""
    assert settings.meilisearch_url is not None
    key = settings.meilisearch_api_key
    headers = {} if key is None else {"Authorization": f"Bearer {key.get_secret_value()}"}
    async with httpx2.AsyncClient(
        base_url=str(settings.meilisearch_url), headers=headers
    ) as client:
        for name in names:
            await client.delete(f"/indexes/{name}")
