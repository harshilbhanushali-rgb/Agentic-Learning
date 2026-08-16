"""Tests for calibration/layer_b_routers.py -- the R (routing) knob.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md sections 3.1-3.3

*** THE FIXTURES ARE BUILT SO A WRONG IMPLEMENTATION FAILS, NOT SO THE RIGHT ONE PASSES. ***
An earlier suite in this trial was rejected for the opposite: its pool gave every cluster a
distinct account, so the statistic under test was trivially 1.0 and a deliberately broken
implementation passed. The defence used here is that every fixture is checked for
DISCRIMINATION before it is used as evidence:

  * the out-of-fold world is asserted to give a DIFFERENT top-1 in fold and out of fold, so
    an R2 that forgot the exclusion cannot pass;
  * the scenario whose only evidence is the querying call is the one with cosine 1.0 to the
    trigger, so an R2 that forgot to drop it routes to it;
  * the cap-accounting fixture asserts `flat_pick != topk_pick` on its own numbers before
    asserting which one the router follows;
  * R1's fallback and R0 are compared against `v1.layer_b.assign_scenarios` itself, not
    against a restatement of it.

Vectors are hand-built orthogonal unit axes, the precedent of `tests/test_layer_b_assignment.py`:
these test the RULE, and a change of embedding model must not be able to move them. Thresholds
come from `load_tuning()` rather than being written in, so retuning `relative_margin` cannot
silently turn a rule test into a boundary test.
"""
import copy
import math

import numpy as np
import pytest

from calibration import layer_b_routers as lr
from calibration.layer_bc_arms import scenario_map_from_rows
from preprocessing.transcript_parser import SpeakerRole, Turn
from shared.relative_match import cosine_sims, flat_pick, is_sink_flags, topk_pick
from shared.tuning import load_tuning

C, N, J, U = (SpeakerRole.CLIENT, SpeakerRole.NAREN,
              SpeakerRole.JOVEO_OTHER, SpeakerRole.UNATTRIBUTED)

_LB = load_tuning().layer_b
MARGIN, CAP = _LB.relative_margin, _LB.max_scenarios_per_pair

_AXES = {"e0": [1.0, 0.0, 0.0, 0.0], "e1": [0.0, 1.0, 0.0, 0.0],
         "e2": [0.0, 0.0, 1.0, 0.0], "e3": [0.0, 0.0, 0.0, 1.0]}


def _resolve(text: str) -> np.ndarray:
    """Sum the axis weights named in a text, then unit-normalise.

    Raises on a text naming no axis, so an unexpected embed call (a response, say) shows up
    as a failure rather than as a plausible vector.
    """
    v = np.zeros(4, dtype=np.float64)
    for token in text.split():
        name, _, weight = token.partition(":")
        if name in _AXES:
            v += np.asarray(_AXES[name], dtype=np.float64) * float(weight or 1.0)
    if not v.any():
        raise AssertionError(f"test text names no known axis: {text!r}")
    return v / np.linalg.norm(v)


def _at(cos: float) -> str:
    """A text whose vector sits at exactly `cos` from e0, in the e0/e1 plane."""
    return f"e0:{cos} e1:{math.sqrt(max(0.0, 1.0 - cos * cos))}"


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Patch the ONE module object v1.layer_b and shared.scenario_vectors both import."""
    from preprocessing import embedder
    resolve = lambda ts: [_resolve(t).tolist() for t in ts]      # noqa: E731
    monkeypatch.setattr(embedder, "embed_query", resolve)
    monkeypatch.setattr(embedder, "embed_document", resolve)


# ---------------------------------------------------------------------------------------
# world builders
# ---------------------------------------------------------------------------------------

def _world(spec):
    """[(call, text, cluster_key)] -> (members, vecs, calls, texts) in pool order."""
    texts = [t for _, t, _ in spec]
    calls = [c for c, _, _ in spec]
    vecs = np.stack([_resolve(t) for t in texts]).astype(np.float64)
    members = {}
    for i, (_, _, key) in enumerate(spec):
        if key is not None:
            members.setdefault(key, []).append(i)
    return members, vecs, calls, texts


def _smap(**spec):
    """key -> {'desc text': is_coachable}. scenario_id is the declaration order."""
    return {k: {"scenario_id": i, "scenario_key": k, "business_description": desc,
                "keyphrases": [], "is_coachable": coachable}
            for i, (k, (desc, coachable)) in enumerate(spec.items())}


def _ctx(router, members, vecs, calls, texts=None, turn_index_map=None, move_len=None):
    """A hand-built context, resolving a permutation-placebo name to its REAL router.

    `build_router_context` does this resolution for the production path; this helper bypasses
    it, so without the same resolution an `r2p` context would carry `oof=None` and the placebo
    would crash on the first centroid lookup. Mirroring the resolution here keeps the helper a
    stand-in for the real builder rather than a differently-behaved one.
    """
    real = lr._PLACEBO_OF.get(router, router)
    return lr.RouterContext(
        router=router, diag={"router": router}, members=members,
        lookup=lr.build_lookup(members), texts=list(texts or []), calls=list(calls),
        turn_index_map=dict(turn_index_map or {}), move_len=dict(move_len or {}),
        oof=(lr.OutOfFoldCentroids(members, vecs, calls) if real in ("r2", "r3") else None))


def _pair(trigger, call="a.txt", idx=0):
    return {"call_filename": call, "turn_index": idx, "trigger_text": trigger,
            "response_text": "e3", "scenario_key": None, "scenario_id": None}


def _turns(*spec):
    return [Turn(index=i, speaker_raw="s", role=r, text=t, call_id="c")
            for i, (r, t) in enumerate(spec)]


def _parsed(*calls):
    from pathlib import Path
    return [(n, Path(name), turns) for n, (name, turns) in enumerate(calls, 1)]


def _row(cid, kind, key, merge_into=None, failed=False, desc="e0"):
    return {"cluster_id": cid, "kind": kind, "scenario_key": key, "failed": failed,
            "merge_into_key": merge_into, "business_description": desc, "keyphrases": []}


def _cluster(cid, idxs):
    return {"cluster_id": cid, "idxs": list(idxs)}


# =======================================================================================
# member_sets -- the four-valued enum that has produced two phantom findings
# =======================================================================================

def test_a_merged_rows_turns_land_in_its_TARGETS_member_set():
    members, diag = lr.member_sets(
        [_row("c1", "scenario", "real"), _row("c2", "merged", "dupe", merge_into="real")],
        [_cluster("c1", [0, 1]), _cluster("c2", [7, 8])])
    assert members == {"real": [0, 1, 7, 8]}
    assert diag["merged_folded"] == 1
    assert diag["scenarios"] == 1


def test_a_failed_row_contributes_no_key_and_no_turns():
    members, diag = lr.member_sets(
        [_row("c1", "scenario", "real"), _row("c2", "failed", "ghost", failed=True)],
        [_cluster("c1", [0]), _cluster("c2", [5])])
    assert members == {"real": [0]}
    assert diag["failed"] == 1
    assert 5 not in [i for v in members.values() for i in v]


def test_sinks_keep_their_own_member_sets():
    members, diag = lr.member_sets(
        [_row("c1", "scenario", "real"), _row("c2", "mechanics", "junk"),
         _row("c3", "logistics", "sched")],
        [_cluster("c1", [0]), _cluster("c2", [1]), _cluster("c3", [2])])
    assert members == {"real": [0], "junk": [1], "sched": [2]}
    assert diag["sinks"] == 2


def test_duplicate_keys_are_SUFFIXED_IDENTICALLY_to_scenario_map_from_rows():
    """The two functions run SEPARATE suffix loops. If they ever disagree, every member set
    after the first duplicate is attached to the wrong scenario while both key sets still
    look complete -- so this compares them row by row, not as sets."""
    rows = [_row("c1", "scenario", "dup"), _row("c2", "mechanics", "dup"),
            _row("c3", "scenario", "dup")]
    clusters = [_cluster("c1", [0]), _cluster("c2", [1]), _cluster("c3", [2])]
    members, _ = lr.member_sets(rows, clusters)
    smap, cluster_of_key = scenario_map_from_rows(rows)

    assert set(members) == set(smap) == {"dup", "dup_1", "dup_2"}
    # row order is the alignment: key -> cluster must agree on BOTH sides
    for key, cid in (("dup", "c1"), ("dup_1", "c2"), ("dup_2", "c3")):
        assert cluster_of_key[key] == cid
        assert members[key] == next(c["idxs"] for c in clusters if c["cluster_id"] == cid)


def test_suffixes_stay_aligned_when_merged_and_failed_rows_sit_between_duplicates():
    rows = [_row("c1", "scenario", "dup"),
            _row("c2", "merged", "dup", merge_into="dup"),
            _row("c3", "failed", "dup", failed=True),
            _row("c4", "scenario", "dup")]
    clusters = [_cluster("c1", [0]), _cluster("c2", [1]), _cluster("c3", [2]),
                _cluster("c4", [3])]
    members, _ = lr.member_sets(rows, clusters)
    smap, cluster_of_key = scenario_map_from_rows(rows)
    assert set(members) == set(smap) == {"dup", "dup_1"}
    assert members["dup"] == [0, 1]          # the merged cluster folded into the first
    assert members["dup_1"] == [3]
    assert cluster_of_key["dup_1"] == "c4"


def test_an_unresolvable_merge_target_is_REPORTED_not_silently_dropped():
    members, diag = lr.member_sets(
        [_row("c1", "scenario", "real"), _row("c2", "merged", "dupe", merge_into="ghost")],
        [_cluster("c1", [0]), _cluster("c2", [9])])
    assert members == {"real": [0]}
    assert diag["merged_unresolved"] == [("ghost", "c2")]
    assert diag["merged_folded"] == 0


def test_a_merge_into_resolves_to_the_FIRST_holder_of_a_duplicated_key():
    """Gemma chose `merge_into` against the key it saw in its accepted list, which is the
    unsuffixed one."""
    rows = [_row("c1", "scenario", "dup"), _row("c2", "scenario", "dup"),
            _row("c3", "merged", "x", merge_into="dup")]
    clusters = [_cluster("c1", [0]), _cluster("c2", [1]), _cluster("c3", [2])]
    members, _ = lr.member_sets(rows, clusters)
    assert members == {"dup": [0, 2], "dup_1": [1]}


def test_an_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown adjudication kind"):
        lr.member_sets([_row("c1", "banana", "x")], [_cluster("c1", [0])])


# =======================================================================================
# turn_to_pool_index -- a silently misaligned join is the worst failure available here
# =======================================================================================

def test_the_positional_join_is_correct_and_covers_only_CLIENT_turns():
    parsed = _parsed(
        ("a.txt", _turns((C, "alpha"), (N, "reply"), (J, "colleague"), (C, "beta"))),
        ("b.txt", _turns((U, "who?"), (C, "gamma"))))
    pool = ["alpha", "beta", "gamma"]
    assert lr.turn_to_pool_index(parsed, pool) == {
        ("a.txt", 0): 0, ("a.txt", 3): 1, ("b.txt", 1): 2}


def test_a_text_mismatch_raises_rather_than_returning_a_partial_map():
    parsed = _parsed(("a.txt", _turns((C, "alpha"), (C, "beta"))))
    with pytest.raises(ValueError, match="POSITIONAL JOIN BROKEN"):
        lr.turn_to_pool_index(parsed, ["alpha", "NOT beta"])


def test_a_pool_shorter_than_the_corpus_raises():
    parsed = _parsed(("a.txt", _turns((C, "alpha"), (C, "beta"))))
    with pytest.raises(ValueError, match="pool exhausted"):
        lr.turn_to_pool_index(parsed, ["alpha"])


def test_a_pool_longer_than_the_corpus_raises():
    parsed = _parsed(("a.txt", _turns((C, "alpha"))))
    with pytest.raises(ValueError, match="different corpora"):
        lr.turn_to_pool_index(parsed, ["alpha", "beta"])


def test_call_of_pool_index_labels_every_item_and_refuses_a_length_mismatch():
    parsed = _parsed(("a.txt", _turns((C, "alpha"), (N, "r"), (C, "beta"))),
                     ("b.txt", _turns((C, "gamma"))))
    assert lr.call_of_pool_index(parsed, ["alpha", "beta", "gamma"]) == [
        "a.txt", "a.txt", "b.txt"]
    with pytest.raises(ValueError, match="call labels for"):
        lr.call_of_pool_index(parsed, ["alpha", "beta"])


# =======================================================================================
# move_lengths / pair_pool_indices -- the s1 unit must be the extractor's unit
# =======================================================================================

def test_move_lengths_is_empty_for_s0_because_a_trigger_is_one_turn():
    parsed = _parsed(("a.txt", _turns((C, "alpha"), (C, "beta"))))
    assert lr.move_lengths(parsed, "s0") == {}
    assert lr.pair_pool_indices(_pair("t", "a.txt", 0), {("a.txt", 0): 4}) == [4]


def test_move_lengths_AGREES_WITH_the_extractors_own_client_move_rule():
    """Cross-checked against `layer_b_variants.client_move` rather than against a restatement
    of it: these two must define one trigger identically or an s1 move is looked up against
    the pool indices of a different span."""
    from calibration.layer_b_variants import client_move

    turns = _turns((C, "a1"), (C, "a2"), (C, "a3"), (N, "r"), (C, "b1"), (U, "?"),
                   (C, "c1"), (J, "x"), (C, "d1"), (C, "d2"))
    parsed = _parsed(("a.txt", turns))
    got = lr.move_lengths(parsed, "s1")

    expected = {}
    i = 0
    while i < len(turns):
        if turns[i].role != C:
            i += 1
            continue
        _text, idx, after = client_move(turns, i, "s1")
        expected[("a.txt", idx)] = after - i
        i = after
    assert got == expected
    assert got == {("a.txt", 0): 3, ("a.txt", 4): 1, ("a.txt", 6): 1, ("a.txt", 8): 2}


def test_an_s1_move_covers_the_CONSECUTIVE_pool_indices_of_its_run():
    parsed = _parsed(("a.txt", _turns((N, "r"), (C, "a1"), (C, "a2"), (C, "a3"))))
    pool = ["a1", "a2", "a3"]
    tmap = lr.turn_to_pool_index(parsed, pool)
    n = lr.move_lengths(parsed, "s1")[("a.txt", 1)]
    assert lr.pair_pool_indices(_pair("a1 a2 a3", "a.txt", 1), tmap, n) == [0, 1, 2]


def test_a_pair_whose_trigger_is_not_in_the_pool_yields_no_indices():
    assert lr.pair_pool_indices(_pair("t", "ghost.txt", 3), {("a.txt", 0): 0}) == []


# =======================================================================================
# r1_pick -- the whole of R1's mechanism
# =======================================================================================

def test_r1_pick_reads_the_label_of_a_single_turn():
    assert lr.r1_pick([2], {2: "real"}, ["x", "y", "z"]) == "real"


def test_r1_pick_resolves_a_move_spanning_two_clusters_by_MAJORITY():
    lookup = {0: "alpha", 1: "beta", 2: "beta"}
    assert lr.r1_pick([0, 1, 2], lookup, ["aaaaaaaaaa", "b", "b"]) == "beta"


def test_r1_pick_breaks_a_TIE_by_longest_text_and_is_order_independent():
    lookup = {0: "alpha", 1: "beta"}
    texts = ["short", "a much longer turn carrying the subject"]
    assert lr.r1_pick([0, 1], lookup, texts) == "beta"
    # reversing the turn order must not move the answer -- that is what "deterministic"
    # means here, and dict/insertion order is exactly what a naive tie-break would follow.
    assert lr.r1_pick([1, 0], lookup, texts) == "beta"
    assert lr.r1_pick([0, 1], {0: "beta", 1: "alpha"}, texts) == "alpha"


def test_r1_pick_returns_None_when_every_turn_was_hdbscan_noise():
    assert lr.r1_pick([3, 4], {0: "real"}, ["a", "b", "c", "d", "e"]) is None
    assert lr.r1_pick([], {0: "real"}, ["a"]) is None


# =======================================================================================
# build_lookup
# =======================================================================================

def test_build_lookup_maps_every_member_index():
    assert lr.build_lookup({"a": [0, 2], "b": [1]}) == {0: "a", 2: "a", 1: "b"}


def test_overlapping_member_sets_raise_rather_than_letting_dict_order_decide():
    with pytest.raises(ValueError, match="member sets "):
        lr.build_lookup({"a": [0, 1], "b": [1]})


# =======================================================================================
# OutOfFoldCentroids -- without this, R2 reproduces membership having learned nothing
# =======================================================================================

# call     text                cluster
_OOF_SPEC = [
    ("a.txt", "e0", "A"),           # 0
    ("a.txt", "e0", "A"),           # 1
    ("b.txt", "e1", "A"),           # 2
    ("b.txt", _at(0.6), "B"),       # 3
    ("a.txt", _at(0.6), "B"),       # 4
    ("a.txt", "e0", "ONLY_A"),      # 5  cosine 1.0 to the trigger, evidenced by a.txt alone
    ("b.txt", "e2", "SINK"),        # 6
    ("a.txt", "e2", "SINK"),        # 7
]
_OOF_MAP = _smap(A=("e3", True), B=("e3", True), ONLY_A=("e3", True), SINK=("e3", False))


def _oof_world(drop_only_a=False):
    spec = [s for s in _OOF_SPEC if not (drop_only_a and s[2] == "ONLY_A")]
    members, vecs, calls, texts = _world(spec)
    return members, vecs, calls, texts


def test_excluding_the_querying_call_CHANGES_the_top1_so_a_forgetful_R2_cannot_pass():
    """The fixture is asserted to discriminate BEFORE it is used as evidence."""
    members, vecs, calls, _ = _oof_world(drop_only_a=True)
    oof = lr.OutOfFoldCentroids(members, vecs, calls)
    t = _resolve("e0")[None, :]

    in_keys, in_cents = oof.in_fold()
    out_keys, out_cents = oof.for_call("a.txt")
    in_top = in_keys[int(np.argmax(cosine_sims(t, in_cents)[0]))]
    out_top = out_keys[int(np.argmax(cosine_sims(t, out_cents)[0]))]

    assert in_top == "A"        # in fold, a.txt's own two e0 turns drag A's centroid to e0
    assert out_top == "B"       # out of fold, A is only b.txt's e1 turn
    assert in_top != out_top


def test_a_scenario_evidenced_only_by_the_querying_call_is_DROPPED():
    members, vecs, calls, _ = _oof_world()
    oof = lr.OutOfFoldCentroids(members, vecs, calls)
    keys_a, _ = oof.for_call("a.txt")
    keys_b, _ = oof.for_call("b.txt")
    assert "ONLY_A" not in keys_a
    assert "ONLY_A" in keys_b
    # and it is the one that would WIN if it were not dropped -- cosine 1.0 to the trigger
    in_keys, in_cents = oof.in_fold()
    assert in_keys[int(np.argmax(cosine_sims(_resolve("e0")[None, :], in_cents)[0]))] == "ONLY_A"


def test_partial_sums_equal_a_naive_recomputation():
    members, vecs, calls, _ = _oof_world()
    oof = lr.OutOfFoldCentroids(members, vecs, calls)
    for call in ("a.txt", "b.txt", "no_such_call.txt"):
        keys, cents = oof.for_call(call)
        for k, c in zip(keys, cents):
            kept = [i for i in members[k] if calls[i] != call]
            naive = vecs[kept].mean(axis=0)
            naive = naive / np.linalg.norm(naive)
            assert np.allclose(c, naive, atol=1e-9), (call, k)


def test_a_call_contributing_nothing_leaves_every_centroid_untouched():
    members, vecs, calls, _ = _oof_world()
    oof = lr.OutOfFoldCentroids(members, vecs, calls)
    in_keys, in_cents = oof.in_fold()
    keys, cents = oof.for_call("no_such_call.txt")
    assert keys == in_keys
    assert np.allclose(cents, in_cents)


# =======================================================================================
# router_context_from_clusters -- the guards, which are where a silent misroute would come from
# =======================================================================================

def _join_world():
    parsed = _parsed(("a.txt", _turns((C, "e0"), (N, "r"), (C, "e1"))))
    texts = ["e0", "e1"]
    vecs = np.stack([_resolve(t) for t in texts])
    return parsed, texts, vecs


def test_a_row_naming_a_MISSING_cluster_raises_because_the_suffixes_would_shift():
    parsed, texts, vecs = _join_world()
    rows = [_row("gone", "scenario", "dup"), _row("c2", "scenario", "dup")]
    smap, _ = scenario_map_from_rows(rows)
    # both keys still exist on both sides, so a set-difference check would pass -- which is
    # exactly why the guard is on `missing_cluster` and not on the key sets.
    members, mdiag = lr.member_sets(rows, [_cluster("c2", [0, 1])])
    assert set(members) <= set(smap) and mdiag["missing_cluster"] == ["gone"]
    with pytest.raises(ValueError, match="not in this clustering"):
        lr.router_context_from_clusters("r1", rows, [_cluster("c2", [0, 1])], parsed,
                                        texts, vecs, smap)


def test_the_context_verifies_the_pool_join_before_anything_is_routed():
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    with pytest.raises(ValueError, match="POSITIONAL JOIN BROKEN"):
        lr.router_context_from_clusters("r1", rows, [_cluster("c1", [0, 1])], parsed,
                                        ["e0", "WRONG"], vecs, smap)


def test_the_context_reports_the_membership_shape_it_built():
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real"), _row("c2", "mechanics", "junk"),
            _row("c3", "merged", "d", merge_into="real")]
    smap, _ = scenario_map_from_rows(rows)
    clusters = [_cluster("c1", [0]), _cluster("c2", [1]), _cluster("c3", [])]
    ctx = lr.router_context_from_clusters("r2", rows, clusters, parsed, texts, vecs, smap)
    assert ctx.diag["n_member_keys"] == 2
    assert ctx.diag["member_scenarios"] == 1 and ctx.diag["member_sinks"] == 1
    assert ctx.diag["merged_folded"] == 1
    assert ctx.diag["scenarios_without_members"] == 0
    assert ctx.oof is not None and ctx.lookup == {0: "real", 1: "junk"}


def _stub_clustering(monkeypatch, sha, clusters, texts, vecs):
    """Stand in for build_clusters so the PINNING logic can be tested without UMAP."""
    from calibration import adjudication_ab as ab
    monkeypatch.setattr(ab, "build_clusters",
                        lambda rec, mf, resc: (clusters, texts, [], vecs, 1, None))
    monkeypatch.setattr(ab, "members_sha", lambda cs: sha)


def test_a_clustering_that_does_not_hash_to_the_taxonomys_members_sha_is_REFUSED(monkeypatch):
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    _stub_clustering(monkeypatch, "aaaa", [_cluster("c1", [0, 1])], texts, vecs)
    with pytest.raises(SystemExit, match="MEMBERSHIP MISMATCH"):
        lr.build_router_context("r2", rows, parsed, smap, width=vecs.shape[1],
                                taxonomy_identity={"members_sha": "bbbb"})


def test_a_taxonomy_with_no_members_sha_is_REFUSED_rather_than_trusted(monkeypatch):
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    _stub_clustering(monkeypatch, "aaaa", [_cluster("c1", [0, 1])], texts, vecs)
    with pytest.raises(SystemExit, match="records no `members_sha`"):
        lr.build_router_context("r2", rows, parsed, smap, width=vecs.shape[1],
                                taxonomy_identity={})


def test_a_width_other_than_the_pools_own_is_REFUSED(monkeypatch):
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    _stub_clustering(monkeypatch, "aaaa", [_cluster("c1", [0, 1])], texts, vecs)
    with pytest.raises(SystemExit, match="A truncated centroid space"):
        lr.build_router_context("r2", rows, parsed, smap, width=2,
                                taxonomy_identity={"members_sha": "aaaa"})


def test_a_pinned_clustering_builds_a_usable_context(monkeypatch):
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    _stub_clustering(monkeypatch, "aaaa", [_cluster("c1", [0, 1])], texts, vecs)
    ctx = lr.build_router_context("r2", rows, parsed, smap, width=vecs.shape[1],
                                  taxonomy_identity={"members_sha": "aaaa"})
    assert ctx.router == "r2" and ctx.lookup == {0: "real", 1: "real"}
    assert ctx.calls == ["a.txt", "a.txt"]


def test_r1_gets_no_out_of_fold_centroids_and_r0_gets_no_context_at_all():
    parsed, texts, vecs = _join_world()
    rows = [_row("c1", "scenario", "real")]
    smap, _ = scenario_map_from_rows(rows)
    ctx = lr.router_context_from_clusters("r1", rows, [_cluster("c1", [0, 1])], parsed,
                                          texts, vecs, smap)
    assert ctx.oof is None
    assert lr.build_router_context("r0").oof is None
    with pytest.raises(ValueError, match="r0 needs no context"):
        lr.router_context_from_clusters("r0", rows, [], parsed, texts, vecs, smap)


# =======================================================================================
# assign_scenarios_router -- the contract, and each router's rule
# =======================================================================================

def test_an_unknown_router_raises():
    with pytest.raises(ValueError, match="unknown router"):
        lr.assign_scenarios_router([_pair("e0")], _smap(a=("e0", True)), "r9", None)


def test_a_context_built_for_another_router_is_refused():
    members, vecs, calls, texts = _oof_world()
    ctx = _ctx("r2", members, vecs, calls, texts)
    with pytest.raises(ValueError, match="context was built for"):
        lr.assign_scenarios_router([_pair("e0")], _OOF_MAP, "r3", ctx)


def test_r0_is_the_production_function_and_adds_nothing_to_the_pairs(fake_embeddings):
    """r0 must be `v1.layer_b.assign_scenarios` itself -- same assignments, same returned
    vectors, same three fields and no fourth."""
    from v1 import layer_b

    # A two-axis mixture weighted 1.0 and w puts the weaker match's cosine at exactly w times
    # the stronger's, so w is directly comparable to relative_margin -- halfway between the
    # margin and a perfect tie, which keeps this a rule test at any retuned margin.
    tie = MARGIN + (1.0 - MARGIN) / 2.0
    smap = _smap(pricing=("e0", True), quality=("e1", True), ack=("e2", False))
    triggers = ["e0", "e2", f"e0:1.0 e1:{tie}", "e0:1.0 e1:0.2"]
    prod_pairs = [_pair(t) for t in triggers]
    router_pairs = copy.deepcopy(prod_pairs)

    prod_vecs = layer_b.assign_scenarios(prod_pairs, smap, None)
    ctx = lr.build_router_context("r0")
    router_vecs = lr.assign_scenarios_router(router_pairs, smap, "r0", ctx)

    assert router_pairs == prod_pairs
    assert router_vecs == prod_vecs
    # the sink trigger really did exercise the short-circuit, so this is not four copies of
    # the same branch
    assert prod_pairs[1]["scenario_keys"] == ["ack"]
    assert set(prod_pairs[2]["scenario_keys"]) == {"pricing", "quality"}
    assert prod_pairs[3]["scenario_keys"] == ["pricing"]
    assert ctx.diag["top1_sink_share"] == pytest.approx(0.25)


def test_r1_assigns_the_lookup_key_ALONE_and_never_ranks(fake_embeddings):
    """The trigger is closest to `other` by description, so an R1 that fell through to
    description matching would answer `other`, and one that ranked would answer two keys."""
    members, vecs, calls, texts = _world([("a.txt", "e0", "real"), ("b.txt", "e0", "real")])
    smap = _smap(real=("e2", True), other=("e0", True))
    ctx = _ctx("r1", members, vecs, calls, texts, {("a.txt", 0): 0})

    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r1", ctx)
    assert pairs[0]["scenario_keys"] == ["real"]
    assert pairs[0]["scenario_key"] == "real"
    assert pairs[0]["scenario_id"] == smap["real"]["scenario_id"]
    assert ctx.diag["r1_lookup_resolved"] == 1 and ctx.diag["r1_fallback_share"] == 0.0


def test_r1_files_a_SINK_lookup_to_the_sink_alone(fake_embeddings):
    members, vecs, calls, texts = _world([("a.txt", "e0", "junk"), ("b.txt", "e0", "junk")])
    smap = _smap(real=("e0", True), junk=("e2", False))
    ctx = _ctx("r1", members, vecs, calls, texts, {("a.txt", 0): 0})
    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r1", ctx)
    assert pairs[0]["scenario_keys"] == ["junk"]
    assert ctx.diag["r1_lookup_to_sink"] == 1
    assert ctx.diag["top1_sink_share"] == 1.0


def test_r1_falls_back_to_PRODUCTIONS_answer_when_the_turn_was_noise(fake_embeddings):
    """Compared against `assign_scenarios` itself. The noise case is ~47% of this pool, so a
    fallback that quietly differed from R0 would contaminate most of R1's result."""
    from v1 import layer_b

    # nothing in the pool belongs to a cluster -> every lookup misses
    members, vecs, calls, texts = _world([("a.txt", "e0", "real"), ("b.txt", "e1", "real")])
    smap = _smap(real=("e0", True), near=(_at(MARGIN + (1 - MARGIN) / 2), True),
                 ack=("e2", False))
    ctx = _ctx("r1", members, vecs, calls, texts, {("a.txt", 5): 99, ("a.txt", 6): 98})

    triggers = ["e0", "e2"]
    prod_pairs = [_pair(t, "a.txt", 5 + k) for k, t in enumerate(triggers)]
    r1_pairs = copy.deepcopy(prod_pairs)
    layer_b.assign_scenarios(prod_pairs, smap, None)
    lr.assign_scenarios_router(r1_pairs, smap, "r1", ctx)

    assert r1_pairs == prod_pairs
    assert ctx.diag["r1_lookup_resolved"] == 0
    assert ctx.diag["r1_fallback_noise"] == 2
    assert ctx.diag["r1_fallback_unmapped"] == 0
    # and the fallback is not degenerate: production kept a near-tie on the first trigger
    assert len(prod_pairs[0]["scenario_keys"]) > 1


def test_r1_separates_a_BROKEN_JOIN_from_hdbscan_noise(fake_embeddings):
    members, vecs, calls, texts = _world([("a.txt", "e0", "real"), ("b.txt", "e1", "real")])
    smap = _smap(real=("e0", True))
    ctx = _ctx("r1", members, vecs, calls, texts, {("a.txt", 0): 0})
    pairs = [_pair("e0", "a.txt", 0), _pair("e0", "a.txt", 4)]   # second is not in the map
    lr.assign_scenarios_router(pairs, smap, "r1", ctx)
    assert ctx.diag["r1_lookup_resolved"] == 1
    assert ctx.diag["r1_fallback_unmapped"] == 1
    assert ctx.diag["r1_fallback_noise"] == 0


def test_r1_routes_an_s1_move_by_MAJORITY_over_its_own_turns(fake_embeddings):
    parsed = _parsed(("a.txt", _turns((C, "e0"), (C, "e1"), (C, "e2"), (N, "r"))))
    members, vecs, calls, texts = _world(
        [("a.txt", "e0", "alpha"), ("a.txt", "e1", "beta"), ("a.txt", "e2", "beta")])
    smap = _smap(alpha=("e0", True), beta=("e3", True))
    ctx = _ctx("r1", members, vecs, calls, texts,
               lr.turn_to_pool_index(parsed, texts), lr.move_lengths(parsed, "s1"))
    pairs = [_pair("e0 e1 e2", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r1", ctx)
    assert pairs[0]["scenario_keys"] == ["beta"]


# ---------------------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------------------

def test_r2_routes_on_the_OUT_OF_FOLD_centroid_not_the_in_fold_one(fake_embeddings):
    members, vecs, calls, texts = _oof_world(drop_only_a=True)
    ctx = _ctx("r2", members, vecs, calls, texts)
    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, _OOF_MAP, "r2", ctx)
    assert pairs[0]["scenario_keys"] == ["B"]        # in fold this would be "A"
    assert ctx.diag["in_fold_top1_agreement"] == 0.0


def test_r2_drops_a_scenario_with_no_out_of_fold_evidence_and_REPORTS_it(fake_embeddings):
    members, vecs, calls, texts = _oof_world()
    ctx = _ctx("r2", members, vecs, calls, texts)
    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, _OOF_MAP, "r2", ctx)
    assert pairs[0]["scenario_key"] == "B"           # NOT ONLY_A, which sits at cosine 1.0
    assert ctx.diag["oof_scenarios_total"] == 4
    assert ctx.diag["oof_dropped_slots_per_pair"] == 1.0
    assert ctx.diag["oof_pairs_with_a_drop_share"] == 1.0


def test_r2_short_circuits_when_the_top1_centroid_is_a_SINK(fake_embeddings):
    """A real scenario sits inside the margin, so without the short-circuit this pair would
    be filed to that scenario instead."""
    members, vecs, calls, texts = _world([
        ("b.txt", _at(0.99), "junk"), ("b.txt", _at(0.99), "junk"),
        ("b.txt", _at(0.98), "real"), ("b.txt", _at(0.98), "real")])
    smap = _smap(junk=("e3", False), real=("e3", True))
    ctx = _ctx("r2", members, vecs, calls, texts)
    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r2", ctx)
    assert pairs[0]["scenario_keys"] == ["junk"]
    assert 0.98 >= MARGIN * 0.99                     # the alternative really was in range
    assert ctx.diag["top1_sink_share"] == 1.0


def test_r2_applies_PRODUCTIONS_cap_accounting_in_which_a_sink_consumes_a_slot(
        fake_embeddings):
    """Production takes the top `cap` of ALL scenarios then drops sinks from that slice, so a
    second-placed sink costs a slot; `topk_pick` takes the top `cap` NON-SINKS and would keep
    one more real scenario. The fixture is asserted to distinguish the two rules first."""
    spec, smap_spec = [], {}
    for name, cos, coachable in (("X", 1.00, True), ("SINK", 0.99, False),
                                 ("Y", 0.98, True), ("Z", 0.97, True)):
        spec += [("b.txt", _at(cos), name), ("b.txt", _at(cos), name)]
        smap_spec[name] = ("e3", coachable)
    members, vecs, calls, texts = _world(spec)
    smap = _smap(**smap_spec)
    ctx = _ctx("r2", members, vecs, calls, texts)

    keys, cents = ctx.oof.for_call("a.txt")
    sims = cosine_sims(_resolve("e0")[None, :], cents)[0]
    sink = is_sink_flags(smap, keys)
    prod_rule = flat_pick(sims, keys, sink, CAP, MARGIN)
    other_rule = topk_pick(sims, keys, sink, CAP, MARGIN)
    assert prod_rule != other_rule, "fixture does not distinguish the two rules"

    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r2", ctx)
    assert pairs[0]["scenario_keys"] == prod_rule


def test_r2_refuses_a_call_that_leaves_no_out_of_fold_candidate_at_all(fake_embeddings):
    members, vecs, calls, texts = _world([("a.txt", "e0", "only")])
    smap = _smap(only=("e0", True))
    ctx = _ctx("r2", members, vecs, calls, texts)
    with pytest.raises(ValueError, match="nothing can be routed out of fold"):
        lr.assign_scenarios_router([_pair("e0", "a.txt", 0)], smap, "r2", ctx)


def test_r2_reuses_one_candidate_set_per_call_without_changing_the_answer(fake_embeddings):
    """Pairs are grouped by call for speed; two pairs of the same call must get the same
    candidate set, and a pair of another call a different one."""
    members, vecs, calls, texts = _oof_world()
    ctx = _ctx("r2", members, vecs, calls, texts)
    pairs = [_pair("e0", "a.txt", 0), _pair("e0", "a.txt", 1), _pair("e0", "b.txt", 0)]
    lr.assign_scenarios_router(pairs, _OOF_MAP, "r2", ctx)
    assert pairs[0]["scenario_keys"] == pairs[1]["scenario_keys"] == ["B"]
    # from b.txt, ONLY_A is available (it is evidenced by a.txt) and wins at cosine 1.0
    assert pairs[2]["scenario_keys"][0] == "ONLY_A"


# ---------------------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------------------

def _r3_world():
    members, vecs, calls, texts = _world([
        ("b.txt", _at(0.6), "cent_winner"), ("b.txt", _at(0.6), "cent_winner"),
        ("b.txt", _at(0.5), "desc_winner"), ("b.txt", _at(0.5), "desc_winner"),
        ("b.txt", "e2", "junk"), ("b.txt", "e2", "junk")])
    smap = _smap(cent_winner=("e3", True), desc_winner=("e0", True), junk=("e2", False))
    return members, vecs, calls, texts, smap


def test_r3_with_alpha_1_equals_r2(fake_embeddings):
    """Not a tautology: R2 never builds a description vector, so this compares two separate
    code paths that must agree at the boundary."""
    members, vecs, calls, texts, smap = _r3_world()
    triggers = ["e0", _at(0.3), "e2"]
    r2_pairs = [_pair(t, "a.txt", i) for i, t in enumerate(triggers)]
    r3_pairs = copy.deepcopy(r2_pairs)
    lr.assign_scenarios_router(r2_pairs, smap, "r2", _ctx("r2", members, vecs, calls, texts))
    lr.assign_scenarios_router(r3_pairs, smap, "r3", _ctx("r3", members, vecs, calls, texts),
                               alpha=1.0)
    assert r3_pairs == r2_pairs


def test_r3_with_alpha_0_equals_description_only_routing_over_the_SAME_candidates(
        fake_embeddings):
    from shared.scenario_vectors import build_scenario_vecs

    members, vecs, calls, texts, smap = _r3_world()
    triggers = ["e0", _at(0.3), "e2"]
    pairs = [_pair(t, "a.txt", i) for i, t in enumerate(triggers)]
    ctx = _ctx("r3", members, vecs, calls, texts)
    lr.assign_scenarios_router(pairs, smap, "r3", ctx, alpha=0.0)

    # expected, computed independently: descriptions restricted to the out-of-fold candidates
    dkeys, dvecs = build_scenario_vecs(smap)
    pos = {k: i for i, k in enumerate(dkeys)}
    keys, _ = ctx.oof.for_call("a.txt")
    cols = [pos[k] for k in keys]
    sink = is_sink_flags(smap, keys)
    T = np.asarray([_resolve(t) for t in triggers])
    sims = cosine_sims(T, np.asarray(dvecs))[:, cols]
    for i, p in enumerate(pairs):
        assert p["scenario_keys"] == flat_pick(sims[i], keys, sink, CAP, MARGIN)
    # and description-only genuinely disagrees with the centroid arm here, so the assertion
    # is not comparing two identical answers
    r2_pairs = [_pair(t, "a.txt", i) for i, t in enumerate(triggers)]
    lr.assign_scenarios_router(r2_pairs, smap, "r2", _ctx("r2", members, vecs, calls, texts))
    assert [p["scenario_key"] for p in r2_pairs] != [p["scenario_key"] for p in pairs]


def test_r3_lets_the_description_term_OVERRIDE_the_centroid_argmax(fake_embeddings):
    """0.75*0.6 + 0.25*0.0 = 0.450 for the centroid winner, 0.75*0.5 + 0.25*1.0 = 0.625 for
    the description winner. The blend is live, not decorative."""
    members, vecs, calls, texts, smap = _r3_world()
    pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r3", _ctx("r3", members, vecs, calls, texts))
    assert pairs[0]["scenario_key"] == "desc_winner"

    r2_pairs = [_pair("e0", "a.txt", 0)]
    lr.assign_scenarios_router(r2_pairs, smap, "r2", _ctx("r2", members, vecs, calls, texts))
    assert r2_pairs[0]["scenario_key"] == "cent_winner"


def test_r3_keeps_the_sink_short_circuit(fake_embeddings):
    members, vecs, calls, texts, smap = _r3_world()
    ctx = _ctx("r3", members, vecs, calls, texts)
    pairs = [_pair("e2", "a.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r3", ctx)
    assert pairs[0]["scenario_keys"] == ["junk"]
    assert ctx.diag["blend_alpha"] == lr.BLEND_ALPHA


# ---------------------------------------------------------------------------------------
# diagnostics every arm must carry
# ---------------------------------------------------------------------------------------

def test_every_router_reports_the_top1_sink_share(fake_embeddings):
    members, vecs, calls, texts = _world([("a.txt", "e2", "junk"), ("b.txt", "e2", "junk"),
                                          ("a.txt", "e0", "real"), ("b.txt", "e0", "real")])
    smap = _smap(junk=("e2", False), real=("e0", True))
    tmap = {("a.txt", 0): 0, ("a.txt", 1): 2}
    pairs_spec = [("e2", 0), ("e0", 1)]              # one sink-bound, one not
    for router in lr.ROUTERS:
        ctx = (lr.build_router_context("r0") if router == "r0"
               else _ctx(router, members, vecs, calls, texts, tmap))
        pairs = [_pair(t, "a.txt", i) for t, i in pairs_spec]
        lr.assign_scenarios_router(pairs, smap, router, ctx)
        assert ctx.diag["n_pairs"] == 2
        assert ctx.diag["top1_sink_share"] == pytest.approx(0.5), router


def test_an_empty_pair_list_returns_no_vectors_and_touches_nothing():
    for router in lr.ROUTERS:
        assert lr.assign_scenarios_router([], _smap(a=("e0", True)), router, None) == []


# =======================================================================================
# CROSS-CHECK against calibration/routing_arms.py
#
# Two independent implementations of "route a turn to the nearest scenario centroid" live in
# this repo. A centroid is a mean of member vectors either way, so if they disagree on the
# same input one of them is wrong -- and that has to be settled before any R2 number is read.
#
# *** THEY ARE COMPARABLE, BUT NOT TO THE ARM THE NAME SUGGESTS. *** routing_arms has TWO
# centroid arms and they are different methods:
#
#   arm_centroid         ONE centroid per adjudicated CLUSTER, then MAX-pooled per key. A key
#                        with three merged duplicates routes against three prototypes.
#   arm_centroid_pooled  ONE centroid per KEY, every folded cluster's members averaged
#                        together. Its own docstring calls arm_centroid "quietly a
#                        multi-prototype method".
#
# layer_b_routers builds ONE member set per key (member_sets EXTENDS the target's list), so
# R2 is the POOLED shape. It agrees with arm_centroid only when no key owns more than one
# cluster; where merges exist the second test below shows exactly where they part. Both facts
# are asserted, so neither can be assumed later.
# =======================================================================================

def _arm_ctx(members, vecs, coach_by_key, eval_rows, cluster_keys=None):
    """An ArmContext over the SAME vectors and memberships my RouterContext sees.

    `cluster_keys` lets one key own several clusters, which is what merge_into produces and
    what separates the two routing_arms centroid arms.
    """
    from calibration.routing_arms import ArmContext, key_universe

    cluster_members = list(members.values())
    ckeys = cluster_keys or list(members)
    ccoach = [coach_by_key[k] for k in ckeys]
    keys, coach, owner = key_universe(ckeys, ccoach)
    fit_mask = np.zeros(len(vecs), dtype=bool)
    for m in cluster_members:
        fit_mask[m] = True
    return ArmContext(vecs=vecs.astype(np.float32), eval_idx=np.asarray(eval_rows),
                      fit_mask=fit_mask, cluster_members=cluster_members,
                      cluster_keys=ckeys, cluster_coach=ccoach,
                      desc_vecs=None, desc_have=None, keys=keys, coach=coach, owner=owner)


def _cross_check_world():
    """Three keys, three members each -- routing_arms drops a cluster under
    MIN_TRAIN_MEMBERS=3 -- and every member sits in a call the triggers do not belong to, so
    my out-of-fold exclusion is a no-op and the only thing left to compare is the centroid
    arithmetic. That no-op is itself asserted in the test below rather than assumed.
    """
    member_spec = [
        ("b.txt", "e0", "alpha"), ("b.txt", _at(0.95), "alpha"), ("c.txt", _at(0.90), "alpha"),
        ("b.txt", "e1", "beta"), ("b.txt", _at(0.20), "beta"), ("c.txt", _at(0.10), "beta"),
        ("b.txt", "e2", "junk"), ("b.txt", "e2:0.98 e3:0.199", "junk"),
        ("c.txt", "e2:0.95 e3:0.312", "junk"),
    ]
    triggers = ["e0", "e1", "e2", _at(0.5), "e0:1.0 e2:1.0", _at(0.3), "e1:1.0 e2:0.9"]
    members, mvecs, calls, texts = _world(member_spec)
    tvecs = np.stack([_resolve(t) for t in triggers])
    vecs = np.vstack([mvecs, tvecs])
    calls = calls + ["q.txt"] * len(triggers)       # a call no member belongs to
    eval_rows = list(range(len(mvecs), len(vecs)))
    coach = {"alpha": True, "beta": True, "junk": False}
    return members, vecs, calls, texts, triggers, eval_rows, coach


def test_the_out_of_fold_exclusion_is_a_verified_NO_OP_in_the_cross_check_fixture():
    members, vecs, calls, texts, _t, _e, _c = _cross_check_world()
    oof = lr.OutOfFoldCentroids(members, vecs, calls)
    in_keys, in_cents = oof.in_fold()
    keys, cents = oof.for_call("q.txt")
    assert keys == in_keys and np.allclose(cents, in_cents)


def test_R2_reproduces_routing_arms_arm_centroid_when_no_key_owns_two_clusters(
        fake_embeddings):
    from calibration.routing_arms import arm_centroid, arm_centroid_pooled

    members, vecs, calls, texts, triggers, eval_rows, coach = _cross_check_world()
    smap = _smap(**{k: ("e3", coach[k]) for k in members})

    pairs = [_pair(t, "q.txt", i) for i, t in enumerate(triggers)]
    lr.assign_scenarios_router(pairs, smap, "r2", _ctx("r2", members, vecs, calls, texts))
    mine = [p["scenario_key"] for p in pairs]

    ctx = _arm_ctx(members, vecs, coach, eval_rows)
    assert arm_centroid(ctx).keys == mine
    assert arm_centroid_pooled(ctx).keys == mine
    # the fixture must reach more than one destination, or the agreement is vacuous
    assert len(set(mine)) >= 3, mine


def test_R2_is_the_POOLED_centroid_shape_and_arm_centroid_is_the_multi_prototype_one(
        fake_embeddings):
    """With two clusters folded into one key the two routing_arms arms disagree, and R2
    follows the pooled one. This is the contract difference, pinned."""
    from calibration.routing_arms import arm_centroid, arm_centroid_pooled

    # alpha owns TWO clusters, one near e0 and one near e1. Pooled they average to ~cos 0.707
    # from e0; max-pooling the two prototypes keeps alpha at ~1.0. gamma sits between.
    spec = [("b.txt", "e0", "alpha_a"), ("b.txt", _at(0.99), "alpha_a"),
            ("c.txt", _at(0.98), "alpha_a"),
            ("b.txt", "e1", "alpha_b"), ("b.txt", _at(0.01), "alpha_b"),
            ("c.txt", _at(0.02), "alpha_b"),
            ("b.txt", _at(0.85), "gamma"), ("b.txt", _at(0.85), "gamma"),
            ("c.txt", _at(0.85), "gamma")]
    clusters, mvecs, calls, texts = _world(spec)
    vecs = np.vstack([mvecs, _resolve("e0")[None, :]])
    calls = calls + ["q.txt"]

    arm = _arm_ctx(clusters, vecs, {"alpha": True, "gamma": True},
                   [len(mvecs)], cluster_keys=["alpha", "alpha", "gamma"])
    per_cluster = arm_centroid(arm).keys[0]
    pooled = arm_centroid_pooled(arm).keys[0]
    assert per_cluster == "alpha" and pooled == "gamma", (per_cluster, pooled)

    # mine: member_sets folds the merged cluster's INDICES into the target -> one member set
    members = {"alpha": clusters["alpha_a"] + clusters["alpha_b"], "gamma": clusters["gamma"]}
    smap = _smap(alpha=("e3", True), gamma=("e3", True))
    pairs = [_pair("e0", "q.txt", 0)]
    lr.assign_scenarios_router(pairs, smap, "r2", _ctx("r2", members, vecs, calls, texts))
    assert pairs[0]["scenario_key"] == pooled


def test_member_sets_and_routing_arms_key_universe_DIVERGE_on_a_reused_key_string():
    """The one place the two contracts cannot be reconciled, recorded as a test.

    Gemma reuses one scenario_key string across unrelated clusters (up to 26 in a run).
    member_sets SUFFIXES them, matching scenario_map_from_rows, so each cluster keeps its own
    evidence. routing_arms.key_universe COLLAPSES equal strings into one key and raises
    outright when the same string is both coachable and a sink. Neither is wrong for its own
    harness -- but member sets are NOT interchangeable between the two files.
    """
    from calibration.routing_arms import key_universe

    rows = [_row("c1", "scenario", "dup"), _row("c2", "mechanics", "dup")]
    members, _ = lr.member_sets(rows, [_cluster("c1", [0]), _cluster("c2", [1])])
    assert set(members) == {"dup", "dup_1"}          # two independent member sets

    with pytest.raises(ValueError, match="both coachable and sink"):
        key_universe(["dup", "dup"], [True, False])
    # and even when coachability agrees it returns ONE key where member_sets returns two
    keys, _coach, owner = key_universe(["dup", "dup"], [True, True])
    assert keys == ["dup"] and list(owner) == [0, 0]
