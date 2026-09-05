"""layer_d/pipeline.py -- orchestration rules, with storage/checkpoint/signals faked.

The behaviors pinned here are the ones whose absence was a measured defect:
checkpoint-on-success-only, fail-closed speakers, deferrals stored ungraded,
coverage gaps counted, and the natural-key event payload.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from layer_d import aggregate, pipeline
from layer_d.graders import MoveVerdict
from layer_d.signals import Moment


# --------------------------------------------------------------------- fixtures

def fake_tuning(**over):
    base = dict(
        segmentation_arm="e", grader_arm="checks", grader_model="m1",
        grader_reasoning_effort="low", grader_k_runs=1, pairwise_swap=True,
        quote_verify_min_overlap=0.80, shrinkage_prior_strength=5.0,
        dead_check_naren_floor=0.50, min_attempts_to_rank=8,
        similarity_relative_margin=0.95, max_scenarios_per_signal=1,
    )
    base.update(over)
    return SimpleNamespace(layer_d=SimpleNamespace(**base))


# The FLATTENED shape (what pipeline internals consume, post live_playbooks_flat).
PLAYBOOK = {
    "playbook_id": 7, "scenario_key": "app_volume",
    "situation_signature": "volume worries",
    "key_moves": [
        {"move_id": "M1", "name": "Probe", "criterion": "Probe the mechanics",
         "evidence": [{"quote": "do you have UTM tags?"}]},
    ],
}

# The REAL storage readback shape: content nested under "playbook"
# (storage._playbook_row_to_dict). The first blind audit caught this suite passing
# with a flat fixture while the real shape KeyError'd -- FakeStorage must return
# THIS, so live_playbooks_flat is actually exercised.
PLAYBOOK_ROW = {
    "playbook_id": 7, "scenario_key": "app_volume", "arm": "real", "status": "live",
    "playbook": {
        "situation_signature": PLAYBOOK["situation_signature"],
        "arc": [], "key_moves": PLAYBOOK["key_moves"], "signature_language": [],
        "pitfalls_and_variants": [], "layer_d_checks": [],
    },
}


def moment(scen="app_volume", outcome="csm", idx=0, response="a reply"):
    return Moment(
        call_id="callA", scenario_key=scen, candidate_scenario_keys=(scen,),
        trigger_text="trigger", signal_turn_index=idx, via="last_turn",
        response_outcome=outcome, response_text=response,
    )


class FakeStorage:
    """Just enough of shared.storage for the pipeline, recording every write."""

    def __init__(self, moments_map=None):
        self.events = []
        self.csms = []
        self.refreshed = 0

    def install(self, monkeypatch):
        st = pipeline.storage
        monkeypatch.setattr(st, "get_scenarios", lambda conn: [
            {"scenario_key": "app_volume", "is_coachable": True},
            {"scenario_key": "orphan_topic", "is_coachable": True},
            {"scenario_key": "sink_x", "is_coachable": False},
        ])
        monkeypatch.setattr(st, "get_playbooks",
                            lambda conn, status=None: [PLAYBOOK_ROW])
        monkeypatch.setattr(st, "upsert_csm",
                            lambda conn, cid, cname: self.csms.append((cid, cname)))
        monkeypatch.setattr(st, "upsert_move_event",
                            lambda conn, e: self.events.append(e) or len(self.events))
        monkeypatch.setattr(st, "refresh_move_performance",
                            lambda conn: setattr(self, "refreshed", self.refreshed + 1) or 0)
        monkeypatch.setattr(st, "get_pairs_for_scenario_multilabel",
                            lambda conn, key: [])


class FakeCheckpoint:
    def __init__(self):
        self.done = set()

    def install(self, monkeypatch):
        monkeypatch.setattr(pipeline.checkpoint, "is_done",
                            lambda run_id, item, layer: (item, layer) in self.done)
        monkeypatch.setattr(pipeline.checkpoint, "mark_done",
                            lambda run_id, item, layer: self.done.add((item, layer)))


@pytest.fixture
def recordings(tmp_path):
    (tmp_path / "mapping.csv").write_text(
        "filename,csm_id,csm_name\ncallA.txt,csm1,Madhumita\n", encoding="utf-8")
    (tmp_path / "callA.txt").write_text(
        "Alexa\nwe are drowning in applications\n\nMadhumita\na reply\n",
        encoding="utf-8")
    return tmp_path


CONFIG = SimpleNamespace(joveo_speakers_lower=frozenset({"naren"}))


def run(monkeypatch, recordings, *, moments, chat=None, tuning=None, grade=None,
        roster=frozenset({"alexa"}), **kw):
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: tuning or fake_tuning())
    monkeypatch.setattr(pipeline.signals, "SignalScorer",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(pipeline.signals, "detect_moments",
                        lambda turns, call_id, scorer, arm: moments)
    if grade is not None:
        monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    report, _conn = pipeline.run_layer_d_batch(
        CONFIG, conn=None, recordings_dir=recordings, run_id="r1",
        client_roster=roster, chat=chat or (lambda p: []), **kw)
    return report, fs, fc


# ------------------------------------------------------------------------ tests

def test_refuses_without_roster_unless_explicitly_allowed(monkeypatch, recordings):
    with pytest.raises(RuntimeError, match="client roster"):
        pipeline.run_layer_d_batch(
            CONFIG, conn=None, recordings_dir=recordings, run_id="r1",
            client_roster=None, chat=lambda p: [])


def test_unverified_speaker_excludes_the_transcript(monkeypatch, recordings):
    report, fs, fc = run(monkeypatch, recordings, moments=[moment()],
                         roster=frozenset({"someone else"}))
    assert report["excluded_unverified_speakers"] == [
        {"stem": "callA", "speakers": ["Alexa"]}]
    assert report["processed"] == 0 and fs.events == []


def test_grading_failure_does_not_checkpoint(monkeypatch, recordings):
    def boom(*a, **k):
        raise RuntimeError("gateway down")
    report, fs, fc = run(monkeypatch, recordings, moments=[moment()], grade=boom)
    assert report["failed"] and report["processed"] == 0
    assert fc.done == set()                     # THE rule: no checkpoint on failure
    assert fs.events == []


def test_success_checkpoints_and_writes_the_event(monkeypatch, recordings):
    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        return {m["moment_id"]: [MoveVerdict("M1", "hit", quote="a reply",
                                             quote_score=1.0)]
                for m in moments_}
    report, fs, fc = run(monkeypatch, recordings, moments=[moment()], grade=grade)
    assert report["processed"] == 1 and report["graded"] == 1
    assert ("callA", "layer_d_e_checks_m1_low_swap_v3") in fc.done
    [e] = [e for e in fs.events if e["rater_population"] == "csm"]
    assert e["source_ref"] == "turn:0" and e["playbook_id"] == 7
    assert e["verdicts"] == [{"move_id": "M1", "verdict": "hit", "quote": "a reply",
                              "quote_score": 1.0, "reason": ""}]
    assert fs.refreshed == 1                    # move_performance rebuilt at the end


def test_deferral_is_stored_ungraded(monkeypatch, recordings):
    report, fs, fc = run(monkeypatch, recordings,
                         moments=[moment(outcome="other_joveo", response="")])
    assert report["deferrals"] == 1 and report["graded"] == 0
    [e] = [e for e in fs.events if e["rater_population"] == "csm"]
    assert e["verdicts"] == [] and e["response_outcome"] == "other_joveo"


def test_interjection_is_stored_ungraded_in_its_own_bucket(monkeypatch, recordings):
    """Kept separate from "deferrals" -- folding it in would silently move the
    already-reported deferral-rate finding."""
    report, fs, fc = run(monkeypatch, recordings,
                         moments=[moment(outcome="interjection", response="So the last.")])
    assert report["interjections"] == 1 and report["deferrals"] == 0
    assert report["graded"] == 0
    [e] = [e for e in fs.events if e["rater_population"] == "csm"]
    assert e["verdicts"] == [] and e["response_outcome"] == "interjection"
    assert e["response_text"] == "So the last."          # text preserved, not graded


def test_coachable_scenario_without_playbook_is_a_coverage_gap(monkeypatch, recordings):
    report, fs, fc = run(monkeypatch, recordings, moments=[moment(scen="orphan_topic")])
    assert report["coverage_gaps"] == {"orphan_topic": 1}
    assert [e for e in fs.events if e["rater_population"] == "csm"] == []


def test_checkpointed_transcript_is_skipped(monkeypatch, recordings):
    fs, fc = FakeStorage(), FakeCheckpoint()
    fc.done.add(("callA", "layer_d_e_checks_m1_low_swap_v3"))
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline.signals, "SignalScorer", lambda *a, **k: None)
    report, _conn = pipeline.run_layer_d_batch(
        CONFIG, conn=None, recordings_dir=recordings, run_id="r1",
        client_roster=frozenset({"alexa"}), chat=lambda p: [])
    assert report["skipped_checkpointed"] == 1 and report["processed"] == 0


def test_naren_benchmark_grades_pairs_with_the_same_instrument(monkeypatch, recordings):
    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        return {m["moment_id"]: [MoveVerdict("M1", "miss")] for m in moments_}
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline.storage, "get_pairs_for_scenario_multilabel",
                        lambda conn, key: [
                            {"pair_id": 3, "trigger_text": "t", "response_text": "r",
                             "call_filename": "narencall", "is_primary": True}])
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    out, _conn = pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                              run_id="r1", sample=5)
    assert out == {"scenarios": 1, "graded": 1, "failed": [], "aborted_read_only": False}
    [e] = fs.events
    assert e["rater_population"] == "naren" and e["rater_id"] == aggregate.NAREN
    assert e["source_ref"] == "pair:3"
    # checkpoint item carries the playbook version: a remade playbook (new id)
    # must regrade instead of reusing the superseded document's marker
    assert ("app_volume:pb7", "layer_d_e_checks_m1_low_swap_v3_naren") in fc.done


def test_pairwise_arm_skips_the_naren_benchmark_pass(monkeypatch, recordings):
    # The benchmark is inside every pairwise judgment; a separate pass is obsolete.
    called = []
    monkeypatch.setattr(pipeline, "run_naren_benchmark",
                        lambda *a, **k: called.append(1) or {})
    report, fs, fc = run(monkeypatch, recordings, moments=[],
                         tuning=fake_tuning(grader_arm="pairwise"))
    assert called == []
    assert report["naren"] == {"skipped": "pairwise embeds the benchmark", "failed": []}


def test_naren_benchmark_aborts_immediately_when_db_is_read_only(monkeypatch):
    """Same fail-fast fix as run_layer_d_batch, applied to the standalone
    --naren-only entry point -- it has its own real (non-pairwise-arm-skipped)
    write loop over live playbooks and is equally exposed."""
    graded = []

    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        graded.append(1)
        return {m["moment_id"]: [MoveVerdict("M1", "hit")] for m in moments_}

    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline.storage, "get_pairs_for_scenario_multilabel",
                        lambda conn, key: [
                            {"pair_id": 3, "trigger_text": "t", "response_text": "r",
                             "call_filename": "narencall", "is_primary": True}])
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    monkeypatch.setattr(pipeline.storage, "reconnect_if_closed", lambda conn: conn)
    monkeypatch.setattr(pipeline.storage, "clear_read_only", lambda conn: True)

    out, conn = pipeline.run_naren_benchmark(CONFIG, object(), chat=lambda p: [],
                                             run_id="r1", sample=5)
    assert out["aborted_read_only"] is True
    assert out["scenarios"] == 0 and graded == []              # zero spend wasted
    assert fs.events == [] and fc.done == set()


def test_naren_benchmark_only_filter_skips_other_scenarios(monkeypatch):
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    out, _conn = pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                              run_id="r1", sample=5,
                                              only={"some_other_scenario"})
    assert out == {"scenarios": 0, "graded": 0, "failed": [], "aborted_read_only": False}
    assert fs.events == [] and fc.done == set()


def test_naren_benchmark_failure_does_not_checkpoint(monkeypatch, recordings):
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline.storage, "get_pairs_for_scenario_multilabel",
                        lambda conn, key: [
                            {"pair_id": 3, "trigger_text": "t", "response_text": "r",
                             "call_filename": "narencall", "is_primary": True}])
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())

    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(pipeline, "grade_moment_set", boom)
    out, _conn = pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                              run_id="r1", sample=5)
    assert out["failed"] and fc.done == set()


def test_naren_benchmark_flattens_the_storage_playbook_shape(monkeypatch):
    """grade_moment_set must receive key_moves/situation_signature at the TOP level
    even though storage returns them nested -- the audit-caught defect, pinned."""
    seen = {}

    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        seen["pb"] = pb
        return {m["moment_id"]: [MoveVerdict("M1", "hit")] for m in moments_}

    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline.storage, "get_pairs_for_scenario_multilabel",
                        lambda conn, key: [
                            {"pair_id": 1, "trigger_text": "t", "response_text": "r",
                             "call_filename": "c", "is_primary": True}])
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    pipeline.run_naren_benchmark(CONFIG, conn=None, chat=lambda p: [],
                                 run_id="r1", sample=5)
    assert seen["pb"]["key_moves"] == PLAYBOOK["key_moves"]
    assert seen["pb"]["situation_signature"] == "volume worries"


def test_live_playbooks_flat_merges_the_nested_body(monkeypatch):
    monkeypatch.setattr(pipeline.storage, "get_playbooks",
                        lambda conn, status=None: [PLAYBOOK_ROW])
    [flat] = pipeline.live_playbooks_flat(None)
    assert flat["key_moves"] == PLAYBOOK["key_moves"]
    assert flat["situation_signature"] == "volume worries"
    assert flat["playbook_id"] == 7


# ------------------------------------------------------------ helper functions

def test_grade_moment_set_applies_k_run_consensus():
    calls = []

    def chat(prompt):
        calls.append(prompt)
        # run 1 says hit (with a real quote), runs 2-3 say miss -> majority miss
        if len(calls) == 1:
            return [{"moment_id": "m1", "verdicts": [
                {"move_id": "M1", "performed": "full", "quote": "a reply"}]}]
        return [{"moment_id": "m1", "verdicts": [
            {"move_id": "M1", "performed": "no"}]}]

    tuning_d = fake_tuning(grader_k_runs=3).layer_d
    out = pipeline.grade_moment_set(
        chat, PLAYBOOK,
        [{"moment_id": "m1", "trigger_text": "t", "response_text": "a reply"}],
        tuning_d)
    assert [v.verdict for v in out["m1"]] == ["miss"]
    assert len(calls) == 3


def test_grade_moment_set_unknown_arm_raises():
    with pytest.raises(ValueError, match="unknown grader_arm"):
        pipeline.grade_moment_set(lambda p: [], PLAYBOOK,
                                  [{"moment_id": "m", "trigger_text": "t",
                                    "response_text": "r"}],
                                  fake_tuning(grader_arm="likert").layer_d)


def test_make_exemplar_picker_picks_by_trigger_cosine():
    # Both candidate responses are short/filler and get caught by the substantive
    # filter below -- picker falls back to the unfiltered pool, so cosine-only
    # selection is exactly what THIS test exercises.
    pairs = [
        {"trigger_text": "pricing question", "response_text": "resp A"},
        {"trigger_text": "volume question", "response_text": "resp B"},
    ]
    vecs = {"pricing question": [1.0, 0.0], "volume question": [0.0, 1.0],
            "about volume": [0.1, 0.9]}
    pick = pipeline.make_exemplar_picker(
        pairs, lambda texts: np.array([vecs[t] for t in texts]))
    assert pick({"trigger_text": "about volume"})["response_text"] == "resp B"


def test_make_exemplar_picker_filters_out_filler_responses():
    """The exemplar-misfire fix: a filler Naren reply must never be picked as the
    benchmark, even when its trigger is the closest cosine match."""
    pairs = [
        {"trigger_text": "about volume", "response_text": "Yep. Absolutely. Perfect."},
        {"trigger_text": "volume question",
         "response_text": "Let me walk you through the pixel firing setup."},
    ]
    vecs = {"about volume": [1.0, 0.0], "volume question": [0.0, 1.0]}
    pick = pipeline.make_exemplar_picker(
        pairs, lambda texts: np.array([vecs[t] for t in texts]))
    # Exact-match trigger cosine would pick the filler pair; the filter must
    # exclude it, leaving only the substantive one to pick regardless of cosine.
    assert pick({"trigger_text": "about volume"})["response_text"] == \
        "Let me walk you through the pixel firing setup."


def test_make_exemplar_picker_falls_back_when_every_candidate_is_filler(capsys):
    """A scenario whose Naren pairs are ALL filler must not crash grading --
    falls back to the unfiltered pool and prints a warning to grep for later."""
    pairs = [
        {"trigger_text": "pricing question", "response_text": "resp A"},
        {"trigger_text": "volume question", "response_text": "resp B"},
    ]
    vecs = {"pricing question": [1.0, 0.0], "volume question": [0.0, 1.0],
            "about volume": [0.1, 0.9]}
    pick = pipeline.make_exemplar_picker(
        pairs, lambda texts: np.array([vecs[t] for t in texts]))
    assert pick({"trigger_text": "about volume"})["response_text"] == "resp B"
    assert "non-substantive" in capsys.readouterr().out


def test_checkpoint_layer_encodes_both_arms():
    t = fake_tuning(segmentation_arm="today", grader_arm="pairwise").layer_d
    assert pipeline.checkpoint_layer(t) == "layer_d_today_pairwise_m1_low_swap_v3"


def test_conn_is_none_never_touches_reconnect(monkeypatch, recordings):
    """The test suite's mode (storage entirely mocked, conn=None) must never call
    reconnect_if_closed or clear_read_only -- both would raise on a real DB call
    with nothing to talk to."""
    reconnect_calls, ro_calls = [], []
    monkeypatch.setattr(pipeline.storage, "reconnect_if_closed",
                        lambda conn: reconnect_calls.append(1) or conn)
    monkeypatch.setattr(pipeline.storage, "clear_read_only",
                        lambda conn: ro_calls.append(1) or False)
    run(monkeypatch, recordings, moments=[moment()])
    assert reconnect_calls == [] and ro_calls == []


def test_aborts_immediately_when_db_is_read_only(monkeypatch, recordings):
    """The fail-fast fix (2026-08-26): a read-only database is a DIFFERENT failure
    from a dropped connection -- reconnect_if_closed's SELECT 1 succeeds (the
    connection is alive, only writes are refused), so only an explicit
    clear_read_only check catches it. When the reset can't clear it (a genuine
    restriction, not just a leaked session setting), it must abort BEFORE
    grading (no wasted spend), not after a failed write."""
    graded = []

    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        graded.append(1)
        return {m["moment_id"]: [MoveVerdict("M1", "hit")] for m in moments_}

    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline.signals, "SignalScorer",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(pipeline.signals, "detect_moments",
                        lambda turns, call_id, scorer, arm: [moment()])
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    monkeypatch.setattr(pipeline.storage, "reconnect_if_closed", lambda conn: conn)
    monkeypatch.setattr(pipeline.storage, "clear_read_only", lambda conn: True)

    report, conn = pipeline.run_layer_d_batch(
        CONFIG, object(), recordings_dir=recordings, run_id="r1",
        client_roster=frozenset({"alexa"}), chat=lambda p: [])
    assert report["aborted_read_only"] is True
    assert report["processed"] == 0 and graded == []          # zero spend wasted
    assert report["move_performance_rows"] is None
    assert fs.events == [] and fs.refreshed == 0
    assert fc.done == set()                                   # nothing checkpointed


def test_reconnects_per_transcript_and_returns_the_live_connection(monkeypatch, recordings):
    """The self-heal fix: a dropped connection otherwise cascades into every
    remaining transcript's write failing for the rest of the run (measured
    2026-08-26). conn is checked/reconnected once per transcript, and the
    caller gets back whatever connection is actually live -- its original handle
    can be dead by the time this returns, same contract as
    ego_trap.pipeline.run_ego_trap_batch."""
    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        return {m["moment_id"]: [MoveVerdict("M1", "hit", quote="a reply",
                                             quote_score=1.0)]
                for m in moments_}
    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline.signals, "SignalScorer",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(pipeline.signals, "detect_moments",
                        lambda turns, call_id, scorer, arm: [moment()])
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)

    reconnect_calls = []
    live_conn = object()
    monkeypatch.setattr(pipeline.storage, "reconnect_if_closed",
                        lambda conn: reconnect_calls.append(conn) or live_conn)
    monkeypatch.setattr(pipeline.storage, "clear_read_only", lambda conn: False)

    original_conn = object()          # stands in for a real (non-None) connection
    report, returned_conn = pipeline.run_layer_d_batch(
        CONFIG, original_conn, recordings_dir=recordings, run_id="r1",
        client_roster=frozenset({"alexa"}), chat=lambda p: [])
    assert reconnect_calls                            # called at least once
    assert returned_conn is live_conn                 # caller gets the LIVE one back
    assert report["aborted_read_only"] is False


def test_final_aggregate_aborts_cleanly_when_db_goes_read_only(monkeypatch, recordings):
    """Audit #7 gap: the FINAL refresh_move_performance call (reached after a
    fully successful loop -- every transcript already checkpointed) must also
    check clear_read_only, not just the per-item loop. Otherwise a read-only
    flip at exactly this moment raises an unhandled traceback and loses the
    printed report for a run that, in substance, completed fine."""
    def grade(chat, pb, moments_, tuning_d, exemplar_for=None):
        return {m["moment_id"]: [MoveVerdict("M1", "hit")] for m in moments_}

    fs, fc = FakeStorage(), FakeCheckpoint()
    fs.install(monkeypatch)
    fc.install(monkeypatch)
    monkeypatch.setattr(pipeline, "get_tuning", lambda: fake_tuning())
    monkeypatch.setattr(pipeline.signals, "SignalScorer",
                        lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(pipeline.signals, "detect_moments",
                        lambda turns, call_id, scorer, arm: [moment()])
    monkeypatch.setattr(pipeline, "grade_moment_set", grade)
    monkeypatch.setattr(pipeline.storage, "reconnect_if_closed", lambda conn: conn)
    # Writable for the per-transcript check, read-only only at the final step.
    monkeypatch.setattr(pipeline.storage, "clear_read_only", lambda conn: False)

    report, conn = pipeline.run_layer_d_batch(
        CONFIG, object(), recordings_dir=recordings, run_id="r1",
        client_roster=frozenset({"alexa"}), chat=lambda p: [])
    assert report["aborted_read_only"] is False       # writable throughout: sanity
    assert report["processed"] == 1 and fs.refreshed == 1

    # Now flip only the FINAL check to read-only and re-run against a fresh fake.
    fs2, fc2 = FakeStorage(), FakeCheckpoint()
    fs2.install(monkeypatch)
    fc2.install(monkeypatch)
    calls = []
    def clear_read_only_late(conn):
        calls.append(1)
        return len(calls) > 1          # False on the per-transcript check, True after
    monkeypatch.setattr(pipeline.storage, "clear_read_only", clear_read_only_late)
    report2, conn2 = pipeline.run_layer_d_batch(
        CONFIG, object(), recordings_dir=recordings, run_id="r2",
        client_roster=frozenset({"alexa"}), chat=lambda p: [])
    assert report2["aborted_read_only"] is True
    assert report2["processed"] == 1                  # the transcript itself succeeded
    assert report2["move_performance_rows"] is None
    assert fs2.refreshed == 0                          # the DELETE never ran


def test_load_client_roster_lowercases_and_skips_blanks(tmp_path):
    p = tmp_path / "roster.txt"
    p.write_text("Alexa Smith\n\n  BOB  \n", encoding="utf-8")
    assert pipeline.load_client_roster(p) == frozenset({"alexa smith", "bob"})
