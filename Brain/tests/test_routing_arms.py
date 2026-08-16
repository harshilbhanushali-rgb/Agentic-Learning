"""Tests for calibration/routing_arms.py -- the pluggable turn->scenario routers.

Hand-built orthogonal unit vectors throughout, deliberately: these test the ROUTING RULE, not
the embedding model. Same reasoning as tests/test_layer_b_assignment.py, which is why a
threshold or a model swap cannot silently turn these green.
"""
from __future__ import annotations

import numpy as np
import pytest

from calibration import routing_arms as ra


# -- fixtures ----------------------------------------------------------------------------

def _adj(kind, key, merge_into=None):
    return {"kind": kind, "scenario_key": key, "merge_into_key": merge_into}


ADJ = [
    _adj("scenario", "sc_a"),
    _adj("scenario", "sc_b"),
    _adj("mechanics", "sink_m"),
    _adj("merged", "dup_of_a", merge_into="sc_a"),      # RETAINED, folds into sc_a
    _adj("merged", "orphan", merge_into="never_kept"),  # target is not a kept scenario
    _adj("logistics", "sink_l"),
]


def _ctx(dim=8, per=6, eval_all=True, fit_all=True, seed=0):
    """4 point-bearing clusters on distinct axes + 2 more, plus unaffiliated stray turns."""
    rng = np.random.default_rng(seed)
    axes = [0, 1, 2, 0, 3, 4]                       # cluster 3 shares sc_a's axis, as a dup
    vecs, members = [], []
    for c, ax in enumerate(axes):
        idx = []
        for _ in range(per):
            v = np.zeros(dim, dtype=np.float32)
            v[ax] = 1.0
            v += rng.normal(0, 0.05, dim).astype(np.float32)
            vecs.append(v / np.linalg.norm(v))
            idx.append(len(vecs) - 1)
        members.append(idx)
    for _ in range(5):                              # strays: in no cluster
        v = rng.normal(0, 1, dim).astype(np.float32)
        vecs.append(v / np.linalg.norm(v))
    vecs = np.stack(vecs).astype(np.float32)

    cl_keys, cl_coach, _ = ra.cluster_labels(ADJ)
    keys, coach, owner = ra.key_universe(cl_keys, cl_coach)
    n = len(vecs)
    return ra.ArmContext(
        vecs=vecs, eval_idx=np.arange(n) if eval_all else np.arange(n)[::2],
        fit_mask=np.ones(n, bool) if fit_all else np.arange(n) % 2 == 1,
        cluster_members=members, cluster_keys=cl_keys, cluster_coach=cl_coach,
        desc_vecs=None, desc_have=None, keys=keys, coach=coach, owner=owner)


# -- labelling ---------------------------------------------------------------------------

def test_merged_means_retained_not_discarded():
    """The four-valued `kind` collapsed to a boolean is what produced the phantom
    'Gemma over-sinks 14.6%' finding, twice. A `merged` row folds into its target."""
    keys, coach, stats = ra.cluster_labels(ADJ)
    assert keys[3] == "sc_a" and coach[3] is True
    assert stats["merged_folded"] == 1
    assert stats["scenario"] == 2


def test_orphaned_merge_becomes_a_sink_and_is_counted():
    keys, coach, stats = ra.cluster_labels(ADJ)
    assert keys[4] == "orphan" and coach[4] is False
    assert stats["merged_orphaned"] == 1


def test_key_universe_dedups_and_maps_owners():
    keys, coach, owner = ra.key_universe(*ra.cluster_labels(ADJ)[:2])
    assert len(keys) == 5                       # sc_a, sc_b, sink_m, orphan, sink_l
    assert owner[0] == owner[3]                 # the dup shares sc_a's key index
    assert coach[keys.index("sc_a")] and not coach[keys.index("sink_m")]


def test_key_universe_rejects_a_key_that_is_both_coachable_and_sink():
    with pytest.raises(ValueError, match="both coachable and sink"):
        ra.key_universe(["k", "k"], [True, False])


# -- pooling primitives ------------------------------------------------------------------

def test_pool_max_matches_brute_force():
    rng = np.random.default_rng(1)
    t = rng.normal(size=(7, 5)).astype(np.float32)
    p = rng.normal(size=(11, 5)).astype(np.float32)
    pk = np.array([0, 0, 1, 1, 1, 2, 2, 0, 2, 1, 0], dtype=np.int32)
    got = ra._pool_max(t, p, pk, 3)
    want = np.stack([(t @ p[pk == k].T).max(axis=1) for k in range(3)], axis=1)
    assert np.allclose(got, want, atol=1e-6)


def test_pool_max_leaves_a_key_with_no_points_at_negative_infinity():
    t = np.eye(3, dtype=np.float32)
    p = np.eye(3, dtype=np.float32)[:1]
    got = ra._pool_max(t, p, np.array([0], np.int32), 3)
    assert np.isneginf(got[:, 1]).all() and np.isneginf(got[:, 2]).all()


def test_pool_topk_mean_averages_all_points_when_k_exceeds_the_count():
    """A key with fewer than k points must not be penalised for being small -- otherwise
    this arm is a cluster-size filter wearing a similarity costume."""
    rng = np.random.default_rng(2)
    t = rng.normal(size=(4, 6)).astype(np.float32)
    p = rng.normal(size=(3, 6)).astype(np.float32)
    pk = np.zeros(3, dtype=np.int32)
    got = ra._pool_topk_mean(t, p, pk, 1, k=10)
    assert np.allclose(got[:, 0], (t @ p.T).mean(axis=1), atol=1e-6)


def test_pool_topk_mean_takes_the_k_best_not_all():
    t = np.array([[1.0, 0.0]], dtype=np.float32)
    p = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, -1.0]], dtype=np.float32)
    pk = np.zeros(3, dtype=np.int32)
    top1 = ra._pool_topk_mean(t, p, pk, 1, k=1)[0, 0]
    allm = ra._pool_topk_mean(t, p, pk, 1, k=3)[0, 0]
    assert top1 == pytest.approx(1.0) and allm == pytest.approx(1.0 / 3)


def test_routing_from_scores_picks_argmax_and_reports_the_runner_up_margin():
    scores = np.array([[0.1, 0.9, 0.4], [0.7, 0.2, 0.71]], dtype=np.float32)
    r = ra.routing_from_scores(scores, ["a", "b", "c"], np.array([True, False, True]), 3)
    assert r.keys == ["b", "c"]
    assert list(r.accepted) == [False, True]
    assert r.margin[0] == pytest.approx(0.5, abs=1e-6)
    assert r.margin[1] == pytest.approx(0.01, abs=1e-6)


# -- arms --------------------------------------------------------------------------------

def test_centroid_routes_a_turn_to_the_cluster_on_its_own_axis():
    ctx = _ctx()
    r = ra.arm_centroid(ctx)
    for i in ctx.cluster_members[1]:                       # sc_b's axis
        assert r.keys[i] == "sc_b"
    for i in ctx.cluster_members[2]:                       # a sink cluster
        assert r.keys[i] == "sink_m" and not r.accepted[i]


def test_rejection_happens_only_because_a_sink_key_wins():
    """Not a threshold. Removing sink points would abolish the pipeline's only junk filter,
    which is pre-registered failure condition F4."""
    ctx = _ctx()
    r = ra.arm_centroid(ctx)
    assert not r.accepted.all() and r.accepted.any()
    for i in range(len(r.keys)):
        assert r.accepted[i] == (r.keys[i] in ("sc_a", "sc_b"))


def test_knn_max_is_self_inflating_when_fit_and_eval_overlap():
    """Every member is its own nearest neighbour at cosine 1.0, so the arm reproduces
    membership exactly while having learned nothing. This is why the harness marks the
    full-corpus column and reads the held-out one."""
    ctx = _ctx()
    r = ra.arm_knn_max(ctx)
    for c, mem in enumerate(ctx.cluster_members):
        for i in mem:
            assert r.keys[i] == ctx.keys[ctx.owner[c]]
    assert np.allclose(r.best_sim[[i for m in ctx.cluster_members for i in m]], 1.0, atol=1e-5)


def test_a_cluster_below_the_train_floor_contributes_no_points():
    ctx = _ctx(per=2, fit_all=False)                       # ~1 fittable member per cluster
    assert all(not m for m in ctx.fit_members())
    with pytest.raises(ValueError, match="no cluster retained enough"):
        ra.arm_centroid(ctx)


def test_medoid_uses_a_real_member_turn_not_an_average():
    ctx = _ctx()
    pv, _ = ra._key_points_from_members(ctx, lambda m: [m[int(np.argmax(m @ ra._unit(m.mean(0))))]])
    sims = pv @ ctx.vecs.T
    assert (sims.max(axis=1) > 0.999).all()                # each point IS one of the turns


def test_placebo_preserves_group_count_size_and_coachability_but_not_content():
    """The placebo must differ from `centroid` in exactly one respect: which turn sits in
    which group. If it also changed the number or size of groups it would be testing that
    instead."""
    ctx = _ctx()
    real, plac = ra.arm_centroid(ctx), ra.arm_placebo_centroid(ctx)
    assert real.n_points == plac.n_points
    assert set(plac.keys) <= set(ctx.keys)
    assert real.keys != plac.keys                          # content genuinely randomised


def test_placebo_is_deterministic_under_the_seed():
    assert ra.arm_placebo_centroid(_ctx(seed=3)).keys == ra.arm_placebo_centroid(_ctx(seed=3)).keys


def _with_desc(ctx):
    ctx.desc_vecs = np.zeros((len(ctx.keys), ctx.vecs.shape[1]), dtype=np.float32)
    ctx.desc_have = np.ones(len(ctx.keys), dtype=bool)
    for j in range(len(ctx.keys)):                         # descriptions on a far-off axis
        ctx.desc_vecs[j, 5 + (j % 3)] = 1.0
    return ctx


def test_blend_reduces_to_centroid_POOLED_not_to_centroid():
    """`blend` averages a key's members into ONE vector; `arm_centroid` keeps one centroid per
    CLUSTER and max-pools. So blend's alpha=1 endpoint is `centroid_pooled`, NOT `centroid`.

    An earlier version of this test asserted `blend(1.0) == centroid` and PASSED -- but only
    because this fixture's two sc_a clusters sit on the same axis, so pooling them changed no
    decision. That made a two-variable comparison (add the description AND pool the merges)
    look like a one-variable one. Asserted on point COUNT, which the fixture cannot mask.
    """
    ctx = _with_desc(_ctx())
    assert ra.make_blend(1.0)(ctx).keys == ra.arm_centroid_pooled(ctx).keys
    assert ra.make_blend(0.0)(ctx).keys == ra.arm_description(ctx).keys
    assert ra.arm_centroid(ctx).n_points > ra.arm_centroid_pooled(ctx).n_points


def test_centroid_pooled_emits_exactly_one_point_per_populated_key():
    ctx = _ctx()
    pooled = ra.arm_centroid_pooled(ctx)
    assert pooled.n_points == len({int(o) for c, o in enumerate(ctx.owner)
                                   if ctx.fit_members()[c]})
    assert ra.arm_centroid(ctx).n_points == sum(1 for m in ctx.fit_members() if m)


def test_text_arm_max_pools_several_vectors_per_key():
    """Synthetic utterances must be scored against the CLOSEST one, never their average --
    averaging k utterances drifts back toward the generic prose this arm exists to escape."""
    ctx = _ctx()
    far = np.zeros(ctx.vecs.shape[1], dtype=np.float32); far[7] = 1.0
    near = ctx.vecs[ctx.cluster_members[1][0]]
    arm = ra.make_text_arm({"sc_b": np.stack([far, near]), "sc_a": far[None, :]}, "t")
    r = arm(ctx)
    assert r.keys[ctx.cluster_members[1][0]] == "sc_b"
    assert r.best_sim[ctx.cluster_members[1][0]] == pytest.approx(1.0, abs=1e-5)


def test_abstain_only_ever_removes_acceptances():
    ctx = _ctx()
    r = ra.arm_centroid(ctx)
    kept = ra.abstain(r, 0.5)
    assert kept.sum() <= r.accepted.sum()
    assert not (kept & ~r.accepted).any()


def test_every_registered_arm_returns_one_decision_per_evaluated_turn():
    ctx = _with_desc(_ctx())
    for name, fn in ra.FREE_ARMS.items():
        r = fn(ctx)
        assert len(r.keys) == len(ctx.eval_idx), name
        assert r.accepted.shape == (len(ctx.eval_idx),), name
        assert r.margin.shape == (len(ctx.eval_idx),), name


# -- rerank arms -------------------------------------------------------------------------

def _ctx_with_text():
    ctx = _ctx()
    ctx.texts = [f"turn{i}" for i in range(len(ctx.vecs))]
    return ctx


def test_topk_candidates_are_returned_best_first():
    s = np.array([[0.1, 0.9, 0.4, 0.7]], dtype=np.float32)
    assert list(ra._topk_candidates(s, 3)[0]) == [1, 3, 2]


def test_topk_handles_k_larger_than_the_key_count():
    s = np.array([[0.2, 0.5]], dtype=np.float32)
    assert len(ra._topk_candidates(s, 9)[0]) == 2


def test_representative_members_are_real_turns_and_deterministic():
    ctx = _ctx_with_text()
    acc = ra.pooled_key_members(ctx)
    a = ra.representative_members(ctx, acc, 3)
    b = ra.representative_members(ctx, acc, 3)
    assert a == b
    for k, mem in a.items():
        assert len(mem) <= 3
        assert set(mem) <= set(acc[k])


def test_rerank_can_override_the_proposer():
    """If re-ranking could not change the answer it would be untestable by construction."""
    ctx = _ctx_with_text()
    base = ra.arm_centroid_pooled(ctx)
    # a scorer that prefers whichever member text sorts last -> deliberately not the centroid
    arm = ra.make_rerank_arm(lambda prs: [float(hash(b) % 1000) for _, b in prs], k=4)
    assert arm(ctx).keys != base.keys


def test_rerank_only_ever_picks_from_the_proposed_shortlist():
    ctx = _ctx_with_text()
    base, acc = ra.pooled_centroid_scores(ctx)
    cand = ra._topk_candidates(base, 3)
    out = ra.make_rerank_arm(lambda prs: np.zeros(len(prs)), k=3)(ctx)
    for r, key in enumerate(out.keys):
        assert ctx.keys.index(key) in set(cand[r].tolist())


def test_rerank_keeps_sinks_as_candidates_so_rejection_survives():
    """Spec F4/F9: dropping sinks from the shortlist would abolish the junk filter."""
    ctx = _ctx_with_text()
    out = ra.make_rerank_arm(lambda prs: np.random.default_rng(0).normal(size=len(prs)),
                             k=len(ctx.keys))(ctx)
    assert not out.accepted.all(), "no turn was ever rejected -- sinks left the shortlist"


def test_rerank_rejects_a_scorer_that_returns_the_wrong_number_of_scores():
    ctx = _ctx_with_text()
    with pytest.raises(ValueError, match="returned .* scores for"):
        ra.make_rerank_arm(lambda prs: [0.0])(ctx)


def test_rerank_needs_texts():
    with pytest.raises(ValueError, match="need ctx.texts"):
        ra.make_rerank_arm(lambda prs: np.zeros(len(prs)))(_ctx())


def test_random_rerank_placebo_is_seeded_and_stays_inside_the_shortlist():
    a, b = _ctx_with_text(), _ctx_with_text()
    assert ra.make_random_rerank_arm(3)(a).keys == ra.make_random_rerank_arm(3)(b).keys
    ctx = _ctx_with_text()
    base, _ = ra.pooled_centroid_scores(ctx)
    cand = ra._topk_candidates(base, 3)
    out = ra.make_random_rerank_arm(3)(ctx)
    for r, key in enumerate(out.keys):
        assert ctx.keys.index(key) in set(cand[r].tolist())


def test_centroid_pooled_still_matches_its_extracted_scorer():
    ctx = _ctx()
    scores, acc = ra.pooled_centroid_scores(ctx)
    assert ra.arm_centroid_pooled(ctx).keys == [ctx.keys[i] for i in scores.argmax(axis=1)]


def test_split_arm_takes_accept_from_members_and_destination_from_prose():
    ctx = _with_desc(_ctx())
    split = ra.arm_split_member_accept_desc_dest(ctx)
    pooled = ra.arm_centroid_pooled(ctx)
    desc = ra.arm_description(ctx)
    # the accept/reject decision must equal the member arm's, turn for turn
    assert list(split.accepted) == list(pooled.accepted)
    # every accepted turn's destination must be a COACHABLE key
    for i, k in enumerate(split.keys):
        if split.accepted[i]:
            assert ctx.coach[ctx.keys.index(k)]
    # and it must differ from both parents somewhere, or it is not a new arm
    assert split.keys != pooled.keys or split.keys != desc.keys


def test_split_arm_rejects_to_the_member_arms_sink():
    ctx = _with_desc(_ctx())
    split = ra.arm_split_member_accept_desc_dest(ctx)
    pooled = ra.arm_centroid_pooled(ctx)
    for i in range(len(split.keys)):
        if not split.accepted[i]:
            assert split.keys[i] == pooled.keys[i]
