"""The evaluation set on the real persistence: the same documents and fixed answers as
`evaluate --fake` (in memory), cold and trained, through the SQL unit of work (SQLite with the
filesystem; Postgres with S3). The lanes and the checks must come out as in memory."""

from dataclasses import replace
from pathlib import Path

import pytest

from lekto.adapters.inbound.evaluation import Case, Run, evaluate, load_set
from lekto.adapters.outbound.memory import FakeLanguageModel
from lekto.adapters.outbound.sql import Database, SqlUnitOfWorkFactory
from lekto.composition.evaluation import build_environment, evaluation_container
from lekto.composition.settings import Settings
from lekto.core.ports.llm import LanguageModel
from lekto.core.ports.object_store import ObjectStore

SET = Path(__file__).parents[2] / "evaluation"


@pytest.mark.parametrize("run", list(Run))
async def test_the_fixed_answers_give_the_expected_lanes(
    stores: tuple[Database, ObjectStore], run: Run
) -> None:
    database, store = stores
    evaluation = load_set(SET)

    def model_for(case: Case) -> LanguageModel | None:
        assert case.fake is not None
        return FakeLanguageModel(case.fake.respond, model="fixed answers")

    container = replace(
        evaluation_container(run),
        unit_of_work=SqlUnitOfWorkFactory(database),
        object_store=store,
    )
    environment = build_environment(container, Settings.model_construct(), model_for, run)
    results = await evaluate(evaluation, environment)

    assert len(results) == len(evaluation.cases_in(run))
    for result in results:
        assert result.case.fake is not None
        lane = result.case.fake.lane_in(run)
        assert result.lane is lane, (result.case.name, result.reasons)
        assert result.violations == (), result.case.name
