"""Edge cases found in review: inactive uploaders, the executing admin among the members, spaces
that cannot be made, lost answers, big values, documents moved in Lekto, old state files."""

import json
from pathlib import Path
from typing import Any

from lekto_migration.config import public
from lekto_migration.fake_paperless import pdf
from lekto_migration.report import run_documents
from lekto_migration.state import State
from tests.conftest import PDF, Setup
from tests.fake_lekto import ADMIN


def add_document(setup: Setup, id: int, owner: int | None, **changes: Any) -> None:
    template = setup.archive.documents[2]
    setup.archive.documents.append(
        {
            **template,
            "id": id,
            "title": f"Extra {id}",
            "owner": owner,
            "original_file_name": f"extra-{id}.pdf",
            **changes,
        }
    )
    setup.archive.files[id] = pdf(id, PDF)


def titled(setup: Setup, title: str) -> dict[str, Any]:
    return next(d for d in setup.lekto.documents.values() if d["title"] == title)


def row(setup: Setup, command: str, id: int) -> dict[str, Any]:
    return next(d for d in setup.report(command)["documents"] if d["id"] == id)


async def test_documents_of_an_inactive_user_are_taken_over_and_the_user_deactivated(
    setup: Setup,
) -> None:
    # "gone" (id 4) is inactive in Paperless and owns a document that anna may read.
    add_document(
        setup,
        30,
        4,
        permissions={"view": {"users": [2], "groups": []}, "change": {"users": [], "groups": []}},
    )
    assert await setup.migrate() == 0
    document = titled(setup, "Extra 30")
    gone = next(u for u in setup.lekto.users.values() if u["username"] == "gone")
    assert document["uploaded_by"] == gone["id"] and gone["active"] is False
    members = setup.lekto.spaces[document["space_id"]]["members"]
    assert {"user_id": gone["id"], "role": "edit"} in members
    # A second run wakes nobody up and writes nothing.
    writes = len(setup.lekto.writes())
    assert await setup.run("run") == 0
    assert len(setup.lekto.writes()) == writes
    assert await setup.run("check") == 0


async def test_a_run_that_failed_for_an_inactive_uploader_wakes_the_user_for_the_retry(
    setup: Setup,
) -> None:
    add_document(setup, 30, 4)
    setup.lekto.errors["extra-30.pdf"] = (422, 99)
    assert await setup.migrate() == 1
    gone = next(u for u in setup.lekto.users.values() if u["username"] == "gone")
    assert gone["active"] is False
    setup.lekto.errors.clear()
    assert await setup.run("run") == 0
    assert titled(setup, "Extra 30")["uploaded_by"] == gone["id"]
    assert gone["active"] is False


async def test_prepare_wakes_a_user_it_deactivated_to_make_them_a_member(setup: Setup) -> None:
    assert await setup.migrate() == 0
    gone = next(u for u in setup.lekto.users.values() if u["username"] == "gone")
    assert gone["active"] is False
    # tobias' new document is one gone (deactivated in Paperless) may change: a new space.
    add_document(
        setup,
        30,
        1,
        permissions={"view": {"users": [], "groups": []}, "change": {"users": [4], "groups": []}},
    )
    assert await setup.run("prepare") == 0
    space = next(
        s
        for s in setup.lekto.spaces.values()
        if s["name"] == "Geteilt: gone (bearbeiten), tobias (bearbeiten)"
    )
    assert {"user_id": gone["id"], "role": "edit"} in space["members"]
    assert gone["active"] is False  # deactivated again
    assert await setup.run("run") == 0
    assert titled(setup, "Extra 30")["space_id"] == space["id"]


async def test_a_share_with_the_executing_admin_makes_it_an_editor(setup: Setup) -> None:
    setup.archive.users.append(
        {
            "id": 5,
            "username": ADMIN["username"],
            "is_active": True,
            "is_superuser": True,
            "groups": [],
        }
    )
    # No owner: the executing admin uploads the document, and the permissions name the admin.
    add_document(
        setup,
        31,
        None,
        permissions={
            "view": {"users": [5, 3], "groups": []},
            "change": {"users": [], "groups": []},
        },
    )
    assert await setup.migrate() == 0
    document = titled(setup, "Extra 31")
    assert document["uploaded_by"] == ADMIN["id"]
    space = setup.lekto.spaces[document["space_id"]]
    bob = next(u["id"] for u in setup.lekto.users.values() if u["username"] == "bob")
    # The uploader edits the space; the admin's own read share does not lower that.
    assert sorted((m["user_id"], m["role"]) for m in space["members"]) == sorted(
        [(ADMIN["id"], "edit"), (bob, "read")]
    )


async def test_a_space_that_cannot_be_made_holds_the_run_back(setup: Setup) -> None:
    setup.lekto.refuse["POST /spaces"] = 422
    assert await setup.migrate() == 1  # prepare
    spaces = [a for a in setup.report("prepare")["actions"] if a["kind"] == "space"]
    assert [a["status"] for a in spaces] == ["failed", "failed"]
    assert await setup.run("run") == 2
    assert setup.lekto.documents == {}
    setup.lekto.refuse.clear()
    assert await setup.migrate() == 0
    assert len(setup.lekto.documents) == 8


async def test_a_lost_answer_after_creating_a_user_is_not_an_error(setup: Setup) -> None:
    setup.lekto.lose_answer = {"anna", "ACME Energy"}
    assert await setup.migrate() == 0
    names = [u["username"] for u in setup.lekto.users.values()]
    assert names.count("anna") == 1
    assert [c["name"] for c in setup.lekto.contacts.values()].count("ACME Energy") == 1


async def test_a_refusal_of_prepare_leaves_a_report_and_no_document(setup: Setup) -> None:
    setup.lekto.refuse["POST /users"] = 422
    assert await setup.migrate() == 1
    users = [a for a in setup.report("prepare")["actions"] if a["kind"] == "user"]
    assert {u["status"] for u in users if u["name"] != "root"} == {"failed"}
    assert await setup.run("run") == 2
    assert setup.lekto.documents == {}


async def test_a_huge_value_is_left_out_not_the_whole_document(setup: Setup) -> None:
    setup.archive.documents[0]["custom_fields"][1] = {"field": 2, "value": "x" * 60_000}
    assert await setup.migrate() == 0
    document = titled(setup, "Document 10")
    assert len(json.dumps(document["fields"])) < 45_000
    assert any("too large" in note for note in row(setup, "run", 10)["notes"])


async def test_what_paperless_has_beyond_documents_is_counted(setup: Setup) -> None:
    setup.archive.trash, setup.archive.mail_accounts = 3, 2
    assert await setup.run("plan") == 0
    counts = setup.report("plan")["source_counts"]
    assert (counts["trash"], counts["mail_accounts"], counts["saved_views"]) == (3, 2, 2)


async def test_further_versions_of_a_file_are_reported(setup: Setup) -> None:
    setup.archive.documents[0]["versions"] = [
        {"id": 10, "is_root": True, "checksum": "x"},
        {"id": 99, "is_root": False, "checksum": "y"},
    ]
    assert await setup.migrate() == 0
    assert any("further versions" in note for note in row(setup, "run", 10)["notes"])


async def test_a_document_a_person_moved_stays_where_it_is(setup: Setup) -> None:
    assert await setup.migrate() == 0
    document = titled(setup, "Document 12")  # anna's, in her personal space
    document["space_id"] = f"personal:{ADMIN['id']}"  # a rule or a person filed it elsewhere
    assert await setup.run("check") == 0
    differences = row(setup, "check", 12)["differences"]
    assert [(d["what"], d["action"]) for d in differences] == [("space", "kept")]
    assert await setup.run("run") == 0
    assert document["space_id"] == f"personal:{ADMIN['id']}"


async def test_a_duplicate_gets_its_lane_too(setup: Setup) -> None:
    assert await setup.migrate() == 0
    other = setup.directory / "other.sqlite"
    assert await setup.run("prepare", state=other) == 0
    assert await setup.run("run", state=other) == 0
    lanes = {d["lane"] for d in setup.report("run")["documents"] if d["status"] == "duplicate"}
    assert lanes == {"green"}


def test_addresses_lose_their_credentials() -> None:
    assert public("https://user:secret@host:8000/base?x=1") == "https://host:8000/base"
    assert public("http://localhost:8765") == "http://localhost:8765"
    assert public(None) is None


async def test_a_run_notes_that_a_document_was_repaired_since(setup: Setup) -> None:
    setup.lekto.lanes["scan-12.pdf"] = "red"
    assert await setup.migrate() == 0
    assert setup.report("run")["lanes"] == {"green": 7, "red": 1}
    document = titled(setup, "Document 12")
    document["_lane"] = "green"  # retried and fixed in Lekto
    assert await setup.run("run") == 0
    report = setup.report("run")
    assert report["lanes"] == {"green": 8}
    assert row(setup, "run", 12)["reason"] is None


def test_a_state_from_before_spaces_reads_its_drawers_as_spaces(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    state = State(path)
    state.put_object("drawer", "anna|bob", "Shared", "id-1", "new", [])
    state.put_document(7, "done", detail={"title": "T", "drawer": "Shared", "owner": "anna"})
    state.close()

    state = State(path)
    assert state.object("space", "anna|bob") == ("id-1", "new")
    assert state.object("drawer", "anna|bob") is None
    found = state.document(7)
    assert found is not None
    assert found.detail == {"title": "T", "space": "Shared", "owner": "anna"}
    # Before 0.5 the state kept the Paperless owner, which uploaded the document.
    assert run_documents(state, {7})[0]["uploaded_by"] == "anna"
    state.close()


def test_a_state_from_before_the_plan_learns_what_was_applied(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "state.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE documents (
            source_id INTEGER PRIMARY KEY, status TEXT NOT NULL, lekto_id TEXT, sha256 TEXT,
            lane TEXT, reason TEXT, notes TEXT NOT NULL DEFAULT '[]',
            detail TEXT NOT NULL DEFAULT '{}', upload_seconds REAL, pipeline_seconds REAL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO documents (source_id, status, lekto_id, updated_at)
            VALUES (7, 'done', 'l7', '2026-10-10');
        """
    )
    old.commit()
    old.close()
    state = State(path)
    found = state.document(7)
    assert found is not None and found.lekto_id == "l7" and found.applied is None
    state.put_document(7, "done", applied={"title": "T"})
    again = state.document(7)
    assert again is not None and again.applied == {"title": "T"} and again.lekto_id == "l7"
    state.close()
