"""Checks that the services of the devcontainer (or CI) answer. Skipped when they do not.

Which services apply comes from the `PAPIQ_` variables, the same ones the application reads; the
fixtures of `integration/conftest.py` skip when a service is not configured or does not answer.
"""

from lekto.composition.settings import Settings
from tests import probes


def test_postgres_is_reachable(postgres_settings: Settings) -> None:
    assert postgres_settings.db_host is not None
    assert probes.postgres_answers(postgres_settings.db_host, postgres_settings.db_port)


def test_garage_s3_is_reachable(s3_settings: Settings) -> None:
    # An unauthenticated request is answered with an error status (403); any status proves
    # that the S3 API listens.
    assert probes.http_status(str(s3_settings.s3_endpoint_url)) is not None


def test_meilisearch_is_reachable(meilisearch_settings: Settings) -> None:
    assert probes.meilisearch_health(str(meilisearch_settings.meilisearch_url)) == "available"
