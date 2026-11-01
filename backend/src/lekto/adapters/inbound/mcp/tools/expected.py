"""The tool of the domain `expected`: the documents expected next (#145)."""

from datetime import date
from typing import Annotated
from uuid import UUID

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.core.domain.series import SeriesState


class SeriesOut(BaseModel):
    contact: str
    document_type: str
    number: str | None
    cadence: str
    interval_days: int
    spread_days: int
    documents: int
    last_document: UUID
    last_date: date
    next_date: date
    next_period: str | None
    state: str


class ExpectedOut(BaseModel):
    series: list[SeriesOut]


def add_expected_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "expected_list",
        "The documents expected next: series of documents you may read (one contact and type, "
        "and one contract or customer number where they show one, at least three at a steady "
        "interval) with the next date and state overdue, soon (30 days), later or ended; the "
        "overdue first. Nothing is stored.",
    )
    async def expected_list(
        ctx: Context,
        include_ended: Annotated[
            bool, Field(description="Also the series that ended (two dates missed).")
        ] = False,
    ) -> str:
        user = principal_of(ctx).id
        series = []
        for item in await context.expected.expected(user):
            if item.state is SeriesState.ENDED and not include_ended:
                continue
            key, last = item.series.key, item.last
            assert last.document_date is not None
            series.append(
                SeriesOut(
                    contact=item.contact,
                    document_type=item.document_type,
                    number=None if key.number is None else key.number[1],
                    cadence=item.series.cadence.value,
                    interval_days=item.series.interval,
                    spread_days=item.series.spread,
                    documents=len(item.series.documents),
                    last_document=last.id,
                    last_date=last.document_date,
                    next_date=item.series.next_date,
                    next_period=(
                        None
                        if item.series.next_period is None
                        else item.series.next_period.notation
                    ),
                    state=item.state.value,
                )
            )
        return compact(ExpectedOut(series=series))
