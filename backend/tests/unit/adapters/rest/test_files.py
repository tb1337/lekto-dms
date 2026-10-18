"""A document's files over HTTP: size, SHA-256 and what they say about themselves."""

import hashlib

from tests.api import auth
from tests.contracts.processing import SAMPLES
from tests.unit.adapters.rest.support import DOCUMENTS, FILENAME, Api, upload


async def test_the_original_and_the_archive_with_their_metadata(api: Api) -> None:
    owner = await api.user()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner))}"

    response = await api.client.get(f"{url}/files", headers=auth(owner))
    assert response.status_code == 200, response.text
    files = response.json()
    sample = (SAMPLES / "scan.pdf").read_bytes()
    assert (files["original_filename"], files["media_type"]) == (FILENAME, "application/pdf")
    assert files["original"]["size"] == len(sample)
    assert files["original"]["sha256"] == hashlib.sha256(sample).hexdigest()
    assert files["original"]["metadata"]["format"] == "PDF"
    assert files["original"]["metadata"]["entries"] == [
        {"source": "info", "key": "Producer", "value": "fake-metadata 1"}
    ]
    archive = files["archive"]
    assert archive["size"] > 0
    assert len(archive["sha256"]) == 64
    assert files["added"] and files["modified"]


async def test_no_archive_before_the_text_is_recognised(api: Api) -> None:
    owner = await api.user()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner), drain=False)}"
    files = (await api.client.get(f"{url}/files", headers=auth(owner))).json()
    assert files["archive"] is None
    assert files["original"]["metadata"]["pages"] == 1


async def test_files_need_read_access(api: Api) -> None:
    owner, other = await api.user(), await api.user()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner))}"
    response = await api.client.get(f"{url}/files", headers=auth(other))
    assert response.status_code == 404
