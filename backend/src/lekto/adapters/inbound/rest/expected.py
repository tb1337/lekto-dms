"""`/expected`: the documents expected next by their series (issue #145)."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.automation import Zone
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import AllDocuments
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.expected import ExpectedOut

router = APIRouter(prefix="/expected", tags=["expected"], dependencies=PROTECTED)


@router.get(
    "",
    summary="The documents expected next",
    description=(
        "The series among the documents the caller may read (with `all_users`, an admin's, "
        "every user's; others 403): documents of one contact and type, and of one contract or "
        "customer number where they show one, at least three at a steady interval. Each with "
        "its next date and where that stands today; the overdue first, then by date. Derived "
        "on each call, nothing stored; today as it is in `tz`."
    ),
    response_model=list[ExpectedOut],
    responses=problem_responses(401, 403, 422),
)
async def expected(
    user: CurrentUser, context: Context, all_users: AllDocuments = False, tz: Zone = "UTC"
) -> list[ExpectedOut]:
    found = await context.expected.expected(user, all_users=all_users, zone=ZoneInfo(tz))
    return [ExpectedOut.of(item) for item in found]
