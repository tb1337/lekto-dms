"""What a node sent to the language model and what came back, per processing run.

The processing log names the prompt only by its version (`classify-2`): the rendered messages
hold the document's text and the master data of the moment, so they are kept beside the
document instead, one file per node with every run. A person checking a document reads them
there; nothing in the pipeline reads them back.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import JsonObject, JsonValue, as_int, as_object


@dataclass(frozen=True, kw_only=True)
class ModelCall:
    """One request and its answer: `answer` is the model's text as it came, `usage` the
    endpoint's usage report (empty if it sent none)."""

    system: str
    user: str
    answer: str
    model: str
    usage: JsonObject

    def to_json(self) -> JsonObject:
        return {
            "system": self.system,
            "user": self.user,
            "answer": self.answer,
            "model": self.model,
            "usage": self.usage,
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> "ModelCall":
        if not isinstance(data, dict):
            raise ValidationError(f"invalid model call {data!r}")
        return cls(
            system=str(data.get("system", "")),
            user=str(data.get("user", "")),
            answer=str(data.get("answer", "")),
            model=str(data.get("model", "")),
            usage=as_object(data.get("usage")) or {},
        )


@dataclass(frozen=True, kw_only=True)
class RunExchange:
    """The calls of one node in processing run `run`: one, or two after an unfit answer."""

    run: int
    calls: tuple[ModelCall, ...]

    def __post_init__(self) -> None:
        if self.run < 1:
            raise ValidationError("run starts at 1")

    def to_json(self) -> JsonObject:
        return {"run": self.run, "calls": [call.to_json() for call in self.calls]}

    @classmethod
    def from_json(cls, data: JsonValue) -> "RunExchange":
        if not isinstance(data, dict):
            raise ValidationError(f"invalid run exchange {data!r}")
        run, calls = as_int(data.get("run")), data.get("calls")
        if run is None or not isinstance(calls, list):
            raise ValidationError(f"invalid run exchange {data!r}")
        return cls(run=run, calls=tuple(ModelCall.from_json(call) for call in calls))


def exchanges_to_json(runs: Sequence[RunExchange]) -> JsonObject:
    return {"runs": [run.to_json() for run in runs]}


def exchanges_from_json(data: JsonValue) -> list[RunExchange]:
    """The runs of a stored file, oldest first."""
    runs = (as_object(data) or {}).get("runs")
    if not isinstance(runs, list):
        raise ValidationError("invalid exchanges: no list of runs")
    return sorted((RunExchange.from_json(run) for run in runs), key=lambda run: run.run)


def with_run(runs: Sequence[RunExchange], exchange: RunExchange) -> list[RunExchange]:
    """`runs` with `exchange` in place of an earlier one of the same run (a node that ran
    again within its run, e.g. after a lost lease), oldest first."""
    kept = [run for run in runs if run.run != exchange.run]
    return sorted([*kept, exchange], key=lambda run: run.run)


def tokens_of(usages: Iterable[JsonObject]) -> list[JsonValue]:
    """Per model call (a page, or once more after an answer that did not fit) its tokens and
    the endpoint's usage report as it came, as the log keeps them."""
    return [
        {
            "prompt": as_int(usage.get("prompt_tokens")),
            "completion": as_int(usage.get("completion_tokens")),
            "usage": usage,
        }
        for usage in usages
    ]
