"""layer_d/verify_quotes.py -- the fabrication gate, tested on hand-built text."""
from layer_d.verify_quotes import QuoteCheck, best_span, norm_quote, verify_quote

SOURCE = (
    "Yep, and the other thing that's always there, Alexa, is a lot of people -- "
    "one of the biggest bottlenecks of a login is half the people are too lazy "
    "to create an account. Let me just double check the numbers since March."
)


def test_exact_quote_verifies_at_score_1():
    r = verify_quote("one of the biggest bottlenecks of a login", SOURCE, 0.80)
    assert r.verified and r.score == 1.0


def test_punctuation_and_case_do_not_break_containment():
    r = verify_quote("Let me just double-check the numbers, since MARCH!", SOURCE, 0.80)
    assert r.verified and r.score == 1.0


def test_fabricated_quote_is_refused():
    r = verify_quote("we guarantee a 40% lift in conversion by Friday", SOURCE, 0.80)
    assert not r.verified
    assert r.score < 0.80


def test_empty_quote_never_verifies():
    assert verify_quote("", SOURCE, 0.0) == QuoteCheck(False, 0.0, "")
    assert not verify_quote("   ", SOURCE, 0.0).verified


def test_empty_source_never_verifies():
    assert not verify_quote("anything", "", 0.0).verified


def test_near_miss_paraphrase_passes_only_above_threshold():
    quote = "one of the biggest bottleneck of a login is half of the people are too lazy"
    strict = verify_quote(quote, SOURCE, 0.95)
    loose = verify_quote(quote, SOURCE, 0.70)
    assert loose.verified
    assert loose.score >= 0.70
    # the same quote must not silently pass a stricter bar
    assert strict.verified == (strict.score >= 0.95)


def test_best_span_returns_zero_on_disjoint_text():
    score, span = best_span("zzzz", "qqqq")
    assert score == 0.0 and span == ""


def test_norm_quote_collapses_whitespace_and_symbols():
    assert norm_quote("  Hello,   WORLD!! ") == "hello world"
