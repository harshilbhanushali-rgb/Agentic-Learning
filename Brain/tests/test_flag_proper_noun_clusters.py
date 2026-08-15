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


def test_capitalisation_is_only_measured_mid_sentence():
    """A sentence-initial capital carries no information, so it is not counted either way."""
    start = _doc(("Happy", "PROPN"), ("Dance", "PROPN"))            # both sentence-initial-ish
    mid = _doc(("We", "PRON"), ("saw", "VERB"),
               ("Happy", "PROPN"), ("Dance", "PROPN"))
    _, cap = fp.keyword_pos_rates([start] + [mid] * 3, ["happy dance"])
    assert cap["happy dance"] == pytest.approx(1.0)
    assert "happy dance" in cap
