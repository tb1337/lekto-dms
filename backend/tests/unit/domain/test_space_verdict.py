"""The judge's rule for the space (`verdict.judge_space`)."""

from functools import partial

from lekto.core.domain import verdict
from lekto.core.domain.classification import SPACE
from lekto.core.domain.ids import SpaceId, UserId, new_id
from lekto.core.domain.pipeline import Outcome
from lekto.core.domain.verdict import (
    ClassifierView,
    KnownLabels,
    ModelProposal,
    Neighbour,
    Signals,
    SpaceChoice,
    SpaceOption,
)
from tests import builders

judge_space = partial(verdict.judge_space, thresholds=builders.THRESHOLDS)

TOBI, ANNA = UserId(new_id()), UserId(new_id())
OWN, HOUSEHOLD, ANNAS = SpaceId(new_id()), SpaceId(new_id()), SpaceId(new_id())
SHARED_OWN = SpaceId(new_id())  # Tobi's personal space, shared with Anna
OPTIONS = {
    OWN: SpaceOption("own personal space", frozenset({TOBI})),
    HOUSEHOLD: SpaceOption("Haushalt", frozenset({TOBI, ANNA})),
    ANNAS: SpaceOption("personal space of anna", frozenset({ANNA})),
}


def choice(current: SpaceId = OWN, *, locked: bool = False) -> SpaceChoice:
    options = dict(OPTIONS)
    if current == SHARED_OWN:
        options[SHARED_OWN] = SpaceOption("own personal space", frozenset({TOBI, ANNA}))
    return SpaceChoice(
        current=current, options=options, locked=locked, people={TOBI: "tobi", ANNA: "anna"}
    )


def neighbours(*spaces: SpaceId | None) -> tuple[Neighbour, ...]:
    return tuple(
        Neighbour(document=str(new_id()), contact=None, document_type=None, space=space)
        for space in spaces
    )


def test_two_signals_that_name_a_wider_space_suggest_it_and_name_its_new_readers() -> None:
    signals = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        classifier=ClassifierView(spaces=[(HOUSEHOLD, 0.9)], known_spaces=frozenset(OPTIONS)),
    )
    check = judge_space(signals, choice())
    assert check.field == SPACE
    assert check.outcome is Outcome.UNCERTAIN
    assert check.value is None
    assert check.suggestion == str(HOUSEHOLD)
    assert check.reason == "suggests the space 'Haushalt', which shows it to anna"
    assert check.confidence < 0.9


def test_a_space_that_shows_it_to_no_one_new_is_moved_to() -> None:
    """From Tobi's shared personal space into Haushalt: Anna sees it in both."""
    signals = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        neighbours=neighbours(HOUSEHOLD, HOUSEHOLD, None),
        neighbours_know=KnownLabels(spaces=frozenset({HOUSEHOLD})),
    )
    check = judge_space(signals, choice(SHARED_OWN))
    assert check.outcome is Outcome.OK
    assert check.value == str(HOUSEHOLD)


def test_sure_of_the_space_it_lies_in_changes_nothing() -> None:
    signals = Signals(
        model=ModelProposal(space=OWN),
        classifier=ClassifierView(spaces=[(OWN, 0.95)], known_spaces=frozenset(OPTIONS)),
    )
    check = judge_space(signals, choice())
    assert check.outcome is Outcome.OK
    assert check.value == str(OWN)
    assert check.confidence == 1.0


def test_unsure_it_stays_and_is_never_uncertain() -> None:
    """The classifier alone names nothing the model does not; disagreeing signals neither."""
    alone = Signals(
        classifier=ClassifierView(spaces=[(HOUSEHOLD, 0.95)], known_spaces=frozenset(OPTIONS))
    )
    for signals in (
        alone,
        Signals(model=ModelProposal(space=ANNAS), classifier=alone.classifier),
        Signals(),
    ):
        check = judge_space(signals, choice())
        assert check.outcome is Outcome.OK
        assert check.value is None
        assert check.confidence == 1.0
    disagreeing = judge_space(
        Signals(model=ModelProposal(space=ANNAS), classifier=alone.classifier), choice()
    )
    assert disagreeing.reason is not None and "disagree" in disagreeing.reason
    assert judge_space(alone, choice()).suggestion == str(HOUSEHOLD)


def test_the_model_alone_names_a_space_no_other_signal_knows() -> None:
    """Cold start: a new space the classifier and the neighbours never saw."""
    signals = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        classifier=ClassifierView(spaces=[(OWN, 0.6)], known_spaces=frozenset({OWN})),
    )
    check = judge_space(signals, choice())
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(HOUSEHOLD)
    covered = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        classifier=ClassifierView(spaces=[(OWN, 0.6)], known_spaces=frozenset({OWN, HOUSEHOLD})),
    )
    known = judge_space(covered, choice())
    assert known.outcome is Outcome.OK
    assert known.value is None


def test_a_space_a_person_decided_stays() -> None:
    signals = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        classifier=ClassifierView(spaces=[(HOUSEHOLD, 0.95)], known_spaces=frozenset(OPTIONS)),
    )
    check = judge_space(signals, choice(locked=True))
    assert check.outcome is Outcome.OK
    assert check.value is None
    assert check.suggestion is None
    assert check.reason == "a person chose the space"


def test_a_space_the_uploader_cannot_file_into_is_none_of_the_candidates() -> None:
    elsewhere = SpaceId(new_id())
    signals = Signals(
        model=ModelProposal(space=elsewhere),
        classifier=ClassifierView(spaces=[(elsewhere, 0.99)], known_spaces=frozenset({elsewhere})),
    )
    check = judge_space(signals, choice())
    assert check.outcome is Outcome.OK
    assert check.value is None
    assert check.candidates == ()


def test_handing_over_is_a_wider_space_too() -> None:
    signals = Signals(
        model=ModelProposal(space=ANNAS),
        neighbours=neighbours(ANNAS, ANNAS),
        neighbours_know=KnownLabels(spaces=frozenset({ANNAS})),
    )
    check = judge_space(signals, choice())
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(ANNAS)
    assert check.reason == "suggests the space 'personal space of anna', which shows it to anna"
