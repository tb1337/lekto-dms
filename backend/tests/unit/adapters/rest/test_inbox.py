"""Inbox, review and confirmation over HTTP."""

from datetime import datetime, timedelta
from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.inbound.rest.cursors import encode_cursor
from lekto.core.domain.classification import (
    Candidate,
    CandidateSource,
    FieldCheck,
    checks_to_json,
)
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.labels import LabelCheck, LabelOutcome
from lekto.core.domain.master_data import Contact
from lekto.core.domain.pipeline import Node, NodeResult, Outcome
from lekto.core.domain.reasons import written
from tests.api import auth
from tests.builders import NOW, Returns
from tests.unit.adapters.rest.support import DOCUMENTS, Api, sample_file, unique_pdf, upload

PROBLEM = "application/problem+json"
NEIGHBOUR = UUID("01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b")


def uncertain(contact: Contact) -> NodeResult:
    checks = [
        FieldCheck(
            field="contact",
            outcome=Outcome.UNCERTAIN,
            confidence=0.8,
            reasons=(written("'Stadtwerk' is similar to the contact 'Stadtwerke'"),),
            proposed="Stadtwerk",
            suggestion=str(contact.id),
            candidates=(
                Candidate(
                    value=str(contact.id),
                    label="Stadtwerke",
                    sources=(
                        CandidateSource(signal="signal_llm", score=0.8, quote="Stadtwerk"),
                        CandidateSource(
                            signal="signal_neighbours",
                            names=True,
                            score=2 / 3,
                            votes=2,
                            of=3,
                            documents=(str(NEIGHBOUR), str(NEIGHBOUR)),
                        ),
                        CandidateSource(
                            signal="signal_facts", identifiers=("iban",), named_in_text=True
                        ),
                    ),
                ),
            ),
        ),
        FieldCheck(
            field="document_date",
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(written("the date does not appear in the text"),),
            proposed="2026-03-31",
            label=LabelCheck("Datum", LabelOutcome.APART),
        ),
    ]
    return NodeResult(
        outcome=Outcome.UNCERTAIN,
        reason="contact, document_date",
        model_version="fake-llm 1",
        input={"truncated": False},
        output={"fields": checks_to_json(checks)},
    )


async def test_confirm_from_the_inbox(api: Api) -> None:
    owner = await api.user()
    contact = Contact.create(name="Stadtwerke", now=NOW)
    async with api.container.unit_of_work() as uow:
        await uow.contacts.add(contact)
        await uow.commit()
    api.services.pipeline.replace_executor(Node.JUDGE, Returns(uncertain(contact)))
    response = await api.client.post(DOCUMENTS, files=sample_file(), headers=auth(owner))
    url = response.json()["status_url"]
    await api.drain()

    inbox = (await api.client.get(f"{PREFIX}/inbox", headers=auth(owner))).json()
    (item,) = inbox["items"]
    assert inbox["next_cursor"] is None
    assert item["document"]["lane"] == "yellow"
    assert item["document"]["processing"]["status"] == "review"
    (open,) = item["open"]
    assert (open["node"], open["outcome"]) == ("judge", "uncertain")
    assert [field["field"] for field in open["fields"]] == ["contact", "document_date"]
    assert open["fields"][0]["suggestion"] == str(contact.id)
    (candidate,) = open["fields"][0]["candidates"]
    assert (candidate["label"], candidate["contradicted"]) == ("Stadtwerke", False)
    llm, neighbours, facts = candidate["sources"]
    assert (llm["signal"], llm["names"], llm["score"], llm["quote"]) == (
        "signal_llm",
        False,
        0.8,
        "Stadtwerk",
    )
    assert (neighbours["votes"], neighbours["found"], neighbours["score"]) == (2, 3, 0.6667)
    # A similar document the caller cannot read (here: one that does not exist) is left out.
    assert neighbours["documents"] == []
    assert (facts["identifiers"], facts["named_in_text"]) == (["iban"], True)
    assert open["fields"][1]["candidates"] == []

    review = (await api.client.get(f"{url}/review", headers=auth(owner))).json()
    (classify,) = [node for node in review["nodes"] if node["node"] == "judge"]
    assert (classify["model_version"], classify["truncated"]) == ("fake-llm 1", False)
    assert classify["fields"][1]["proposed"] == "2026-03-31"
    # The label check is exposed as recorded (the fields node's), null where there is none.
    assert classify["fields"][1]["label"] == {"text": "Datum", "outcome": "apart"}
    assert classify["fields"][0]["label"] is None
    assert open["fields"][1]["label"] == {"text": "Datum", "outcome": "apart"}

    undecided = await api.client.post(
        f"{url}/confirm", json={"accept_suggestions": True}, headers=auth(owner)
    )
    assert undecided.status_code == 422
    assert undecided.headers["content-type"] == PROBLEM
    assert undecided.json()["open_fields"] == ["document_date"]

    for body in ({"resume_at": "file"}, {"changes": {"space_id": "x"}}, {"other": 1}):
        invalid = await api.client.post(f"{url}/confirm", json=body, headers=auth(owner))
        assert invalid.status_code == 422, body

    confirmed = await api.client.post(
        f"{url}/confirm",
        json={"changes": {"document_date": "2026-03-31"}, "accept_suggestions": True},
        headers=auth(owner),
    )
    assert confirmed.status_code == 202, confirmed.text
    nodes = {node["node"]: node["status"] for node in confirmed.json()["processing"]["nodes"]}
    assert (nodes["fields"], nodes["apply_rules"]) == ("done", "waiting")
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert document["lane"] == "green"
    assert (document["contact_id"], document["document_date"]) == (str(contact.id), "2026-03-31")
    assert (await api.client.get(f"{PREFIX}/inbox", headers=auth(owner))).json()["items"] == []

    again = await api.client.post(f"{url}/confirm", json={}, headers=auth(owner))
    assert again.status_code == 409


async def test_confirming_a_hand_over_answers_that_the_document_is_out_of_reach(
    api: Api,
) -> None:
    owner, friend = await api.user(), await api.user()
    contact = Contact.create(name="Stadtwerke", now=NOW)
    async with api.container.unit_of_work() as uow:
        await uow.contacts.add(contact)
        await uow.commit()
    api.services.pipeline.replace_executor(Node.JUDGE, Returns(uncertain(contact)))
    response = await api.client.post(DOCUMENTS, files=sample_file(), headers=auth(owner))
    url = response.json()["status_url"]
    await api.drain()
    theirs = (await api.client.get(f"{PREFIX}/users/{friend.id}", headers=auth(owner))).json()
    confirmed = await api.client.post(
        f"{url}/confirm",
        json={
            "changes": {"document_date": "2026-03-31"},
            "accept_suggestions": True,
            "space_id": theirs["personal_space_id"],
        },
        headers=auth(owner),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json() == {"id": url.rsplit("/", 1)[-1], "access": None}
    await api.drain()
    received = (await api.client.get(f"{PREFIX}/inbox", headers=auth(friend))).json()
    assert [item["document"]["id"] for item in received["items"]] == [url.rsplit("/", 1)[-1]]
    assert received["items"][0]["tab"] == "new"


async def test_the_tabs_the_summary_and_seen(api: Api) -> None:
    owner = await api.user()
    first = await upload(api, auth(owner), content=unique_pdf("first"))
    second = await upload(api, auth(owner), content=unique_pdf("second"))
    inbox = f"{PREFIX}/inbox"

    page = (await api.client.get(inbox, headers=auth(owner))).json()
    assert [(item["document"]["id"], item["tab"], item["done"]) for item in page["items"]] == [
        (second, "new", None),
        (first, "new", None),
    ]
    summary = (await api.client.get(f"{inbox}/summary", headers=auth(owner))).json()
    assert summary == {
        "new": 2,
        "review": 0,
        "intervene": 0,
        "processing": 0,
        "done": 0,
        "open": 2,
        "worst_lane": "green",
    }

    api.clock.advance(timedelta(minutes=1))
    seen = await api.client.put(f"{DOCUMENTS}/{first}/seen", headers=auth(owner))
    assert seen.status_code == 204
    new = (await api.client.get(inbox, params={"tab": "new"}, headers=auth(owner))).json()
    assert [item["document"]["id"] for item in new["items"]] == [second]
    done = (await api.client.get(inbox, params={"tab": "done"}, headers=auth(owner))).json()
    (item,) = done["items"]
    assert (item["document"]["id"], item["tab"], item["open"]) == (first, "done", [])
    assert item["done"]["how"] == "seen"
    assert item["done"]["by"] == str(owner.id)
    assert datetime.fromisoformat(item["done"]["at"]) == api.clock.now()

    again = await api.client.delete(f"{DOCUMENTS}/{first}/seen", headers=auth(owner))
    assert again.status_code == 204
    marked = await api.client.post(f"{inbox}/seen", headers=auth(owner))
    assert marked.status_code == 200
    assert marked.json() == {"marked": 2}
    summary = (await api.client.get(f"{inbox}/summary", headers=auth(owner))).json()
    assert (summary["open"], summary["done"], summary["worst_lane"]) == (0, 2, None)


async def test_done_goes_by_when_documents_left(api: Api) -> None:
    owner = await api.user()
    first = await upload(api, auth(owner), content=unique_pdf("first"))
    second = await upload(api, auth(owner), content=unique_pdf("second"))
    for document in (second, first):  # the older one is seen last
        api.clock.advance(timedelta(minutes=1))
        seen = await api.client.put(f"{DOCUMENTS}/{document}/seen", headers=auth(owner))
        assert seen.status_code == 204
    found, cursor = [], None
    while True:
        params: dict[str, str | int] = {"tab": "done", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = (await api.client.get(f"{PREFIX}/inbox", params=params, headers=auth(owner))).json()
        found += [item["document"]["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == [first, second]
    await api.client.delete(f"{DOCUMENTS}/{first}/seen", headers=auth(owner))
    gone = await api.client.get(
        f"{PREFIX}/inbox",
        params={"tab": "done", "cursor": encode_cursor(DocumentId(UUID(first)))},
        headers=auth(owner),
    )
    assert gone.status_code == 422  # its document is no longer done


async def test_the_inbox_refuses_what_it_does_not_know(api: Api) -> None:
    owner = await api.user()
    missing = "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b"
    for method in ("PUT", "DELETE"):
        response = await api.client.request(
            method, f"{DOCUMENTS}/{missing}/seen", headers=auth(owner)
        )
        assert response.status_code == 404
        assert response.headers["content-type"] == PROBLEM
    invalid = await api.client.get(f"{PREFIX}/inbox", params={"tab": "all"}, headers=auth(owner))
    assert invalid.status_code == 422
