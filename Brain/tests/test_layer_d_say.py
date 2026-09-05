"""The say arm (docs/findings/layer-d-say-arm.md): occurrence + anchored
specificity for SAY-routed moves, call-level aggregation, fail-closed routing.

The behaviors pinned here are the design's load-bearing decisions:
  * specific->hit / generic->partial / no->miss, quote-gated exactly like checks
  * the routing artifact is fail-closed (missing move / drifted criterion -> raise)
  * a say run grades ONLY the SAY-routed moves (no unscored pollution of DO moves)
  * playbooks with zero SAY moves are skipped entirely under the say identity
  * the Naren benchmark samples WHOLE CALLS for the say arm
  * the checkpoint identity carries the classification fingerprint
"""
import json
from types import SimpleNamespace

import pytest

from layer_d import graders, move_classes, pipeline
from layer_d.graders import MoveVerdict
from layer_d.signals import Moment

from tests.test_layer_d_pipeline import (  # reuse, not re-invent
    CONFIG, FakeCheckpoint, FakeStorage, PLAYBOOK, fake_tuning, moment,
)


@pytest.fixture
def recordings(tmp_path):
    # pytest fixtures don't survive a from-import; same tiny corpus as
    # test_layer_d_pipeline's fixture, redeclared.
    (tmp_path / "mapping.csv").write_text(
        "filename,csm_id,csm_name\ncallA.txt,csm1,Madhumita\n", encoding="utf-8")
    (tmp_path / "callA.txt").write_text(
        "Alexa\nwe are drowning in applications\n\nMadhumita\na reply\n",
        encoding="utf-8")
    return tmp_path

SAY_SPECS = [{"move_id": "M1", "name": "Probe", "criterion": "Probe the mechanics",
              "anchor": "do you have UTM tags?"}]

MOVES = [{"move_id": "M1", "name": "Probe", "criterion": "Probe the mechanics"},
         {"move_id": "M2", "name": "Warn", "criterion": "Warn about the deadline"}]

MOMENTS = [{"moment_id": "m1", "trigger_text": "client asks",
            "response_text": "we set up UTM tags on your careers page"}]


# ------------------------------------------------------------------ parse/prompt

def _one(raw_verdicts):
    return [{"moment_id": "m1", "verdicts": raw_verdicts}]


def test_parse_say_specific_with_verified_quote_is_hit():
    [g] = graders.parse_say_response(
        _one([{"move_id": "M1", "raised": "specific",
               "quote": "UTM tags on your careers page"},
              {"move_id": "M2", "raised": "no", "quote": ""}]),
        MOMENTS, MOVES, 0.80)
    v1, v2 = g.verdicts
    assert v1.verdict == "hit" and v1.quote_score == 1.0
    assert v2.verdict == "miss" and v2.quote == ""


def test_parse_say_generic_with_verified_quote_is_partial():
    [g] = graders.parse_say_response(
        _one([{"move_id": "M1", "raised": "generic", "quote": "we set up UTM tags"},
              {"move_id": "M2", "raised": "no"}]),
        MOMENTS, MOVES, 0.80)
    assert g.verdicts[0].verdict == "partial"


def test_parse_say_unverifiable_quote_is_unscored_not_miss():
    # The judge's claim is untrustworthy; converting it to a miss would punish
    # the rep for the instrument's failure -- the checks-arm rule, kept.
    [g] = graders.parse_say_response(
        _one([{"move_id": "M1", "raised": "specific",
               "quote": "words that appear nowhere in the reply"},
              {"move_id": "M2", "raised": "generic", "quote": ""}]),
        MOMENTS, MOVES, 0.80)
    assert g.verdicts[0].verdict == "unscored"
    assert g.verdicts[0].reason == "quote_unverified"
    assert g.verdicts[1].verdict == "unscored"      # empty quote never verifies


def test_parse_say_missing_move_is_unscored_and_every_asked_move_answered():
    [g] = graders.parse_say_response(
        _one([{"move_id": "M1", "raised": "no"}]), MOMENTS, MOVES, 0.80)
    assert [v.verdict for v in g.verdicts] == ["miss", "unscored"]
    assert g.verdicts[1].reason == "missing_from_response"


def test_parse_say_tolerates_the_wrapped_object_shape():
    [g] = graders.parse_say_response(
        {"results": _one([{"move_id": "M1", "raised": "no"},
                          {"move_id": "M2", "raised": "no"}])},
        MOMENTS, MOVES, 0.80)
    assert [v.verdict for v in g.verdicts] == ["miss", "miss"]


def test_parse_say_rejects_legacy_vocabulary():
    # 'full'/'partial' are the CHECKS vocabulary; the say arm must not credit them.
    [g] = graders.parse_say_response(
        _one([{"move_id": "M1", "raised": "full", "quote": "we set up UTM tags"},
              {"move_id": "M2", "raised": "no"}]),
        MOMENTS, MOVES, 0.80)
    assert g.verdicts[0].verdict == "unscored"


def test_build_say_prompt_carries_criterion_anchor_and_moment():
    p = graders.build_say_prompt("app_volume", "volume worries", SAY_SPECS, MOMENTS)
    assert "Probe the mechanics" in p
    assert 'WHAT "SPECIFIC" LOOKS LIKE' in p and "do you have UTM tags?" in p
    assert "we set up UTM tags on your careers page" in p
    assert '"raised"' in p                      # the say vocabulary, not "performed"


def test_grade_say_batch_batches_six_moments_per_request():
    prompts = []

    def chat(prompt):
        prompts.append(prompt)
        return []
    moments = [{"moment_id": f"m{i}", "trigger_text": "t", "response_text": "r"}
               for i in range(13)]
    graded = graders.grade_say_batch(chat, "s", "sig", MOVES, moments, 0.80)
    assert len(prompts) == 3 and len(graded) == 13
    assert all(v.verdict == "unscored" for g in graded for v in g.verdicts)


# -------------------------------------------------------------------- routing

def make_artifact(tmp_path, criterion="Probe the mechanics", route="say",
                  key="app_volume:M1"):
    art = tmp_path / "classes.json"
    art.write_text(json.dumps({"moves": {
        key: {"route": route, "class": "SAY", "readers": ["SAY", "SAY"],
              "playbook_id": 7,
              "criterion_sha256": move_classes.criterion_hash(criterion)},
    }}), encoding="utf-8")
    return art


def test_load_move_classes_missing_file_refuses(tmp_path):
    with pytest.raises(FileNotFoundError, match="routing artifact"):
        move_classes.load_move_classes(tmp_path / "nope.json")


def test_say_moves_filters_by_route_and_carries_the_anchor(tmp_path):
    classes = move_classes.load_move_classes(make_artifact(tmp_path))
    specs = move_classes.say_moves(PLAYBOOK, classes)
    assert specs == [{"move_id": "M1", "name": "Probe",
                      "criterion": "Probe the mechanics",
                      "anchor": "do you have UTM tags?"}]
    classes_pw = move_classes.load_move_classes(
        make_artifact(tmp_path, route="pairwise"))
    assert move_classes.say_moves(PLAYBOOK, classes_pw) == []


def test_say_moves_refuses_an_unclassified_live_move(tmp_path):
    classes = move_classes.load_move_classes(
        make_artifact(tmp_path, key="app_volume:M9"))
    with pytest.raises(KeyError, match="missing from the routing artifact"):
        move_classes.say_moves(PLAYBOOK, classes)


def test_say_moves_refuses_a_drifted_criterion(tmp_path):
    # A remade playbook must be re-classified loudly, never silently mis-routed.
    classes = move_classes.load_move_classes(
        make_artifact(tmp_path, criterion="the OLD criterion text"))
    with pytest.raises(ValueError, match="no longer matches"):
        move_classes.say_moves(PLAYBOOK, classes)


def test_fingerprint_changes_when_a_route_changes(tmp_path):
    a = move_classes.load_move_classes(make_artifact(tmp_path))
    b = move_classes.load_move_classes(make_artifact(tmp_path, route="pairwise"))
    assert (move_classes.classes_fingerprint(a)
            != move_classes.classes_fingerprint(b))


def test_checkpoint_layer_carries_the_classification_fingerprint():
    t = fake_tuning(grader_arm="say").layer_d
    assert pipeline.checkpoint_layer(t) == "layer_d_e_say_m1_low_swap_v3"
    assert (pipeline.checkpoint_layer(t, classes_fp="abcd1234")
            == "layer_d_e_say_m1_low_swap_clsabcd1234_v3")


# ------------------------------------------------------------- grade_moment_set

def test_grade_moment_set_say_grades_only_the_say_specs():
    def chat(prompt):
        assert "Warn about the deadline" not in prompt       # DO move never sent
        return [{"moment_id": "m1", "verdicts": [{"move_id": "M1", "raised": "no"}]}]
    out = pipeline.grade_moment_set(
        chat, {**PLAYBOOK, "key_moves": PLAYBOOK["key_moves"] + [
            {"move_id": "M2", "name": "Warn", "criterion": "Warn about the deadline"}]},
        [{"moment_id": "m1", "trigger_text": "t", "response_text": "r"}],
        fake_tuning(grader_arm="say").layer_d, say_specs=SAY_SPECS)
    assert [v.move_id for v in out["m1"]] == ["M1"]          # no DO pollution


def test_grade_moment_set_say_without_specs_raises():
    with pytest.raises(ValueError, match="say_specs"):
        pipeline.grade_moment_set(
            lambda p: [], PLAYBOOK, [{"moment_id": "m1"}],
            fake_tuning(grader_arm="say").layer_d)


# ------------------------------------------------------------------ formatting

def test_format_say_priorities_publishes_the_opportunity_density():
    from layer_d import aggregate
    gap = aggregate.Gap(rater_id="csm1", playbook_id=7, move_id="M1",
                        naren_rate=0.8, naren_attempts=10,
                        csm_rate_raw=0.2, csm_rate_shrunk=0.25, csm_attempts=12)
    meta = {(7, "M1"): {"scenario_key": "app_volume", "name": "Probe",
                        "criterion": "Probe the mechanics", "naren_quote": "q"}}
    rates = {(7, "M1"): aggregate.MoveRate(7, "M1", 12, 2, 1)}
    nrates = {(7, "M1"): aggregate.MoveRate(7, "M1", 10, 7, 1)}
    text = aggregate.format_say_priorities(
        "Madhumita", [gap], meta, rates, nrates, {},
        densities={("csm", 7, "M1"): (30, 12), ("naren", 7, "M1"): (11, 10)})
    assert "said it on 3/12 calls (specific on 2)" in text
    assert "benchmark: 8/10 calls (specific on 7)" in text
    assert "you 2.5 moments/call, benchmark 1.1" in text


# ------------------------------------------------------------------- pipeline

def say_run(monkeypatch, recordings, *, moments, classes_map=None, grade=None):
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    classes_map = classes_map if classes_map is not None else {
        "app_volume:M1": {
            "route": "say", "class": "SAY", "playbook_id": 7,
            "criterion_sha256": move_classes.criterion_hash("Probe the mechanics")},
    }
    monkeypatch.setattr(move_classes, "load_move_classes",
                        lambda path=None: classes_map)
    monkeypatch.setattr(pipeline, "get_tuning",
                        lambda: fake_tuning(grader_arm="say"))
    monkeypatch.setattr(pipeline.signals, "SignalScorer",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(pipeline.signals, "detect_moments",
                        lambda turns, call_id, scorer, arm: moments)
    # the say arm runs the benchmark pass; neutralize it for the CSM-loop tests
    monkeypatch.setattr(pipeline, "run_naren_benchmark",
                        lambda *a, **k: ({"scenarios": 0, "graded": 0,
                                          "failed": []}, k.get("conn")))
    if grade is not None:
        monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    report, _conn = pipeline.run_layer_d_batch(
        CONFIG, conn=None, recordings_dir=recordings, run_id="r1",
        client_roster=frozenset({"alexa"}),
        chat=lambda p: [{"moment_id": "callA:t0", "verdicts":
                         [{"move_id": "M1", "raised": "no"}]}])
    return report, fs, fc


def test_say_run_writes_events_under_the_say_identity(monkeypatch, recordings):
    report, fs, fc = say_run(monkeypatch, recordings, moments=[moment()])
    assert report["graded"] == 1
    [e] = [e for e in fs.events if e["rater_population"] == "csm"]
    assert e["grader_arm"] == "say"
    assert e["verdicts"] == [{"move_id": "M1", "verdict": "miss", "quote": "",
                              "quote_score": 0.0, "reason": ""}]
    # the checkpoint layer carries the classification fingerprint
    fp = move_classes.classes_fingerprint({
        "app_volume:M1": {"route": "say"}})
    assert ("callA", f"layer_d_e_say_m1_low_swap_cls{fp}_v3") in fc.done


def test_say_run_skips_playbooks_with_no_say_moves(monkeypatch, recordings):
    report, fs, fc = say_run(
        monkeypatch, recordings, moments=[moment()],
        classes_map={"app_volume:M1": {
            "route": "pairwise", "class": "DISAGREEMENT", "playbook_id": 7,
            "criterion_sha256": move_classes.criterion_hash("Probe the mechanics")}})
    assert report["no_say_moves"] == 1 and report["graded"] == 0
    assert fs.events == []                      # nothing recorded under say either


def test_say_run_still_records_deferrals_on_say_playbooks(monkeypatch, recordings):
    report, fs, fc = say_run(monkeypatch, recordings,
                             moments=[moment(outcome="other_joveo", response="")])
    assert report["deferrals"] == 1
    [e] = fs.events
    assert e["grader_arm"] == "say" and e["verdicts"] == []


def test_naren_benchmark_say_samples_whole_calls(monkeypatch):
    """Pair-by-pair sampling would hand Naren fewer moments per call than the CSM
    side gets; the say arm takes calls whole until the pair budget is covered."""
    fs, fc = FakeCheckpoint(), None  # noqa: F841 (naming symmetry)
    st, cp = FakeStorage(), FakeCheckpoint()
    st.install(monkeypatch)
    cp.install(monkeypatch)
    pairs = [
        {"pair_id": 1, "trigger_text": "t1", "response_text": "r1",
         "call_filename": "callX", "is_primary": True},
        {"pair_id": 2, "trigger_text": "t2", "response_text": "r2",
         "call_filename": "callX", "is_primary": False},
        {"pair_id": 3, "trigger_text": "t3", "response_text": "r3",
         "call_filename": "callY", "is_primary": False},
    ]
    monkeypatch.setattr(pipeline.storage, "get_pairs_for_scenario_multilabel",
                        lambda conn, key: pairs)
    monkeypatch.setattr(move_classes, "load_move_classes", lambda path=None: {
        "app_volume:M1": {
            "route": "say", "class": "SAY", "playbook_id": 7,
            "criterion_sha256": move_classes.criterion_hash("Probe the mechanics")},
    })
    monkeypatch.setattr(pipeline, "get_tuning",
                        lambda: fake_tuning(grader_arm="say"))
    seen = {}

    def grade(chat, pb, moments_, tuning_d, exemplar_for=None, say_specs=None):
        seen["moments"] = moments_
        seen["say_specs"] = say_specs
        return {m["moment_id"]: [MoveVerdict("M1", "miss")] for m in moments_}
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)

    out, _conn = pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                              run_id="r1", sample=1)
    # sample=1 pair-by-pair would take ONE pair; whole-call sampling takes callX whole
    assert [m["pair_id"] for m in seen["moments"]] == [1, 2]
    assert seen["say_specs"] == SAY_SPECS
    assert out["graded"] == 2


def test_naren_benchmark_say_skips_playbooks_with_no_say_moves(monkeypatch):
    st, cp = FakeStorage(), FakeCheckpoint()
    st.install(monkeypatch)
    cp.install(monkeypatch)
    monkeypatch.setattr(move_classes, "load_move_classes", lambda path=None: {
        "app_volume:M1": {
            "route": "pairwise", "class": "DO", "playbook_id": 7,
            "criterion_sha256": move_classes.criterion_hash("Probe the mechanics")},
    })
    monkeypatch.setattr(pipeline, "get_tuning",
                        lambda: fake_tuning(grader_arm="say"))
    out, _conn = pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                              run_id="r1", sample=5)
    assert out["skipped_no_say_moves"] == 1 and out["graded"] == 0
    assert st.events == []
