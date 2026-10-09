"""Tests for calibration/layer_b_variants.py -- the S (segmentation) and A (admission) knobs.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md sections 3.4-3.7

*** THE LOAD-BEARING TEST IS `test_s0a0_is_production_on_every_shape`. *** This module is the
ONE place this trial paraphrases production. The repo rule is "import production code, never
paraphrase it" -- two scratchpad reimplementations of the transcript parse disagreed with the
real thing by ~20%. The knobs vary the INTERIOR of `extract_pairs`, so there is nothing to
import and a hook would mean editing production, which this trial forbids. What buys the right
to paraphrase is a PROOF of equality at the control setting: these tests cover the branch
shapes, and `verify_equivalence()` covers all 393 real transcripts field-for-field.

Turns are hand-built. Admission is stubbed by monkeypatching `_is_substantive` to a word-count
rule wherever the test is about CONTROL FLOW rather than about spaCy, so a test asserting
"this turn was dropped" cannot pass because spaCy happened to agree.
"""
import pytest

from calibration import layer_b_variants as lv
from preprocessing.transcript_parser import Turn, SpeakerRole


def turns(*spec):
    """(role, text) pairs -> Turns with sequential indices, as the parser produces.

    Built against the REAL `Turn` dataclass rather than a stub, so a field rename in
    `transcript_parser` breaks these tests instead of letting them keep passing against a
    shape production no longer uses.
    """
    return [Turn(index=i, speaker_raw="s", role=r, text=t, call_id="c")
            for i, (r, t) in enumerate(spec)]


C, N, J, U = (SpeakerRole.CLIENT, SpeakerRole.NAREN,
              SpeakerRole.JOVEO_OTHER, SpeakerRole.UNATTRIBUTED)


@pytest.fixture
def wordy(monkeypatch):
    """Substantive == 3+ whitespace words. Deterministic, and independent of the stoplist.

    Using real spaCy here would make every control-flow assertion depend on whether spaCy
    happens to consider a fixture's words substantive -- so a test could pass for a reason
    that has nothing to do with the branch it claims to cover.
    """
    monkeypatch.setattr(lv, "admission_predicates",
                        lambda admit, floors=None: _preds(admit))
    return None


def _preds(admit):
    sub = lambda t: len(t.split()) >= 3          # noqa: E731
    always = lambda t: True                      # noqa: E731
    return {"a0": (sub, sub), "a1": (always, sub),
            "a4": (sub, always), "a3": (sub, sub)}[admit]


# ---------------------------------------------------------------------------------------
# THE PROOF -- (s0, a0) must be production on every branch shape
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,spec", [
    ("simple pair", [(C, "we are on workday for ats"), (N, "yes we have a connector")]),
    ("consecutive client turns", [
        (C, "we are on workday for the ats"), (C, "does that integrate with it"),
        (N, "yes we have a direct connector")]),
    ("multi turn response", [
        (C, "how does the pixel work here"), (N, "it fires on page load"),
        (N, "and it reports back conversions")]),
    ("teammate interleaved", [
        (C, "what is the cost per click"), (J, "let me pull that up"),
        (N, "it averages two dollars")]),
    ("teammate only, no naren", [
        (C, "what is the cost per click"), (J, "it averages two dollars")]),
    ("short trigger dropped", [(C, "yeah ok"), (N, "we can look at the feed")]),
    ("short response dropped", [(C, "how does the feed refresh work"), (N, "sure")]),
    ("unattributed breaks window", [
        (C, "how does the feed refresh work"), (U, "unknown voice here"),
        (N, "it refreshes nightly")]),
    ("trailing client block", [
        (C, "how does the feed refresh work"), (N, "it refreshes nightly"),
        (C, "and what about the cost")]),
    ("no client at all", [(N, "here is how it works"), (J, "agreed")]),
    ("empty", []),
])
def test_s0a0_is_production_on_every_shape(name, spec):
    """Field-for-field against the real `extract_pairs`, with real spaCy.

    Parametrised over the branch shapes rather than one happy path, because the two
    implementations can agree on a simple case and diverge on the advance rule -- which is
    exactly where a paraphrase goes wrong.
    """
    from v1.layer_b import extract_pairs

    ts = turns(*spec)
    assert lv.extract_pairs_variant(ts, 7, "s0", "a0") == extract_pairs(ts, 7), name


# ---------------------------------------------------------------------------------------
# Knob S -- client move
# ---------------------------------------------------------------------------------------

def test_s0_takes_exactly_one_turn():
    ts = turns((C, "first part"), (C, "second part"), (N, "reply"))
    text, idx, after = lv.client_move(ts, 0, "s0")
    assert (text, idx, after) == ("first part", 0, 1)


def test_s1_merges_a_run_of_adjacent_client_turns():
    ts = turns((C, "we are on workday"), (C, "does that integrate"), (N, "yes"))
    text, idx, after = lv.client_move(ts, 0, "s1")
    assert text == "we are on workday does that integrate"
    assert (idx, after) == (0, 2)


def test_s1_uses_the_FIRST_turn_index_so_pair_ids_stay_unique():
    """`layer_bc_arms.build_pairs` stamps `f"{stem}:{turn_index}"`. Two moves in one call must
    not collide, and the first turn is where the move began."""
    ts = turns((N, "opening"), (C, "a"), (C, "b"), (N, "reply"))
    _, idx, after = lv.client_move(ts, 1, "s1")
    assert (idx, after) == (1, 3)


def test_s1_move_ends_at_a_naren_turn():
    ts = turns((C, "one"), (N, "reply"), (C, "two"))
    text, _, after = lv.client_move(ts, 0, "s1")
    assert (text, after) == ("one", 1)


def test_s1_move_ends_at_an_UNATTRIBUTED_turn():
    """An unidentified speaker cannot be asserted to be the client continuing -- the same
    reason UNATTRIBUTED can never be a trigger."""
    ts = turns((C, "one"), (U, "unknown"), (C, "two"))
    text, _, after = lv.client_move(ts, 0, "s1")
    assert (text, after) == ("one", 1)


def test_s1_move_ends_at_a_teammate_turn():
    ts = turns((C, "one"), (J, "colleague"), (C, "two"))
    assert lv.client_move(ts, 0, "s1")[0] == "one"


def test_s1_run_to_the_end_of_the_call_does_not_overrun():
    ts = turns((C, "one"), (C, "two"))
    text, _, after = lv.client_move(ts, 0, "s1")
    assert (text, after) == ("one two", 2)


def test_an_unknown_segment_RAISES():
    with pytest.raises(ValueError, match="unknown segment"):
        lv.client_move(turns((C, "x")), 0, "s9")


def test_s1_recovers_the_setup_turn_the_spec_names(wordy):
    """The worked example in the handoff: production pairs only 'does that integrate' and
    discards 'we are on Workday for the ATS'. s1 keeps both as one trigger."""
    ts = turns((C, "we are on workday for the ats"),
               (C, "does that integrate with what you said"),
               (N, "yes we have a direct connector"))
    s0 = lv.extract_pairs_variant(ts, 1, "s0", "a0")
    s1 = lv.extract_pairs_variant(ts, 1, "s1", "a0")
    assert len(s0) == len(s1) == 1, "the pair COUNT does not change -- only the trigger"
    assert "workday" not in s0[0]["trigger_text"]
    assert "workday" in s1[0]["trigger_text"] and "integrate" in s1[0]["trigger_text"]


def test_s1_rescues_a_block_whose_last_turn_alone_fails_the_floor(wordy):
    """The only route by which s1 adds a PAIR rather than just trigger text: the merged move
    clears the floor where its final turn alone did not."""
    ts = turns((C, "we are on workday for the ats"), (C, "right"),
               (N, "yes we have a connector"))
    assert lv.extract_pairs_variant(ts, 1, "s0", "a0") == []
    assert len(lv.extract_pairs_variant(ts, 1, "s1", "a0")) == 1


def test_s1_skips_the_whole_consumed_run_rather_than_re_entering_it(wordy):
    """If the advance were `i + 1`, the second turn of a rejected move would be retried as its
    own trigger and produce a pair production never would."""
    ts = turns((C, "aa bb"), (C, "cc dd"), (N, "one two three"))
    got = lv.extract_pairs_variant(ts, 1, "s1", "a0")
    assert len(got) == 1
    assert got[0]["trigger_text"] == "aa bb cc dd"


# ---------------------------------------------------------------------------------------
# Knob A -- admission
# ---------------------------------------------------------------------------------------

def test_a4_admits_a_short_naren_reply_that_a0_deletes(wordy):
    """The sleeper. `_is_substantive` gates each NAREN turn at v1/layer_b.py:54, and Layer C
    consumes ONLY response text -- so that line deletes evidence from the one thing being
    clustered."""
    ts = turns((C, "does indeed charge per api call"), (N, "no theirs"))
    assert lv.extract_pairs_variant(ts, 1, "s0", "a0") == []
    got = lv.extract_pairs_variant(ts, 1, "s0", "a4")
    assert len(got) == 1 and got[0]["response_text"] == "no theirs"


def test_a4_also_lengthens_a_response_that_a0_truncates(wordy):
    """Two distinct effects, and the funnel must report them separately: a4 creates pairs AND
    adds text to pairs that already existed."""
    ts = turns((C, "how does the feed refresh work"),
               (N, "it refreshes every night"), (N, "roughly"))
    a0 = lv.extract_pairs_variant(ts, 1, "s0", "a0")[0]["response_text"]
    a4 = lv.extract_pairs_variant(ts, 1, "s0", "a4")[0]["response_text"]
    assert a0 == "it refreshes every night"
    assert a4 == "it refreshes every night roughly"


def test_a1_admits_a_short_trigger_that_a0_drops(wordy):
    ts = turns((C, "and pricing"), (N, "it is two dollars per click"))
    assert lv.extract_pairs_variant(ts, 1, "s0", "a0") == []
    assert len(lv.extract_pairs_variant(ts, 1, "s0", "a1")) == 1


def test_a1_does_NOT_change_the_response_side(wordy):
    ts = turns((C, "and pricing"), (N, "sure"))
    assert lv.extract_pairs_variant(ts, 1, "s0", "a1") == []


def test_a4_does_NOT_change_the_trigger_side(wordy):
    ts = turns((C, "and pricing"), (N, "it is two dollars per click"))
    assert lv.extract_pairs_variant(ts, 1, "s0", "a4") == []


def test_a_pair_still_requires_naren_to_have_replied_under_every_setting(wordy):
    """`if response_parts:` is production's and is NOT a knob. A teammate answering is defect
    2.4 / knob S2, deferred."""
    ts = turns((C, "what is the cost per click"), (J, "it is two dollars"))
    for admit in ("a0", "a1", "a4"):
        assert lv.extract_pairs_variant(ts, 1, "s0", admit) == [], admit


# ---------------------------------------------------------------------------------------
# admission_predicates -- the real ones, with real spaCy
# ---------------------------------------------------------------------------------------

def test_a0_gates_both_sides_with_the_same_production_function():
    from v1.layer_b import _is_substantive
    trig, resp = lv.admission_predicates("a0")
    assert trig is _is_substantive and resp is _is_substantive


def test_a1_frees_the_trigger_only():
    from v1.layer_b import _is_substantive
    trig, resp = lv.admission_predicates("a1")
    assert trig("x") is True and resp is _is_substantive


def test_a4_frees_the_response_only():
    from v1.layer_b import _is_substantive
    trig, resp = lv.admission_predicates("a4")
    assert trig is _is_substantive and resp("x") is True


def test_a3_without_floors_RAISES_rather_than_defaulting():
    """A hardcoded fallback would be a threshold nobody chose -- the failure mode
    ego_trap/settings.py was deleted for."""
    with pytest.raises(ValueError, match="a3 requires"):
        lv.admission_predicates("a3")
    with pytest.raises(ValueError, match="a3 requires"):
        lv.admission_predicates("a3", {"client": 5})


def test_an_unknown_admit_RAISES():
    with pytest.raises(ValueError, match="unknown admit"):
        lv.admission_predicates("a9")


def test_a3_does_not_consult_the_stoplist_and_that_is_the_Indeed_fix():
    """'indeed' IS a spaCy stopword while ziprecruiter, workday and linkedin are NOT, so
    production's filter is inconsistent across direct competitors in a recruitment corpus.
    a3 counts alphabetic tokens only, so the vocabulary dependence is gone at its source --
    by deletion, not by a curated whitelist."""
    from v1.layer_b import _is_substantive

    sentence = "Indeed has three cost per call"
    trig, _ = lv.admission_predicates("a3", {"client": 6, "naren": 6})
    assert trig(sentence) is True, "six alphabetic tokens clears a floor of six"
    assert _is_substantive(sentence) is False, "production drops it -- 'indeed' is a stopword"


def test_a3_floor_is_a_real_bar_not_a_rubber_stamp():
    trig, _ = lv.admission_predicates("a3", {"client": 6, "naren": 6})
    assert trig("yeah ok sure") is False


# ---------------------------------------------------------------------------------------
# derive_alpha_floors -- volume neutrality by construction
# ---------------------------------------------------------------------------------------

def test_a3_floors_are_chosen_to_match_a_target_admitted_FRACTION():
    """a3 must admit the same NUMBER production does, so the comparison is 'which turns' and
    not 'how many'. That is what makes it need no placebo."""
    spec = []
    for n in range(1, 21):
        spec.append((C, " ".join(["w"] * n)))
        spec.append((N, " ".join(["w"] * n)))
    ts = turns(*spec)
    floors = lv.derive_alpha_floors([ts], target_client=0.5, target_naren=0.5)
    trig, _ = lv.admission_predicates("a3", floors)
    client = [t for t in ts if t.role == C]
    admitted = sum(1 for t in client if trig(t.text))
    assert 8 <= admitted <= 12, f"expected ~50% of 20 client turns, got {admitted}"


def test_derive_alpha_floors_RAISES_when_a_side_has_no_turns():
    ts = turns((C, "one two three"))
    with pytest.raises(ValueError, match="naren"):
        lv.derive_alpha_floors([ts], 0.5, 0.5)


# ---------------------------------------------------------------------------------------
# the advance rule -- where a paraphrase goes wrong
# ---------------------------------------------------------------------------------------

def test_the_response_window_is_consumed_not_rescanned(wordy):
    """Production advances `i = j` on a hit. If the variant advanced by one, the turns inside
    a consumed window would be re-examined and could emit duplicate pairs."""
    ts = turns((C, "how does the feed work"), (N, "it refreshes nightly"),
               (C, "and the cost of it"), (N, "two dollars per click"))
    got = lv.extract_pairs_variant(ts, 1, "s0", "a0")
    assert len(got) == 2
    assert [p["turn_index"] for p in got] == [0, 2]


def test_a_rejected_trigger_advances_past_itself_only(wordy):
    """On a miss production does `i + 1`, so the NEXT client turn still gets its chance."""
    ts = turns((C, "ok"), (C, "how does the feed work"), (N, "it refreshes nightly"))
    got = lv.extract_pairs_variant(ts, 1, "s0", "a0")
    assert len(got) == 1 and got[0]["turn_index"] == 1


def test_every_pair_carries_the_fields_the_runner_expects(wordy):
    """`layer_bc_arms.build_pairs` stamps call_filename/pair_id onto these and
    `assign_scenarios` writes scenario_key/scenario_id into them."""
    ts = turns((C, "how does the feed work"), (N, "it refreshes nightly"))
    p = lv.extract_pairs_variant(ts, 42, "s0", "a0")[0]
    assert set(p) == {"call_id", "scenario_id", "scenario_key", "turn_index",
                      "trigger_text", "response_text"}
    assert p["call_id"] == 42 and p["scenario_key"] is None
