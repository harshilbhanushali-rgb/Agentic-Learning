"""Tests for calibration/flag_proper_noun_clusters.py's keyword lookup.

Pins F14: BERTopic runs `ngram_range=(1,2)`, so ~40% of the top-3 c-TF-IDF keywords are
bigrams -- `happy dance`, the motivating example of the whole script, among them. The old
lookup held a set of UNIGRAMS per turn, so every multiword keyword matched nothing and both
Signal B (keyword-account concentration) and Signal C (proper-noun rate) came out NaN on
exactly the cases the script exists to catch.

No spaCy import at module level: keyword_pos_rates takes already-tagged docs, so the token
shape can be faked and these run on a box where loading en_core_web_lg is unreliable.
"""
from __future__ import annotations

import pytest

from calibration import flag_proper_noun_clusters as fp


# -- Signal B ---------------------------------------------------------------------------

TEXTS = [
    "We ran the happy dance campaign last quarter.",   # 0  the phrase
    "Happy to help, and the dance floor was busy.",    # 1  both words, NOT the phrase
    "dance",                                           # 2  one word only
    "Nothing relevant here at all.",                   # 3  neither
]


def test_a_bigram_keyword_matches_the_phrase_not_the_loose_words():
    hits = fp.keyword_turns(TEXTS, ["happy dance"])
    assert hits["happy dance"] == [0], (
        "turn 1 contains 'happy' and 'dance' but not the phrase, so it must not match")


def test_unigram_lookup_is_unchanged():
    hits = fp.keyword_turns(TEXTS, ["dance", "happy"])
    assert hits["dance"] == [0, 1, 2]
    assert hits["happy"] == [0, 1]


def test_a_keyword_absent_from_the_corpus_yields_an_empty_list_not_a_missing_key():
    hits = fp.keyword_turns(TEXTS, ["pixel yeah"])
    assert hits["pixel yeah"] == []


def test_a_turn_repeating_the_phrase_is_counted_once():
    """Signal B is a share of TURNS, so a turn must not be double counted."""
    hits = fp.keyword_turns(["happy dance and more happy dance"], ["happy dance"])
    assert hits["happy dance"] == [0]


def test_punctuation_and_case_do_not_break_a_phrase_match():
    hits = fp.keyword_turns(["Happy Dance, the account."], ["happy dance"])
    assert hits["happy dance"] == [0]


def test_two_keywords_normalising_alike_raise_rather_than_shadow_each_other():
    """Keywords are keyed by token tuple, so a collision would leave the loser matching
    nothing -- indistinguishable from 'this phrase never occurs'. Measured zero non-empty
    collisions today; R15's tokeniser change is exactly what could introduce one."""
    with pytest.raises(SystemExit, match="KEYWORD COLLISION"):
        fp.keyword_turns(["a b"], ["happy dance", "Happy  Dance!"])


def test_keywords_that_normalise_to_nothing_are_skipped_not_collided():
    """Purely numeric keywords all normalise to (), which is not a collision -- they are
    excluded equally and simply read as missing."""
    hits = fp.keyword_turns(["we spent 2021 on it"], ["2021", "18", "spent"])
    assert hits["2021"] == [] and hits["18"] == []
    assert hits["spent"] == [0]


def test_top_keywords_of_is_the_single_definition():
    """Both consumers must slice and strip identically; they used to differ on empty slots."""
    assert fp.top_keywords_of("okay okay, okay, ") == ["okay okay", "okay", ""]
    assert fp.top_keywords_of("a, b, c, d") == ["a", "b", "c"]


def test_phrase_tokens_normalises_the_keyword():
    assert fp.phrase_tokens("happy dance") == ("happy", "dance")
    assert fp.phrase_tokens("pixel") == ("pixel",)


# -- Signal C ---------------------------------------------------------------------------

class _Tok:
    def __init__(self, text, pos, alpha=True):
        self.text, self.pos_, self.is_alpha = text, pos, alpha


def _doc(*pairs):
    return [_Tok(t, p) if t.isalpha() else _Tok(t, p, alpha=False) for t, p in pairs]


def test_a_bigram_keyword_gets_a_real_propn_rate_instead_of_nan():
    """`happy dance` as a name: both tokens PROPN on every occurrence."""
    docs = [_doc(("Happy", "PROPN"), ("Dance", "PROPN")) for _ in range(4)]
    propn, _ = fp.keyword_pos_rates(docs, ["happy dance"])
    assert propn["happy dance"] == pytest.approx(1.0)


def test_a_phrase_is_propn_only_when_every_token_is():
    """Reduces to the unigram rule at n=1 rather than being a second rule."""
    docs = ([_doc(("Happy", "PROPN"), ("Dance", "PROPN"))] * 3
            + [_doc(("happy", "ADJ"), ("dance", "NOUN"))] * 1)
    propn, _ = fp.keyword_pos_rates(docs, ["happy dance", "dance"])
    assert propn["happy dance"] == pytest.approx(0.75)
    assert propn["dance"] == pytest.approx(0.75)


def test_a_keyword_below_the_occurrence_floor_is_omitted():
    """Fewer than 3 occurrences is too thin to rate, matching the unigram floor."""
    docs = [_doc(("Happy", "PROPN"), ("Dance", "PROPN"))] * 2
    propn, _ = fp.keyword_pos_rates(docs, ["happy dance"])
    assert "happy dance" not in propn


# -- F15: a missing value must be counted, never silently absorbed -----------------------

def _cluster(key, share, lift=0.1, propn=0.5, kind="scenario"):
    return {"scenario_key": key, "kind": kind, "top_account_share": share, "lift": lift,
            "null_mean": 0.2, "propn_rate": propn,
            "exceeds_null_p99": (share > 0.4) if share == share else False}


def test_a_missing_value_does_not_poison_the_summary_mean():
    """np.mean over one NaN returns NaN and takes the whole per-kind row with it."""
    rows = [_cluster("a", 0.6), _cluster("b", 0.4), _cluster("c", float("nan"))]
    mean, n_used, n_missing = fp.mean_scoreable(rows, "top_account_share")
    assert mean == pytest.approx(0.5)
    assert (n_used, n_missing) == (2, 1)


def test_the_missing_count_is_returned_so_the_denominator_is_reportable():
    """A rate whose denominator is not printed is the defect this whole audit is about."""
    rows = [_cluster("a", float("nan")), _cluster("b", float("nan"))]
    mean, n_used, n_missing = fp.mean_scoreable(rows, "top_account_share")
    assert (n_used, n_missing) == (0, 2)
    assert mean != mean, "no scoreable rows must yield NaN, not a fabricated 0.0"


def test_is_missing_catches_nan_and_none_but_not_zero():
    assert fp.is_missing(float("nan"))
    assert fp.is_missing(None)
    assert not fp.is_missing(0.0), "0% concentration is a real measurement, not a gap"


def test_is_missing_catches_numpy_nan_of_every_width():
    """np.float64 subclasses float but np.float32 does NOT, so an isinstance check calls a
    float32 NaN present and readmits the row it was written to exclude."""
    np = pytest.importorskip("numpy")
    assert fp.is_missing(np.float64("nan"))
    assert fp.is_missing(np.float32("nan"))
    assert not fp.is_missing(np.float32(0.0))
    assert not fp.is_missing("not a number"), "a non-number is not a missing number"


def test_the_lift_subtracts_means_taken_over_the_same_rows():
    """Dropping each field's own missing rows and then subtracting is the asymmetric-arms
    defect -- the printed lift would compare two different populations."""
    rows = [
        {"share": 0.9, "null": 0.2},
        {"share": float("nan"), "null": 0.2},     # scoreable on null only
        {"share": 0.1, "null": float("nan")},     # scoreable on share only
        {"share": 0.5, "null": 0.2},
    ]
    a, b, n_ok, n_missing = fp.paired_means(rows, "share", "null")
    assert (n_ok, n_missing) == (2, 2)
    assert a == pytest.approx(0.7)                # (0.9 + 0.5) / 2, NOT (0.9+0.1+0.5)/3
    assert b == pytest.approx(0.2)
    unpaired_a, _, _ = fp.mean_scoreable(rows, "share")
    assert unpaired_a != pytest.approx(a), "the unpaired mean must actually differ here"


def test_multiplicity_note_states_the_chance_expectation_and_the_null_resolution():
    rows = [{"i": i} for i in range(245)]
    coach = rows[:38]
    flagged = coach[:21]
    note = fp.multiplicity_note(rows, coach, flagged, null_reps=400)
    assert "245" in note and "2.5" in note, "expected false flags across all clusters"
    assert "0.4" in note, "expected false flags among the coachable"
    assert "400" in note, "the p99's own resolution must be stated"
    assert "21" in note


def test_multiplicity_note_does_not_claim_an_individual_flag_is_real():
    """The aggregate beating chance says nothing about any one cluster."""
    note = fp.multiplicity_note([{}] * 245, [{}] * 38, [{}] * 21, null_reps=400)
    assert "INDIVIDUAL" in note and "reading its turns" in note


def test_paired_means_with_nothing_scoreable_is_nan_not_zero():
    rows = [{"share": float("nan"), "null": 0.2}]
    a, b, n_ok, n_missing = fp.paired_means(rows, "share", "null")
    assert (n_ok, n_missing) == (0, 1)
    assert a != a and b != b


def test_missing_values_sort_last_not_wherever_the_input_happened_to_put_them():
    rows = [_cluster("nan_one", float("nan"), lift=float("nan")),
            _cluster("high", 0.9, lift=0.9),
            _cluster("low", 0.1, lift=0.1)]
    order = [r["scenario_key"] for r in sorted(rows, key=fp.rank_key("lift"))]
    assert order == ["high", "low", "nan_one"]
    reversed_order = [r["scenario_key"]
                      for r in sorted(list(reversed(rows)), key=fp.rank_key("lift"))]
    assert order == reversed_order, "order must not depend on input order"


def test_ties_are_broken_deterministically_by_key():
    """Three real coachable clusters share propn_rate 0.3333 and six share 0.0, so a stable
    sort alone leaves the printed ranking dependent on input order."""
    rows = [_cluster("zebra", 0.5, propn=0.3333), _cluster("alpha", 0.5, propn=0.3333),
            _cluster("mango", 0.5, propn=0.3333)]
    order = [r["scenario_key"] for r in sorted(rows, key=fp.rank_key("propn_rate"))]
    assert order == ["alpha", "mango", "zebra"]
    assert order == [r["scenario_key"]
                     for r in sorted(list(reversed(rows)), key=fp.rank_key("propn_rate"))]


def test_capitalisation_is_only_measured_mid_sentence():
    """A sentence-initial capital carries no information, so it is not counted either way."""
    start = _doc(("Happy", "PROPN"), ("Dance", "PROPN"))            # both sentence-initial-ish
    mid = _doc(("We", "PRON"), ("saw", "VERB"),
               ("Happy", "PROPN"), ("Dance", "PROPN"))
    _, cap = fp.keyword_pos_rates([start] + [mid] * 3, ["happy dance"])
    assert cap["happy dance"] == pytest.approx(1.0)
    assert "happy dance" in cap
