from datetime import timedelta

import pytest

from lekto.core.domain.errors import AuthenticationError, ConflictError
from lekto.core.domain.identity import ExternalIdentity, LoginMethod, safe_redirect
from lekto.core.domain.users import Role, User
from lekto.core.services.oidc import OidcOutcome, OidcService, OidcStart
from tests.builders import NOW
from tests.unit.services.support import World


async def link(world: World, user: User, subject: str) -> None:
    async with world.uow() as uow:
        await uow.external_identities.add(
            ExternalIdentity.link(
                issuer=world.idp.issuer, subject=subject, user_id=user.id, now=NOW
            )
        )
        await uow.commit()


def state_of(start: OidcStart) -> str:
    return start.url.split("state=")[1].split("&")[0]


async def round_trip(
    service: OidcService,
    world: World,
    start: OidcStart,
    subject: str,
    *,
    username: str | None = None,
    caller: User | None = None,
) -> OidcOutcome:
    code = world.idp.consent(start.url, subject, username=username)
    return await service.complete(
        start.flow,
        state=state_of(start),
        code=code,
        caller=None if caller is None else caller.id,
    )


async def test_sign_in_through_a_linked_account(world: World) -> None:
    user = await world.user("alice")
    await link(world, user, "sub-alice")
    service = world.oidc()
    start = await service.begin("/inbox?lane=yellow")
    assert start.flow not in start.url

    outcome = await round_trip(service, world, start, "sub-alice")

    assert outcome.redirect_to == "/inbox?lane=yellow"
    assert outcome.signed_in is not None
    assert outcome.signed_in.user.id == user.id
    assert outcome.signed_in.session.method is LoginMethod.OIDC
    await world.auth.authenticate_session(outcome.signed_in.token)


async def test_unknown_accounts_are_refused_by_default(world: World) -> None:
    await world.user("alice")
    service = world.oidc()
    with pytest.raises(AuthenticationError):
        await round_trip(service, world, await service.begin(), "sub-x", username="alice")
    async with world.uow() as uow:
        assert len(await uow.users.list_all()) == 1


async def test_accounts_can_be_created_at_first_sign_in(world: World) -> None:
    service = world.oidc(auto_create=True)
    outcome = await round_trip(service, world, await service.begin(), "sub-bob", username="bob")
    assert outcome.signed_in is not None
    bob = outcome.signed_in.user
    assert bob.username == "bob" and bob.role is Role.USER
    assert (await world.personal_space(bob)).personal_of == bob.id
    again = await round_trip(service, world, await service.begin(), "sub-bob", username="robert")
    assert again.signed_in is not None and again.signed_in.user.id == bob.id

    # Never by name: another subject with a taken name does not get that account.
    with pytest.raises(ConflictError):
        await round_trip(service, world, await service.begin(), "sub-other", username="bob")
    with pytest.raises(AuthenticationError):
        await round_trip(service, world, await service.begin(), "sub-nameless")


async def test_a_new_account_takes_the_name_and_e_mail_given(world: World) -> None:
    """Only at creation, and only what is free and valid."""
    service = world.oidc(auto_create=True)
    start = await service.begin()
    code = world.idp.consent(
        start.url, "sub-bob", username="bob", name="Bob Example", email="Bob@Mail.Example"
    )
    outcome = await service.complete(start.flow, state=state_of(start), code=code, caller=None)
    assert outcome.signed_in is not None
    bob = outcome.signed_in.user
    start = await service.begin()
    code = world.idp.consent(start.url, "sub-rob", username="rob", name="bob example", email="x")
    other = await service.complete(start.flow, state=state_of(start), code=code, caller=None)
    assert other.signed_in is not None
    async with world.uow() as uow:
        assert (await uow.users.get(bob.id)).display_name == "Bob Example"
        assert (await uow.profiles.get(bob.id)).email == "bob@mail.example"
        assert (await uow.users.get(other.signed_in.user.id)).display_name is None  # taken
        assert await uow.profiles.find(other.signed_in.user.id) is None  # no address


async def test_the_flow_must_match_and_be_fresh(world: World) -> None:
    user = await world.user("alice")
    await link(world, user, "sub-alice")
    service = world.oidc()
    start = await service.begin()
    code = world.idp.consent(start.url, "sub-alice")
    other = await service.begin()
    for flow, state in [
        (start.flow, state_of(other)),  # state of another flow
        (other.flow, state_of(start)),  # cookie of another browser
        (None, state_of(start)),  # no cookie
        (start.flow[:-4] + "AAAA", state_of(start)),  # tampered
    ]:
        with pytest.raises(AuthenticationError):
            await service.complete(flow, state=state, code=code)

    late = await service.begin()
    world.clock.advance(timedelta(minutes=10))
    with pytest.raises(AuthenticationError):
        await round_trip(service, world, late, "sub-alice")


async def test_deactivated_users_cannot_sign_in(world: World) -> None:
    user = await world.user("alice")
    await link(world, user, "sub-alice")
    async with world.uow() as uow:
        stored = await uow.users.get(user.id)
        stored.active = False
        await uow.users.update(stored)
        await uow.commit()
    service = world.oidc()
    with pytest.raises(AuthenticationError):
        await round_trip(service, world, await service.begin(), "sub-alice")


async def test_linking_an_account(world: World) -> None:
    alice, bob = await world.account("alice"), await world.account("bob")
    service = world.oidc()

    start = await service.begin_link(alice.id, "/settings")
    with pytest.raises(AuthenticationError):  # signed in as someone else at the callback
        await round_trip(service, world, start, "sub-alice", caller=bob)
    start = await service.begin_link(alice.id, "/settings")
    with pytest.raises(AuthenticationError):  # not signed in at the callback
        await round_trip(service, world, start, "sub-alice")

    start = await service.begin_link(alice.id, "/settings")
    outcome = await round_trip(service, world, start, "sub-alice", caller=alice)
    assert outcome == OidcOutcome(signed_in=None, redirect_to="/settings")
    assert [link.subject for link in await service.links(alice.id)] == ["sub-alice"]

    signed_in = await round_trip(service, world, await service.begin(), "sub-alice")
    assert signed_in.signed_in is not None and signed_in.signed_in.user.id == alice.id

    start = await service.begin_link(bob.id)
    with pytest.raises(ConflictError):
        await round_trip(service, world, start, "sub-alice", caller=bob)


async def test_unlinking_needs_a_password(world: World) -> None:
    alice = await world.account("alice")
    nopass = await world.user("nopass")
    await link(world, alice, "sub-alice")
    await link(world, nopass, "sub-nopass")
    service = world.oidc()
    with pytest.raises(ConflictError):
        await service.unlink(nopass.id)
    assert await service.unlink(alice.id) == 1
    with pytest.raises(AuthenticationError):
        await round_trip(service, world, await service.begin(), "sub-alice")


def test_only_paths_here_are_redirect_targets() -> None:
    for good in ("/", "/inbox", "/documents/1?x=y#z"):
        assert safe_redirect(good) == good
    for bad in (
        None,
        "",
        "https://evil.example",
        "//evil.example/x",
        "/\\evil.example",
        "javascript:alert(1)",
        "/in box",
        "/x\r\nLocation: https://evil.example",
        "/" + "a" * 2001,
    ):
        assert safe_redirect(bad) == "/"
