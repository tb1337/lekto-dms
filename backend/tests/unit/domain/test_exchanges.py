"""The stored exchanges with the language model: JSON both ways, one entry per run."""

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.exchanges import (
    ModelCall,
    RunExchange,
    exchanges_from_json,
    exchanges_to_json,
    tokens_of,
    with_run,
)
from lekto.core.domain.json_value import JsonObject


def call(answer: str = "{}") -> ModelCall:
    return ModelCall(
        system="You read one document.",
        user="Contacts: …",
        answer=answer,
        model="qwen3:8b",
        usage={"prompt_tokens": 2318, "completion_tokens": 184, "eval_duration": 3030000000},
    )


def test_runs_go_to_json_and_back() -> None:
    runs = [RunExchange(run=1, calls=(call("x"), call())), RunExchange(run=3, calls=(call(),))]
    assert exchanges_from_json(exchanges_to_json(runs)) == runs


def test_a_run_replaces_its_earlier_entry_and_stays_in_order() -> None:
    runs = [RunExchange(run=2, calls=(call("old"),)), RunExchange(run=1, calls=(call(),))]
    updated = with_run(runs, RunExchange(run=2, calls=(call("new"),)))
    assert [(run.run, run.calls[0].answer) for run in updated] == [(1, "{}"), (2, "new")]
    assert [run.run for run in with_run(updated, RunExchange(run=4, calls=()))] == [1, 2, 4]


@pytest.mark.parametrize(
    "data",
    [None, {}, {"runs": "x"}, {"runs": [{"run": "1", "calls": []}]}, {"runs": [{"run": 1}]}],
)
def test_damaged_files_are_refused(data: object) -> None:
    with pytest.raises(ValidationError):
        exchanges_from_json(data)  # type: ignore[arg-type]


def test_runs_start_at_one() -> None:
    with pytest.raises(ValidationError):
        RunExchange(run=0, calls=())


def test_the_tokens_of_calls_from_their_usage_reports() -> None:
    usage: JsonObject = {"prompt_tokens": 12, "completion_tokens": 5, "total_duration": 9}
    assert tokens_of([usage, {}]) == [
        {"prompt": 12, "completion": 5, "usage": usage},
        {"prompt": None, "completion": None, "usage": {}},
    ]
