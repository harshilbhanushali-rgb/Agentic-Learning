#!/usr/bin/env python3
"""Adjudicate the Gemini turn-mode clusters into real scenarios. ~245 chat calls, ZERO DB writes.

Spec: docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md

WHAT THIS IS. Every measurement so far has used a content-free-word PROXY for "is this
cluster a real scenario". This replaces the proxy with the actual decision: production's
`PROMPT_LAYER_A_V2_TRIAGE`, one call per surviving cluster, producing real scenario keys,
descriptions and coachable/sink verdicts.

READ-ONLY BY CONSTRUCTION. Nothing is written to Postgres. The live 161 scenarios, their
rubrics and every milestone_performance row are untouched, so no snapshot is needed and
nothing has to be cleared. Output is an artifact.

*** WHY THIS IS SEQUENTIAL AND MUST STAY SEQUENTIAL. ***
The prompt carries "NEAREST SCENARIOS ALREADY ACCEPTED", and `accepted` accumulates as the
loop runs. That is the entire duplicate-detection mechanism: it is what lets the model see
it is looking at the 9th acknowledgment variant and answer "merge_into" instead of minting
a near-duplicate. Clusters are adjudicated LARGEST-FIRST so the best-evidenced member of a
family becomes canonical and later variants have something to merge into.

Run these 245 calls concurrently and every one sees an empty or partial accepted-list, so
duplicate detection collapses and the taxonomy inflates with siblings. Concurrency was
correct for embeddings -- each request there is genuinely independent -- and is WRONG here.
This is an ordered dependency, not a throughput problem.

TRANSPORT ONLY. The prompt text is production's, unmodified, including the bloom_level
block that nothing downstream reads. Only the transport differs: gw.chat_json against the
Joveo gateway rather than call_gemma against Google AI Studio. Both force JSON and parse
with json.loads, so the contract is identical.

CONFIGURATION, all derived earlier and none of it guessed:
  embedder      gemini-embedding-2 @ 3072 native (cached; 768 truncation is exact, validated
                over 11,977 real turns at min cosine 1.000000)
  pool unit     turn
  min_cluster   16  (scale-matched to clause's 50/73,771 -- a count, not a cosine)
  merge         0.97, derived by READING groups in Gemini's own centroid band (p50 0.810).
                bge's 0.92 leaves 136 clusters and a 1,790-item blob here. Counting alone
                would have picked 0.90 on bge and reading proved it fused six business
                topics, so counting is not trusted for this.

Checkpoints after every cluster, so a crash resumes rather than re-paying.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/trial_adjudicate_gemini.py --limit 5   # cheap path test
    ..\\.venv\\Scripts\\python.exe calibration/trial_adjudicate_gemini.py
    ..\\.venv\\Scripts\\python.exe calibration/trial_adjudicate_gemini.py --load
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import hashlib
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

MERGE = 0.97
DEFAULT_MIN_CLUSTER_SIZE = 16
CHAT_MODEL = "gemini-3.5-flash-lite"

# --- the turn-aware amendment (--turn-aware) ------------------------------------------
# MEASURED PROBLEM. Nine blind judges read all 245 min-16 clusters without seeing any
# verdict. They called 92 coachable; Gemma called 38. The disagreement is almost entirely
# one-directional -- Gemma sank 56 clusters the judges would keep (1,831 turns, 14.6% of
# the corpus) while admitting only 2 the judges rejected. So Gemma is precise and
# under-recalling, not miscalibrated in both directions.
#
# WHY. PROMPT_LAYER_A_V2_TRIAGE defines "mechanics" as "acknowledgment, backchannel,
# greetings, thanks, filler, scheduling chatter". That worked on CLAUSE input, where a
# cluster was purely filler or purely substance. A whole TURN routinely OPENS with
# acknowledgement before its real content, so the representative utterances visibly contain
# filler and the cluster gets sunk. The prompt predates the pool-unit change and was written
# for a different unit.
#
# WHAT THIS IS NOT. It does not tell the judge to accept more, lower a bar, or prefer
# "new_scenario". It tells it WHERE in a turn to look. Every decision option, and the
# standard for each, is unchanged -- otherwise this would be tuning a result into existence
# rather than fixing a unit mismatch.
TURN_AWARE_NOTE = """

INPUT UNIT -- READ THIS BEFORE JUDGING. Each utterance above is a COMPLETE client turn, not
a sentence fragment. A substantive turn routinely OPENS with acknowledgement or filler
before its real content: "Yeah. Okay. So on the ATS integration, do we need a separate
pixel?" is a technical question, not backchannel. Judge a turn by its substantive content
wherever that content sits in the turn, and call the cluster "mechanics" only when the turns
contain NO substantive content at all. The standard for every decision is otherwise
unchanged."""
NEAREST_SHOWN = 3
REPRESENTATIVE_SHOWN = 6
# Filenames carry the granularity: a run at 50 must not overwrite the run at 16, and the
# checkpoint must not be reused across them (its guard only compares cluster COUNT, which
# could coincide).
def _paths(mcs: int, turn_aware: bool, tag: str = ""):
    t = f"min{mcs}" + ("_turnaware" if turn_aware else "") + (f"_{tag}" if tag else "")
    return (ARTIFACTS_DIR / f"adjudicate_gemini_{t}_ckpt.json",
            ARTIFACTS_DIR / f"adjudicate_gemini_{t}.json")


def checkpoint_identity(clusters: list[dict], a, ta) -> dict:
    """Everything that must match for a resume to be the SAME run.

    The old guard compared CLUSTER COUNT alone, which is worse than no guard for the paired
    rescue A/B: the rescue grows membership without changing count, so both arms have exactly
    245 and the guard CANNOT fail. Arm 2 would resume from arm 1's completed checkpoint, run
    `range(245, 245)` (i.e. nothing), and write arm 1's verdicts out as its own -- a perfect
    "the rescue changes nothing" produced with zero chat calls, detectable only by wall-clock.
    Same defect class as `trial_grader_inputs.py`'s one-integer key (commit 926d6b4).

    So the key is a CONTENT HASH of the actual memberships -- the one thing the treatment
    moves -- plus every knob that changes what a verdict means.
    """
    h = hashlib.sha256()
    for c in clusters:
        h.update(b"|" + ",".join(map(str, sorted(c["idxs"]))).encode())
    return {"members_sha": h.hexdigest()[:16], "n_clusters": len(clusters),
            "min_cluster_size": a.min_cluster_size, "merge": MERGE,
            "turn_aware": bool(a.turn_aware), "chat_model": CHAT_MODEL,
            "representatives": a.representatives,
            "min_call_support_fraction": ta.min_call_support_fraction,
            "min_call_support_floor": ta.min_call_support_floor,
            "ubiquity_ceiling": ta.ubiquity_ceiling}


def guard_overwrite(out: Path, n_rows: int, force: bool) -> None:
    """Refuse to shrink an existing artifact. `OUT` defaults to the file that IS the published
    baseline, and it is written unconditionally -- so a `--limit 5` PATH TEST silently replaced
    245 adjudicated rows with 5. Precedent: trial_call_scoring.py's own guard (commit 31899f9).
    """
    if not out.exists() or force:
        return
    try:
        have = len(json.loads(out.read_text(encoding="utf-8-sig")).get("rows", []))
    except Exception:                                    # noqa: BLE001
        return
    if have > n_rows:
        raise SystemExit(
            f"REFUSING to overwrite {out.name}: it holds {have} rows, this run has {n_rows}. "
            f"That file is a published baseline. Use --tag to write elsewhere, or --force if "
            f"you genuinely mean to discard it.")


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE,
                   help="HDBSCAN min_cluster_size. 16 is scale-matched to clause mode's "
                        "50/73,771; 50 is what PRODUCTION uses in absolute terms. Comparing a "
                        "run at 16 against production's coachable count compares GRANULARITIES, "
                        "not pool units -- which is exactly the confound this flag exists to "
                        "remove.")
    p.add_argument("--turn-aware", action="store_true",
                   help="append TURN_AWARE_NOTE to the prompt. Fixes a measured unit mismatch: the mechanics definition was written for clause input and sinks turns that merely OPEN with filler. Judged blind, that costs 56 clusters / 1,831 turns at min 16.")
    p.add_argument("--limit", type=int, default=0,
                   help="adjudicate only the N largest clusters -- a PATH TEST. Numbers are "
                        "not interpretable: the accepted-list never fills up, so duplicate "
                        "detection is not exercised.")
    p.add_argument("--delay", type=float, default=0.0,
                   help="seconds between calls. 0 by default -- the gateway client already "
                        "backs off on 429/5xx, and sequential chat calls are self-pacing.")
    p.add_argument("--fresh", action="store_true", help="ignore the checkpoint and restart")
    p.add_argument("--load", action="store_true", help="re-report the artifact, free")
    p.add_argument("--representatives", choices=("centroid", "judge"), default="centroid",
                   help="centroid = top-6 by cosine to the cluster centroid (default); "
                        "judge = the EXACT 12 strided samples the blind judges saw")
    p.add_argument("--tag", default="",
                   help="suffix BOTH the checkpoint and the artifact. Required to run two arms "
                        "of a paired comparison -- without it they share one checkpoint and one "
                        "output file.")
    p.add_argument("--members-from", default="",
                   help="arm name in artifacts/clustering_bench_members.json whose cluster "
                        "MEMBERSHIPS replace this run's (e.g. rescue_centroid). Cluster order, "
                        "count and keywords are held at the base run's, so membership is the "
                        "only variable. Verified position-for-position against the base.")
    p.add_argument("--force", action="store_true",
                   help="allow overwriting an artifact that holds MORE rows than this run")
    return p.parse_args()


def report(rows: list[dict]) -> None:
    kinds = defaultdict(int)
    for r in rows:
        kinds[r["kind"]] += 1
    n = len(rows) or 1
    coach = kinds["scenario"]
    print("\n" + "=" * 78)
    print(f"ADJUDICATED {len(rows)} CLUSTERS -> REAL SCENARIOS")
    print("=" * 78)
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {k:<14}{v:>5}  ({v/n*100:>5.1f}%)")
    # `merged` means RETAINED -- the cluster is folded into an existing scenario, and
    # production never creates a row for it. So `coach/len(rows)` divides by a denominator the
    # treatment MOVES: growing clusters makes more of them look like duplicates, which shrinks
    # the scenario count and the denominator together and can move the ratio the wrong way.
    # Same collapse-a-four-valued-enum error that produced the phantom "Gemma over-sinks
    # 14.6%" finding. Report both, and compare arms on RETENTION and the re-based share.
    merged = kinds["merged"]
    base = (len(rows) - merged) or 1
    print(f"\n  coachable (raw)      : {coach}/{len(rows)} = {coach/n*100:.1f}%")
    print(f"  coachable (re-based) : {coach}/{base} = {coach/base*100:.1f}%   "
          f"<- comparable to production's 85/161 = 52.8%")
    print(f"  RETAINED (scenario+merged): {coach + merged}/{len(rows)} = "
          f"{(coach + merged)/n*100:.1f}%")
    if any(r.get("failed") for r in rows):
        print(f"  !! failed adjudications: {sum(1 for r in rows if r.get('failed'))}")

    print("\n--- COACHABLE, 12 largest ---")
    for r in [x for x in rows if x["kind"] == "scenario"][:12]:
        print(f"\n  [{r['scenario_key']}]  {r['n_items']} items / {r['calls']} calls "
              f"({r['coverage']:.0%}) | thin {r['thin']:.0%}")
        print(f"    {r['business_description']}")
        print(f"    keyphrases: {r['keyphrases']}")
    print("\n--- SINKS, 8 largest ---")
    for r in [x for x in rows if x["kind"] != "scenario"][:8]:
        print(f"\n  [{r['scenario_key']}] ({r['kind']}) {r['n_items']} items | thin {r['thin']:.0%}")
        print(f"    {r['reason'][:150]}")

    merged = [r for r in rows if r["decision"] == "merge_into"]
    print(f"\n--- DUPLICATE DETECTION: {len(merged)} merge_into decisions ---")
    print("  (this is what the sequential accepted-list buys; 0 would mean it never fired)")
    for r in merged[:6]:
        print(f"    {r['n_items']:>5} items -> {r['merge_into_key']}")

    # The proxy this whole effort has leaned on, now checkable against the real answer.
    thin_hi = [r for r in rows if r["thin"] >= 0.70]
    thin_lo = [r for r in rows if r["thin"] < 0.30]
    if thin_hi:
        s = sum(1 for r in thin_hi if r["kind"] == "scenario")
        print(f"\n--- PROXY vs REALITY ---")
        print(f"  clusters >=70% content-free ('junk' by proxy): {len(thin_hi)}, "
              f"of which Gemma called {s} coachable ({s/len(thin_hi)*100:.0f}%)")
    if thin_lo:
        s = sum(1 for r in thin_lo if r["kind"] == "scenario")
        print(f"  clusters <30% content-free ('subject-bearing'): {len(thin_lo)}, "
              f"of which Gemma called {s} coachable ({s/len(thin_lo)*100:.0f}%)")


def main() -> None:
    a = _args()
    CKPT, OUT = _paths(a.min_cluster_size, a.turn_aware, a.tag)
    if a.load:
        report(json.loads(OUT.read_text(encoding="utf-8-sig"))["rows"])
        return

    from config import load_config
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from shared.prompts import PROMPT_LAYER_A_V2_TRIAGE
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool, fit_topic_model, _KIND_BY_DECISION
    from calibration.trial_gateway import GatewayClient
    from calibration.trial_pool_unit_gemini import embed_cached

    ta = load_tuning().layer_a
    cfg = load_config()
    turns = []
    for f in sorted(Path(a.recordings).glob("*.txt")):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    total_calls = len(set(call_ids))
    print(f"{len(texts)} CLIENT turns over {total_calls} calls")

    vecs = embed_cached(texts, workers=20)          # fully cached from the 3072 run
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    print(f"[embed] {vecs.shape} (cache)")

    print(f"[cluster] min_cluster_size={a.min_cluster_size} "
          f"({a.min_cluster_size/len(texts)*100:.3f}% of pool)...", flush=True)
    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=a.min_cluster_size)
    topics = np.array(topics)
    members = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    cent = np.stack([cluster_evidence.support_stats(
        [call_ids[i] for i in members[t]], vecs[members[t]], total_calls).centroid
        for t in raw_ids])
    groups = cluster_evidence.merge_by_similarity(cent, MERGE)
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor)
    print(f"[cluster] {len(raw_ids)} raw -> {len(groups)} merged at {MERGE}; "
          f"support floor {min_support}")

    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        ctexts = [texts[i] for i in idxs]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=ctexts)
        v = cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling)
        if v == cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        lead = max(tids, key=lambda z: len(members[z]))
        clusters.append({
            "stats": st, "verdict": v, "n_merged": len(tids), "idxs": idxs,
            # STABLE IDENTITY. `i` is a RANK in the largest-first sort, and the rescue changes
            # sizes unequally -- so joining two arms on `i` silently compares different
            # clusters after the first size inversion. The raw-topic id set is invariant under
            # a membership-only rescue by construction, so it is the join key.
            "cluster_id": "-".join(map(str, sorted(tids))),
            "keywords": ", ".join(w for w, _ in tm.get_topic(lead)[:10]),
            "texts": ctexts,
            "thin": float(np.mean([not cluster_evidence.is_substantive(t, 5) for t in ctexts])),
        })
    # LARGEST FIRST -- production's order, and the reason duplicate detection works.
    clusters.sort(key=lambda c: c["stats"].n_items, reverse=True)

    # --- substitute rescued memberships, holding ORDER and KEYWORDS fixed -------------------
    # Deliberate: re-sorting by the grown sizes would move adjudication ORDER, and order
    # cascades through the accepted-list that IS the duplicate-detection mechanism. Holding it
    # fixed makes MEMBERSHIP the single variable. Keywords are c-TF-IDF of the original fit and
    # are likewise held, so exactly one thing differs between arms.
    if a.members_from:
        bench = json.loads((ARTIFACTS_DIR / "clustering_bench.json")
                           .read_text(encoding="utf-8-sig"))
        side = json.loads((ARTIFACTS_DIR / "clustering_bench_members.json")
                          .read_text(encoding="utf-8-sig"))
        if a.members_from not in side.get("arms", {}):
            raise SystemExit(f"no memberships stored for arm {a.members_from!r}")
        base = [sorted(map(int, c["idxs"])) for c in bench["incumbent_clusters"]]
        mine = [sorted(c["idxs"]) for c in clusters]
        if base != mine:
            raise SystemExit(
                f"POSITION CHECK FAILED: this run's {len(mine)} clusters do not match the "
                f"bench's {len(base)} incumbent clusters member-for-member. The rescued "
                f"memberships cannot be aligned; the arm is void.")
        print(f"[members] position check OK -- {len(mine)}/{len(mine)} clusters identical "
              f"to the bench's incumbent")
        new = [sorted(map(int, c)) for c in side["arms"][a.members_from]["clusters"]]
        if len(new) != len(clusters):
            raise SystemExit(f"{a.members_from} has {len(new)} clusters, base has {len(clusters)}")
        grown = 0
        for c, idxs in zip(clusters, new):
            if len(idxs) != len(c["idxs"]):
                grown += 1
            ctexts = [texts[i] for i in idxs]
            c["idxs"] = idxs
            c["texts"] = ctexts
            c["stats"] = cluster_evidence.support_stats(
                [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=ctexts)
            c["thin"] = float(np.mean([not cluster_evidence.is_substantive(t, 5)
                                       for t in ctexts]))
        print(f"[members] substituted {a.members_from}: {grown}/{len(clusters)} clusters grew, "
              f"{sum(len(c['idxs']) for c in clusters)} total member turns "
              f"(order and keywords held fixed)")

    if a.limit:
        clusters = clusters[:a.limit]
        print(f"--limit {a.limit}: PATH TEST ONLY, duplicate detection is not exercised")
    print(f"[adjudicate] {len(clusters)} clusters to judge, SEQUENTIALLY\n", flush=True)

    ident = checkpoint_identity(clusters, a, ta)
    rows, accepted, start = [], [], 0
    if CKPT.exists() and not a.fresh:
        ck = json.loads(CKPT.read_text(encoding="utf-8-sig"))
        old = ck.get("identity")
        if old is not None and old != ident:
            diff = [k for k in ident if old.get(k) != ident[k]]
            raise SystemExit(
                f"CHECKPOINT MISMATCH on {diff} -- {CKPT.name} was built from a DIFFERENT run "
                f"and resuming would BLEND them. Use --tag for this arm, or --fresh.")
        if old is None:
            raise SystemExit(
                f"{CKPT.name} predates the identity guard (it only recorded a cluster COUNT, "
                f"which cannot distinguish a rescued arm from its base). Use --tag or --fresh.")
        if ck.get("n_clusters") == len(clusters):
            rows = ck["rows"]; start = len(rows)
            for r in rows:
                if r["kind"] == "scenario":
                    accepted.append({"scenario_key": r["scenario_key"],
                                     "business_description": r["business_description"],
                                     "centroid": np.array(r["_centroid"], dtype=np.float32)})
            print(f"[resume] {start} already adjudicated\n")

    t0 = time.time()
    with GatewayClient() as gw:
        for i in range(start, len(clusters)):
            c = clusters[i]
            st = c["stats"]
            near = []
            if accepted:
                mat = np.stack([x["centroid"] for x in accepted])
                sims = mat @ st.centroid
                for j in np.argsort(sims)[::-1][:NEAREST_SHOWN]:
                    near.append(f'- {accepted[j]["scenario_key"]} (cosine {sims[j]:.2f}): '
                                f'{accepted[j]["business_description"]}')
            nearest_block = "\n".join(near) or "- (none yet: this is the first cluster considered)"
            coverage_note = (
                "- FLAGGED: this cluster spans an unusually large share of the corpus. That is "
                "characteristic of conversational mechanics, but a core business topic can also "
                "legitimately appear in most calls. Decide from the utterances above which of "
                "the two this is."
                if c["verdict"] == cluster_evidence.NEEDS_REVIEW
                else "- coverage is within the normal range for a specific scenario.")

            # REPRESENTATIVES BY CENTROID COSINE, not by pool position. The old rule showed
            # `texts[:6]`, i.e. the first six by CORPUS FILE ORDER -- so appending rescued
            # turns left the six shown byte-identical and the judge never saw the treatment at
            # all, leaving three integers as the only difference between arms. Ranking by
            # cosine to the cluster's own centroid is deterministic, applies identically to
            # both arms, and lets a rescued turn appear only if it is genuinely central.
            if a.representatives == "judge":
                # SYMMETRY WITH THE BLIND JUDGES. They were shown 12 STRIDED samples while
                # this loop showed Gemma 6 HEAD samples, so the published agreement compared
                # two different views of the same cluster -- different rule AND different
                # size, both letting the judges see substance Gemma could not. Importing
                # their sampler is what makes the comparison like-for-like.
                from calibration.export_cluster_batches import judge_samples
                reps = judge_samples(c["texts"])
            else:
                order = np.argsort(-(vecs[c["idxs"]] @ st.centroid))[:REPRESENTATIVE_SHOWN]
                reps = [c["texts"][int(j)] for j in order]

            prompt = PROMPT_LAYER_A_V2_TRIAGE.format(
                keywords=c["keywords"],
                representative_utterances="\n".join(
                    f"- {' '.join(t.split())}" for t in reps),
                distinct_calls=st.distinct_calls, total_calls=total_calls,
                call_coverage=st.call_coverage, n_clauses=st.n_items,
                n_merged=c["n_merged"], coverage_note=coverage_note,
                nearest_scenarios=nearest_block)
            if a.turn_aware:
                prompt += TURN_AWARE_NOTE

            failed, served = False, ""
            try:
                parsed, meta = gw.chat_json(prompt, model=CHAT_MODEL, temperature=0.2)
                served = (meta or {}).get("served_model") or ""
            except Exception as e:                      # noqa: BLE001
                print(f"  ! cluster {i} failed: {str(e)[:160]}", flush=True)
                failed = True
                parsed = {"decision": "new_scenario", "reason": f"ADJUDICATION FAILED: {e}",
                          "scenario_key": f"failed_cluster_{i}", "sub_topic": "", "keyphrases": []}

            decision = (parsed.get("decision") or "new_scenario").strip()
            kind = _KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)
            key = (parsed.get("scenario_key") or f"cluster_{i}").strip()
            row = {"i": i, "decision": decision,
                   "kind": "merged" if decision == "merge_into" else kind,
                   "merge_into_key": parsed.get("merge_into_key"),
                   "scenario_key": key, "business_description": parsed.get("sub_topic") or "",
                   "keyphrases": parsed.get("keyphrases") or [],
                   "soft_skills": parsed.get("soft_skills") or [],
                   "bloom_level": parsed.get("bloom_level") or "",
                   "reason": (parsed.get("reason") or "").strip(),
                   "n_items": st.n_items, "calls": st.distinct_calls,
                   "coverage": float(st.call_coverage), "thin": c["thin"],
                   "n_merged": c["n_merged"], "keywords": c["keywords"],
                   "cluster_id": c["cluster_id"], "served_model": served, "failed": failed,
                   "triage": c["verdict"], "_centroid": st.centroid.tolist()}
            rows.append(row)
            # A FAILED call must NOT enter the accepted list. The synthesised row defaults to
            # `new_scenario`, so it used to (a) count as coachable and (b) join the "NEAREST
            # SCENARIOS ALREADY ACCEPTED" block with an EMPTY description -- perturbing
            # duplicate detection for every later cluster and becoming a legal merge target.
            # One transport blip would then read as a rescue effect.
            if not failed and decision != "merge_into" and kind == cluster_evidence.KIND_SCENARIO:
                accepted.append({"scenario_key": key,
                                 "business_description": row["business_description"],
                                 "centroid": st.centroid})

            mark = {"scenario": "+", "mechanics": "~", "logistics": "~"}.get(kind, "=")
            if decision == "merge_into":
                mark = "="
            done = i + 1
            rate = done / max(time.time() - t0, 1e-6) if start < done else 0
            print(f"  [{done}/{len(clusters)}] {mark} {key[:44]:<44} "
                  f"{st.n_items:>5}it {st.call_coverage:>4.0%} thin{c['thin']:>4.0%} "
                  f"eta {(len(clusters)-done)/max(rate,1e-6)/60:>4.1f}m", flush=True)

            CKPT.write_text(json.dumps({"n_clusters": len(clusters), "identity": ident,
                                        "rows": rows}, default=float), encoding="utf-8")
            if a.delay:
                time.sleep(a.delay)

    for r in rows:
        r.pop("_centroid", None)
    n_failed = sum(1 for r in rows if r.get("failed"))
    served = defaultdict(int)
    for r in rows:
        served[r.get("served_model") or "(unrecorded)"] += 1
    guard_overwrite(OUT, len(rows), a.force)
    OUT.write_text(json.dumps({"merge": MERGE, "min_cluster_size": a.min_cluster_size,
                               "turn_aware": bool(a.turn_aware),
                               "chat_model": CHAT_MODEL, "embed": "gemini-embedding-2@3072",
                               "members_from": a.members_from or None,
                               "identity": ident, "n_failed": n_failed,
                               "served_models": dict(served), "incomplete": bool(n_failed),
                               "total_calls": total_calls, "rows": rows},
                              indent=1, default=float), encoding="utf-8")
    if n_failed:
        print(f"\n  !! {n_failed} clusters FAILED adjudication and are excluded from the "
              f"accepted list. The artifact is stamped incomplete -- do not compare arms "
              f"whose failure counts differ materially.")
    print(f"  served by: {dict(served)}")
    report(rows)
    print(f"\nwrote {OUT}")
    print("NOTHING was written to Postgres. The live 161 scenarios are untouched.")


if __name__ == "__main__":
    main()
