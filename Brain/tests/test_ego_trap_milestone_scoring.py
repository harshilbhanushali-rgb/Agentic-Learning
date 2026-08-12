"""Tests for ego_trap/milestone_scoring.py -- Step 3 batched scoring.

The non-batched score_milestones/score_soft_skills were deleted (nothing but their own
tests called them), so the verdict-normalisation cases they covered are re-expressed
against score_milestones_batch here.
"""
from config import Config
from ego_trap import milestone_scoring
from shared import rubric_validation


def _config():
    return Config(
        gemma_api_key="key",
        database_url="",
        joveo_speakers_lower=frozenset(),
        naren_name_lower="",
        pinecone_api_key="",
        pinecone_index_name="",
    )


def _v2_milestone(order, description="d", **extra):
    """A milestone as v2/layer_c._finish_rubric writes it -- all 10 keys."""
    base = {
        "order": order, "label": f"L{order}", "description": description,
        "detection_hint": "hint", "sequencing_type": "fixed", "position_variance": 0.1,
        "support_calls": 12, "support_clauses": 40, "relevance_mean": 0.66,
        "source_v": "v2_hdbscan",
    }
    base.update(extra)
    return base


def _item(milestones, response="resp", benchmark="bench"):
    return {
        "rubric": {"milestones": milestones},
        "csm_response_text": response,
        "benchmark_response": benchmark,
    }


# --- milestone_ids: the KeyError and collision fixes -----------------------

def test_ids_are_positional_and_dense():
    assert milestone_scoring.milestone_ids([{}, {}, {}]) == ["M1", "M2", "M3"]


def test_ids_survive_a_v1_rubric_with_no_order_field():
    """v1/layer_c stores Gemma's raw array unvalidated and PROMPT_LAYER_C_V1 only ASKS
    for 'order'. Bracket access on it used to KeyError and kill the whole run."""
    v1 = [{"description": "a"}, {"description": "b"}]
    assert milestone_scoring.milestone_ids(v1) == ["M1", "M2"]


def test_ids_do_not_collide_on_duplicate_order():
    """A duplicate 'order' used to produce two identical milestone_ids, which merge
    into ONE milestone_performance row under its (csm_id, rubric_id, milestone_id) PK
    -- silently and permanently fusing two distinct milestones' counters."""
    dupes = [{"order": 1}, {"order": 1}, {"order": 2}]
    ids = milestone_scoring.milestone_ids(dupes)
    assert ids == ["M1", "M2", "M3"]
    assert len(set(ids)) == 3


def test_ids_match_legacy_for_a_dense_v2_rubric():
    """THE MIGRATION GUARANTEE. v2 writes order = index + 1 over the same list it
    stores, so no existing milestone_performance row for a v2 rubric is orphaned."""
    v2 = [_v2_milestone(1), _v2_milestone(2), _v2_milestone(3)]
    assert milestone_scoring.milestone_ids(v2) == [f"M{m['order']}" for m in v2]


def test_ids_of_an_empty_rubric_is_empty():
    assert milestone_scoring.milestone_ids([]) == []


# --- milestone_evidence ----------------------------------------------------

def test_evidence_captures_every_v2_field():
    ev = milestone_scoring.milestone_evidence(_v2_milestone(1))
    assert ev["support_calls"] == 12
    assert ev["support_clauses"] == 40
    assert ev["relevance_mean"] == 0.66
    assert ev["sequencing_type"] == "fixed"
    assert ev["source_v"] == "v2_hdbscan"


def test_evidence_is_none_not_zero_on_a_v1_milestone():
    """support_calls=0 would assert "this milestone recurs in zero calls", which is
    false. None correctly says "never measured"."""
    ev = milestone_scoring.milestone_evidence({"description": "d", "source_v": "v1_gemma"})
    assert ev["support_calls"] is None
    assert ev["support_clauses"] is None
    assert ev["relevance_mean"] is None
    assert ev["source_v"] == "v1_gemma"


def test_evidence_records_conditional_without_acting_on_it():
    """sequencing_type is persisted so its real distribution becomes visible, but it
    changes no verdict -- it means "position varies", not "optional"."""
    ev = milestone_scoring.milestone_evidence(_v2_milestone(1, sequencing_type="conditional"))
    assert ev["sequencing_type"] == "conditional"


# --- score_milestones_batch ------------------------------------------------

def test_batch_matches_by_id_and_defaults_missing_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[
            {"id": "S0_M1", "verdict": "full_hit", "confidence": "high", "reason": "r0",
             "quote": "", "gap_to_ideal": ""},
            {"id": "S1_M1", "verdict": "miss", "confidence": "high", "reason": "r1",
             "quote": "", "gap_to_ideal": "Should have addressed pricing."},
        ],
    )
    items = [_item([_v2_milestone(1, f"d{i}")]) for i in range(3)]

    results = milestone_scoring.score_milestones_batch(items, _config())

    assert results[0][0]["verdict"] == "full_hit"
    assert results[1][0]["verdict"] == "miss"
    assert results[1][0]["gap_to_ideal"] == "Should have addressed pricing."
    # S2_M1 was never returned -> defaults to miss rather than crashing.
    assert results[2][0]["verdict"] == "miss"


def test_batch_unrecognized_verdict_defaults_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "confidence": "low", "reason": "unparseable"}],
    )
    results = milestone_scoring.score_milestones_batch([_item([_v2_milestone(1)])], _config())
    assert results[0][0]["verdict"] == "miss"
    assert results[0][0]["quote"] == ""


def test_batch_carries_evidence_and_the_rubrics_own_order_claim(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "verdict": "partial_hit", "confidence": "medium",
                       "reason": "r", "quote": "q", "gap_to_ideal": "g"}],
    )
    results = milestone_scoring.score_milestones_batch([_item([_v2_milestone(1)])], _config())
    r = results[0][0]
    assert r["milestone_id"] == "M1"
    # The claim is preserved for audit but never trusted for identity.
    assert r["milestone_order"] == 1
    assert r["evidence"]["support_calls"] == 12


def test_batch_scores_a_v1_rubric_without_raising(mocker):
    """The regression that matters most: a v1-fallback rubric must not kill the run."""
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "verdict": "full_hit", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    v1 = [{"description": "no order key at all", "label": "L"}]
    results = milestone_scoring.score_milestones_batch([_item(v1)], _config())
    assert results[0][0]["milestone_id"] == "M1"
    assert results[0][0]["milestone_order"] is None
    assert results[0][0]["evidence"]["support_calls"] is None


def test_batch_makes_no_gemma_call_for_an_empty_rubric(mocker):
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    assert milestone_scoring.score_milestones_batch([_item([])], _config()) == [[]]
    gemma.assert_not_called()


def test_batch_handles_a_wrapped_results_object(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={"results": [
            {"id": "S0_M1", "verdict": "full_hit", "confidence": "high", "reason": "r",
             "quote": "", "gap_to_ideal": ""}
        ]},
    )
    results = milestone_scoring.score_milestones_batch([_item([_v2_milestone(1)])], _config())
    assert results[0][0]["verdict"] == "full_hit"


# --- score_soft_skills_batch ----------------------------------------------

_RUBRIC_SS = {
    "milestones": [],
    "soft_skill_rubric": {"excellent_execution": "e", "failing_execution": "f"},
}


def _ss_item(skill_names, rubric=None):
    return {
        "rubric": rubric or _RUBRIC_SS,
        "csm_response_text": "resp",
        "skill_names": skill_names,
    }


def test_soft_skill_ids_do_not_collide_on_names_differing_only_by_a_space(mocker):
    """f"S{i}_{name.replace(' ', '_')}" collided "Active Listening" with
    "Active_Listening", so one skill's rating silently overwrote the other's."""
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[
            {"id": "S0_K0", "rating": "failing", "confidence": "high", "reason": "r0"},
            {"id": "S0_K1", "rating": "excellent", "confidence": "high", "reason": "r1"},
        ],
    )
    results = milestone_scoring.score_soft_skills_batch(
        [_ss_item(["Active Listening", "Active_Listening"])], _config()
    )
    assert [r["skill"] for r in results[0]] == ["Active Listening", "Active_Listening"]
    assert [r["rating"] for r in results[0]] == ["failing", "excellent"]


def test_invalid_rating_clamps_to_adequate_and_warns(mocker, capsys):
    """Before the prompt enumerated its ratings, a returned "poor" produced no gap and
    no trace at all. It must clamp to adequate -- never to failing, which would put a
    fabricated coaching finding in front of a human -- and it must say so."""
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_K0", "rating": "poor", "confidence": "low", "reason": "r"}],
    )
    results = milestone_scoring.score_soft_skills_batch(
        [_ss_item(["Confidence Under Pushback"])], _config()
    )
    assert results[0][0]["rating"] == "adequate"
    out = capsys.readouterr().out
    assert "poor" in out and "Confidence Under Pushback" in out


def test_a_missing_rating_defaults_quietly(mocker, capsys):
    """A silently absent id is already reported by the batch machinery; only an
    actively wrong value deserves a warning."""
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_K0", "confidence": "low", "reason": "r"}],
    )
    results = milestone_scoring.score_soft_skills_batch([_ss_item(["Empathy"])], _config())
    assert results[0][0]["rating"] == "adequate"
    assert "Invalid soft-skill rating" not in capsys.readouterr().out


def test_every_valid_rating_passes_through(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[
            {"id": "S0_K0", "rating": "excellent", "confidence": "high", "reason": "r"},
            {"id": "S0_K1", "rating": "adequate", "confidence": "high", "reason": "r"},
            {"id": "S0_K2", "rating": "failing", "confidence": "high", "reason": "r"},
        ],
    )
    results = milestone_scoring.score_soft_skills_batch([_ss_item(["a", "b", "c"])], _config())
    assert [r["rating"] for r in results[0]] == ["excellent", "adequate", "failing"]


def test_no_soft_skill_rubric_skips_the_item_entirely(mocker):
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    item = _ss_item(["a"], rubric={"milestones": [], "soft_skill_rubric": {}})
    assert milestone_scoring.score_soft_skills_batch([item], _config()) == [[]]
    gemma.assert_not_called()


def test_empty_skill_names_falls_back_to_the_default_name(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_K0", "rating": "failing", "confidence": "high", "reason": "r"}],
    )
    results = milestone_scoring.score_soft_skills_batch([_ss_item([])], _config())
    assert results[0][0]["skill"] == milestone_scoring._DEFAULT_SKILL_NAME


def test_prompt_enumerates_the_rating_vocabulary(mocker):
    """The half of the fix that constrains the model rather than netting its output."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_K0", "rating": "adequate", "confidence": "high", "reason": "r"}],
    )
    milestone_scoring.score_soft_skills_batch([_ss_item(["Empathy"])], _config())
    prompt = gemma.call_args[0][0]
    for rating in ("excellent", "adequate", "failing"):
        assert f'"{rating}"' in prompt


def test_the_deleted_non_batched_scorers_are_gone():
    """They were dead (only their own tests called them) and a second prompt stating
    the same verdict rules is how a rule change lands in only one place."""
    assert not hasattr(milestone_scoring, "score_milestones")
    assert not hasattr(milestone_scoring, "score_soft_skills")


# --- uncoachable-milestone skipping ---------------------------------------

def _flagged(order, **kw):
    m = _v2_milestone(order, **kw)
    m["not_coachable_flag"] = True
    return m


def test_is_uncoachable_reads_the_flag():
    assert milestone_scoring.is_uncoachable(_flagged(1)) is True
    assert milestone_scoring.is_uncoachable(_v2_milestone(1)) is False
    assert milestone_scoring.is_uncoachable({}) is False


def test_skipping_preserves_positional_ids(mocker):
    """THE INVARIANT THAT MATTERS. milestone_id is the array POSITION, so a skipped
    milestone must NOT renumber the ones after it -- otherwise existing
    milestone_performance rows silently start pointing at a different criterion."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M3", "verdict": "full_hit", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    # M2 is flagged; M1 and M3 are not.
    ms = [_v2_milestone(1), _flagged(2), _v2_milestone(3)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), skip_uncoachable=True
    )
    ids = [r["milestone_id"] for r in results[0]]
    assert ids == ["M1", "M3"], "M3 must stay M3, not be renumbered to M2"
    prompt = gemma.call_args[0][0]
    assert "S0_M2" not in prompt
    assert "S0_M1" in prompt and "S0_M3" in prompt


def test_skipping_off_by_default_scores_everything(mocker):
    mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    ms = [_v2_milestone(1), _flagged(2)]
    results = milestone_scoring.score_milestones_batch([_item(ms)], _config())
    assert [r["milestone_id"] for r in results[0]] == ["M1", "M2"]


def test_an_all_flagged_rubric_makes_no_gemma_call(mocker):
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    results = milestone_scoring.score_milestones_batch(
        [_item([_flagged(1), _flagged(2)])], _config(), skip_uncoachable=True
    )
    assert results == [[]]
    gemma.assert_not_called()


def test_a_fully_flagged_item_does_not_shift_other_items(mocker):
    """Exchange indices are enumerate() over items, so an item contributing no lines must
    not renumber the following item's S-prefix."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S1_M1", "verdict": "full_hit", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    items = [_item([_flagged(1)]), _item([_v2_milestone(1)])]
    results = milestone_scoring.score_milestones_batch(items, _config(), skip_uncoachable=True)
    assert results[0] == []
    assert results[1][0]["verdict"] == "full_hit"
    assert "S1_M1" in gemma.call_args[0][0]


# --- validation-verdict gating (layer_d.require_validated_milestones) ------

def _judged(order, verdict, **kw):
    """A milestone carrying a FRESH verdict for its own text."""
    m = _v2_milestone(order, **kw)
    return rubric_validation.with_validation(
        m, {"verdict": verdict}, run_id="r", scored_by="test")


def test_validation_gating_is_off_by_default(mocker):
    """The key ships false, so an unvalidated corpus scores exactly as it does today."""
    mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    ms = [_v2_milestone(1), _judged(2, rubric_validation.NOT_DISCRIMINATING)]
    results = milestone_scoring.score_milestones_batch([_item(ms)], _config())
    assert [r["milestone_id"] for r in results[0]] == ["M1", "M2"]


def test_a_non_discriminating_milestone_is_never_sent_to_the_scorer(mocker):
    """Not merely dropped from the results -- never put in the prompt, so it costs no
    tokens and produces no verdict, no milestone_performance row and no gap."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "verdict": "miss", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    ms = [_judged(1, rubric_validation.VALIDATED),
          _judged(2, rubric_validation.NOT_DISCRIMINATING)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), require_validated=True)
    assert [r["milestone_id"] for r in results[0]] == ["M1"]
    assert "S0_M2" not in gemma.call_args[0][0]


def test_validation_gating_preserves_positional_ids(mocker):
    """Same invariant as skip_uncoachable: a gated-out milestone must not renumber the
    ones after it, or existing milestone_performance rows repoint at another criterion."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M3", "verdict": "full_hit", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    ms = [_judged(1, rubric_validation.NOT_SATISFIABLE),
          _judged(2, rubric_validation.NOT_DISCRIMINATING),
          _judged(3, rubric_validation.VALIDATED)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), require_validated=True)
    assert [r["milestone_id"] for r in results[0]] == ["M3"]
    assert "S0_M3" in gemma.call_args[0][0]


def test_a_contingent_milestone_is_scored_only_where_it_applies(mocker):
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "verdict": "full_hit", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    ms = [_judged(1, rubric_validation.CONTINGENT),
          _judged(2, rubric_validation.CONTINGENT)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), require_validated=True,
        applicable_by_item=[{"M1"}])
    assert [r["milestone_id"] for r in results[0]] == ["M1"]
    assert "S0_M2" not in gemma.call_args[0][0]


def test_applicability_is_read_per_item_not_shared_across_the_batch(mocker):
    """Two exchanges in one batch legitimately call for different milestones -- that IS
    contingency. Applying one exchange's answer to another would erase the measurement."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M1", "verdict": "miss", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""},
                      {"id": "S1_M2", "verdict": "miss", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    ms = [_judged(1, rubric_validation.CONTINGENT),
          _judged(2, rubric_validation.CONTINGENT)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms), _item(ms)], _config(), require_validated=True,
        applicable_by_item=[{"M1"}, {"M2"}])
    assert [r["milestone_id"] for r in results[0]] == ["M1"]
    assert [r["milestone_id"] for r in results[1]] == ["M2"]
    prompt = gemma.call_args[0][0]
    assert "S0_M1" in prompt and "S1_M2" in prompt
    assert "S0_M2" not in prompt and "S1_M1" not in prompt


def test_an_unanswered_applicability_item_scores_no_contingent_milestone(mocker):
    """None means the judge did not answer for that exchange. Scoring anyway would emit
    a Milestone_Omission gap -- written advice that the CSM failed a move the moment may
    never have called for."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    ms = [_judged(1, rubric_validation.CONTINGENT)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), require_validated=True, applicable_by_item=[None])
    assert results == [[]]
    gemma.assert_not_called()


def test_a_stale_verdict_gates_the_milestone_out(mocker):
    """A Layer C re-run replaces `milestones` in place and leaves the verdict object
    behind. Trusting it would score against a criterion that was never measured."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    stale = _judged(1, rubric_validation.VALIDATED)
    stale["description"] = "reworded by a later Layer C run"
    results = milestone_scoring.score_milestones_batch(
        [_item([stale])], _config(), require_validated=True)
    assert results == [[]]
    gemma.assert_not_called()


# --- the applicability judge ----------------------------------------------

def _appl_item(milestones, utterance="Can you show me how the dashboard works?"):
    return {"rubric": {"milestones": milestones}, "client_utterance": utterance}


def test_the_judge_returns_the_applicable_subset_per_exchange(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0", "applicable": ["M1"], "reason": "r"}],
    )
    ms = [_judged(1, rubric_validation.CONTINGENT),
          _judged(2, rubric_validation.CONTINGENT)]
    assert milestone_scoring.judge_applicability_batch(
        [_appl_item(ms)], _config()) == [{"M1"}]


def test_only_contingent_milestones_are_put_to_the_judge(mocker):
    """A `validated` milestone already cleared the contingency threshold corpus-wide, so
    asking about it per response spends tokens to apply the same correction twice."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0", "applicable": ["M2"], "reason": "r"}],
    )
    ms = [_judged(1, rubric_validation.VALIDATED),
          _judged(2, rubric_validation.CONTINGENT)]
    milestone_scoring.judge_applicability_batch([_appl_item(ms)], _config())
    prompt = gemma.call_args[0][0]
    assert "M2" in prompt and "id: M1" not in prompt


def test_a_batch_with_no_contingent_milestone_makes_no_gemma_call(mocker):
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    ms = [_judged(1, rubric_validation.VALIDATED)]
    assert milestone_scoring.judge_applicability_batch(
        [_appl_item(ms)], _config()) == [None]
    gemma.assert_not_called()


def test_the_client_turn_is_shown_and_the_csm_response_is_not(mocker):
    """The measurement is 'did the moment call for this move'. A judge shown the response
    answers 'was the move made', which is what Step 3 already scores -- making this a
    second copy of the scorer rather than a control on it."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0", "applicable": [], "reason": "r"}],
    )
    item = _appl_item([_judged(1, rubric_validation.CONTINGENT)],
                      utterance="What does the integration actually require?")
    item["csm_response_text"] = "SHOULD NEVER APPEAR"
    milestone_scoring.judge_applicability_batch([item], _config())
    prompt = gemma.call_args[0][0]
    assert "What does the integration actually require?" in prompt
    assert "SHOULD NEVER APPEAR" not in prompt


def test_an_exchange_the_judge_skipped_comes_back_unknown(mocker):
    mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    ms = [_judged(1, rubric_validation.CONTINGENT)]
    assert milestone_scoring.judge_applicability_batch(
        [_appl_item(ms)], _config()) == [None]


def test_exchange_positions_survive_an_item_with_nothing_to_judge(mocker):
    """Item 0 has no contingent milestone and contributes no block, so item 1 must still
    be S1 -- the same off-by-one that skip_uncoachable's own test pins."""
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S1", "applicable": ["M1"], "reason": "r"}],
    )
    got = milestone_scoring.judge_applicability_batch(
        [_appl_item([_judged(1, rubric_validation.VALIDATED)]),
         _appl_item([_judged(1, rubric_validation.CONTINGENT)])],
        _config(),
    )
    assert got == [None, {"M1"}]


def test_the_validator_can_ask_about_every_milestone(mocker):
    """calibration/validate_rubrics.py measures applicable_rate for milestones that have
    no verdict yet -- at validation time NOTHING is contingent, so the default selection
    would ask about nothing and the whole measurement would silently return empty."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0", "applicable": ["M1", "M2"], "reason": "r"}],
    )
    ms = [_v2_milestone(1), _v2_milestone(2)]
    got = milestone_scoring.judge_applicability_batch(
        [_appl_item(ms)], _config(), include=lambda m: True)
    assert got == [{"M1", "M2"}]
    assert "id: M1" in gemma.call_args[0][0]


def test_a_stale_contingent_verdict_is_not_put_to_the_judge(mocker):
    """It is gated out of scoring anyway, so asking about it spends tokens on a milestone
    whose answer can never be used."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma")
    stale = _judged(1, rubric_validation.CONTINGENT)
    stale["description"] = "reworded by a later Layer C run"
    assert milestone_scoring.judge_applicability_batch(
        [_appl_item([stale])], _config()) == [None]
    gemma.assert_not_called()


def test_both_gates_apply_together(mocker):
    """require_validated and skip_uncoachable are independent switches over the same
    list; a milestone failing either is out."""
    gemma = mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[{"id": "S0_M2", "verdict": "miss", "confidence": "high",
                       "reason": "r", "quote": "", "gap_to_ideal": ""}],
    )
    flagged = _judged(1, rubric_validation.VALIDATED)
    flagged["not_coachable_flag"] = True
    ms = [flagged, _judged(2, rubric_validation.VALIDATED)]
    results = milestone_scoring.score_milestones_batch(
        [_item(ms)], _config(), skip_uncoachable=True, require_validated=True)
    assert [r["milestone_id"] for r in results[0]] == ["M2"]


# --- the benchmark, and withholding it -------------------------------------

def test_the_benchmark_is_shown_by_default(mocker):
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    milestone_scoring.score_milestones_batch(
        [_item([_v2_milestone(1)], benchmark="NAREN SAID THIS")], _config())

    assert "NAREN SAID THIS" in gemma.call_args[0][0]


def test_the_benchmark_can_be_withheld(mocker):
    """Arm 0b of the profile-rebuild trial. The benchmark may be turning the judgement
    into 'does this look like the reference?' rather than 'does this satisfy the
    criterion?' -- and because the benchmark travels with the RUBRIC, that resemblance
    would inflate the unrelated-rubric null, since two competent sales responses resemble
    each other whatever the topic."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    milestone_scoring.score_milestones_batch(
        [_item([_v2_milestone(1)], benchmark="NAREN SAID THIS")], _config(),
        show_benchmark=False)

    prompt = gemma.call_args[0][0]
    assert "NAREN SAID THIS" not in prompt
    assert "BENCHMARK" not in prompt


def test_withholding_the_benchmark_keeps_the_response_and_milestones(mocker):
    """Only the reference is removed. If the response or the criteria went with it the
    arm would differ from baseline in more than one way and attribute nothing."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    milestone_scoring.score_milestones_batch(
        [_item([_v2_milestone(1, description="QUANTIFIES THE OUTCOME")],
               response="HER ANSWER", benchmark="NAREN SAID THIS")],
        _config(), show_benchmark=False)

    prompt = gemma.call_args[0][0]
    assert "HER ANSWER" in prompt and "QUANTIFIES THE OUTCOME" in prompt


def test_withholding_the_benchmark_does_not_change_the_ids(mocker):
    """Positional ids must be identical across arms or the two cannot be compared
    per milestone at all."""
    gemma = mocker.patch("ego_trap.milestone_scoring.call_gemma", return_value=[])
    ms = [_v2_milestone(1), _v2_milestone(2)]
    milestone_scoring.score_milestones_batch([_item(ms)], _config(), show_benchmark=False)

    prompt = gemma.call_args[0][0]
    assert "S0_M1" in prompt and "S0_M2" in prompt
