"""Reading a period field: as `{start, end}` or as written, shown by its quote, plausible; one
without a year and a single day equal to the document date only suggested."""

from datetime import date
from typing import Any

import pytest

from papiq.core.domain.classification import FieldCheck, field_key
from papiq.core.domain.fields import FieldDefinition, FieldType
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.master_data import DocumentType
from papiq.core.domain.periods import Period
from papiq.core.domain.pipeline import Outcome
from papiq.core.services.classification.answers import extract_schema, field_keys
from papiq.core.services.classification.prompts import (
    extract_message,
    propose_message,
    shorten,
)
from papiq.core.services.pipeline import MetadataResult
from tests.builders import NOW
from tests.unit.services.conftest import World
from tests.unit.services.test_classification import checks, document_with, fields_step, model

TIMESHEET = """\
Zeitnachweis
Erstellt am 05.10.2026
Abrechnungsmonat: September 2026
Woche 38: 14.09.2026 bis 20.09.2026, 38,5 Stunden
Stunden gesamt 151,5
"""
SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


async def seeded(world: World, *, required: bool = True) -> tuple[DocumentType, FieldDefinition]:
    kind = DocumentType.create(name="Zeitnachweis", now=NOW)
    period = FieldDefinition.create(
        name="Bezugszeitraum",
        data_type=FieldType.PERIOD,
        document_type_ids=[kind.id],
        required_types=[kind.id] if required else [],
        now=NOW,
    )
    async with world.uow() as uow:
        await uow.document_types.add(kind)
        await uow.fields.add(period)
        await uow.commit()
    return kind, period


async def read(
    world: World, value: Any, evidence: str | None, text: str = TIMESHEET
) -> tuple[FieldCheck, MetadataResult, FieldDefinition]:
    kind, period = await seeded(world)
    document = await document_with(world, text, kind)
    document.document_date = date(2026, 10, 5)
    answer: JsonObject = {"fields": {"a1": {"value": value, "evidence": evidence}}}
    result = await fields_step(world, model(answer)).run(document)
    assert isinstance(result, MetadataResult)
    return checks(result.result)[field_key(period.id)], result, period


async def test_a_period_shown_by_its_quote_is_applied(world: World) -> None:
    check, result, period = await read(world, SEPTEMBER, "Abrechnungsmonat: September 2026")
    assert (check.outcome, check.value) == (Outcome.OK, SEPTEMBER)
    assert result.changes.fields == {period.id: Period.month(2026, 9)}
    assert result.result.outcome is Outcome.OK


@pytest.mark.parametrize(
    ("value", "evidence", "reason", "suggested"),
    [
        # The quote shows another day of the text, not the month.
        (SEPTEMBER, "Erstellt am 05.10.2026", "the quoted passage does not show the value", True),
        # A week the text shows from Monday to Sunday is a span of its two dates.
        (
            {"start": "2026-09-14", "end": "2026-09-21"},
            "Woche 38: 14.09.2026 bis 20.09.2026, 38,5 Stunden",
            "the quoted passage does not show the value",
            True,
        ),
        # The model's stand-in for a period the text does not give.
        (
            {"start": "2026-10-05", "end": "2026-10-05"},
            "Erstellt am 05.10.2026",
            "the same day as the document date",
            True,
        ),
        ({"start": "1850-01-01", "end": "1850-12-31"}, "1850", None, False),
        ({"start": "September", "end": "2026"}, "Abrechnungsmonat: September 2026", None, False),
        ({"start": "2026-09-30", "end": "2026-09-01"}, "September 2026", None, False),
    ],
)
async def test_uncertain_periods(
    world: World, value: Any, evidence: str, reason: str | None, suggested: bool
) -> None:
    check, result, period = await read(world, value, evidence)
    assert check.outcome is Outcome.UNCERTAIN
    if reason is not None:
        assert check.reason == f"'Bezugszeitraum': {reason}"
    assert (check.suggestion is not None) is suggested
    assert period.id not in result.changes.fields
    assert result.result.outcome is Outcome.UNCERTAIN


async def test_a_week_and_a_span_as_the_text_writes_them(world: World) -> None:
    week = {"start": "2026-09-14", "end": "2026-09-20"}
    check, _, _ = await read(world, week, "Woche 38: 14.09.2026 bis 20.09.2026, 38,5 Stunden")
    assert (check.outcome, check.value) == (Outcome.OK, week)


async def test_a_month_without_its_year_takes_that_of_the_document_date(world: World) -> None:
    text = TIMESHEET.replace("September 2026", "September")
    check, result, period = await read(world, SEPTEMBER, "Abrechnungsmonat: September", text)
    assert check.outcome is Outcome.UNCERTAIN
    assert check.reason == (
        "'Bezugszeitraum': no year given; the year of the document date is assumed"
    )
    assert check.suggestion == SEPTEMBER
    assert period.id not in result.changes.fields


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("September 2026", SEPTEMBER),
        ("09/2026", SEPTEMBER),
        ("01.09.\u201330.09.2026", SEPTEMBER),
        ("KW 38/2026", {"start": "2026-09-14", "end": "2026-09-20"}),
    ],
)
async def test_a_period_as_written(world: World, written: str, expected: Any) -> None:
    """As the signal's proposal gives it (propose-2: values as written)."""
    text = TIMESHEET + f"Zeitraum: {written}\n"
    check, _, _ = await read(world, written, f"Zeitraum: {written}", text)
    assert (check.outcome, check.value) == (Outcome.OK, expected)


def test_the_prompts_ask_for_a_period_in_its_form() -> None:
    period = FieldDefinition.create(name="Bezugszeitraum", data_type=FieldType.PERIOD, now=NOW)
    keys = field_keys([period])
    schema: Any = extract_schema(keys)
    value = schema["properties"]["fields"]["properties"]["a1"]["properties"]["value"]
    assert value["anyOf"][0]["required"] == ["start", "end"]
    assert value["anyOf"][1] == {"type": "null"}
    asked = extract_message("Zeitnachweis", keys, shorten("text", 10_000))
    assert "start and end (YYYY-MM-DD, both days included)" in asked
    proposed = propose_message([], [], [("a1", period)], [], shorten("text", 10_000))
    assert "period: a day, week, month, quarter, year or span" in proposed
