"""The classification of the evaluation set on the real persistence: the same documents and
fixed answers as `evaluate --fake` (in memory), through the SQL unit of work (SQLite with the
filesystem; Postgres with S3). The lanes and the checks must come out as in memory."""

from dataclasses import replace
from pathlib import Path

from papiq.adapters.inbound.evaluation import Case, evaluate, load_set
from papiq.adapters.outbound.memory import FakeLanguageModel
from papiq.adapters.outbound.sql import Database, SqlUnitOfWorkFactory
from papiq.composition.container import build_memory_container
from papiq.composition.evaluation import build_environment
from papiq.composition.settings import Settings
from papiq.core.ports import LanguageModel, ObjectStore

SET = Path(__file__).parents[2] / "evaluation"


async def test_the_fixed_answers_give_the_expected_lanes(
    stores: tuple[Database, ObjectStore],
) -> None:
    database, store = stores
    evaluation = load_set(SET)

    def model_for(case: Case) -> LanguageModel | None:
        assert case.fake is not None
        return FakeLanguageModel(case.fake.respond, model="fixed answers")

    container = replace(
        build_memory_container(), unit_of_work=SqlUnitOfWorkFactory(database), object_store=store
    )
    environment = build_environment(container, Settings.model_construct(), model_for)
    results = await evaluate(evaluation, environment)

    assert len(results) == len(evaluation.cases)
    for result in results:
        assert result.case.fake is not None
        assert result.lane is result.case.fake.lane, (result.case.name, result.reasons)
        assert result.violations == (), result.case.name
