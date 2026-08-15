"""Guards the Layer A pool unit switch (tuning.yaml layer_a.pool_unit).

WHY THIS EXISTS. Layer A clusters CLAUSES while Layer B matches TURNS, and the
clause split is what strands a stance sentence as its own data point: one turn
"Yeah. That makes sense. So for the ATS integration, do we need a pixel?" enters
the pool as TWO items, one of which carries no subject at all. 59.1% of the pool
(43,566 of 73,771 clauses) is content-free, which is the raw material every
posture scenario is built from. See
docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md.

The default stays "clause" so production is byte-identical until deliberately
flipped, and the test below is what proves that rather than asserting it.

Fixtures use sentences of >=4 tokens where a clause is expected, because
segmenter.segment_into_clauses silently drops anything shorter -- the same trap
test_layer_c_clause_pool.py documents.
"""
import pytest

from preprocessing.transcript_parser import SpeakerRole, Turn
from v2.layer_a import build_client_pool

_TWO_SENTENCES = "We segment our bids by device type. Mobile traffic converts worse."
_BACKCHANNEL = "Yeah."


def _turn(index, role, text, call_id="call_a"):
    return Turn(index=index, speaker_raw="X", role=role, text=text, call_id=call_id)


def _client_corpus():
    return [
        _turn(0, SpeakerRole.CLIENT, _TWO_SENTENCES, "call_a"),
        _turn(1, SpeakerRole.NAREN, "I would cap the desktop spend there.", "call_a"),
        _turn(2, SpeakerRole.CLIENT, _BACKCHANNEL, "call_a"),
        _turn(3, SpeakerRole.JOVEO_OTHER, "Sharing my screen now for everyone.", "call_a"),
        _turn(4, SpeakerRole.CLIENT, _TWO_SENTENCES, "call_b"),
    ]


def test_turn_mode_emits_exactly_one_item_per_client_turn():
    texts, call_ids = build_client_pool(_client_corpus(), unit="turn")

    assert texts == [_TWO_SENTENCES, _BACKCHANNEL, _TWO_SENTENCES]
    assert call_ids == ["call_a", "call_a", "call_b"]


def test_non_client_turns_are_skipped_in_both_modes():
    corpus = _client_corpus()
    for unit in ("clause", "turn"):
        texts, _ = build_client_pool(corpus, unit=unit)
        joined = " ".join(texts)
        assert "cap the desktop spend" not in joined      # NAREN
        assert "Sharing my screen" not in joined          # JOVEO_OTHER


def test_clause_mode_is_unchanged_from_the_legacy_behaviour():
    """The regression guard for the shipped default.

    Asserted against the segmenter directly rather than a hardcoded list, so it
    keeps holding if spaCy's sentence boundaries shift under a model upgrade --
    what is pinned is "clause mode == segment every CLIENT turn", which is the
    property production depends on.
    """
    from preprocessing.segmenter import segment_into_clauses

    corpus = _client_corpus()
    expected_texts, expected_calls = [], []
    for t in corpus:
        if t.role is not SpeakerRole.CLIENT:
            continue
        for clause in segment_into_clauses(t.text):
            expected_texts.append(clause)
            expected_calls.append(t.call_id)

    texts, call_ids = build_client_pool(corpus, unit="clause")
    assert texts == expected_texts
    assert call_ids == expected_calls


def test_a_backchannel_only_turn_survives_in_turn_mode_but_not_clause_mode():
    """This is the mechanism Layer D's rejection depends on, so it is pinned.

    A turn of only "Yeah." produces no clause at all -- 3,519 client turns
    (12.2%) currently contribute NOTHING to the taxonomy for this reason. In
    turn mode they are present, which is what lets a backchannel sink form with
    MORE evidence than today rather than less. Remove the sink and every
    "Thank you." becomes a coaching event again.
    """
    corpus = [_turn(0, SpeakerRole.CLIENT, _BACKCHANNEL, "call_a")]

    assert build_client_pool(corpus, unit="clause") == ([], [])
    assert build_client_pool(corpus, unit="turn") == ([_BACKCHANNEL], ["call_a"])


def test_min_content_words_still_filters_when_passed():
    """The dry run's --prefilter path. Applies in both units, on the emitted item."""
    corpus = [
        _turn(0, SpeakerRole.CLIENT, _BACKCHANNEL, "call_a"),
        _turn(1, SpeakerRole.CLIENT, _TWO_SENTENCES, "call_a"),
    ]
    texts, call_ids = build_client_pool(corpus, unit="turn", min_content_words=5)

    assert _BACKCHANNEL not in texts
    assert len(texts) == len(call_ids)


def test_an_unknown_unit_raises_rather_than_falling_back():
    """Matches the tuning loader's contract: a typo fails loudly instead of
    silently reverting to a default, which is how a knob quietly stops working.
    """
    with pytest.raises(ValueError, match="pool_unit"):
        build_client_pool(_client_corpus(), unit="sentence")


def test_the_two_units_disagree_on_this_corpus():
    """A guard against the switch being wired to nothing.

    If both arms ever return identical pools the comparison in the spec is
    measuring zero, which is exactly the failure mode of an inert knob
    (cf. layer_a.min_content_words, inert in production since the call site
    passes no argument).
    """
    clause_texts, _ = build_client_pool(_client_corpus(), unit="clause")
    turn_texts, _ = build_client_pool(_client_corpus(), unit="turn")

    assert clause_texts != turn_texts
    assert len(clause_texts) > len(turn_texts)
