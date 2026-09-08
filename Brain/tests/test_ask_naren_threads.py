"""ask_naren/threads.py -- the thread a caller replays, and the rule for shrinking it.

Everything here is hand-built. A thread is caller-supplied data, so what is tested is what
a caller can get away with and what survives being trimmed -- never a prompt string and
never a call count.

THE ONE PROPERTY THAT MATTERS: trimming must not lose a carried identifier. ADR 0006 makes
that load-bearing -- the message that established the scenario is usually the first one, and
every later turn inherits its identifier -- so most of this file is that single rule
approached from different sides.
"""
import pytest

from ask_naren import threads


def _turn(n=1, message="what do i say", reply="say this", outcome="answered",
          pair_id=None, scenario_key="", call_filename=""):
    return threads.ThreadTurn(
        message=f"{message} {n}", reply=f"{reply} {n}", outcome=outcome,
        pair_id=pair_id, scenario_key=scenario_key, call_filename=call_filename)


def _grounded(n, scenario="performance_pushback"):
    return _turn(n, pair_id=n, scenario_key=scenario, call_filename=f"call_{n}.txt")


# -- parsing a caller's thread ------------------------------------------------------------

def test_a_missing_thread_is_an_empty_thread():
    """Every request before issue #15 sent no thread at all, and `--ask` still does."""
    assert threads.parse(None) == ()
    assert threads.parse([]) == ()


def test_a_well_formed_thread_parses():
    parsed = threads.parse([
        {"message": "client says our cpa is 3x", "outcome": "answered",
         "reply": "reframe on their own baseline", "pair_id": 11,
         "scenario_key": "performance_pushback", "call_filename": "a.txt"},
    ])
    assert len(parsed) == 1
    assert parsed[0].pair_id == 11
    assert parsed[0].scenario_key == "performance_pushback"


def test_a_turn_needs_an_outcome_the_service_can_actually_have_produced():
    with pytest.raises(ValueError):
        threads.parse([{"message": "x", "outcome": "maybe"}])


def test_an_unknown_key_is_refused_rather_than_ignored():
    """Same reason IntakeDecision forbids extras: a key nobody validates is a key nobody
    notices, and this one comes from outside."""
    with pytest.raises(ValueError):
        threads.parse([{"message": "x", "outcome": "answered", "quote": "smuggled"}])


def test_a_thread_that_is_not_a_list_is_refused():
    with pytest.raises(ValueError):
        threads.parse({"message": "x", "outcome": "answered"})


def test_a_pair_id_that_is_not_a_real_row_is_refused():
    """A non-positive id is not a kb_pairs row. Admitting one turns a bad caller into a
    silent no-match on the follow-up path rather than into an error."""
    with pytest.raises(ValueError):
        threads.parse([{"message": "x", "outcome": "answered", "pair_id": 0}])


# -- trimming ------------------------------------------------------------------------------

def test_a_thread_within_budget_is_returned_untouched():
    turns = [_grounded(1), _grounded(2)]
    assert threads.trim(turns, budget=10_000) == tuple(turns)


def test_trimming_blanks_prose_and_keeps_every_carried_identifier():
    """The rule in one test. Whatever a trim drops, a scenario key and a pair id survive
    it -- otherwise a conversation that has run long enough strands itself."""
    turns = [_grounded(n, scenario=f"scenario_{n}") for n in range(1, 9)]
    # Below what eight fully-elided turns plus their identifiers cost, so every scrap of
    # prose has to go and only the identifiers can survive.
    trimmed = threads.trim(turns, budget=8 * threads._ELIDED_TURN_CHARS + 20)

    assert len(trimmed) == len(turns)
    assert [t.pair_id for t in trimmed] == [t.pair_id for t in turns]
    assert [t.scenario_key for t in trimmed] == [t.scenario_key for t in turns]
    assert [t.call_filename for t in trimmed] == [t.call_filename for t in turns]
    assert any(not t.message for t in trimmed)      # something really was dropped


def test_the_first_turn_keeps_its_prose_longer_than_the_middle_does():
    """Dropping the oldest messages is the wrong rule (ADR 0006): the first message is
    usually the one that established the situation everything after it is about."""
    # Enough room for the first turn and the last two, and not for the middle three.
    turns = [_turn(n, message="m" * 200, reply="r" * 200) for n in range(1, 7)]
    trimmed = threads.trim(turns, budget=1500)

    assert trimmed[0].message                       # the first survived
    assert not trimmed[1].message                   # the middle did not


def test_the_most_recent_turn_is_the_last_prose_to_go():
    """A follow-up is about the exchange immediately before it. That text is worth more
    than any other text in the thread."""
    turns = [_turn(n, message="m" * 300, reply="r" * 300) for n in range(1, 7)]
    trimmed = threads.trim(turns, budget=700)

    assert trimmed[-1].message
    assert all(not t.message for t in trimmed[:-1])


def test_an_impossible_budget_still_returns_a_usable_thread():
    """A single pasted message larger than the whole budget must not produce a crash or an
    empty thread -- the newest carried identifier is what a follow-up needs."""
    turns = [_grounded(1), _grounded(2), _grounded(3)]
    trimmed = threads.trim(turns, budget=10)

    assert trimmed
    assert trimmed[-1].pair_id == 3


def test_trimming_an_empty_thread_is_an_empty_thread():
    assert threads.trim([], budget=10) == ()
