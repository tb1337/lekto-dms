"""What Lekto needs before the documents come, `prepare` creating it, and documents in terms of
Lekto's ids."""

from typing import Any

from lekto_migration.directory import Directory
from lekto_migration.expect import Expected, field_infos
from lekto_migration.lekto import Lekto
from lekto_migration.masterdata import (
    CREATE,
    CREATED,
    EXISTS,
    FAILED,
    FILL,
    MISSING,
    UPDATE,
    UPDATED,
    Action,
    is_open,
    needs,
    prepare,
)
from lekto_migration.resolve import resolve
from tests import fake_lekto
from tests.fake_lekto import FakeLekto
from tests.world import World


def actions_of(world: World) -> list[Action]:
    plan = world.plan()
    snapshot = world.snapshot()
    return needs(
        plan, world.directory, snapshot, world.all(), field_infos(plan, world.directory, snapshot)
    )


def by(actions: list[Action], kind: str) -> dict[str, Action]:
    return {a.name: a for a in actions if a.kind == kind}


async def prepared(world: World, lekto: FakeLekto) -> tuple[list[Action], Directory]:
    client = Lekto("http://lekto", fake_lekto.TOKEN, transport=lekto.transport(), delays=())
    try:
        directory = await Directory.of(client)
        world.directory = directory
        actions = actions_of(world)
        await prepare(actions, client, directory)
        return actions, directory
    finally:
        await client.close()


def test_an_empty_lekto_needs_everything_of_the_first_plan() -> None:
    world = World()
    actions = actions_of(world)
    users = by(actions, "user")
    assert set(users) == {"tobias", "anna", "bob", "gone"}
    assert {a.status for a in users.values()} == {CREATE}
    assert users["gone"].data.get("deactivate") is True
    assert set(by(actions, "contact")) == {"ACME Energy", "Unused"}
    assert set(by(actions, "document_type")) == {"Invoice"}
    tags = list(by(actions, "tag").values())
    assert [t.name for t in tags] == ["tax", "tax/2024"]  # the parent first
    assert tags[1].data["parent"] == "tax"
    fields = by(actions, "field")
    assert fields["Kind"].data == {"data_type": "choice", "choices": ["One", "Two"]}
    assert fields["ASN"].data == {"data_type": "number"}
    spaces = by(actions, "space")
    assert set(spaces) == {
        "Geteilt: anna (bearbeiten), bob (lesen), tobias (bearbeiten)",
        "Geteilt: gone (lesen), tobias (bearbeiten)",  # deactivated in Paperless, still a member
    }
    space = spaces["Geteilt: anna (bearbeiten), bob (lesen), tobias (bearbeiten)"]
    assert space.data["members"] == [("anna", "edit"), ("bob", "read"), ("tobias", "edit")]
    assert space.data["after"] == space.data["members"]
    assert space.status == CREATE and space.source == "the permissions in Paperless"
    assert space.notes == []  # its members are those Paperless lets see the document
    assert is_open(actions)
    # The order prepare works in: users, objects, fields, groups, spaces.
    kinds = [a.kind for a in actions]
    assert (
        kinds.index("user") < kinds.index("contact") < kinds.index("field") < kinds.index("space")
    )


def test_what_exists_is_found_and_what_may_not_be_created_is_missing() -> None:
    world = World()
    world.directory.add("contact", {"id": "c1", "name": "ACME ENERGY", "group_ids": []})
    world.set("correspondents", "Unused", "{to: contact, name: Nobody}")
    world.set("tags", "tax", "{to: topic, name: Taxes}")
    world.settings["fallback_owner"] = "nobody"
    actions = actions_of(world)
    assert by(actions, "contact")["ACME Energy"].status == EXISTS
    assert by(actions, "contact")["Nobody"].status == MISSING
    assert by(actions, "topic")["Taxes"].status == MISSING
    assert by(actions, "user")["nobody"].status == MISSING


async def test_prepare_creates_it_and_then_nothing_is_open() -> None:
    world, lekto = World(), FakeLekto()
    actions, _ = await prepared(world, lekto)
    assert {a.status for a in actions} <= {CREATED, EXISTS}, [
        (a.kind, a.name, a.notes) for a in actions if a.status == FAILED
    ]
    tags = {t["name"]: t for t in lekto.tags.values()}
    assert tags["tax/2024"]["parent_id"] == tags["tax"]["id"]
    kind = next(f for f in lekto.fields.values() if f["name"] == "Kind")
    assert kind["choices"] == ["One", "Two"]
    space = next(s for s in lekto.spaces.values() if s["name"].startswith("Geteilt"))
    users = {u["id"]: u["username"] for u in lekto.users.values()}
    # The executing admin creates it without being a member.
    assert {users[m["user_id"]]: m["role"] for m in space["members"]} == {
        "anna": "edit",
        "bob": "read",
        "tobias": "edit",
    }
    world.directory = await Directory.of(
        Lekto("http://lekto", fake_lekto.TOKEN, transport=lekto.transport())
    )
    assert not is_open(actions_of(world))


def test_a_space_the_plan_names_is_made_with_the_uploaders_as_editors() -> None:
    world = World()
    world.set(
        "correspondents",
        "ACME Energy",
        "[{to: contact, name: ACME Energy}, {to: space, name: Energie}]",
    )
    space = by(actions_of(world), "space")["Energie"]
    assert space.status == CREATE  # documents of tobias and anna
    assert space.data["members"] == [("anna", "edit"), ("tobias", "edit")]
    # Paperless kept their documents apart; the report says that this space does not.
    assert space.notes == ["anna and tobias see each other's documents in 'Energie'"]


def test_an_existing_space_the_plan_names_gets_its_uploaders_and_keeps_its_members() -> None:
    world = World()
    world.set(
        "correspondents",
        "ACME Energy",
        "[{to: contact, name: ACME Energy}, {to: space, name: Energie}]",
    )
    for id, name in (("u1", "tobias"), ("u2", "anna"), ("u3", "bob")):
        world.directory.add("user", {"id": id, "username": name, "active": True})
    world.directory.spaces.append(
        {
            "id": "s1",
            "name": "ENERGIE",
            "personal_of": None,
            "members": [{"user_id": "u3", "role": "edit"}, {"user_id": "u2", "role": "read"}],
        }
    )
    space = by(actions_of(world), "space")["Energie"]
    # Every uploader edits it, to see their own documents in every lane; bob stays.
    assert (space.status, space.data["id"]) == (UPDATE, "s1")
    assert space.data["members"] == [("anna", "edit"), ("tobias", "edit")]
    assert space.data["after"] == [("anna", "edit"), ("bob", "edit"), ("tobias", "edit")]
    assert space.notes[0] == "gains access: anna (read → edit), tobias (edit)"
    assert "anna and tobias see each other's documents in 'Energie'" in space.notes
    assert any(n.startswith("bob sees documents of anna") for n in space.notes)
    # Once the uploaders are in, nothing is left to do.
    world.directory.spaces[-1]["members"] += [
        {"user_id": "u1", "role": "edit"},
        {"user_id": "u2", "role": "edit"},
    ]
    assert by(actions_of(world), "space")["Energie"].status == EXISTS


def test_a_space_an_earlier_prepare_made_gets_only_uploaders_again() -> None:
    world = World()
    for id, name in (("u1", "tobias"), ("u2", "anna"), ("u3", "bob")):
        world.directory.add("user", {"id": id, "username": name, "active": True})
    name = "Geteilt: anna (bearbeiten), bob (lesen), tobias (bearbeiten)"
    # An editor took bob and tobias (who writes in Paperless) out since; anna uploads.
    world.directory.spaces.append(
        {
            "id": "s1",
            "name": name,
            "personal_of": None,
            "members": [
                {"user_id": "u2", "role": "edit"},
            ],
        }
    )
    plan, snapshot = world.plan(), world.snapshot()
    infos = field_infos(plan, world.directory, snapshot)
    fresh = by(needs(plan, world.directory, snapshot, world.all(), infos), "space")[name]
    assert fresh.status == UPDATE  # the migration has not touched it: Paperless' members
    assert fresh.data["members"] == [("bob", "read"), ("tobias", "edit")]
    made = needs(plan, world.directory, snapshot, world.all(), infos, recorded=frozenset({"s1"}))
    assert by(made, "space")[name].status == EXISTS  # the uploader anna is in; they stay out


async def test_a_space_of_members_gets_who_is_missing_and_keeps_more() -> None:
    world, lekto = World(), FakeLekto()
    await prepared(world, lekto)
    space = next(s for s in lekto.spaces.values() if s["name"].startswith("Geteilt"))
    users = {u["username"]: u["id"] for u in lekto.users.values()}
    # Someone let bob edit and took tobias out since.
    space["members"] = [
        {"user_id": users["anna"], "role": "edit"},
        {"user_id": users["bob"], "role": "edit"},
    ]
    world.directory = await Directory.of(
        Lekto("http://lekto", fake_lekto.TOKEN, transport=lekto.transport())
    )
    assert by(actions_of(world), "space")[space["name"]].status == UPDATE
    actions, _ = await prepared(world, lekto)
    assert by(actions, "space")[space["name"]].status == UPDATED
    assert {m["user_id"]: m["role"] for m in space["members"]} == {
        users["anna"]: "edit",
        users["bob"]: "edit",
        users["tobias"]: "edit",
    }


async def test_groups_put_contacts_and_types_in_them() -> None:
    world, lekto = World(), FakeLekto()
    world.set(
        "tags",
        "tax",
        "[{to: contact_group, name: Taxpayers, create: true},"
        " {to: type_group, name: Bills, create: true}]",
    )
    actions, _ = await prepared(world, lekto)
    assert by(actions, "group")["ACME Energy in Taxpayers"].status == UPDATED
    group = next(t for t in lekto.tags.values() if t["name"] == "Taxpayers")
    assert group["scope"] == "contact"
    acme = next(c for c in lekto.contacts.values() if c["name"] == "ACME Energy")
    assert acme["group_ids"] == [group["id"]]
    invoice = next(t for t in lekto.document_types.values() if t["name"] == "Invoice")
    assert len(invoice["group_ids"]) == 1


def test_values_name_new_objects_only_with_create() -> None:
    world = World()
    world.set("custom_fields", "Text", "{to: contact, by_value: true}")
    world.set("correspondents", "ACME Energy", "drop")
    assert by(actions_of(world), "contact")["Hello"].status == MISSING
    world.set("custom_fields", "Text", "{to: contact, by_value: true, create: true}")
    assert by(actions_of(world), "contact")["Hello"].status == CREATE


def test_an_option_a_choice_field_lacks_is_added() -> None:
    world = World()
    world.directory.add(
        "field", {"id": "k", "name": "Kind", "data_type": "choice", "choices": ["One"]}
    )
    action = by(actions_of(world), "choices")["Kind"]
    assert action.status == UPDATE and action.data["choices"] == ["One", "Two"]


async def test_resolved_documents_carry_lekto_ids() -> None:
    world, lekto = World(), FakeLekto()
    world.set(
        "correspondents",
        "ACME Energy",
        "{to: contact, name: ACME Energy, create: true, review: true}",
    )
    world.set("tags", "tax", "{to: topic, name: Taxes, create: true}")
    world.set(
        "custom_fields",
        "Count",
        "{to: field, name: Count, type: number, create: true, review: Count it}",
    )
    _, directory = await prepared(world, lekto)
    expected: dict[int, Expected] = {e.id: e for e in world.all()}
    ten = resolve(expected[10], directory)
    assert ten.missing == []
    names = {
        "contact": {c["id"]: c["name"] for c in lekto.contacts.values()},
        "tag": {t["id"]: t["name"] for t in lekto.tags.values()},
        "field": {f["id"]: f["name"] for f in lekto.fields.values()},
    }
    values: dict[str, Any] = ten.values
    assert names["contact"][values["contact_id"]] == "ACME Energy"
    assert names["tag"][values["topic_id"]] == "Taxes"
    assert [names["tag"][t] for t in values["tag_ids"]] == ["tax/2024"]
    assert names["field"][next(iter(values["fields"]))] in ("Text", "Count")
    count = next(f["id"] for f in lekto.fields.values() if f["name"] == "Count")
    assert {"reason": "Count it", "field": f"field:{count}"} in ten.review
    reasons = [r["reason"] for r in ten.review]
    assert "Paperless correspondent 'ACME Energy': to be checked in Lekto" in reasons
    # The default reason goes with its code, a reason the plan writes as it is.
    coded = next(r for r in ten.review if r["reason"].startswith("Paperless correspondent"))
    assert (coded["code"], coded["params"]) == (
        "paperless_correspondent_review",
        {"name": "ACME Energy"},
    )
    assert "code" not in next(r for r in ten.review if r["reason"] == "Count it")
    assert "topic_id" not in ten.metadata() and ten.metadata()["review"] == ten.review
    shared = resolve(expected[13], directory)
    space = next(s for s in lekto.spaces.values() if s["name"].startswith("Geteilt"))
    anna = next(u["id"] for u in lekto.users.values() if u["username"] == "anna")
    assert (shared.space_id, shared.uploader_id) == (space["id"], anna)
    assert resolve(expected[14], directory).uploader_id == fake_lekto.ADMIN["id"]
    assert resolve(expected[10], directory).space_id is None  # tobias' personal space


def test_names_that_do_not_resolve_are_missing() -> None:
    world = World()
    ten = resolve(world.all()[0], world.directory)
    assert "user 'tobias'" in ten.missing and "contact 'ACME Energy'" in ten.missing


async def test_users_get_their_names_and_e_mail_from_paperless() -> None:
    """A new user gets first and last name as display name and the e-mail; an existing user
    without a name gets them too, one with a name keeps everything; a name another user has is
    left out."""
    lekto = FakeLekto()
    world = World()
    actions, directory = await prepared(world, lekto)
    users = by(actions, "user")
    assert users["anna"].detail == "Anna Example"
    assert "display name and e-mail from Paperless" in users["anna"].notes
    anna = directory.find("user", "anna")
    assert anna is not None
    assert lekto.users[str(anna["id"])]["display_name"] == "Anna Example"
    assert lekto.profiles[str(anna["id"])]["email"] == "anna@mail.example"
    bob = directory.find("user", "bob")
    assert bob is not None and lekto.users[str(bob["id"])]["display_name"] == "Bob"
    tobias = directory.find("user", "tobias")
    assert tobias is not None and not lekto.users[str(tobias["id"])].get("display_name")

    # Again: nothing changes for users who have a name.
    again, _ = await prepared(World(), lekto)
    assert {a.status for a in by(again, "user").values()} == {EXISTS}


async def test_an_existing_user_keeps_what_they_have() -> None:
    lekto = FakeLekto()
    lekto.users["u-anna"] = {"id": "u-anna", "username": "anna", "role": "user", "active": True}
    lekto.spaces["personal:u-anna"] = fake_lekto._personal("u-anna")
    lekto.profiles["u-anna"] = {"email": "own@mail.example"}
    lekto.users["u-carla"] = {
        "id": "u-carla",
        "username": "carla",
        "display_name": "Bob",
        "role": "user",
        "active": True,
    }
    lekto.spaces["personal:u-carla"] = fake_lekto._personal("u-carla")
    actions, _ = await prepared(World(), lekto)
    users = by(actions, "user")
    assert users["anna"].status == UPDATED
    assert lekto.users["u-anna"]["display_name"] == "Anna Example"
    assert lekto.profiles["u-anna"]["email"] == "own@mail.example"  # never overwritten
    assert "display name 'Bob' is taken: left out" in users["bob"].notes


async def test_filling_a_profile_is_no_open_need_and_is_planned_once() -> None:
    """An existing user without a display name gets what Paperless knows (`FILL`), which `run`
    does not wait for; once an earlier `prepare` filled it (the state's `profiled`), nothing."""
    lekto = FakeLekto()
    lekto.users["u-anna"] = {"id": "u-anna", "username": "anna", "role": "user", "active": True}
    lekto.spaces["personal:u-anna"] = fake_lekto._personal("u-anna")
    client = Lekto("http://lekto", fake_lekto.TOKEN, transport=lekto.transport(), delays=())
    try:
        directory = await Directory.of(client)
    finally:
        await client.close()
    world = World()
    world.directory = directory
    plan, snapshot = world.plan(), world.snapshot()
    infos = field_infos(plan, directory, snapshot)
    anna = by(needs(plan, directory, snapshot, world.all(), infos), "user")["anna"]
    assert anna.status == FILL and not is_open([anna])
    again = needs(plan, directory, snapshot, world.all(), infos, profiled=frozenset({"u-anna"}))
    assert by(again, "user")["anna"].status == EXISTS


async def test_an_address_lekto_refuses_is_left_out_and_the_name_still_set() -> None:
    world = World()
    for user in world.archive.users:
        if user["username"] == "anna":
            user["email"] = "anna@localhost"
    lekto = FakeLekto()
    actions, directory = await prepared(world, lekto)
    anna = by(actions, "user")["anna"]
    assert anna.status == CREATED and anna.data.get("profiled") is True
    assert "e-mail address 'anna@localhost' refused by Lekto: left out" in anna.notes
    found = directory.find("user", "anna")
    assert found is not None and lekto.users[str(found["id"])]["display_name"] == "Anna Example"
    assert not lekto.profiles[str(found["id"])]["email"]
