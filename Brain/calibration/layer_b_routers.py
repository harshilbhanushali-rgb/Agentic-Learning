#!/usr/bin/env python3
"""Layer B ROUTING variants: R1 membership lookup, R2 out-of-fold centroid, R3 blend.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md sections 3.1-3.3

Third module of the trial, and the split is deliberate: `layer_b_arms.py` holds the METRIC,
`layer_b_variants.py` holds pair EXTRACTION, this holds ROUTING. Three concerns, three files,
each audited independently. A change to how a trigger picks its scenario must not be able to
touch how the result is scored.

*** WHAT R1 IS, AND WHY THE WITHDRAWN BENCH DOES NOT FORBID IT. *** CLAUDE.md records a 16-arm
routing bench in which membership-style routing beat description routing 12-1 -- and records
that ranking as WITHDRAWN, because the gate was the centroid arms' own objective function. That
bench asked whether a centroid can PREDICT the cluster of an unseen turn. R1 predicts nothing:
Layer A already assigned a label to that exact turn and R1 reads it. No cosine, no threshold,
no parameter. It is the only option in this trial where Layer A's unit (a client turn) and
Layer B's unit are the same object, which is the entire reason the rescue's +62% became +0.8%.

R2 IS a prediction and inherits that bench's caveat, which is why it is computed OUT OF FOLD.

WHAT THIS COSTS: nothing. `build_clusters` re-derives memberships from the gemini cache with a
hard abort on a miss, and the vectors are the same ones the adjudication arm used.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROUTERS = ("r0", "r1", "r2", "r3", "r1p", "r2p", "r3p")
BLEND_ALPHA = 0.75      # `blend_a0.75`, the withdrawn bench's top scorer. Not re-tuned here.
PLACEBO_SEED = 20260817
# `<router>p` is that router's PERMUTATION PLACEBO -- see `_route_permutation_placebo`.
_PLACEBO_OF = {"r1p": "r1", "r2p": "r2", "r3p": "r3"}


# ---------------------------------------------------------------------------------------
# member sets -- the four-valued enum that has produced two phantom findings
# ---------------------------------------------------------------------------------------

def member_sets(rows: list[dict], clusters: list[dict]) -> tuple[dict[str, list[int]], dict]:
    """scenario_key -> pool indices of every turn that cluster owns.

    *** `merged` MEANS RETAINED, NOT DISCARDED, AND COLLAPSING THAT IS THE BUG THIS REPO HAS
    HIT TWICE. *** `kind` is four-valued:

        scenario / mechanics / logistics  -> owns its own key
        merged                            -> RETAINED, folded INTO another scenario, so its
                                             turns belong to that scenario's member set
        failed                            -> a transport failure, excluded entirely

    Testing `kind == "scenario"` and treating everything else as discarded produced the phantom
    "Gemma over-sinks 14.6% of the corpus" finding, and again a broken positive control in
    `null_test_taxonomy`. 69 merged clusters carried 2,434 turns in one measured run. Dropping
    them here would silently shrink every centroid and every lookup population.

    KEY COLLISIONS ARE SUFFIXED THE SAME WAY `layer_bc_arms.scenario_map_from_rows` SUFFIXES
    THEM, and it must stay that way or the member sets and the scenario map would disagree
    about which key is which. Gemma independently invents `conversational_acknowledgment` for
    up to 26 different sink clusters in one run, so collisions are routine, not exotic.

    A `merge_into_key` resolves to the FIRST (unsuffixed) scenario carrying that key, because
    that is the key Gemma saw in its accepted-scenarios list at the time it chose to merge.
    An unresolvable target is REPORTED, never silently dropped -- those turns would otherwise
    vanish from every router's population while still counting in the taxonomy.

    Returns (key -> idxs, diagnostics).
    """
    by_cid = {c["cluster_id"]: c for c in clusters}
    out: dict[str, list[int]] = {}
    first_with_base: dict[str, str] = {}
    pending: list[tuple[str, str]] = []          # (merge_into_key, cluster_id)
    diag = {"scenarios": 0, "sinks": 0, "merged_folded": 0, "merged_unresolved": [],
            "missing_cluster": [], "failed": 0}

    for i, r in enumerate(rows):
        kind, cid = r.get("kind"), r.get("cluster_id")
        if r.get("failed") or kind in (None, "failed"):
            diag["failed"] += 1
            continue
        if cid not in by_cid:
            diag["missing_cluster"].append(cid)
            continue
        if kind == "merged":
            pending.append((r.get("merge_into_key") or "", cid))
            continue
        if kind not in ("scenario", "mechanics", "logistics"):
            raise ValueError(f"unknown adjudication kind {kind!r} on row {i}")
        base = r["scenario_key"] or f"cluster_{i}"
        key, n = base, 1
        while key in out:
            key = f"{base}_{n}"
            n += 1
        out[key] = list(by_cid[cid]["idxs"])
        first_with_base.setdefault(base, key)
        diag["scenarios" if kind == "scenario" else "sinks"] += 1

    for target, cid in pending:
        key = first_with_base.get(target)
        if key is None:
            diag["merged_unresolved"].append((target, cid))
            continue
        out[key].extend(by_cid[cid]["idxs"])
        diag["merged_folded"] += 1

    return out, diag


# ---------------------------------------------------------------------------------------
# the positional join -- pool index <-> client turn
# ---------------------------------------------------------------------------------------

def turn_to_pool_index(parsed, pool_texts: list[str]) -> dict[tuple[str, int], int]:
    """(call_filename, turn.index) -> index into Layer A's turn pool. VERIFIED, not assumed.

    `v2/layer_a.build_client_pool(turns, unit="turn")` emits CLIENT turns in file order, so the
    i-th pool item is the i-th CLIENT turn across sorted transcripts. That is an ordering
    assumption, and this repo's precedent for such a join is to verify it member-for-member --
    `flag_proper_noun_clusters` checks 245/245 positions before trusting one.

    Raises on the first mismatch rather than returning a partial map. A silently misaligned
    join would route every trigger to the wrong cluster while producing perfectly plausible
    numbers, which is the worst failure mode available here.
    """
    from preprocessing.transcript_parser import SpeakerRole

    out: dict[tuple[str, int], int] = {}
    i = 0
    for _, path, turns in parsed:
        for t in turns:
            if t.role != SpeakerRole.CLIENT:
                continue
            if i >= len(pool_texts):
                raise ValueError(
                    f"pool exhausted at {path.name}:{t.index} -- the corpus has more CLIENT "
                    f"turns ({i + 1}+) than the pool has items ({len(pool_texts)}). The pool "
                    f"was built from a different corpus.")
            if pool_texts[i] != t.text:
                raise ValueError(
                    f"POSITIONAL JOIN BROKEN at pool[{i}] / {path.name}:{t.index}.\n"
                    f"  pool: {pool_texts[i][:90]!r}\n  turn: {t.text[:90]!r}\n"
                    f"Routing on this map would send every trigger to the wrong cluster while "
                    f"producing plausible numbers.")
            out[(path.name, t.index)] = i
            i += 1
    if i != len(pool_texts):
        raise ValueError(f"pool has {len(pool_texts)} items but the corpus yielded {i} CLIENT "
                         f"turns -- the two were built from different corpora.")
    return out


def pair_pool_indices(pair: dict, turn_index_map: dict[tuple[str, int], int],
                      n_turns_in_move: int = 1) -> list[int]:
    """The pool indices a pair's trigger covers.

    Under `s0` a trigger is one client turn, so one index. Under `s1` a MOVE spans a run of
    adjacent client turns whose pool indices are CONSECUTIVE by construction -- the pool is
    client turns in order, and a move is adjacent client turns -- so the run is
    `[i, i + n_turns_in_move)`. That is why `s1` needs no separate index bookkeeping.
    """
    start = turn_index_map.get((pair["call_filename"], pair["turn_index"]))
    if start is None:
        return []
    return list(range(start, start + max(1, n_turns_in_move)))


# ---------------------------------------------------------------------------------------
# R1 -- lookup
# ---------------------------------------------------------------------------------------

def build_lookup(members: dict[str, list[int]]) -> dict[int, str]:
    """pool index -> scenario key. The whole of R1's mechanism.

    A pool index can appear in only one cluster (HDBSCAN assigns one label, and merges fold
    disjoint clusters), so a collision means the member sets were built wrong -- most likely a
    `merge_into` folded into two targets. Raise rather than let last-write-wins decide routing.
    """
    out: dict[int, str] = {}
    for key, idxs in members.items():
        for i in idxs:
            if i in out and out[i] != key:
                raise ValueError(
                    f"pool index {i} claimed by both {out[i]!r} and {key!r} -- member sets "
                    f"overlap, so a lookup would be decided by dict order")
            out[i] = key
    return out


def r1_pick(idxs: list[int], lookup: dict[int, str], texts: list[str]) -> str | None:
    """The scenario a trigger's own Layer A label points to, or None to fall back to R0.

    MAJORITY VOTE over a move's turns, because an `s1` move can span turns HDBSCAN placed in
    different clusters. Ties break toward the turn with the most alphabetic-ish content -- the
    longest text -- rather than by dict order, so the rule is deterministic and does not depend
    on which cluster happened to be built first.

    None means every turn was HDBSCAN NOISE. ~47% of the pool is noise, so this is the common
    case, not an edge case: R1 is a HYBRID and the caller MUST report the lookup/fallback split
    or a result that is really R0's gets credited to membership.
    """
    votes = [lookup[i] for i in idxs if i in lookup]
    if not votes:
        return None
    counts = Counter(votes)
    top = max(counts.values())
    tied = [k for k, v in counts.items() if v == top]
    if len(tied) == 1:
        return tied[0]
    best, best_len = None, -1
    for i in idxs:
        k = lookup.get(i)
        if k in tied and len(texts[i]) > best_len:
            best, best_len = k, len(texts[i])
    return best


# ---------------------------------------------------------------------------------------
# R2 -- out-of-fold centroids
# ---------------------------------------------------------------------------------------

def call_of_pool_index(parsed, pool_texts: list[str]) -> list[str]:
    """pool index -> call filename, in pool order. Needed for the out-of-fold exclusion."""
    from preprocessing.transcript_parser import SpeakerRole

    out: list[str] = []
    for _, path, turns in parsed:
        out.extend(path.name for t in turns if t.role == SpeakerRole.CLIENT)
    if len(out) != len(pool_texts):
        raise ValueError(f"{len(out)} call labels for {len(pool_texts)} pool items")
    return out


class OutOfFoldCentroids:
    """Scenario centroids with the querying trigger's OWN CALL removed.

    *** WITHOUT THIS, R2 REPRODUCES MEMBERSHIP HAVING LEARNED NOTHING. *** Triggers ARE client
    turns from the pool Layer A clustered, so an in-fold centroid is the mean of a set that
    contains the trigger itself. `routing_bench` marks `knn_max` / `medoid` / `probe` with a
    `*` for exactly this and calls their full-corpus column uninterpretable.

    Held as per-(scenario, call) partial sums so the exclusion is EXACT and O(1) per trigger
    rather than a re-mean over thousands of vectors. `in_fold` is computed too, as a
    diagnostic, so the size of the inflation is visible rather than assumed.

    A scenario whose ONLY evidence is the querying call is dropped from that trigger's
    candidate set -- it cannot be routed to without leaking. How often that fires is counted.
    """

    def __init__(self, members: dict[str, list[int]], vecs: np.ndarray, calls: list[str]):
        self.keys = sorted(members)
        self.dim = vecs.shape[1]
        self._total = np.zeros((len(self.keys), self.dim), dtype=np.float64)
        self._n = np.zeros(len(self.keys), dtype=np.int64)
        self._by_call: list[dict[str, tuple[np.ndarray, int]]] = []
        for ki, key in enumerate(self.keys):
            idxs = members[key]
            acc: dict[str, list[int]] = defaultdict(list)
            for i in idxs:
                acc[calls[i]].append(i)
            per_call = {}
            for call, ii in acc.items():
                s = vecs[ii].sum(axis=0).astype(np.float64)
                per_call[call] = (s, len(ii))
                self._total[ki] += s
                self._n[ki] += len(ii)
            self._by_call.append(per_call)
        self.dropped_no_out_of_fold = 0

    def _normalise(self, mat: np.ndarray) -> np.ndarray:
        return mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10)

    def in_fold(self) -> tuple[list[str], np.ndarray]:
        keep = self._n > 0
        return ([k for k, ok in zip(self.keys, keep) if ok],
                self._normalise(self._total[keep] / self._n[keep, None]))

    def for_call(self, call: str) -> tuple[list[str], np.ndarray]:
        """(keys, unit centroids) with every turn from `call` removed."""
        tot = self._total.copy()
        n = self._n.copy()
        for ki, per_call in enumerate(self._by_call):
            hit = per_call.get(call)
            if hit is not None:
                tot[ki] -= hit[0]
                n[ki] -= hit[1]
        keep = n > 0
        self.dropped_no_out_of_fold += int((~keep).sum())
        return ([k for k, ok in zip(self.keys, keep) if ok],
                self._normalise(tot[keep] / n[keep, None]))


# ---------------------------------------------------------------------------------------
# the context -- built ONCE, so no router can quietly rebuild a join on its own terms
# ---------------------------------------------------------------------------------------

@dataclass
class RouterContext:
    """Everything R1/R2/R3 need, assembled and VERIFIED in one place.

    One object rather than five loose arguments because every one of these is derived from
    the same two things -- the taxonomy's rows and the corpus's parse -- and a router that
    rebuilt any of them on its own terms could be joining against a different corpus while
    still returning plausible numbers. Assembling once means the position check
    (`turn_to_pool_index`) and the key-agreement check run exactly once, before any routing.

    `diag` is the channel for everything §3.1-3.3 requires reported. It is a dict on the
    context, NOT a second return value, because `assign_scenarios_router` must match
    `v1.layer_b.assign_scenarios`'s contract exactly -- one return, the trigger vectors.
    """
    router: str
    diag: dict = field(default_factory=dict)
    members: dict[str, list[int]] | None = None
    lookup: dict[int, str] | None = None
    texts: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    turn_index_map: dict[tuple[str, int], int] = field(default_factory=dict)
    move_len: dict[tuple[str, int], int] = field(default_factory=dict)
    oof: OutOfFoldCentroids | None = None


def move_lengths(parsed, segment: str) -> dict[tuple[str, int], int]:
    """(call, FIRST turn index) -> how many CLIENT turns that trigger MOVE spans.

    Empty for `s0`, where a trigger is one turn and `pair_pool_indices`' default of 1 is
    already right. For `s1` this reproduces `layer_b_variants.client_move`'s rule exactly --
    a MAXIMAL RUN OF ADJACENT CLIENT TURNS, ended by any other role including
    `UNATTRIBUTED` -- because the extractor and the router must agree about what ONE trigger
    is. If they disagreed, an `s1` move would be looked up against the pool indices of a
    different span and R1 would read a label belonging to a turn the trigger does not
    contain.
    """
    from preprocessing.transcript_parser import SpeakerRole

    out: dict[tuple[str, int], int] = {}
    if segment == "s0":
        return out
    if segment != "s1":
        raise ValueError(f"unknown segment setting {segment!r}")
    for _, path, turns in parsed:
        i = 0
        while i < len(turns):
            if turns[i].role != SpeakerRole.CLIENT:
                i += 1
                continue
            j = i
            while j < len(turns) and turns[j].role == SpeakerRole.CLIENT:
                j += 1
            out[(path.name, turns[i].index)] = j - i
            i = j
    return out


def router_context_from_clusters(router: str, rows: list[dict], clusters: list[dict],
                                 parsed, texts: list[str], vecs: np.ndarray,
                                 scenario_map: dict[str, dict],
                                 segment: str = "s0") -> RouterContext:
    """The pure half of the context build: no clustering, no I/O, fully testable.

    *** THE KEY-ALIGNMENT GUARD IS THE ONE THAT MATTERS, AND IT IS NOT THE OBVIOUS ONE. ***
    `member_sets` and `layer_bc_arms.scenario_map_from_rows` each run their OWN suffix loop
    over the same rows, and they agree only because they skip the same rows in the same
    order. `member_sets` skips one extra class -- a row whose `cluster_id` is absent from
    `clusters` -- and that single extra skip SHIFTS EVERY LATER SUFFIX. Two rows both named
    `conversational_acknowledgment` would then have the map calling row 0 `...` and row 1
    `..._1` while the member sets call row 1 `...`: a silent misalignment in which every key
    still exists on both sides, so a set-difference check passes and the routing is wrong.
    Gemma reuses one key for up to 26 sink clusters in a run, so this is a live shape, not a
    hypothetical. Hence the hard raise on `missing_cluster` -- it is the ONLY divergence
    between the two loops -- with the set-difference kept as a second, weaker net.
    """
    if router not in ROUTERS:
        raise ValueError(f"unknown router {router!r}; expected one of {ROUTERS}")
    if router == "r0":
        raise ValueError("r0 needs no context -- it delegates to production verbatim")

    members, mdiag = member_sets(rows, clusters)
    if mdiag["missing_cluster"]:
        raise ValueError(
            f"{len(mdiag['missing_cluster'])} adjudication row(s) name a cluster_id that is "
            f"not in this clustering, e.g. {mdiag['missing_cluster'][:3]!r}. member_sets "
            f"skips those rows while scenario_map_from_rows keeps them, so every duplicate "
            f"key AFTER the first such row gets a different suffix on the two sides and the "
            f"member sets would be attached to the wrong scenarios. Refusing to route.")
    unknown = sorted(set(members) - set(scenario_map))
    if unknown:
        raise ValueError(
            f"member_sets produced {len(unknown)} key(s) absent from the scenario map, e.g. "
            f"{unknown[:3]!r}. The two suffix loops have diverged; routing would assign keys "
            f"that Layer C will never look up.")

    turn_index_map = turn_to_pool_index(parsed, texts)      # raises on any mismatch
    calls = call_of_pool_index(parsed, texts)
    lookup = build_lookup(members)                          # raises on overlapping members

    diag = {
        "router": router, "n_clusters": len(clusters), "n_pool_items": len(texts),
        "n_member_keys": len(members),
        "n_member_turns": sum(len(v) for v in members.values()),
        "member_scenarios": mdiag["scenarios"], "member_sinks": mdiag["sinks"],
        "merged_folded": mdiag["merged_folded"], "failed_rows": mdiag["failed"],
        "merged_unresolved": len(mdiag["merged_unresolved"]),
        # A scenario the map knows and the member sets do not can only come from a row whose
        # cluster is gone -- which now raises above -- so this must be 0. Reported anyway: a
        # future change to either loop shows up here as a number instead of as bad routing.
        "scenarios_without_members": len(set(scenario_map) - set(members)),
    }
    if mdiag["merged_unresolved"]:
        print(f"  !! {len(mdiag['merged_unresolved'])} merge_into target(s) do not resolve to "
              f"any accepted scenario: {mdiag['merged_unresolved'][:3]}. Those turns are in "
              f"NO member set, so R1 cannot route them and they do not feed any centroid.",
              flush=True)

    oof = None
    if router in ("r2", "r3"):
        oof = OutOfFoldCentroids(members, vecs, calls)
    return RouterContext(router=router, diag=diag, members=members, lookup=lookup,
                         texts=list(texts), calls=calls, turn_index_map=turn_index_map,
                         move_len=move_lengths(parsed, segment), oof=oof)


def build_router_context(router: str, rows: list[dict] | None = None, parsed=None,
                         scenario_map: dict[str, dict] | None = None, *,
                         recordings: str = "recordings",
                         taxonomy_identity: dict | None = None,
                         segment: str = "s0", width: int = 3072) -> RouterContext:
    """Rebuild the taxonomy's own clustering, then assemble the context against it.

    `parsed` is the caller's ALREADY-PARSED corpus (the same tuples `layer_bc_arms` built
    its pairs from), and it is what the positional join is verified against. `build_clusters`
    performs its own independent parse -- that is its signature and this trial does not edit
    it -- so the two parses are cross-checked text-for-text by `turn_to_pool_index` rather
    than assumed equal. A parse that drifted (the Avoma-roster and spaCy-component failures
    both moved ~20% of this corpus) aborts here instead of routing every trigger to the wrong
    cluster.

    *** THE CLUSTERING IS PINNED TO THE TAXONOMY BY `members_sha`, NOT BY ARGUMENTS. ***
    `adjudication_ab` records a content hash of the exact memberships it adjudicated. This
    recomputes it and refuses to continue on a mismatch, so "I passed the right --rescue" is
    never something a reader has to take on trust. It also catches the artifacts built with
    `--members-from`, whose identity does not record where their memberships came from.
    """
    # A permutation placebo runs its REAL router first and then shuffles the destinations, so
    # it needs that router's context -- not one of its own. Resolving it here rather than at
    # the call site means `--router r1p` cannot be handed an r0 context and silently degrade
    # into "permute nothing", which would produce a placebo identical to the control and read
    # as "the treatment did nothing".
    if router in _PLACEBO_OF:
        router = _PLACEBO_OF[router]

    if router == "r0":
        return RouterContext(router="r0", diag={
            "router": "r0",
            "note": "production description matching; no membership context is built"})

    from calibration.adjudication_ab import build_clusters, members_sha

    ident = dict(taxonomy_identity or {})
    rescue = ident.get("rescue", "")
    print(f"[router {router}] rebuilding the taxonomy's clustering (rescue={rescue!r}, "
          f"cache-only)...", flush=True)
    clusters, texts, _call_ids, vecs, _total_calls, _ta = build_clusters(
        recordings, "", rescue)

    if int(vecs.shape[1]) != int(width):
        raise SystemExit(
            f"the memberships were fitted at width {vecs.shape[1]} and this run asks for "
            f"{width}. A truncated centroid space is a SECOND variable on top of the router "
            f"-- clusters from one width, routing in another -- so it is refused rather than "
            f"silently mixed. Re-run at --width {vecs.shape[1]}.")

    want = ident.get("members_sha")
    got = members_sha(clusters)
    if not want:
        raise SystemExit(
            f"the taxonomy artifact records no `members_sha`, so there is nothing to pin this "
            f"clustering ({got}) to. Every member set and every centroid would rest on the "
            f"UNCHECKED assumption that re-running the clustering reproduces the one that was "
            f"adjudicated. Re-run the adjudication arm with the current adjudication_ab.py, "
            f"which records it.")
    if want != got:
        raise SystemExit(
            f"MEMBERSHIP MISMATCH: this clustering hashes to {got}, the taxonomy artifact was "
            f"adjudicated over {want}. Its scenarios describe clusters that are not these, so "
            f"every member set and every centroid would be attached to the wrong scenario. "
            f"Likely causes: the corpus changed, or the taxonomy was built with "
            f"`--members-from` (whose identity does not record the membership source and so "
            f"cannot be reproduced from `rescue={rescue!r}`).")
    print(f"[router {router}] members_sha {got} matches the taxonomy artifact", flush=True)

    return router_context_from_clusters(router, rows or [], clusters, parsed, texts, vecs,
                                        scenario_map or {}, segment)


# ---------------------------------------------------------------------------------------
# the entry point -- `assign_scenarios`'s contract, four implementations behind it
# ---------------------------------------------------------------------------------------

def _assign(pair: dict, keys: list[str], scenario_map: dict[str, dict]) -> None:
    """Byte-for-byte `v1.layer_b.assign_scenarios._assign`. Three fields, same three names."""
    pair["scenario_keys"] = keys
    pair["scenario_key"] = keys[0]
    pair["scenario_id"] = scenario_map[keys[0]]["scenario_id"]


def assign_scenarios_router(pairs: list[dict], scenario_map: dict[str, dict], router: str,
                            ctx: RouterContext | None, *,
                            alpha: float = BLEND_ALPHA) -> list[list[float]]:
    """Route every pair, MUTATING it in place, and return the trigger vectors.

    Exactly `v1.layer_b.assign_scenarios`'s contract: sets `scenario_keys`, `scenario_key`
    and `scenario_id` on each pair and returns the trigger vectors so the caller can reuse
    them (`layer_bc_arms` spends them on the top1-top2 margin). Matching the contract is what
    lets `run_arm` swap routers without a second code path -- a router that returned a
    different shape would need its own call site, and the r0 arm would stop being production.

    *** THE SINK/TOP-K RULE IS `shared.relative_match.flat_pick`, WHICH IS PRODUCTION'S OWN
    RULE MOVED VERBATIM. *** It is NOT `topk_pick`, and the difference is not cosmetic:
    production takes the top `max_scenarios_per_pair` of ALL scenarios and then drops sinks
    from that slice, so a sink ranking second CONSUMES a slot; `topk_pick` takes the top `cap`
    NON-SINKS, so it would keep a third real scenario production never keeps. Since the point
    of R2/R3 is to change the SCORE and nothing else, the rule applied to that score has to be
    the one production applies, or the arms would differ from r0 in two ways at once.

    `alpha` is R3's blend weight, exposed only so the identities `alpha=1 -> R2` and
    `alpha=0 -> description-only` are testable. Production arms never pass it.
    """
    if router not in ROUTERS:
        raise ValueError(f"unknown router {router!r}; expected one of {ROUTERS}")
    if not pairs:
        return []

    if router == "r0":
        # VERBATIM production. Not reimplemented, not wrapped, not re-tuned: the control arm
        # must be an external reference rather than a paraphrase of one.
        from v1.layer_b import assign_scenarios
        trigger_vecs = assign_scenarios(pairs, scenario_map, None)
    elif router in _PLACEBO_OF:
        trigger_vecs = _route_permutation_placebo(pairs, scenario_map, router, ctx, alpha)
    else:
        trigger_vecs = _assign_membership(pairs, scenario_map, router, ctx, alpha)

    if ctx is not None and scenario_map:
        _record_common_diag(pairs, scenario_map, ctx)
    return trigger_vecs


def _assign_membership(pairs, scenario_map, router, ctx, alpha):
    from preprocessing import embedder
    from shared.tuning import load_tuning

    if ctx is None:
        raise ValueError(f"router {router!r} needs a RouterContext; build one with "
                         f"build_router_context()")
    if _PLACEBO_OF.get(ctx.router, ctx.router) != _PLACEBO_OF.get(router, router):
        raise ValueError(f"context was built for {ctx.router!r} but routing asked for "
                         f"{router!r}; the two would disagree about what was verified")

    # The SAME call production makes, so the returned vectors mean the same thing in every
    # arm and the top1-top2 margin stays comparable across routers.
    trigger_vecs = embedder.embed_query([p["trigger_text"] for p in pairs])
    if not scenario_map:
        return trigger_vecs

    lb = load_tuning().layer_b
    cap, margin = lb.max_scenarios_per_pair, lb.relative_margin
    if router == "r1":
        _route_r1(pairs, scenario_map, ctx, trigger_vecs, cap, margin)
    elif router == "r2":
        _route_centroid(pairs, scenario_map, ctx, trigger_vecs, cap, margin,
                        blend_alpha=None)
    else:
        _route_centroid(pairs, scenario_map, ctx, trigger_vecs, cap, margin,
                        blend_alpha=alpha)
    return trigger_vecs


def _route_permutation_placebo(pairs, scenario_map, router, ctx, alpha):
    """F4 for a ROUTING arm: keep WHAT the router moved and WHERE, randomise WHICH goes where.

    *** THE a4 PLACEBO DESIGN DOES NOT TRANSFER, AND USING IT HERE WOULD BE THE SAME BUG
    AGAIN. *** An ADMISSION arm adds clauses to the corpus, so its placebo must match the
    added clauses -- count, length, embedding character. A ROUTING arm adds NOTHING: the same
    3,977 pairs exist either way and only their destinations change. There is no "added
    content" to reassign. The donor-padding placebo built for `a4` matched a proxy for volume
    rather than volume itself and ended up adding 2x the clauses at 3.4x the length -- 6.9x
    the text mass it claimed to match. A placebo that is silently wrong looks exactly like a
    valid result, which is why the invariants below are ASSERTED rather than checked after.

    THE CONSTRUCTION:
      1. route every pair under r0, and under the real router
      2. take the pairs whose destination CHANGED
      3. keep that exact multiset of destinations, and PERMUTE which pair receives which

    What is held identical to the treatment, by construction rather than by matching:
      * the number of pairs re-routed
      * the number of pairs each scenario receives
      * therefore the clause volume each scenario receives, up to which pair carries which
        response -- and `scenario_calls`, up to the same
      * the sink-share change: the same pairs leave sinks

    The ONLY difference is which pair lands where. So this answers "did membership CHOOSE
    well", and deliberately NOT "was leaving the sinks good" -- that is a different claim
    needing a different placebo (move the same number of RANDOM sink pairs out), and
    conflating them is how a control ends up testing something other than the thing.

    Deterministic: `PLACEBO_SEED` is a module constant, so two runs of the same arm are
    byte-identical and a floor pair means what it says.
    """
    import random

    real = _PLACEBO_OF[router]
    # The context may be labelled with EITHER the placebo name or its real router -- both
    # carry the same membership machinery, and `build_router_context` resolves the placebo
    # name before building. What must still fail is an r0 context, which has no membership at
    # all and would silently permute nothing, producing a "placebo" identical to the control.
    if ctx is None or _PLACEBO_OF.get(ctx.router, ctx.router) != real:
        raise ValueError(f"{router!r} needs a RouterContext built for {real!r}, got "
                         f"{None if ctx is None else ctx.router!r}")

    from v1.layer_b import assign_scenarios

    base = [dict(p) for p in pairs]
    trigger_vecs = assign_scenarios(base, scenario_map, None)
    treat = [dict(p) for p in pairs]
    _assign_membership(treat, scenario_map, real, ctx, alpha)

    changed = [i for i in range(len(pairs)) if treat[i]["scenario_key"] != base[i]["scenario_key"]]
    dests = [treat[i]["scenario_key"] for i in changed]
    shuffled = list(dests)
    random.Random(PLACEBO_SEED).shuffle(shuffled)

    # INVARIANTS, asserted. Each corresponds to one way this could silently stop being a
    # placebo, and each has a real precedent in this repo's retracted findings.
    assert Counter(shuffled) == Counter(dests), (
        "the permutation changed the DESTINATION MULTISET -- scenarios would receive "
        "different volumes than the treatment and the control would no longer be matched")
    assert len(shuffled) == len(changed), "permutation dropped or duplicated a pair"

    # An index -> permuted destination map, so the assignment loop is a dict lookup rather
    # than a membership test against a 4,000-element list (which would be quadratic).
    permuted = {i: shuffled[j] for j, i in enumerate(changed)}
    for i, pair in enumerate(pairs):
        key = permuted.get(i)
        if key is None:
            pair["scenario_key"] = base[i]["scenario_key"]
            pair["scenario_keys"] = list(base[i]["scenario_keys"])
            pair["scenario_id"] = base[i]["scenario_id"]
        else:
            pair["scenario_key"] = key
            pair["scenario_keys"] = [key]
            pair["scenario_id"] = scenario_map[key]["scenario_id"]
    assert len(permuted) == len(changed), "a pair index was lost building the permutation map"

    kept = sum(1 for j, i in enumerate(changed) if shuffled[j] == dests[j])
    if ctx is not None:
        ctx.diag.update({
            "placebo_of": real,
            "placebo_seed": PLACEBO_SEED,
            "placebo_pairs_permuted": len(changed),
            "placebo_share_of_corpus": len(changed) / max(1, len(pairs)),
            # A permutation can coincidentally return a pair to its own destination. If this
            # is large the placebo is barely a placebo, so it is reported rather than assumed
            # small -- the destination multiset is dominated by a few big scenarios, so
            # coincidence is NOT negligible here.
            "placebo_coincidental_matches": kept,
            "placebo_coincidental_share": kept / max(1, len(changed)),
        })
    return trigger_vecs


def _description_sims(pairs, scenario_map, trigger_vecs):
    """(keys, is_sink, sims) against the scenario DESCRIPTIONS -- R0's own space.

    R1 needs it for the noise fallback and R3 for the blend term, and both must obtain it the
    way production does: `build_scenario_vecs` resolves `layer_a.scenario_vector_mode`, so a
    harness that concatenated the fields itself would silently ignore that flag.

    *** float64, NOT float32. *** R1's noise fallback must reproduce
    `v1.layer_b.assign_scenarios` exactly, and production builds these matrices with a bare
    `np.array(...)` over Python floats, i.e. float64. Rounding the triggers to float32 first
    would move the last bits of a cosine, which is enough to flip an argmax on a near-tie --
    and near-ties are the norm here, the measured top1-top2 gap being ~0.01.
    """
    from shared.relative_match import cosine_sims, is_sink_flags
    from shared.scenario_vectors import build_scenario_vecs

    keys, svecs = build_scenario_vecs(scenario_map)
    sims = cosine_sims(np.asarray(trigger_vecs, dtype=np.float64),
                       np.asarray(svecs, dtype=np.float64))
    return keys, is_sink_flags(scenario_map, keys), sims


def _route_r1(pairs, scenario_map, ctx, trigger_vecs, cap, margin) -> None:
    """Read the label Layer A already gave this exact turn. A miss falls back to R0.

    ONE key, never a ranked list: a lookup has no runner-up to be within a margin of, so
    `scenario_keys` is `[key]` and `max_scenarios_per_pair` never applies. A SINK key is
    assigned as-is, which is the same outcome production's short-circuit produces for a junk
    trigger -- the pair stops there either way.

    *** THE FALLBACK SPLIT IS NOT A FOOTNOTE, IT IS THE READ. *** ~47% of the pool is HDBSCAN
    noise, so this arm is a HYBRID by construction and a large part of any result it produces
    is R0's. The counts go into `diag` and are printed, split three ways so "the label was
    noise" cannot hide inside "the turn was not found at all" -- the second is a broken join,
    not a property of the clustering, and it must never be readable as one.
    """
    from shared.relative_match import flat_pick

    keys, sink, sims = _description_sims(pairs, scenario_map, trigger_vecs)
    resolved = noise = unmapped = 0
    sink_hits = 0
    for i, pair in enumerate(pairs):
        n_turns = ctx.move_len.get((pair["call_filename"], pair["turn_index"]), 1)
        idxs = pair_pool_indices(pair, ctx.turn_index_map, n_turns)
        key = r1_pick(idxs, ctx.lookup, ctx.texts) if idxs else None
        if key is None:
            _assign(pair, flat_pick(sims[i], keys, sink, cap, margin), scenario_map)
            if idxs:
                noise += 1
            else:
                unmapped += 1
        else:
            _assign(pair, [key], scenario_map)
            resolved += 1
            sink_hits += int(not scenario_map[key].get("is_coachable", True))

    n = len(pairs)
    ctx.diag.update({
        "r1_lookup_resolved": resolved, "r1_lookup_share": resolved / n,
        "r1_fallback_noise": noise, "r1_fallback_unmapped": unmapped,
        "r1_fallback_share": (noise + unmapped) / n,
        "r1_lookup_to_sink": sink_hits,
        "r1_lookup_to_sink_share": (sink_hits / resolved) if resolved else float("nan"),
    })


def _route_centroid(pairs, scenario_map, ctx, trigger_vecs, cap, margin,
                    blend_alpha: float | None) -> None:
    """R2 (`blend_alpha is None`) and R3 (a float), sharing one per-call loop.

    R2 never builds a description vector -- its whole claim is that membership alone routes --
    so the two are separate code paths rather than R2 being R3 at alpha=1. That is also what
    makes `alpha=1.0 -> R2` a real test rather than a tautology.

    *** CENTROIDS ARE COMPUTED PER CALL, NOT PER PAIR. *** The exclusion is defined by the
    querying trigger's CALL, so every pair in a call shares one candidate set; recomputing it
    per pair would be identical arithmetic ~15x over. Pairs are processed in sorted call
    order, so the result does not depend on the order the corpus happened to arrive in.

    Two diagnostics come out of here and both are required by §3.2:
      * how often a scenario is DROPPED from a trigger's candidate set for having no
        out-of-fold evidence -- counted per pair, not per call, because that is the unit the
        loss lands on;
      * IN-FOLD vs OUT-OF-FOLD top-1 agreement -- the size of the self-inflation this whole
        construction exists to remove. Scored with the arm's OWN score (blended for R3), so
        it measures that arm rather than a different one.
    """
    from shared.relative_match import cosine_sims, flat_pick, is_sink_flags

    # float64 throughout, matching production's own `np.array(trigger_vecs)`. The blend puts
    # a centroid cosine and a description cosine on one scale, so a width difference between
    # the two terms would be a difference in the ARM, not in precision.
    T = np.asarray(trigger_vecs, dtype=np.float64)
    desc_pos, D = None, None
    if blend_alpha is not None:
        from shared.scenario_vectors import build_scenario_vecs
        dkeys, dvecs = build_scenario_vecs(scenario_map)
        desc_pos = {k: i for i, k in enumerate(dkeys)}
        D = np.asarray(dvecs, dtype=np.float64)

    by_call: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(pairs):
        by_call[p["call_filename"]].append(i)

    in_keys, in_cents = ctx.oof.in_fold()
    in_pos_cols = ([desc_pos[k] for k in in_keys] if desc_pos is not None else None)
    n_all = len(ctx.oof.keys)

    dropped_slots = pairs_with_drop = agree = 0
    for call in sorted(by_call):
        rows = by_call[call]
        keys, cents = ctx.oof.for_call(call)
        if not keys:
            raise ValueError(
                f"every scenario's entire evidence comes from {call!r}, so nothing can be "
                f"routed out of fold. That is only possible on a one-call taxonomy; refusing "
                f"rather than quietly routing this call in fold.")
        Ts = T[rows]
        sims = cosine_sims(Ts, cents)
        in_sims = cosine_sims(Ts, in_cents)
        if blend_alpha is not None:
            d = cosine_sims(Ts, D)
            sims = blend_alpha * sims + (1.0 - blend_alpha) * d[:, [desc_pos[k] for k in keys]]
            in_sims = blend_alpha * in_sims + (1.0 - blend_alpha) * d[:, in_pos_cols]

        sink = is_sink_flags(scenario_map, keys)
        drop = n_all - len(keys)
        dropped_slots += drop * len(rows)
        pairs_with_drop += len(rows) if drop else 0
        for r, pi in enumerate(rows):
            kept = flat_pick(sims[r], keys, sink, cap, margin)
            _assign(pairs[pi], kept, scenario_map)
            # `kept[0]` IS the out-of-fold top-1 in both of flat_pick's branches, so this
            # compares argmax to argmax and needs no second ranking pass.
            agree += int(in_keys[int(np.argmax(in_sims[r]))] == kept[0])

    n = len(pairs)
    ctx.diag.update({
        "oof_scenarios_total": n_all,
        "oof_dropped_slots_per_pair": dropped_slots / n,
        "oof_pairs_with_a_drop": pairs_with_drop,
        "oof_pairs_with_a_drop_share": pairs_with_drop / n,
        "in_fold_top1_agreement": agree / n,
        "blend_alpha": blend_alpha,
    })


def _record_common_diag(pairs, scenario_map, ctx) -> None:
    """The share of pairs whose TOP-1 is a sink -- the one number every router reports.

    `scenario_key` is the top-1 under every router here: `flat_pick` returns the argmax first
    in both branches, and R1's lookup assigns a single key. So this reads the final assignment
    rather than re-deriving a ranking, which is why it works for r0 without touching
    production.
    """
    from shared.relative_match import is_sink_flags

    keys = [p.get("scenario_key") for p in pairs]
    if any(k is None for k in keys):
        return
    flags = is_sink_flags(scenario_map, keys)
    ctx.diag.update({"n_pairs": len(pairs), "top1_sink": int(sum(flags)),
                     "top1_sink_share": sum(flags) / len(pairs)})


def report_router(diag: dict) -> None:
    """Print what §3.1-3.3 requires reported. Lives here so a router and its read ship as one."""
    r = diag.get("router", "?")
    if r == "r0":
        print(f"[router r0] production description matching; "
              f"top-1 is a sink for {diag.get('top1_sink_share', float('nan'))*100:.1f}% "
              f"of pairs", flush=True)
        return
    print(f"[router {r}] taxonomy: {diag.get('n_member_keys')} member sets over "
          f"{diag.get('n_member_turns')} pool turns "
          f"({diag.get('member_scenarios')} scenarios + {diag.get('member_sinks')} sinks, "
          f"{diag.get('merged_folded')} merged folded in, "
          f"{diag.get('merged_unresolved')} unresolved)", flush=True)
    if r == "r1":
        print(f"[router r1] *** HYBRID: {diag['r1_lookup_resolved']} pairs "
              f"({diag['r1_lookup_share']*100:.1f}%) routed BY LOOKUP, "
              f"{diag['r1_fallback_noise']} fell back to R0 (HDBSCAN noise) and "
              f"{diag['r1_fallback_unmapped']} had no pool index at all. A result is only "
              f"R1's to the extent of the first number.", flush=True)
        if diag["r1_fallback_unmapped"]:
            print(f"  !! {diag['r1_fallback_unmapped']} trigger(s) were not in the pool. "
                  f"That is a JOIN defect, not clustering noise -- read it before the "
                  f"headline.", flush=True)
        print(f"[router r1] of the looked-up pairs, "
              f"{diag['r1_lookup_to_sink_share']*100:.1f}% landed on a sink", flush=True)
    else:
        print(f"[router {r}] out-of-fold: {diag['oof_dropped_slots_per_pair']:.2f} of "
              f"{diag['oof_scenarios_total']} scenarios dropped per pair for having no "
              f"evidence outside the trigger's own call; {diag['oof_pairs_with_a_drop_share']*100:.1f}% "
              f"of pairs lost at least one candidate", flush=True)
        print(f"[router {r}] IN-FOLD vs OUT-OF-FOLD top-1 agreement "
              f"{diag['in_fold_top1_agreement']*100:.1f}%   <- 100% would mean the exclusion "
              f"changed nothing and the arm is reproducing membership", flush=True)
    print(f"[router {r}] top-1 is a sink for "
          f"{diag.get('top1_sink_share', float('nan'))*100:.1f}% of pairs", flush=True)
