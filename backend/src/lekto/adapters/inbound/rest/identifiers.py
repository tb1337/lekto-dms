"""`/identifiers/open`: the identifiers no person has confirmed, and decisions about them."""

from typing import Annotated

from fastapi import APIRouter, Query

from lekto.adapters.inbound.rest.auth import PROTECTED, Authenticated, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.open_identifiers import (
    OpenCountsOut,
    OpenDecisionsIn,
    OpenDetailOut,
    OpenPageOut,
    OutcomeOut,
)
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.open_identifiers import OpenSource

router = APIRouter(prefix="/identifiers/open", tags=["identifiers"], dependencies=PROTECTED)

PAGE_LIMIT = 200

_OPEN = (
    "Open are the identifiers no person has confirmed: those training learned at a contact "
    "(`learned`), and those of a contact's kind that confirmed documents with a contact show but "
    "no contact has, entered, learned or rejected (`unknown`). A person's value (a user's "
    "profile) is never open."
)


@router.get(
    "",
    summary="The open identifiers",
    description=(
        ADMINS_ONLY + " " + _OPEN + " The most documents first, then the newest. `q` finds "
        "words in the value (with or without spaces), as written or in a contact's name; "
        "`recommended` keeps those whose documents recommend confirming or rejecting them "
        "(`recommendation`)."
    ),
    response_model=OpenPageOut,
    responses=problem_responses(401, 403, 422),
)
async def open_identifiers(
    user: CurrentUser,
    context: Context,
    source: OpenSource | None = None,
    kind: IdentifierKind | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    recommended: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=0, le=PAGE_LIMIT)] = 50,
) -> OpenPageOut:
    page = await context.open_identifiers.page(
        user,
        source=source,
        kind=kind,
        words=q,
        recommended=recommended,
        offset=offset,
        limit=limit,
    )
    return OpenPageOut.of(page)


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
    "/detail",
    summary="An open identifier and where it stands",
    description=(
        ADMINS_ONLY + " The open identifier of `kind` and `value` (normalised, as the list "
        "gives it) and where it stands in its five newest documents. 404 if it is not open."
    ),
    response_model=OpenDetailOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def open_detail(
    user: CurrentUser,
    context: Context,
    kind: IdentifierKind,
    value: Annotated[str, Query(min_length=1, max_length=200)],
) -> OpenDetailOut:
    return OpenDetailOut.of(await context.open_identifiers.detail(user, kind, value))


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
