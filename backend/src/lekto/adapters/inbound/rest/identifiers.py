"""`/identifiers/open`: the identifiers no person has confirmed, and decisions about them;
`/identifiers/refs`: the references that name a value in an address."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from lekto.adapters.inbound.rest.auth import PROTECTED, READS, Authenticated, CurrentUser
from lekto.adapters.inbound.rest.context import ApiContext, Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.open_identifiers import (
    OpenCountsOut,
    OpenDecisionsIn,
    OpenDetailOut,
    OpenPageOut,
    OpenSearchIn,
    OutcomeOut,
    PlaceOut,
    PlacesOut,
)
from lekto.adapters.inbound.rest.schemas.refs import MAX_REF, RefIn, RefOut, opened, seal
from lekto.core.domain.identifiers import IdentifierKind, normalise_identifier
from lekto.core.domain.ids import UserId
from lekto.core.domain.open_identifiers import OpenSource
from lekto.core.ports.repository import PAGE_LIMIT

router = APIRouter(prefix="/identifiers/open", tags=["identifiers"], dependencies=PROTECTED)

_OPEN = (
    "Open are the identifiers no person has confirmed: those training learned at a contact "
    "(`learned`), and those of a contact's kind that confirmed documents with a contact show but "
    "no contact has, entered, learned or rejected (`unknown`). A person's value (a user's "
    "profile) is never open."
)


_LIST = (
    " The most documents first, then the newest. `recommended` keeps those whose documents "
    "recommend confirming or rejecting them (`recommendation`)."
)


class _Listing:
    """The query parameters of the list, shared by `GET` and the search."""

    def __init__(
        self,
        source: OpenSource | None = None,
        kind: IdentifierKind | None = None,
        recommended: bool = False,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=0, le=PAGE_LIMIT)] = 50,
    ) -> None:
        self.source, self.kind, self.recommended = source, kind, recommended
        self.offset, self.limit = offset, limit

    async def page(self, user: UserId, context: ApiContext, words: str | None) -> OpenPageOut:
        page = await context.open_identifiers.page(
            user,
            source=self.source,
            kind=self.kind,
            words=words,
            recommended=self.recommended,
            offset=self.offset,
            limit=self.limit,
        )
        return OpenPageOut.of(page, context.refs)


Listing = Annotated[_Listing, Depends()]


@router.get(
    "",
    summary="The open identifiers",
    description=ADMINS_ONLY + " " + _OPEN + _LIST + " To find words: `POST /search`.",
    response_model=OpenPageOut,
    responses=problem_responses(401, 403, 422),
)
async def open_identifiers(user: CurrentUser, context: Context, listing: Listing) -> OpenPageOut:
    return await listing.page(user, context, None)


@router.post(
    "/search",
    openapi_extra=READS,
    summary="Find open identifiers by words",
    description=(
        ADMINS_ONLY + " The list of `GET` with the words of `q`, which go in the body so that "
        "they stay out of addresses and logs." + _LIST
    ),
    response_model=OpenPageOut,
    responses=problem_responses(401, 403, 422),
)
async def search_open_identifiers(
    body: OpenSearchIn, user: CurrentUser, context: Context, listing: Listing
) -> OpenPageOut:
    return await listing.page(user, context, body.q)


@router.get(
    "/summary",
    summary="How many identifiers are open",
    description=ADMINS_ONLY + " " + _OPEN,
    response_model=OpenCountsOut,
    responses=problem_responses(401, 403),
)
async def open_summary(user: CurrentUser, context: Context) -> OpenCountsOut:
    return OpenCountsOut.of(await context.open_identifiers.summary(user))


@router.get(
    "/{kind}/{ref}",
    summary="An open identifier and where it stands",
    description=(
        ADMINS_ONLY + " The open identifier of `kind` with the value of `ref` (its `ref` in the "
        "list) and where it stands in its five newest documents. 404 if it is not open, 422 "
        "for a reference that names no value of the kind."
    ),
    response_model=OpenDetailOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def open_detail(
    user: CurrentUser,
    context: Context,
    kind: IdentifierKind,
    ref: Annotated[str, Path(max_length=MAX_REF)],
) -> OpenDetailOut:
    value = opened(context.refs, kind, ref)
    return OpenDetailOut.of(await context.open_identifiers.detail(user, kind, value), context.refs)


@router.post(
    "/decisions",
    summary="Confirm or reject open identifiers",
    description=(
        ADMINS_ONLY + " Each decision is a change of its contact on its own: confirming enters "
        "the identifier there by hand (a learned one keeps its topic and user), rejecting takes "
        "a learned one out or notes an unknown one rejected, so training does not learn it "
        "again. One that cannot be done (no longer open, the contact unclear, another contact "
        "has it entered) says why in its outcome; the others are done all the same. In the "
        "order given."
    ),
    response_model=list[OutcomeOut],
    responses=problem_responses(401, 403, 422),
)
async def decide_open(
    body: OpenDecisionsIn, principal: Authenticated, context: Context
) -> list[OutcomeOut]:
    outcomes = await context.open_identifiers.decide(
        principal.id,
        [item.decision() for item in body.decisions],
        session=principal.session is not None,
    )
    return [OutcomeOut.of(outcome) for outcome in outcomes]


@router.post(
    "/recommended",
    summary="Confirm the open identifiers their documents recommend",
    description=(
        ADMINS_ONLY + " Confirms every open identifier whose `recommendation` is `confirm` "
        "(`to_confirm` of the list), each as a decision `confirm` of `POST /decisions`: one "
        "that cannot be done says why in its outcome, the others are done all the same. Never "
        "rejects. A suggestion for a person's profile needs a session."
    ),
    response_model=list[OutcomeOut],
    responses=problem_responses(401, 403),
)
async def confirm_recommended(principal: Authenticated, context: Context) -> list[OutcomeOut]:
    outcomes = await context.open_identifiers.confirm_recommended(
        principal.id, session=principal.session is not None
    )
    return [OutcomeOut.of(outcome) for outcome in outcomes]


refs_router = APIRouter(prefix="/identifiers/refs", tags=["identifiers"], dependencies=PROTECTED)


@refs_router.post(
    "",
    openapi_extra=READS,
    summary="The reference to a value",
    description=(
        "The reference to an identifier's value, for addresses that name it (the `fact` "
        "filter of the documents): the value goes in the body, the reference in the URL, so "
        "the value stays out of histories, bookmarks and logs. The same value (normalised) "
        "always gives the same reference while the instance's secret key stays. 422 for a "
        "value that is none of its kind."
    ),
    response_model=RefOut,
    responses=problem_responses(401, 422),
)
async def make_ref(body: RefIn, user: CurrentUser, context: Context) -> RefOut:
    value = normalise_identifier(body.kind, body.value)
    return RefOut(kind=body.kind, value=value, ref=seal(context.refs, body.kind, value))


@refs_router.get(
    "/{kind}/{ref}",
    summary="The value of a reference",
    description="To show what a reference names. 422 for one that names no value of the kind.",
    response_model=RefOut,
    responses=problem_responses(401, 422),
)
async def read_ref(
    kind: IdentifierKind,
    ref: Annotated[str, Path(max_length=MAX_REF)],
    user: CurrentUser,
    context: Context,
) -> RefOut:
    return RefOut(kind=kind, value=opened(context.refs, kind, ref), ref=ref)


places_router = APIRouter(
    prefix="/identifiers/places", tags=["identifiers"], dependencies=PROTECTED
)


@places_router.get(
    "/{kind}/{ref}",
    summary="Where an identifier stands",
    description=(
        "The newest documents within the caller's reach that have the value of `ref` of `kind` "
        "as a fact (none a person rejected), by document date, at most five: the text around "
        "it and each place their pages show it, the one the fact was read at as `own`. A "
        "person's kinds only for admins (403, as the `fact` filter); 422 for a reference that "
        "names no value of the kind."
    ),
    response_model=PlacesOut,
    responses=problem_responses(401, 403, 422),
)
async def identifier_places(
    kind: IdentifierKind,
    ref: Annotated[str, Path(max_length=MAX_REF)],
    user: CurrentUser,
    context: Context,
) -> PlacesOut:
    value = opened(context.refs, kind, ref)
    places = await context.documents.identifier_places(user, kind, value)
    return PlacesOut(places=[PlaceOut.of(place) for place in places])
