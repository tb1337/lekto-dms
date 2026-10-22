"""The persons a document names in the judge's rule for the space (`verdict.judge_space`), and
the model's recipient as a person (`verdict.recipient_persons`)."""

from functools import partial

from lekto.core.domain import verdict
from lekto.core.domain.facts import Strength
from lekto.core.domain.ids import SpaceId, UserId, new_id
from lekto.core.domain.pipeline import Outcome
from lekto.core.domain.verdict import (
    ClassifierView,
    FactsView,
    ModelProposal,
    Signals,
    SpaceChoice,
    SpaceOption,
    named_persons,
    recipient_persons,
)
from tests import builders

judge_space = partial(verdict.judge_space, thresholds=builders.THRESHOLDS)

TOBI, ANNA, BOB = UserId(new_id()), UserId(new_id()), UserId(new_id())
OWN, HOUSEHOLD, ANNAS, BOBS = (SpaceId(new_id()) for _ in range(4))
FAMILY = SpaceId(new_id())  # Tobi, Anna and their child Bob
OPTIONS = {
    OWN: SpaceOption("the uploader's personal space", frozenset({TOBI}), personal_of=TOBI),
    HOUSEHOLD: SpaceOption("a shared space", frozenset({TOBI, ANNA})),
    ANNAS: SpaceOption("another user's personal space", frozenset({ANNA}), personal_of=ANNA),
    BOBS: SpaceOption("another user's personal space", frozenset({BOB}), personal_of=BOB),
}


def choice(
    current: SpaceId = OWN,
    *,
    locked: bool = False,
    options: dict[SpaceId, SpaceOption] | None = None,
) -> SpaceChoice:
    return SpaceChoice(
        current=current, options=options or dict(OPTIONS), locked=locked, uploader=TOBI
    )


def sure_of(space: SpaceId) -> Signals:
    """The model and the classifier name `space`: the judge is sure of it."""
    return Signals(
        model=ModelProposal(space=space),
        classifier=ClassifierView(spaces=[(space, 0.95)], known_spaces=frozenset(OPTIONS)),
    )


def test_anna_s_identifier_alone_suggests_handing_it_over() -> None:
    """Tobi uploads Anna's tax assessment: no signal names a space, her tax ID stands in it."""
    check = judge_space(Signals(), choice(), persons={ANNA: Strength.HARD})
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(ANNAS)
    assert check.value is None
    # Anna is new there: it shows the document to more people (a hand-over among them).
    assert str(check.reason).endswith("which shows it to more people")
    assert check.unseen_by == ()  # Anna sees it where the check leads
    # Names stay out of what is stored: ids only.
    assert "anna" not in str(check.reason).lower()


def test_hard_evidence_against_a_sure_choice_makes_it_uncertain() -> None:
    """The signals are sure it stays with Tobi; Anna's identifier says otherwise."""
    check = judge_space(sure_of(OWN), choice(), persons={ANNA: Strength.HARD})
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(ANNAS)


def test_hard_evidence_backs_a_space_a_signal_names() -> None:
    """The joint account names both; the model names Haushalt: sure, and suggested (wider)."""
    signals = Signals(
        model=ModelProposal(space=HOUSEHOLD),
        classifier=ClassifierView(known_spaces=frozenset(OPTIONS)),
    )
    without = judge_space(signals, choice())
    assert without.outcome is Outcome.OK  # the model alone, and the classifier knows Haushalt
    assert without.value is None
    backed = judge_space(signals, choice(), persons={TOBI: Strength.HARD, ANNA: Strength.HARD})
    assert backed.outcome is Outcome.UNCERTAIN
    assert backed.suggestion == str(HOUSEHOLD)
    assert backed.reason == "suggests another space, which shows it to more people"


def test_hard_evidence_of_two_backs_the_smallest_space_of_both() -> None:
    options = {**OPTIONS, FAMILY: SpaceOption("a shared space", frozenset({TOBI, ANNA, BOB}))}
    del options[HOUSEHOLD]
    check = judge_space(
        Signals(), choice(options=options), persons={TOBI: Strength.HARD, ANNA: Strength.HARD}
    )
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(FAMILY)


def test_the_uploader_s_own_evidence_only_confirms_staying() -> None:
    check = judge_space(Signals(), choice(), persons={TOBI: Strength.HARD})
    assert check.outcome is Outcome.OK
    assert check.value is None
    assert check.suggestion is None
    assert check.unseen_by == ()


def test_medium_evidence_only_warns() -> None:
    """Anna's birth date or the model's recipient: never yellow, the check lists her."""
    check = judge_space(Signals(), choice(), persons={ANNA: Strength.MEDIUM})
    assert check.outcome is Outcome.OK
    assert check.suggestion is None
    assert check.unseen_by == (str(ANNA),)
    assert check.reason == "names someone who would not see it there"


def test_a_warning_follows_the_suggestion() -> None:
    """Suggested Haushalt: Anna sees it there, Bob (named by his birth date) does not."""
    check = judge_space(
        sure_of(HOUSEHOLD), choice(), persons={ANNA: Strength.MEDIUM, BOB: Strength.MEDIUM}
    )
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(HOUSEHOLD)
    assert check.unseen_by == (str(BOB),)
    assert check.reason == "suggests another space, which shows it to more people"


def test_weak_evidence_only_breaks_ties() -> None:
    """Unsure (the model names Anna's space, the classifier Haushalt): no move, no warning.
    Neither named, Bob's space likelier: Haushalt, where Anna (named) sees it, comes first."""
    signals = Signals(
        model=ModelProposal(space=ANNAS),
        classifier=ClassifierView(spaces=[(HOUSEHOLD, 0.95)], known_spaces=frozenset(OPTIONS)),
    )
    check = judge_space(signals, choice(), persons={ANNA: Strength.WEAK})
    assert check.outcome is Outcome.OK
    assert check.unseen_by == ()
    assert check.value is None
    tied = judge_space(
        Signals(classifier=ClassifierView(spaces=[(BOBS, 0.5), (HOUSEHOLD, 0.45)])),
        choice(),
        persons={ANNA: Strength.WEAK, TOBI: Strength.WEAK},
    )
    assert tied.outcome is Outcome.OK
    assert tied.suggestion == str(HOUSEHOLD)


def test_persons_never_change_a_space_a_person_chose() -> None:
    check = judge_space(Signals(), choice(locked=True), persons={ANNA: Strength.HARD})
    assert check.outcome is Outcome.OK
    assert check.suggestion is None
    assert check.unseen_by == ()


def test_two_others_without_a_space_of_their_own_warn_but_stay() -> None:
    """Anna's and Bob's identifiers, no space shows it to both and not to more: unsure, it
    stays, the check lists both."""
    check = judge_space(Signals(), choice(), persons={ANNA: Strength.HARD, BOB: Strength.HARD})
    assert check.outcome is Outcome.OK
    assert check.value is None
    assert set(check.unseen_by) == {str(ANNA), str(BOB)}


def test_the_recipient_names_every_user_it_contains() -> None:
    people = [(TOBI, ("Tobias Busch", "Tobi")), (ANNA, ("Anna Busch",)), (BOB, ("Bob",))]
    found = recipient_persons("Tobias und Anna Busch", people, builders.THRESHOLDS)
    assert found == {ANNA: Strength.MEDIUM}  # "Tobias Busch" does not stand whole in it
    assert recipient_persons("Frau Anna Busch", people, builders.THRESHOLDS) == {
        ANNA: Strength.MEDIUM
    }
    assert recipient_persons("Herrn Tobi Busch", people, builders.THRESHOLDS) == {
        TOBI: Strength.MEDIUM
    }
    assert recipient_persons("Anna Bush", people, builders.THRESHOLDS) == {
        ANNA: Strength.MEDIUM
    }  # close enough
    assert recipient_persons("Stadtwerke Musterstadt", people, builders.THRESHOLDS) == {}
    assert recipient_persons(None, people, builders.THRESHOLDS) == {}


def test_the_strongest_evidence_counts() -> None:
    merged = named_persons({ANNA: Strength.WEAK, BOB: Strength.HARD}, {ANNA: Strength.MEDIUM})
    assert merged == {ANNA: Strength.MEDIUM, BOB: Strength.HARD}


def test_facts_view_persons_reach_the_judge_through_signals() -> None:
    """The facts' persons as the judge node merges them with the recipient's."""
    signals = Signals(facts=FactsView(persons={ANNA: Strength.HARD}))
    persons = named_persons(signals.facts.persons if signals.facts else {})
    check = judge_space(signals, choice(), persons=persons)
    assert check.suggestion == str(ANNAS)
