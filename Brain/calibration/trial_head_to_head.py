#!/usr/bin/env python3
"""Head-to-head pairwise comparison harness.

Design: docs/superpowers/specs/2026-08-13-head-to-head-comparison-design.md
Plan:   docs/superpowers/plans/2026-08-13-head-to-head.md

Criteria-based scoring is closed -- the expert scores 0.114 against his own rubrics and 0.090
against deliberately unrelated ones, 1.2:1, reproduced three times, and the four-arm rebuild
then failed its gate. This harness drops criteria entirely: for a client moment, show a judge
the CSM's reply and the expert's real reply to the nearest comparable moment, and ask which
handled it better. A judge with no ability lands at 50%, so the null is structural rather than
arguable -- which is the one thing every previous attempt lacked.

STAGES (--stage). w0 is free; everything else spends Gemma calls and is gated on w0.

    w0      build and FREEZE the moment set. Zero Gemma. Re-measures the retrieval gate in
            the CSM->Naren direction, which is stopping condition #1.
    smoke   2 items through EVERY paid stage. ~20 calls. py_compile and an import check are
            not enough -- this harness still failed twice on first run, on a reversed
            argument order and a NaN that printed a confident FAIL computed from nothing.
    c2      expert vs expert. Two expert replies at ADJACENT retrieval ranks within cosine
            tolerance, so neither has a fit advantage. Must land in [0.40, 0.60].
    c3      sensitivity. Matched reply vs one from a DERANGED unrelated scenario. Matched
            must win >= 0.75, else the judge cannot tell relevant from irrelevant.
    c4      transplant penalty. The expert's real reply to a turn vs a retrieved neighbour
            of his own, his whole call held out. Both sides are the same person, so any win
            for the native side IS the provenance cost. >= 0.75 is fatal to the headline.
    w3      the headline: CSM vs expert. Runs only if every control passes.

Every paid stage asserts the frozen moments_sha and refuses to run on a mismatch -- without
that, two sessions judge different moment sets and their results cannot be combined, the
defect that made arm0_baseline incomparable to the arms it was measured against.

Zero writes: the connection is opened read-only at the Postgres level, and no Layer D table is
touched, so this cannot corrupt a Layer D baseline and needs no clear_ego_trap_data.py first.

    python calibration/trial_head_to_head.py --stage w0
    python calibration/trial_head_to_head.py --load artifacts/h2h_moments.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""

import numpy as np

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR, BRAIN_DIR
from calibration.probe_retrieval_gate import (
    _connect_read_only, _load_pool, bootstrap_lift, candidate_base_rate,
)
from config import load_config
from ego_trap import csm_registry
from ego_trap.scenario_pool import coachable_only, pool_summary
from ego_trap.transcript_parser import (
    EgoTrapRole, classify_response_outcome, parse_transcript, turns_until_next_client,
)
from preprocessing import embedder
from shared import relative_match, storage
from shared import gemma as gemma_mod
from shared.gemma import GemmaError, call_gemma
from shared.head_to_head import (
    adjacent_rank_pair, assign_swap_batches, by_decile, length_matched, moments_sha,
    normalize_winner, order_average, swap_agreement, win_rate,
)
from shared.prompts import PROMPT_HEAD_TO_HEAD_BATCH
from shared.scenario_vectors import build_scenario_vecs
from v1.layer_b import _is_substantive

# The retrieval floor, from the trigger-vs-trigger band probe_retrieval_gate.py measured on
# the real 4,605-pair pool: p10=0.630 p25=0.659 p50=0.689 p75=0.717 p90=0.746. p10 drops the
# worst tenth. Every item's cosine is persisted, so a HIGHER floor is recoverable afterwards
# by stratification with no re-run -- the same property as Layer C's (percentile, fraction)
# grid, where selecting a row later costs nothing.
_RETRIEVAL_FLOOR = 0.630

# Ranks kept per moment. 1 is all the headline needs; 2-5 exist because control C2 pairs two
# neighbours at ADJACENT ranks whose cosines are within a tolerance.
_KEEP_RANKS = 5

# Pinned, NOT read from tuning.yaml's embedding.backend. If that key flips to 'gemini' under
# this harness it would either fire thousands of paid requests or -- far worse -- compare a
# bge vector against a gemini vector in one cosine matrix, which is meaningless and would
# produce confident numbers. Recorded in the artifact for the same reason `scored_by` is.
_EMBEDDING_BACKEND = "local_bge"

# Judge batch size. Each item carries a trigger plus two full replies -- several times a
# milestone description -- and truncation is the binding constraint, measured at batch 20 for
# the far smaller rewrite payload in ops/rewrite_milestone_criteria.py. A prompt-packing
# constant, deliberately NOT a tuning.yaml key: same precedent as v2/layer_c._DESCRIBE_BATCH_SIZE.
_BATCH_SIZE = 5

# C2 only: how close two adjacent-rank neighbours must be for neither to hold a fit advantage.
_C2_TOLERANCE = 0.01

# Reported, never a filter. Judge everything and stratify afterwards, so this band is one row
# of a table rather than the whole sample -- the same free-grid property as the cosine floor.
_LENGTH_BAND = 0.25

# The judge model chain, pinned. gemma-4-31b-it is deliberately NOT in it: its 16k TPM
# ceiling cannot hold a prompt carrying a trigger plus two full replies, and one call under
# it burned 8+ minutes of backoff. Every historical number in CLAUDE.md was produced under
# gemma-4-31b-it, so a verdict blended across that boundary is model-confounded -- which is
# why `judged_by` is recorded per verdict and `models` per artifact.
_JUDGE_MODEL = "gemini-3.5-flash-lite"
_JUDGE_FALLBACK = ("gemini-3.1-flash-lite",)

_PAID_STAGES = ("c2", "c3", "c4", "w3")

# Pre-registered bars (spec section 5). Invented except where noted; recorded here so the
# report cannot quietly grade itself against a number chosen after seeing the result.
_BARS = {
    "c1_agreement_min": 0.75,   # derived: signal share is ~2a-1, so 0.75 means half
    "c2_band": (0.40, 0.60),
    "c3_matched_min": 0.75,
    "c4_native_fatal": 0.75,
}


def _load_transcripts(recordings_dir: _Path, mapping_path: _Path, config):
    """Parse every CSM transcript, and report speakers that resolved to CLIENT.

    JOVEO_SPEAKER_NAMES FAILS OPEN: an unlisted Joveo colleague is classified as the CLIENT,
    which invents coaching signals out of internal chatter. 14 were caught on the first
    106-call pull. This prints the client-side speaker roster so an internal name showing up
    there is visible rather than silently scored.
    """
    mapping = csm_registry.load_mapping(mapping_path)
    out, client_speakers = [], Counter()
    for path in sorted(recordings_dir.glob("*.txt")):
        stem = path.stem
        if stem not in mapping:
            print(f"  [skip] {stem}: not in mapping.csv")
            continue
        csm_id, csm_name = mapping[stem]
        turns = parse_transcript(str(path), csm_name.strip().lower(),
                                 config.joveo_speakers_lower)
        for t in turns:
            if t.role == EgoTrapRole.CLIENT:
                client_speakers[t.speaker_raw.strip()] += 1
        out.append({"stem": stem, "csm_id": csm_id, "turns": turns})
    return out, client_speakers


def _select_signals(calls, scenario_map) -> tuple[list[dict], dict]:
    """Which client turns are coachable moments at all.

    Layer D's rule verbatim: match the turn against the FULL scenario map, sinks included,
    and reject it if the best match is a sink. Filtering sinks out here would make the best
    match a non-sink by construction and admit every turn -- the old absolute-0.35-floor
    pathology wearing a relative margin.

    Note this matches against SCENARIO vectors. Retrieval later matches against kb_pairs
    TRIGGER vectors. They are different populations and their measured numbers (60.7%
    rejection here, 81.2% clean there) do not transfer between the two stages.
    """
    keys, vecs = build_scenario_vecs(scenario_map)
    scen_mat = np.asarray(vecs, dtype=np.float32)
    sink_flags = relative_match.is_sink_flags(scenario_map, keys)

    candidates, n_client = [], 0
    for call in calls:
        for t in call["turns"]:
            if t.role != EgoTrapRole.CLIENT:
                continue
            n_client += 1
            # The SAME filter kb_pairs was built through, so the CSM side cannot admit
            # filler the expert side structurally excludes.
            if not _is_substantive(t.text):
                continue
            candidates.append({"stem": call["stem"], "csm_id": call["csm_id"],
                               "turn_index": t.index, "trigger_text": t.text,
                               "turns": call["turns"]})
    if not candidates:
        return [], {"client_turns": n_client, "candidates": 0}

    trig = embedder.embed_query_matrix([c["trigger_text"] for c in candidates])
    sims = relative_match.cosine_sims(np.asarray(trig, dtype=np.float32), scen_mat)

    kept, rejected_kind = [], Counter()
    for c, row in zip(candidates, sims):
        best = int(np.argmax(row))
        if sink_flags[best]:
            rejected_kind[scenario_map[keys[best]].get("cluster_kind") or "unknown"] += 1
            continue
        c["scenario_key"] = keys[best]
        c["scenario_similarity"] = float(row[best])
        kept.append(c)

    n = len(candidates)
    return kept, {
        "client_turns": n_client,
        "candidates": n,
        "kept": len(kept),
        "rejected": n - len(kept),
        "rejection_rate": (n - len(kept)) / n,
        "rejected_by_kind": dict(rejected_kind),
    }


def _attach_responses(signals) -> dict:
    """The CSM's own answer to each signal turn.

    SYMMETRY, and it is load-bearing. `layer_b.extract_pairs` applies `_is_substantive` to the
    trigger AND the response, so every expert response in kb_pairs is substantive by
    construction. Filtering only the CSM's trigger would let the CSM side enter with replies
    like "Yeah." while the expert side structurally cannot -- handing the expert free wins on
    items that were never a comparison. Measured on the first W0 run: 80.2% of CSM replies pass,
    so this asymmetry would have contaminated ~1 item in 5.

    Known defect, bounded rather than fixed (spec 5.3): extract_csm_response_window sometimes
    captures scheduling chatter instead of the substantive answer. A moment with no CSM reply
    at all is dropped -- there is nothing to compare -- and the drop is reported, since 36% of
    Layer D's gap events were exactly this case.
    """
    outcomes = Counter()
    for s in signals:
        turns = s["turns"]
        outcome = classify_response_outcome(turns, s["turn_index"])
        outcomes[outcome] += 1
        following = turns_until_next_client(turns, s["turn_index"])
        s["csm_response"] = " ".join(
            t.text for t in following if t.role == EgoTrapRole.CSM
        ).strip()
        s["response_outcome"] = outcome
        s["csm_response_substantive"] = _is_substantive(s["csm_response"])
    return dict(outcomes)


def _retrieve(signals, pool_rows) -> dict:
    """Nearest expert moments, from the COACHABLE-FILED kb_pairs only.

    Measured on the real pool: 18.8% of UNFILTERED neighbours are sink-filed, i.e. one in
    five comparisons would hand the judge backchannel as the expert's response. One predicate
    takes that to zero by construction. This filter is also why retrieval runs against
    Postgres rather than Pinecone, whose "triggers" metadata carries no is_coachable.
    """
    pool = [r for r in pool_rows if r["is_coachable"]]
    pool_mat = embedder.embed_query_matrix([r["trigger_text"] for r in pool])
    pool_mat = np.asarray(pool_mat, dtype=np.float32)
    pool_mat /= np.maximum(np.linalg.norm(pool_mat, axis=1, keepdims=True), 1e-12)

    q = embedder.embed_query_matrix([s["trigger_text"] for s in signals])
    q = np.asarray(q, dtype=np.float32)
    q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)

    sims = q @ pool_mat.T
    order = np.argsort(-sims, axis=1)[:, :_KEEP_RANKS]
    for s, row, idx in zip(signals, sims, order):
        s["candidates"] = [{
            "pair_id": pool[int(j)]["pair_id"],
            "scenario_key": pool[int(j)]["scenario_key"],
            "trigger_text": pool[int(j)]["trigger_text"],
            "response_text": pool[int(j)]["response_text"],
            "cosine": float(row[int(j)]),
        } for j in idx]
    return {"coachable_pool": len(pool), "full_pool": len(pool_rows)}


def _cross_corpus_gate(signals, pool_rows, seed: int) -> dict:
    """STOPPING CONDITION #1, measured in the direction the design actually needs.

    probe_retrieval_gate.py established that trigger similarity finds a comparable moment
    when Naren queries Naren -- the OPTIMISTIC bound, same speaker and register. This asks
    the cross-corpus question: does a CSM's client turn retrieve a comparable expert moment?
    Same metric, same bootstrap, same bar (the lift's 95% CI must exclude zero).

    Measured against the FULL pool, deliberately -- the production retrieval filters to
    coachable pairs, which would force this metric to 1.0 and measure nothing. What is being
    tested is whether trigger similarity carries topical signal across corpora at all.
    """
    pool_mat = embedder.embed_query_matrix([r["trigger_text"] for r in pool_rows])
    pool_mat = np.asarray(pool_mat, dtype=np.float32)
    pool_mat /= np.maximum(np.linalg.norm(pool_mat, axis=1, keepdims=True), 1e-12)
    coach = np.array([bool(r["is_coachable"]) for r in pool_rows])

    q = embedder.embed_query_matrix([s["trigger_text"] for s in signals])
    q = np.asarray(q, dtype=np.float32)
    q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)

    top1 = np.argmax(q @ pool_mat.T, axis=1)
    clean = coach[top1].astype(float)
    # The base rate here is the WHOLE pool's coachable share, with no call holdout.
    # probe_retrieval_gate needed a per-query holdout because it queried Naren against Naren,
    # so a query's own call sat in its candidate pool. These corpora share no call, so the leak
    # cannot occur and every query faces the identical pool.
    #
    # Do NOT reach for candidate_base_rate here: it excludes rows matching the query's call id,
    # and feeding it one synthetic id for every row empties every candidate pool and returns
    # nan -- which this harness did on its first run, printing a confident FAIL computed from
    # nothing. Same class of self-inflicted error as the merge-blind _match_milestones.
    base = float(coach.mean())
    lift, lo, hi = bootstrap_lift(clean, base, seed=seed)
    return {"observed": float(clean.mean()), "base": base, "lift": lift, "lo": lo, "hi": hi,
            "n_queries": int(len(clean))}


# --------------------------------------------------------------------------------------
# Paid stages. Every one of them: two orders per item in DISJOINT batches, an explicit
# verdict on every item, raw judge output persisted, flushed after each batch.
# --------------------------------------------------------------------------------------

def _select_keys(config, which: str) -> tuple:
    """Which API keys this run may rotate through.

    config.load_config already builds (key1, key2) when GEMMA_API_KEY_2 is set and (key1,)
    when it is not, so "both if both are configured" is the default and needs no flag. This
    selector exists for the other two cases -- deliberately confining a run to one key, e.g.
    to leave the other free for a concurrent workstream, which is what makes the paid stages
    genuinely parallelisable.

    Selecting a key that is not configured is an ERROR, not a silent fallback to the other:
    a run that believes it is on key 2 while actually spending key 1 is exactly the class of
    silent-provenance bug `judged_by` exists to prevent.
    """
    keys = tuple(config.gemma_api_keys)
    if which == "both":
        return keys
    idx = int(which) - 1
    if idx >= len(keys):
        raise SystemExit(
            f"ERROR: --keys {which} requested but only {len(keys)} key(s) configured "
            f"(set GEMMA_API_KEY_2 in .env to enable key 2)."
        )
    return (keys[idx],)


def _pair_for(stage: str, m: dict, partner: dict | None, rng) -> dict | None:
    """Which two replies this stage puts head to head, as (side_a, side_b).

    Side identity is FIXED per stage and never shown to the judge. What each side means:

      c2  A = the higher-ranked expert neighbour, B = the adjacent lower-ranked one.
          Both expert, both transplanted -> a coin flip is the correct answer.
      c3  A = the matched expert reply, B = a reply from a DERANGED unrelated scenario.
          A should win overwhelmingly, or the judge reads nothing.
      c4  A = the expert's OWN reply to this turn (native), B = a retrieved neighbour of
          his (transplant). Same person both sides, so A's win rate IS the provenance cost.
      w3  A = the CSM's reply, B = the expert's retrieved reply. The headline.
    """
    if stage == "c2":
        cands = m["candidates"]
        picked = adjacent_rank_pair([c["cosine"] for c in cands], _C2_TOLERANCE)
        if picked is None:
            return None
        hi, lo = picked
        return {"trigger": m["naren_trigger"], "a": cands[hi]["response_text"],
                "b": cands[lo]["response_text"], "cos": cands[hi]["cosine"]}
    if stage == "c3":
        if not partner:
            return None
        return {"trigger": m["trigger_text"], "a": m["naren_response"],
                "b": partner["response_text"], "cos": m["cosine"]}
    if stage == "c4":
        # The native side is the expert's real reply to HIS OWN trigger, so the trigger
        # shown must be his, not the CSM's -- otherwise neither side is native and the
        # control measures nothing.
        cands = [c for c in m["candidates"][1:] if c["pair_id"] != m["naren_pair_id"]]
        if not cands:
            return None
        return {"trigger": m["naren_trigger"], "a": m["naren_response"],
                "b": cands[0]["response_text"], "cos": cands[0]["cosine"]}
    return {"trigger": m["trigger_text"], "a": m["csm_response"],
            "b": m["naren_response"], "cos": m["cosine"]}


def _render(entries: list[tuple[str, str]], pairs: dict) -> str:
    blocks = []
    for item_id, order in entries:
        p = pairs[item_id]
        one, two = (p["a"], p["b"]) if order == "AB" else (p["b"], p["a"])
        blocks.append(
            f'--- id: {item_id}\nCLIENT TURN:\n{p["trigger"]}\n\n'
            f'Response 1:\n{one}\n\nResponse 2:\n{two}\n'
        )
    return "\n".join(blocks)


def _judge(entries: list[tuple[str, str]], pairs: dict, keys: tuple, model: str,
           fallback_models: tuple) -> dict:
    """One batch -> {item_id: {order: side}}. Missing ids are reported, never inferred.

    Records `judged_by` per verdict from gemma.LAST_MODEL_USED. Without it a verdict has
    unknown provenance, because the chain silently downgrades on a rate limit -- the exact
    confound that split the ceiling run's arm B across two models (793 / 1040) and made its
    published ratio depend on which subset you took. `models` in the artifact is what lets a
    reader tell a single-model result from a blended one.
    """
    # MODEL pinning and KEY rotation are separate concerns, and call_gemma couples them:
    # fallback_enabled=False makes a failure raise GemmaError instead of _ModelExhausted, and
    # only _ModelExhausted is caught by the key-rotation loop -- so disabling fallback also
    # silently disables the second key ("single-model, single-key" in its own docstring).
    # Keeping fallback ON and controlling the chain is how both stay independent.
    raw = call_gemma(PROMPT_HEAD_TO_HEAD_BATCH.format(items_block=_render(entries, pairs)),
                     keys, model=model, fallback_enabled=True,
                     fallback_models=fallback_models)
    judged_by = gemma_mod.LAST_MODEL_USED
    rows = raw if isinstance(raw, list) else raw.get("verdicts") or raw.get("items") or []
    by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
    out = {}
    for item_id, order in entries:
        r = by_id.get(item_id)
        if r is None:
            continue
        try:
            out[(item_id, order)] = {"side": normalize_winner(order, r.get("winner")),
                                     "reason": r.get("reason", ""), "judged_by": judged_by}
        except ValueError as e:
            print(f"    ! unparseable verdict for {item_id}/{order}: {e}")
    return out


def _run_stage(stage: str, moments: list[dict], config, batch_size: int, seed: int,
               max_items: int, out_path: _Path, sha: str, keys: tuple,
               model: str = _JUDGE_MODEL,
               fallback_models: tuple = _JUDGE_FALLBACK) -> dict:
    rng = __import__("random").Random(seed)
    partner_by_scenario = _derange_partners(moments, seed) if stage == "c3" else {}

    pairs, skipped = {}, 0
    for m in moments:
        p = _pair_for(stage, m, partner_by_scenario.get(m["scenario_key"]), rng)
        if p is None or not (p["a"] or "").strip() or not (p["b"] or "").strip():
            skipped += 1
            continue
        pairs[m["item_id"]] = p
    ids = sorted(pairs)
    if max_items and max_items < len(ids):
        # SEEDED RANDOM, never a prefix. item_id is "{call_stem}#{turn}", so ids[:n] would
        # take whole calls in filename order -- the exact `--limit 8` trap that returned
        # every subject-matter scenario and not one client-posture scenario, and invalidated
        # four arm comparisons before anyone noticed. A prefix is not a sample.
        ids = sorted(__import__("random").Random(seed).sample(ids, max_items))
        pairs = {i: pairs[i] for i in ids}
        print(f"  [{stage}] SAMPLED {max_items} of {len(pairs) + skipped} "
              f"(seeded, seed={seed}); spans {len({i.split('#')[0] for i in ids})} calls")

    batches = assign_swap_batches(ids, batch_size, seed)
    print(f"\n[{stage}] {len(ids)} item(s), {skipped} unpairable, "
          f"{len(batches)} batch(es) of up to {batch_size} (x2 orders)")

    verdicts: dict = {}
    for k, batch in enumerate(batches, start=1):
        try:
            verdicts.update(_judge(batch, pairs, keys, model, fallback_models))
        except GemmaError as e:
            print(f"  ! batch {k}/{len(batches)} FAILED: {e} -- {len(batch)} left unjudged")
            continue
        print(f"  batch {k}/{len(batches)} judged ({len(batch)} item(s))")
        # Flush after EVERY batch. One prior run completed all 95 LLM calls and lost every
        # result because a free DB lookup gated the persistence of expensive work.
        _flush(out_path, stage, sha, pairs, verdicts, batch_size, seed, model,
               fallback_models, len(keys))
    return verdicts


def _derange_partners(moments: list[dict], seed: int) -> dict:
    """One UNRELATED partner reply per scenario, for C3.

    Reuses score_naren_ceiling.derange with layer_a.merge_cosine_threshold -- INHERITED, so
    this design adds no tuning.yaml key. Every knob in that file must be a property of the
    data, and a derangement threshold invented here would be neither.
    """
    from calibration.score_naren_ceiling import derange
    from shared.tuning import load_tuning

    by_scen: dict[str, list[dict]] = {}
    for m in moments:
        by_scen.setdefault(m["scenario_key"], []).append(m)
    keys = sorted(by_scen)
    if len(keys) < 2:
        return {}

    vecs = embedder.embed_document_matrix(keys)
    sim = relative_match.cosine_sims(np.asarray(vecs), np.asarray(vecs))
    mapping, how = derange(keys, sim, load_tuning().layer_a.merge_cosine_threshold,
                           __import__("random").Random(seed))
    print(f"  [c3] derangement: {how}")
    if not mapping:
        return {}
    return {k: {"response_text": by_scen[mapping[k]][0]["naren_response"],
                "partner_scenario": mapping[k]} for k in keys}


def _flush(path: _Path, stage: str, sha: str, pairs: dict, verdicts: dict,
           batch_size: int, seed: int, model: str = _JUDGE_MODEL,
           fallback_models: tuple = _JUDGE_FALLBACK, n_keys: int = 1) -> None:
    payload = {
        "stage": stage, "moments_sha": sha, "batch_size": batch_size, "seed": seed,
        "requested_model": model, "fallback_models": list(fallback_models),
        "n_keys": n_keys,
        "models": dict(Counter(v.get("judged_by") for v in verdicts.values())),
        "n_items": len(pairs),
        "raw": [{"item_id": i, "order": o, **v} for (i, o), v in sorted(verdicts.items())],
        "pairs": {i: {k: v for k, v in p.items() if k != "trigger"} for i, p in pairs.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _score_stage(stage: str, verdicts: dict, pairs: dict, moments_by_id: dict) -> dict:
    """Order-average every item, then the rates -- with ties reported, never dropped."""
    ids = sorted({i for i, _ in verdicts})
    outcomes, per_item = [], []
    for item_id in ids:
        ab = verdicts.get((item_id, "AB"), {}).get("side")
        ba = verdicts.get((item_id, "BA"), {}).get("side")
        if ab is None or ba is None:
            continue
        o = order_average(ab, ba)
        outcomes.append(o)
        per_item.append({"item_id": item_id, "ab": ab, "ba": ba, "outcome": o,
                         "cos": pairs[item_id]["cos"],
                         "len_a": len(pairs[item_id]["a"].split()),
                         "len_b": len(pairs[item_id]["b"].split())})
    agree = swap_agreement([(p["ab"], p["ba"]) for p in per_item])
    stats = win_rate(outcomes, "A")
    slot1 = [v["side"] for (i, o), v in verdicts.items()
             if v["side"] != "tie" and ((o == "AB" and v["side"] == "A")
                                        or (o == "BA" and v["side"] == "B"))]
    decisive = [v for v in verdicts.values() if v["side"] != "tie"]
    return {
        "stage": stage, "n_items": len(per_item), "win_rate_A": stats,
        "swap_agreement": agree,
        "position1_win_rate": (len(slot1) / len(decisive)) if decisive else None,
        "by_cosine_decile": by_decile(outcomes, [p["cos"] for p in per_item], "A", bins=4),
        "length_matched": win_rate(
            [outcomes[k] for k in length_matched([p["len_a"] for p in per_item],
                                                [p["len_b"] for p in per_item],
                                                _LENGTH_BAND)], "A"),
        "per_item": per_item,
    }


def _report(art: dict) -> None:
    m = art["moments"]
    print("\n" + "=" * 78)
    print("W0 -- MOMENT SET")
    print("=" * 78)
    print(f"transcripts parsed      {art['transcripts']}")
    print(f"embedding backend       {art['embedding']['backend']} "
          f"({art['embedding']['dims']}d, {art['embedding']['fn']})")
    print(f"\n{art['scenario_pool_summary']}")

    s = art["selection"]
    print(f"\nselection (client turns vs FULL scenario map, Layer D's sink rule)")
    print(f"  client turns             {s.get('client_turns', '?')}")
    print(f"  substantive client turns {s['candidates']}")
    print(f"  rejected as sink         {s['rejected']} ({s['rejection_rate']:.1%})"
          f"   Layer D measured 60.7%")
    print(f"  rejected by kind         {s['rejected_by_kind']}")
    print(f"  kept as signals          {s['kept']}")

    print(f"\nCSM response outcome     {art['response_outcomes']}")
    print(f"  dropped, no CSM reply    {art['dropped_no_response']}")
    print(f"  dropped, reply not substantive {art.get('dropped_thin_response', '?')}"
          f"   (symmetry with layer_b, which filters BOTH sides)")

    r = art["retrieval"]
    print(f"\nretrieval (vs kb_pairs triggers, COACHABLE-FILED only)")
    print(f"  candidate pool           {r['coachable_pool']} of {r['full_pool']} pairs")
    print(f"  floor                    {art['retrieval_floor']} (p10 of the measured band)")
    print(f"  below floor, dropped     {art['dropped_below_floor']}")
    b = art["cosine_band"]
    print(f"  top-1 cosine band        " + "  ".join(f"p{k}={b[str(k)]:.3f}"
                                                    for k in (10, 25, 50, 75, 90)))

    g = art["cross_corpus_gate"]
    print("\n" + "-" * 78)
    print("STOPPING CONDITION #1 -- cross-corpus retrieval (CSM -> Naren)")
    print("-" * 78)
    print(f"  clean top-1  {g['observed']:.3f}   base rate {g['base']:.3f}   "
          f"lift {g['lift']:+.3f}")
    print(f"  95% CI on lift [{g['lo']:+.3f}, {g['hi']:+.3f}]   n={g['n_queries']}")
    passed = g["lo"] > 0
    print(f"  -> {'PASS' if passed else 'FAIL'}: retrieval "
          f"{'carries' if passed else 'does NOT carry'} topical signal across corpora.")

    print("\n" + "=" * 78)
    print(f"FINAL MOMENT SET: {len(m)} moments   sha={art['moments_sha'][:16]}")
    print(f"  from {art['distinct_calls']} calls / {art['distinct_scenarios']} scenarios")
    if not passed:
        print("  STOP. Spend nothing further -- spec section 9, condition 1.")
    print("=" * 78)

    if art.get("read_me_samples"):
        print("\n--- CHECKPOINT: read these (spec section 8) ---")
        for i, s in enumerate(art["read_me_samples"], 1):
            print(f"\n[{i}] cos={s['cosine']:.3f}  scenario={s['scenario_key']}")
            print(f"  CLIENT (CSM call) : {s['trigger_text'][:200]}")
            print(f"  CSM REPLY         : {s['csm_response'][:200]}")
            print(f"  NEAREST EXPERT TRG: {s['naren_trigger'][:200]}")
            print(f"  EXPERT REPLY      : {s['naren_response'][:200]}")


def _verdict(args) -> int:
    """M5 -- the gate. Reads the three control artifacts and grades them against the bars
    fixed in _BARS BEFORE any call was spent.

    C1 is pooled across all three controls, because each judges both orders anyway, and it is
    finalised only once all three exist -- a single stage's slice is a running figure, not a
    verdict.
    """
    loaded, pooled = {}, []
    for stage in ("c2", "c3", "c4"):
        p = ARTIFACTS_DIR / f"h2h_control_{stage}.json"
        if not p.exists():
            print(f"ERROR: {p} missing -- run --stage {stage} first.")
            return 1
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        verdicts = {(r["item_id"], r["order"]): r for r in raw["raw"]}
        s = _score_stage(stage, verdicts, raw["pairs"], {})
        loaded[stage] = s
        pooled += [(i["ab"], i["ba"]) for i in s["per_item"]]

    c1 = swap_agreement(pooled)
    print("\n" + "=" * 78)
    print("M5 -- CONTROL GATE")
    print("=" * 78)
    print(f"\nC1  position-swap agreement, POOLED over all three controls")
    print(f"    agreement {c1['agreement']:.3f}   flip rate {c1['flip_rate']:.3f}   "
          f"n={c1['n_scored']}   both-tie {c1['both_tie_share']:.1%}")
    c1_ok = c1["agreement"] >= _BARS["c1_agreement_min"]
    print(f"    bar >= {_BARS['c1_agreement_min']}  ->  {'PASS' if c1_ok else 'FAIL'}")
    print("    per stage: " + "  ".join(
        f"{k}={loaded[k]['swap_agreement']['agreement']:.3f}" for k in loaded))

    rows, results = [], {"C1": c1_ok}
    for stage, label, check in (
        ("c2", "C2  expert vs expert (higher-ranked neighbour's win rate)",
         lambda r: _BARS["c2_band"][0] <= r <= _BARS["c2_band"][1]),
        ("c3", "C3  sensitivity (matched vs deranged-unrelated)",
         lambda r: r >= _BARS["c3_matched_min"]),
        ("c4", "C4  transplant penalty (native vs transplanted, same person)",
         lambda r: r < _BARS["c4_native_fatal"]),
    ):
        s = loaded[stage]
        w = s["win_rate_A"]
        ok = w["rate"] is not None and check(w["rate"])
        results[stage.upper()] = ok
        lm = s["length_matched"]
        print(f"\n{label}")
        print(f"    A wins {w['rate']:.3f}   n={w['n_decisive']}/{w['n_total']} decisive   "
              f"ties {w['tie_share']:.1%}")
        print(f"    slot-1 win rate {s['position1_win_rate']:.3f}   "
              f"length-matched A wins "
              f"{'n/a' if lm['rate'] is None else f'{lm[chr(114)+chr(97)+chr(116)+chr(101)]:.3f}'}"
              f" (n={lm['n_decisive']})")
        print("    by retrieval-cosine quartile: " + "  ".join(
            f"q{d['bin']}={'n/a' if d['rate'] is None else f'{d[chr(114)+chr(97)+chr(116)+chr(101)]:.2f}'}"
            f"({d['n']})" for d in s["by_cosine_decile"]))
        print(f"    -> {'PASS' if ok else 'FAIL'}")
        rows.append((stage, w["rate"], ok))

    all_ok = all(results.values())
    print("\n" + "=" * 78)
    print(f"GATE: {'PASS -- w3 may run' if all_ok else 'FAIL -- w3 MUST NOT run'}")
    for k, v in results.items():
        print(f"    {k}: {'pass' if v else 'FAIL'}")
    if not all_ok:
        print("\n  A failed control means the INSTRUMENT is broken, not underpowered.")
        print("  More data rescues none of these, and none may be retried with a reworded")
        print("  prompt -- that is how a result gets tuned into existence.")
    print("=" * 78)
    return 0 if all_ok else 3


def _run_paid(args) -> int:
    """Every paid stage. Asserts the frozen sha before spending a single call."""
    moments_path = _Path(args.moments)
    if not moments_path.exists():
        print(f"ERROR: {moments_path} not found -- run --stage w0 first.")
        return 1
    frozen = json.loads(moments_path.read_text(encoding="utf-8-sig"))
    moments = frozen["moments"]

    # The sha is recomputed from the moments themselves, not trusted from the file. A stage
    # that reads a stale or hand-edited artifact and judges a different set than its siblings
    # produces results that cannot be combined -- the arm0_baseline defect.
    recomputed = moments_sha(moments)
    if recomputed != frozen["moments_sha"]:
        print(f"ERROR: moments_sha mismatch.\n  stored     {frozen['moments_sha']}\n"
              f"  recomputed {recomputed}\nThe artifact was edited after freezing. Re-run w0.")
        return 2
    print(f"moment set: {len(moments)} items  sha={recomputed[:16]}")

    config = load_config()
    keys = _select_keys(config, args.keys)
    chain = () if args.no_fallback else _JUDGE_FALLBACK
    print(f"judge: {args.model}  fallback chain: {list(chain) or 'none'}  "
          f"keys in play: {len(keys)} (--keys {args.keys})")
    stages = list(_PAID_STAGES) if args.stage == "smoke" else [args.stage]
    max_items = 2 if args.stage == "smoke" else args.max_items
    if args.stage == "smoke":
        print("SMOKE TEST: 2 items x 2 orders x 4 stages. A path test, not a measurement.")

    summaries = {}
    for stage in stages:
        out = ARTIFACTS_DIR / (f"h2h_smoke_{stage}.json" if args.stage == "smoke"
                               else f"h2h_control_{stage}.json")
        verdicts = _run_stage(stage, moments, config, args.batch_size, args.seed,
                              max_items, out, recomputed, keys, args.model, chain)
        pairs = json.loads(out.read_text(encoding="utf-8"))["pairs"] if out.exists() else {}
        if not verdicts:
            print(f"  [{stage}] no verdicts returned.")
            summaries[stage] = None
            continue
        # _score_stage needs the cos/len fields, which _flush strips the trigger from but
        # otherwise preserves.
        summaries[stage] = _score_stage(stage, verdicts, pairs, {})
        s = summaries[stage]
        w = s["win_rate_A"]
        rate = "n/a" if w["rate"] is None else f"{w['rate']:.3f}"
        ag = s["swap_agreement"]["agreement"]
        print(f"  [{stage}] A-win {rate}  n={w['n_decisive']}/{w['n_total']} decisive"
              f"  ties {w['tie_share']:.1%}"
              f"  swap-agreement {'n/a' if ag is None else f'{ag:.3f}'}")

    if args.stage == "smoke":
        ok = all(v is not None and v["n_items"] > 0 for v in summaries.values())
        print("\n" + "=" * 78)
        print(f"SMOKE: {'PASS' if ok else 'FAIL'} -- "
              f"{sum(1 for v in summaries.values() if v)} of {len(stages)} stages produced "
              f"parseable verdicts.")
        print("Numbers above are a PATH TEST at 2 items. They are not measurements.")
        print("=" * 78)
        return 0 if ok else 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["w0", "smoke", "m5", *_PAID_STAGES],
                    help="which workstream to run")
    ap.add_argument("--load", help="re-report a persisted artifact, zero cost")
    ap.add_argument("--seed", type=int, default=20260813)
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    ap.add_argument("--max-items", type=int, default=0,
                    help="cap items for a path test; 0 = all")
    ap.add_argument("--model", default=_JUDGE_MODEL, help="pin the judge model")
    ap.add_argument("--keys", default="both", choices=["both", "1", "2"],
                    help="which configured API key(s) this run may rotate through")
    ap.add_argument("--no-fallback", action="store_true",
                    help="allow NO model downgrade at all. Key rotation stays on either way.")
    ap.add_argument("--recordings", default=str(BRAIN_DIR / "csm_recordings"))
    ap.add_argument("--moments", default=str(ARTIFACTS_DIR / "h2h_moments.json"))
    ap.add_argument("--out", default=str(ARTIFACTS_DIR / "h2h_moments.json"))
    args = ap.parse_args()

    if args.load:
        _report(json.loads(_Path(args.load).read_text(encoding="utf-8-sig")))
        return 0
    if args.stage == "m5":
        return _verdict(args)
    if args.stage in ("smoke", *_PAID_STAGES):
        return _run_paid(args)
    if args.stage != "w0":
        ap.error("pass --stage w0|smoke|c2|c3|c4|w3, or --load PATH to re-report")

    config = load_config()
    recordings_dir = _Path(args.recordings)
    mapping_path = recordings_dir / "mapping.csv"

    print(f"parsing transcripts from {recordings_dir} ...")
    calls, client_speakers = _load_transcripts(recordings_dir, mapping_path, config)
    print(f"  {len(calls)} transcripts")
    print(f"  distinct CLIENT-side speakers: {len(client_speakers)} "
          f"(check for internal names -- JOVEO_SPEAKER_NAMES fails OPEN)")

    conn = _connect_read_only(config.database_url)
    try:
        scenario_map = {s["scenario_key"]: s for s in storage.get_scenarios(conn)}
        pool_rows = _load_pool(conn)
    finally:
        conn.close()
    print(f"\n{pool_summary(scenario_map)}")

    print("\nselecting signals (embedding client turns; warm cache -> free) ...")
    signals, sel = _select_signals(calls, scenario_map)
    if not signals:
        print("ERROR: no client turn survived selection.")
        return 1

    outcomes = _attach_responses(signals)
    before = len(signals)
    signals = [s for s in signals if s["csm_response"]]
    dropped_no_response = before - len(signals)
    before = len(signals)
    signals = [s for s in signals if s["csm_response_substantive"]]
    dropped_thin_response = before - len(signals)

    print("retrieving nearest expert moments ...")
    ret = _retrieve(signals, pool_rows)

    print("measuring the cross-corpus gate ...")
    gate = _cross_corpus_gate(signals, pool_rows, args.seed)

    before = len(signals)
    signals = [s for s in signals if s["candidates"][0]["cosine"] >= _RETRIEVAL_FLOOR]
    dropped_below_floor = before - len(signals)

    moments = [{
        "item_id": f"{s['stem']}#{s['turn_index']}",
        "call_id": s["stem"], "csm_id": s["csm_id"], "turn_index": s["turn_index"],
        "scenario_key": s["scenario_key"], "scenario_similarity": s["scenario_similarity"],
        "trigger_text": s["trigger_text"], "csm_response": s["csm_response"],
        "naren_pair_id": s["candidates"][0]["pair_id"],
        "naren_trigger": s["candidates"][0]["trigger_text"],
        "naren_response": s["candidates"][0]["response_text"],
        "naren_scenario_key": s["candidates"][0]["scenario_key"],
        "cosine": s["candidates"][0]["cosine"],
        "candidates": s["candidates"],
    } for s in signals]

    cos = np.array([m["cosine"] for m in moments]) if moments else np.array([0.0])
    rng = np.random.default_rng(args.seed)
    pick = rng.choice(len(moments), size=min(args.samples, len(moments)), replace=False)

    art = {
        "transcripts": len(calls),
        "client_side_speakers": dict(client_speakers.most_common()),
        "scenario_pool_summary": pool_summary(scenario_map),
        "embedding": {"backend": _EMBEDDING_BACKEND, "model": "BAAI/bge-base-en-v1.5",
                      "dims": 768, "fn": "embed_query_matrix"},
        "selection": sel,
        "response_outcomes": outcomes,
        "dropped_no_response": dropped_no_response,
        "dropped_thin_response": dropped_thin_response,
        "retrieval": ret,
        "retrieval_floor": _RETRIEVAL_FLOOR,
        "dropped_below_floor": dropped_below_floor,
        "cosine_band": {str(k): float(np.percentile(cos, k)) for k in (10, 25, 50, 75, 90)},
        "cross_corpus_gate": gate,
        "distinct_calls": len({m["call_id"] for m in moments}),
        "distinct_scenarios": len({m["scenario_key"] for m in moments}),
        "moments_sha": moments_sha(moments),
        "moments": moments,
        "read_me_samples": [moments[int(i)] for i in pick],
    }

    out = _Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    _report(art)
    return 0


if __name__ == "__main__":
    sys.exit(main())
