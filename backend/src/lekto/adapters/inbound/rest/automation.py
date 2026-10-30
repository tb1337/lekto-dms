"""The numbers of the page "System" about the automation: every user sees them."""

from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from pydantic import AfterValidator

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.automation import (
    AutomationOut,
    HolderCasesOut,
    HoldersOut,
    SignalsOut,
)
from lekto.core.domain.documents import Channel
from lekto.core.domain.holder_evaluation import HolderOutcome
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.services.automation import DEFAULT_CHANNELS, Period

router = APIRouter(prefix="/automation", tags=["automation"], dependencies=PROTECTED)

SCOPE = (
    "For the documents of the channels given (by default `web` and `api`: migrated documents "
    "bring the metadata of the source system) and the period (30 days, the current month and "
    "the eleven before it, or all time; the history by month reaches back five years at most); "
    "the whole system's numbers, naming no document. Counted again at most once a minute."
)


def _zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone: {name!r:.80}") from None
    return name


Channels = Annotated[
    list[Channel] | None, Query(alias="channel", description="Repeat for several.")
]
Zone = Annotated[
    str,
    Query(
        max_length=64,
        description="The IANA time zone the months begin in.",
        examples=["Europe/Berlin"],
    ),
    AfterValidator(_zone),
]


def channels_of(channel: list[Channel] | None) -> frozenset[Channel]:
    return frozenset(channel) if channel else DEFAULT_CHANNELS


@router.get(
    "",
    summary="How the automation did",
    description=(
        "The documents by the lane their first run stopped in, what became of them, the history "
        "by month, how long the first runs took and worked (per step too), and how people judged "
        "what the automation set, per field, at their first decision on it. " + SCOPE
    ),
    response_model=AutomationOut,
    responses=problem_responses(401, 422),
)
async def automation(
    user: CurrentUser,
    context: Context,
    channel: Channels = None,
    period: Period = Period.MONTHS_12,
    tz: Zone = "UTC",
) -> AutomationOut:
    report = await context.automation.report(
        user, channels=channels_of(channel), period=period, zone=ZoneInfo(tz)
    )
    return AutomationOut.of(report)


@router.get(
    "/signals",
    summary="How often each signal hit",
    description=(
        "Per field and signal (language model, classifier, similar documents, facts in the "
        "text), how often the signal's best value was the one a person decided at their first "
        "decision on the field, and how often another. " + SCOPE
    ),
    response_model=SignalsOut,
    responses=problem_responses(401, 422),
)
async def signals(
    user: CurrentUser,
    context: Context,
    channel: Channels = None,
    period: Period = Period.MONTHS_12,
    tz: Zone = "UTC",
) -> SignalsOut:
    report = await context.automation.signals(
        user, channels=channels_of(channel), period=period, zone=ZoneInfo(tz)
    )
    return SignalsOut.of(report)


@router.get(
    "/holders",
    summary="The holders against the decisions at the contacts",
    description=(
        ADMINS_ONLY + " Each identifier a person confirmed or rejected at a contact that "
        "confirmed documents of that contact show: per kind with a holder, how often the rule's "
        "holder there agreed with the decision, and how often it said the contact's where the "
        "person rejected (training learns it) or someone else's where they confirmed; and the "
        "same for the recommendation of the open identifiers, over every kind. Kept for a "
        "minute."
    ),
    response_model=HoldersOut,
    responses=problem_responses(401, 403),
)
async def holders(user: CurrentUser, context: Context) -> HoldersOut:
    return HoldersOut.of(await context.automation.holders(user))


@router.get(
    "/holders/cases",
    summary="The decisions behind a number of the holders",
    description=(
        ADMINS_ONLY + " The decisions behind one number of `GET /holders`: measured by the "
        "holders of `measure` (a kind with a holder) or by the `recommendation`, with "
        "`outcome` (a column), at most a hundred, each with the confirmed documents of its "
        "contact that show it."
    ),
    response_model=HolderCasesOut,
    responses=problem_responses(401, 403, 422),
)
async def holder_cases(
    user: CurrentUser,
    context: Context,
    measure: IdentifierKind | Literal["recommendation"],
    outcome: HolderOutcome,
) -> HolderCasesOut:
    kind = None if measure == "recommendation" else IdentifierKind(measure)
    cases, names = await context.automation.holder_cases(user, kind, outcome)
    return HolderCasesOut.of(cases, names, context.refs)
