#!/usr/bin/env python3
"""PAIRED ADJUDICATION A/B: does noise-rescue change the taxonomy? ZERO DB writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md
Replaces `trial_adjudicate_gemini.py` for comparison work. That harness was written to
produce ONE taxonomy and is not safe for a paired run; seven defects were found in it by
audit, four of them fatal to an A/B. This file is built for the paired case from the start
and every guard below exists because of a specific one.

THE COMPARISON. Same 23,949-turn pool, same gemini-embedding-2@3072 vectors, same
UMAP+HDBSCAN, same merge(0.97)+triage. One variable:

    base     the 245 surviving clusters
    rescued  the SAME 245 clusters, each grown with previously-discarded turns whose cosine
             to the cluster centroid clears that cluster's own member p25

Cluster COUNT and IDENTITY are unchanged by the rescue -- only membership grows. Run `base`
twice to get the adjudication NOISE FLOOR (Gemma is not deterministic: identical clusters
adjudicated twice previously gave 78 vs 85 coachable). Without that floor an arm difference
cannot be read at all.

*** SEQUENTIAL, AND IT MUST STAY SEQUENTIAL. *** The prompt carries "NEAREST SCENARIOS
ALREADY ACCEPTED" and `accepted` accumulates as the loop runs. That IS the duplicate-detection
mechanism -- it lets the model see it is looking at the 9th acknowledgment variant and answer
`merge_into` instead of minting a near-duplicate. Concurrency was right for embeddings
(independent requests) and is wrong here: this is an ordered dependency.

WHAT THIS FILE DOES DIFFERENTLY, and why each one is not optional
-----------------------------------------------------------------
1. REPRESENTATIVES BY CENTROID COSINE, never by pool position. The old harness showed
   `texts[:6]` -- the first six by CORPUS FILE ORDER. For a rescue arm that appends members
   the six shown stay byte-identical, so the judge never sees the treatment and the arm
   difference collapses to three integers: a guaranteed null. It also broke symmetry against
   `export_cluster_batches.py`, which deliberately strides ("the first N members are whatever
   order HDBSCAN emitted, which can be one call's worth") -- so the published Gemma-vs-blind-
   judges comparison showed the two judges DIFFERENT VIEWS of the same clusters.
2. CHECKPOINT KEYED ON A CONTENT HASH of the memberships, hard-failing on mismatch. Keying on
   cluster COUNT is worse than no key here: the rescue holds the count at 245 by construction,
   so the guard CANNOT fire, and arm 2 resumes arm 1's finished checkpoint, executes
   `range(245, 245)` = nothing, and writes arm 1's verdicts as its own -- a perfect "the
   rescue changes nothing" with zero chat calls. Same class as trial_grader_inputs.py's
   one-integer key (commit 926d6b4).
3. EVERY ARM WRITES TO ITS OWN PATH, and `--arm` is required. No default filename can collide
   with a published baseline, and there is no unconditional write over an existing artifact.
4. STABLE `cluster_id` (the raw-topic id set), because rank is not identity. The rescue
   changes sizes unequally, so the largest-first sort reorders and joining two arms on the
   loop index compares different clusters after the first inversion.
5. A FAILED CALL IS RECORDED AS FAILED. It is not synthesised into `new_scenario`, does not
   count as coachable, and never enters the accepted-list -- where it would carry an empty
   description into the duplicate-detection context of every later cluster.
6. `served_model` IS RECORDED PER ROW. The gateway can answer with a fallback model under
   rate limits (8-18% of batches in a measured run), and an artifact that stamps only what was
   REQUESTED lets two arms be judged by different judges while asserting they were not.
7. ORDER AND KEYWORDS ARE HELD AT THE BASE ARM'S. Re-sorting by grown sizes would move
   adjudication order, and order cascades through the accepted-list; recomputing c-TF-IDF
   would move a second prompt input. Membership is the single variable, deliberately.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/adjudication_ab.py --arm base_a --limit 3   # smoke
    ..\\.venv\\Scripts\\python.exe calibration/adjudication_ab.py --arm base_a
    ..\\.venv\\Scripts\\python.exe calibration/adjudication_ab.py --arm base_b
    ..\\.venv\\Scripts\\python.exe calibration/adjudication_ab.py --arm rescued --members-from rescue_centroid
    ..\\.venv\\Scripts\\python.exe calibration/adjudication_ab.py --compare base_a,base_b,rescued
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

MERGE = 0.97
MIN_CLUSTER_SIZE = 16
CHAT_MODEL = "gemini-3.5-flash-lite"
NEAREST_SHOWN = 3
REPRESENTATIVE_SHOWN = 6
REPRESENTATIVE_RULE = "top_by_centroid_cosine"
BENCH = ARTIFACTS_DIR / "clustering_bench.json"
BENCH_MEMBERS = ARTIFACTS_DIR / "clustering_bench_members.json"
RESCUE_MODE = [""]      # set from --rescue; recorded in the identity so arms cannot blend


def paths(arm: str) -> tuple[Path, Path]:
    """One pair per arm. `--arm` is required precisely so no default can collide with a
    published artifact -- `trial_adjudicate_gemini.py`'s default OUT *was* the baseline."""
    if not arm or not arm.replace("_", "").replace("-", "").isalnum():
        raise SystemExit(f"--arm must be a non-empty alphanumeric name, got {arm!r}")
    return (ARTIFACTS_DIR / f"adjudication_ab_{arm}_ckpt.json",
            ARTIFACTS_DIR / f"adjudication_ab_{arm}.json")


# ---------------------------------------------------------------------------------------
# pure helpers (covered by tests/test_adjudication_ab.py)
# ---------------------------------------------------------------------------------------

def members_sha(clusters: list[dict]) -> str:
    """Content hash of the actual memberships -- the ONE thing the treatment moves."""
    h = hashlib.sha256()
    for c in clusters:
        h.update(b"|" + ",".join(map(str, sorted(c["idxs"]))).encode())
    return h.hexdigest()[:16]


def run_identity(clusters: list[dict], ta) -> dict:
    """Everything that must match for a resume to be the SAME run."""
    return {"members_sha": members_sha(clusters), "n_clusters": len(clusters),
            "min_cluster_size": MIN_CLUSTER_SIZE, "merge": MERGE, "chat_model": CHAT_MODEL,
            "representatives": REPRESENTATIVE_RULE, "no_cache": True,
            "rescue": RESCUE_MODE[0],
            "min_call_support_fraction": ta.min_call_support_fraction,
            "min_call_support_floor": ta.min_call_support_floor,
            "ubiquity_ceiling": ta.ubiquity_ceiling}


def save_checkpoint(path: Path, payload: dict) -> None:
    """Write via a temp file + atomic replace.

    `Path.write_text` truncates before writing, and this file is re-serialised after EVERY
    cluster -- with a 3072-float centroid per scenario row it reaches megabytes, so the
    truncated window is wide and reopened 245 times. A Ctrl-C, OOM or sleep inside it leaves
    invalid JSON, the next run raises JSONDecodeError, and the only recovery is --fresh:
    ~245 paid calls thrown away to protect nothing.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=float), encoding="utf-8")
    os.replace(tmp, path)


def cluster_id(tids: list[int]) -> str:
    """Join key. Invariant under a membership-only rescue; the loop index is NOT."""
    return "-".join(map(str, sorted(tids)))


def pick_representatives(vecs: np.ndarray, idxs: list[int], texts: list[str],
                         centroid: np.ndarray, k: int = REPRESENTATIVE_SHOWN) -> list[str]:
    """The k members closest to the cluster's own centroid, most central first.

    Deterministic and membership-sensitive: a rescued turn appears only if it is genuinely
    central, and identical clusters always yield identical samples. Position-based selection
    (`texts[:k]`) is neither -- it returns whatever HDBSCAN emitted first, which can be one
    call's worth, and is blind to any member appended later.
    """
    if not idxs:
        return []
    order = np.argsort(-(vecs[idxs] @ centroid))[:k]
    return [texts[idxs[int(j)]] for j in order]


def retention_stats(rows: list[dict]) -> dict:
    """`merged` means RETAINED -- the cluster is folded into an existing scenario.

    So `scenario / len(rows)` divides by a denominator the treatment moves: growing clusters
    makes more of them look like duplicates, shrinking numerator and denominator together and
    able to move the ratio the WRONG way. Collapsing this four-valued enum to a boolean is
    what produced the phantom "Gemma over-sinks 14.6%" finding. Report all of it.
    """
    k = Counter(r["kind"] for r in rows)
    n = len(rows) or 1
    scen, merged = k.get("scenario", 0), k.get("merged", 0)
    base = (len(rows) - merged) or 1
    return {"n": len(rows), "scenario": scen, "merged": merged,
            "mechanics": k.get("mechanics", 0), "logistics": k.get("logistics", 0),
            "failed": sum(1 for r in rows if r.get("failed")),
            "share_raw": scen / n, "share_rebased": scen / base,
            "retained": scen + merged, "share_retained": (scen + merged) / n}


def kind_by_cluster(rows: list[dict]) -> dict[str, str]:
    return {r["cluster_id"]: r["kind"] for r in rows if r.get("cluster_id")}


def compare_kinds(a_rows: list[dict], b_rows: list[dict]) -> dict:
    """Per-cluster verdict diff, joined on the STABLE id. Never on the loop index."""
    a, b = kind_by_cluster(a_rows), kind_by_cluster(b_rows)
    shared = sorted(set(a) & set(b))
    flips = [(cid, a[cid], b[cid]) for cid in shared if a[cid] != b[cid]]
    return {"n_shared": len(shared), "n_only_a": len(set(a) - set(b)),
            "n_only_b": len(set(b) - set(a)), "n_flipped": len(flips),
            "flip_rate": len(flips) / len(shared) if shared else float("nan"),
            "transitions": dict(Counter(f"{x}->{y}" for _, x, y in flips)),
            "flips": flips}


# ---------------------------------------------------------------------------------------
# clustering (production entry points, never paraphrased)
# ---------------------------------------------------------------------------------------

def pool_sha(texts: list[str]) -> str:
    import hashlib as _h
    return _h.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:16]


def corpus_files(recordings: str) -> list[Path]:
    """Transcript files for a corpus spec: one directory, or several comma-separated.

    Multi-dir support exists for the union rebuild (`recordings,recordings_pull_keep`).
    Each directory is sorted independently and the blocks are concatenated IN THE ORDER
    GIVEN — the union spec makes the old block's leading position load-bearing (old pool
    index i == union index i), so this function must never re-sort across directories.
    A single-directory spec behaves exactly as the old inline glob did.

    Stems are asserted non-colliding across directories: rosters and account maps join
    on the stem, so a collision would silently cross corpora (the expanded-pool lesson).
    """
    dirs = [d.strip() for d in recordings.split(",") if d.strip()]
    if not dirs:
        raise SystemExit(f"empty --recordings spec {recordings!r}")
    per_dir: list[list[Path]] = []
    for d in dirs:
        fs = sorted(Path(d).glob("*.txt"))
        if not fs:
            raise SystemExit(f"no transcripts in {d}/")
        per_dir.append(fs)
    if len(per_dir) > 1:
        from calibration.expanded_pool_stage1 import assert_no_stem_collision
        seen: set[str] = set()
        for fs in per_dir:
            assert_no_stem_collision(seen, {f.stem for f in fs})
            seen |= {f.stem for f in fs}
    return [f for fs in per_dir for f in fs]


def t2_verdict(stats: dict, served_models: dict,
               max_failed_share: float = 0.05) -> dict:
    """Spec §4 T2 integrity: failed-row share <= 5% (else HALT and ask the operator);
    served_model uniformity reported, shout on mixture.

    Uniformity ignores "(unrecorded)" — that tally key is how a FAILED row's empty
    served_model prints, and counting it would flag a mixture whenever any row failed,
    i.e. exactly when the failed-share check already speaks.
    """
    n = stats.get("n", 0)
    failed = stats.get("failed", 0)
    failed_share = failed / n if n else 0.0
    models = sorted(k for k in served_models if k and k != "(unrecorded)")
    # A SUCCESSFUL row can also tally "(unrecorded)" if the gateway response omitted
    # the model field — excluding the key from uniformity would then mute the mixture
    # shout exactly when the fallback path fired (audit 9.3 finding 1). Surface it.
    unrecorded_successes = max(served_models.get("(unrecorded)", 0) - failed, 0)
    return {"n": n, "failed": failed, "failed_share": failed_share,
            "max_failed_share": max_failed_share,
            "failed_ok": failed_share <= max_failed_share,
            "served_models": dict(served_models),
            "served_uniform": len(models) <= 1 and unrecorded_successes == 0,
            "unrecorded_successes": unrecorded_successes,
            "pass": failed_share <= max_failed_share}


def compute_rescue(clusters: list[dict], vecs, n_texts: int) -> int:
    """Apply the rescue_centroid rule IN PROCESS, rather than loading a stored sidecar.

    The sidecar (`clustering_bench_members.json`) is keyed to one exact pool. The moment the
    corpus changes -- e.g. quarantining the job-interview transcripts -- it describes clusters
    that no longer exist, and loading it would silently align rescued memberships to the wrong
    clusters. Recomputing costs nothing (it is pure cosine arithmetic) and cannot go stale.

    The rule is unchanged and is imported, not re-implemented: a noise turn joins its nearest
    surviving cluster iff its cosine to that centroid clears the cluster's OWN member p25.
    """
    from calibration.clustering_bench import rescue_centroid_additions

    assigned = {i for c in clusters for i in c["idxs"]}
    noise = sorted(set(range(n_texts)) - assigned)

    class _Ctx:                       # rescue_centroid_additions only touches .vecs
        pass
    ctx = _Ctx()
    ctx.vecs = vecs
    adds = rescue_centroid_additions(ctx, clusters, noise)
    for c, a in zip(clusters, adds):
        c["idxs"] = sorted(set(c["idxs"]) | set(a))
    return sum(len(a) for a in adds)


def verify_against_bench(clusters: list[dict]) -> None:
    """EVERY arm must reproduce the bench's 245 incumbent clusters, not just the rescued one.

    This check used to live inside `_substitute` and so ran ONLY for the treatment arm -- the
    asymmetric-guard shape this repo has a standing rule against: the arm that is checked is
    protected, the arms it is compared against are not. A base arm whose fit had drifted (an
    edited `recordings/`, a `tuning.yaml` support-floor change, genuine UMAP drift) would run
    to completion at ~245 paid calls apiece and surface only at --compare, as a differing
    members_sha, with the base<->base pair mislabelled TREATMENT.
    """
    if not BENCH.exists():
        raise SystemExit(f"{BENCH.name} is missing -- it DEFINES the clusters this experiment "
                         "compares against. Run clustering_bench.py --arms incumbent first.")
    bench = json.loads(BENCH.read_text(encoding="utf-8-sig"))
    base = [sorted(map(int, c["idxs"])) for c in bench.get("incumbent_clusters", [])]
    mine = [sorted(c["idxs"]) for c in clusters]
    if base != mine:
        raise SystemExit(
            f"POSITION CHECK FAILED: this run produced {len(mine)} clusters, the bench's "
            f"incumbent has {len(base)}, and they do not match member-for-member. The pool or "
            f"the clustering has drifted, so this arm is NOT comparable to the others. "
            f"Refusing before spending ~{len(mine)} chat calls.")
    print(f"[verify] {len(mine)}/{len(mine)} clusters identical to the bench's incumbent")


def derive_clusters(texts: list[str], call_ids: list[str], vecs: np.ndarray,
                    total_calls: int, tm, topics: np.ndarray, ta) -> list[dict]:
    """Raw HDBSCAN topics -> the adjudication cluster list: production merge(0.97) +
    evidence triage, largest first. Extracted verbatim from build_clusters so the union
    rebuild's Stage B can produce clusters through the SAME code path it adjudicates."""
    from shared import cluster_evidence

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
          f"support floor {min_support}", flush=True)

    clusters = []
    for g in groups:
        tids = [raw_ids[x] for x in g]
        idxs = [i for t in tids for i in members[t]]
        ctexts = [texts[i] for i in idxs]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=ctexts)
        if cluster_evidence.triage(st, min_support, ta.ubiquity_ceiling) == \
                cluster_evidence.INSUFFICIENT_EVIDENCE:
            continue
        lead = max(tids, key=lambda z: len(members[z]))
        clusters.append({
            "stats": st, "verdict": cluster_evidence.triage(st, min_support,
                                                            ta.ubiquity_ceiling),
            "n_merged": len(tids), "idxs": idxs, "cluster_id": cluster_id(tids),
            "keywords": ", ".join(w for w, _ in tm.get_topic(lead)[:10]),
            "thin": float(np.mean([not cluster_evidence.is_substantive(t, 5) for t in ctexts])),
        })
    clusters.sort(key=lambda c: c["stats"].n_items, reverse=True)
    return clusters


def load_persisted_clusters(art: dict, membership: str, texts: list[str],
                            call_ids: list[str], vecs: np.ndarray,
                            total_calls: int) -> list[dict]:
    """Reconstruct the cluster list from a Stage B artifact's persisted memberships.

    WHY LOAD RATHER THAN RE-FIT. The union rebuild persists its one seed-42 clustering
    (both membership sets) at Stage B; adjudicating a fresh fit in this process would
    hang the arm's identity on cross-launch UMAP reproducibility, which this repo treats
    as a property to be verified, never assumed. Loading makes the adjudicated clusters
    provably the persisted ones — the pool sha check in build_clusters plus the
    members_sha in the run identity close the loop.

    Stats and `thin` are recomputed from THIS pool's vectors (pure cosine arithmetic,
    deterministic — the _substitute precedent); cluster_id / keywords / n_merged / the
    triage verdict are carried from the artifact. Order is the artifact's own
    (largest-first at BASE sizes), so a rescued arm keeps the base ordering exactly as
    guard 7 requires.
    """
    from shared import cluster_evidence

    key = f"idxs_{membership}"
    clusters = []
    for c in art["clusters"]:
        idxs = [int(i) for i in c[key]]
        if not idxs:
            raise SystemExit(f"persisted cluster {c.get('cluster_id')!r} has an empty "
                             f"{key} — artifact is malformed")
        ctexts = [texts[i] for i in idxs]
        st = cluster_evidence.support_stats([call_ids[i] for i in idxs], vecs[idxs],
                                            total_calls, texts=ctexts)
        clusters.append({
            "stats": st, "verdict": c["triage_verdict"], "n_merged": c["n_merged"],
            "idxs": idxs, "cluster_id": c["cluster_id"], "keywords": c["keywords"],
            "thin": float(np.mean([not cluster_evidence.is_substantive(t, 5)
                                   for t in ctexts])),
        })
    return clusters


def build_clusters(recordings: str, members_from: str, rescue: str = "",
                   clusters_from: str = "", membership: str = "rescued"):
    from shared import cluster_evidence
    from shared.tuning import load_tuning
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v2.layer_a import build_client_pool, fit_topic_model
    # embed_cache_only, NOT trial_pool_unit_gemini.embed_cached: the latter silently FETCHES
    # and pays for any miss, and a pool that has drifted enough to fail the position check is
    # exactly the pool that would re-embed 24k turns before the check could fire.
    from calibration.routing_bench import embed_cache_only

    ta = load_tuning().layer_a
    cfg = load_config()
    turns = []
    for f in corpus_files(recordings):
        turns.extend(parse_transcript(str(f), cfg.joveo_speakers_lower,
                                      cfg.naren_name_lower, roster=load_roster(str(f))))
    texts, call_ids = build_client_pool(turns, unit="turn")
    total_calls = len(set(call_ids))
    print(f"{len(texts)} CLIENT turns over {total_calls} calls", flush=True)

    vecs = embed_cache_only(texts)
    vecs = (vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)).astype(np.float32)
    print(f"[embed] {vecs.shape} (cache-only; a miss would have aborted)", flush=True)

    if clusters_from:
        # NO FIT IN THIS PROCESS. The clusters were fitted and persisted once (Stage B);
        # this arm must adjudicate exactly those, so it loads them and proves the pool
        # is the same one they were fitted on.
        if members_from or rescue:
            raise SystemExit("--clusters-from is exclusive of --members-from/--rescue: "
                             "the persisted artifact already fixes the memberships.")
        if membership not in ("base", "rescued"):
            raise SystemExit(f"--membership must be base|rescued, got {membership!r}")
        art = json.loads(Path(clusters_from).read_text(encoding="utf-8-sig"))
        want, sha = art["identity"]["pool_sha"], pool_sha(texts)
        if sha != want:
            raise SystemExit(f"POOL MISMATCH: this parse hashes {sha}, the persisted "
                             f"clusters were fitted on {want}. Refusing — the memberships "
                             f"would index the wrong turns.")
        clusters = load_persisted_clusters(art, membership, texts, call_ids, vecs,
                                           total_calls)
        print(f"[clusters-from] {Path(clusters_from).name}: {len(clusters)} clusters, "
              f"membership={membership} (loaded; no fit in this process)", flush=True)
        return clusters, texts, call_ids, vecs, total_calls, ta

    tm, topics = fit_topic_model(texts, vecs, min_cluster_size=MIN_CLUSTER_SIZE)
    topics = np.array(topics)
    clusters = derive_clusters(texts, call_ids, vecs, total_calls, tm, topics, ta)

    # Pin every arm to the same clusters -- but only where a reference for THIS pool exists.
    # Quarantining transcripts changes the pool, so the bench artifact then describes a corpus
    # that is gone; asserting against it would fail for the right reason but block the run.
    sha = pool_sha(texts)
    bench_sha = (json.loads(BENCH.read_text(encoding="utf-8-sig")).get("texts_sha")
                 if BENCH.exists() else None)
    if bench_sha == sha:
        verify_against_bench(clusters)
    else:
        print(f"  !! POOL HAS CHANGED (sha {sha} vs bench {bench_sha}). No stored reference "
              f"exists for this corpus, so the position check is SKIPPED. Arms are still "
              f"mutually comparable -- they share this pool and the members_sha in each "
              f"artifact proves it -- but they are NOT comparable to any earlier run.")
    if rescue == "centroid":
        n = compute_rescue(clusters, vecs, len(texts))
        grown = sum(1 for c in clusters if c)
        print(f"[rescue] centroid p25 rule applied in-process: +{n} turns across "
              f"{len(clusters)} clusters")
        for c in clusters:                     # stats must reflect the grown membership
            ct = [texts[i] for i in c["idxs"]]
            c["stats"] = cluster_evidence.support_stats(
                [call_ids[i] for i in c["idxs"]], vecs[c["idxs"]], total_calls, texts=ct)
            c["thin"] = float(np.mean([not cluster_evidence.is_substantive(t, 5) for t in ct]))
    if members_from:
        if bench_sha != sha:
            raise SystemExit(
                "--members-from loads memberships keyed to the OLD pool and would align them "
                "to clusters that no longer exist. Use --rescue centroid, which recomputes "
                "the same rule against this pool.")
        _substitute(clusters, members_from, texts, call_ids, vecs, total_calls)
    return clusters, texts, call_ids, vecs, total_calls, ta


def _substitute(clusters, members_from, texts, call_ids, vecs, total_calls):
    """Swap in rescued memberships, holding ORDER and KEYWORDS at the base arm's."""
    from shared import cluster_evidence

    side = json.loads(BENCH_MEMBERS.read_text(encoding="utf-8-sig"))
    if members_from not in side.get("arms", {}):
        raise SystemExit(f"no memberships stored for arm {members_from!r}")
    # the position check against the bench already ran, unconditionally, in build_clusters
    new = [sorted(map(int, c)) for c in side["arms"][members_from]["clusters"]]
    if len(new) != len(clusters):
        raise SystemExit(f"{members_from} has {len(new)} clusters, base has {len(clusters)}")
    grown = added = 0
    for c, idxs in zip(clusters, new):
        if not set(c["idxs"]).issubset(set(idxs)):
            raise SystemExit(f"cluster {c['cluster_id']} LOSES members under {members_from}; "
                             "a rescue must only add. Arm void.")
        added += len(idxs) - len(c["idxs"])
        grown += len(idxs) != len(c["idxs"])
        ctexts = [texts[i] for i in idxs]
        c["idxs"] = idxs
        c["stats"] = cluster_evidence.support_stats(
            [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=ctexts)
        c["thin"] = float(np.mean([not cluster_evidence.is_substantive(t, 5) for t in ctexts]))
    print(f"[members] {members_from}: {grown}/{len(clusters)} clusters grew, +{added} turns "
          f"(order and keywords held at the base arm's)")


# ---------------------------------------------------------------------------------------
# run one arm
# ---------------------------------------------------------------------------------------

def run_arm(a) -> None:
    from shared import cluster_evidence
    from shared.prompts import PROMPT_LAYER_A_V2_TRIAGE
    from v2.layer_a import _KIND_BY_DECISION
    from calibration.trial_gateway import GatewayClient

    # For a clusters-from arm the "rescue" identity slot records WHICH persisted
    # membership set is being adjudicated — two arms differing only in that must never
    # resume each other's checkpoints (members_sha would also differ, but the identity
    # should say WHY, not just THAT).
    RESCUE_MODE[0] = (a.rescue or
                      (f"clusters_from:{Path(a.clusters_from).name}:{a.membership}"
                       if a.clusters_from else ""))
    CKPT, OUT = paths(a.arm)
    clusters, texts, call_ids, vecs, total_calls, ta = build_clusters(
        a.recordings, a.members_from, a.rescue, a.clusters_from, a.membership)
    if a.limit:
        clusters = clusters[:a.limit]
        print(f"--limit {a.limit}: PATH TEST ONLY -- the accepted-list never fills, so "
              f"duplicate detection is not exercised and the numbers are not interpretable")

    ident = run_identity(clusters, ta)
    rows, accepted, start, attempts = [], [], 0, 0
    if CKPT.exists() and not a.fresh:
        ck = json.loads(CKPT.read_text(encoding="utf-8-sig"))
        if ck.get("identity") != ident:
            diff = [k for k in ident if (ck.get("identity") or {}).get(k) != ident[k]]
            raise SystemExit(f"CHECKPOINT MISMATCH on {diff or '(no identity recorded)'} -- "
                             f"{CKPT.name} is from a DIFFERENT run and resuming would BLEND "
                             f"them. Use a different --arm, or --fresh.")
        rows = ck["rows"]
        start = len(rows)
        # Older checkpoints carry no attempt counter; rows is the floor (1 POST each).
        attempts = int(ck.get("attempts", len(rows)))
        for r in rows:
            if r["kind"] == "scenario" and not r.get("failed"):
                accepted.append({"scenario_key": r["scenario_key"],
                                 "business_description": r["business_description"],
                                 "centroid": np.array(r["_centroid"], dtype=np.float32)})
        print(f"[resume] {start} already adjudicated ({attempts} attempts)\n")

    # BUDGET STOP BEFORE ANY SPEND. One cluster costs exactly one POST when --budget is
    # set (max_retries=1 below), so the whole spend is known here — refusing now costs
    # nothing; discovering it at cluster 500 costs the operator's whole allowance.
    if a.budget and attempts + (len(clusters) - start) > a.budget:
        raise SystemExit(
            f"BUDGET STOP BEFORE SPEND: {len(clusters) - start} clusters to adjudicate "
            f"(+{attempts} attempts already made) would exceed the frozen hard stop of "
            f"{a.budget} chat calls. HALT — ask the operator.")

    print(f"[adjudicate] arm={a.arm} {len(clusters)} clusters, SEQUENTIALLY"
          + (f", budget {a.budget}" if a.budget else "") + "\n", flush=True)
    t0 = time.time()
    # max_retries=1 under a budget: one POST per attempt so the harness-side counter is
    # exact (the snap-trial discipline). Without a budget the historical default holds.
    with (GatewayClient(max_retries=1) if a.budget else GatewayClient()) as gw:
        for i in range(start, len(clusters)):
            c = clusters[i]
            st = c["stats"]
            near = []
            if accepted:
                sims = np.stack([x["centroid"] for x in accepted]) @ st.centroid
                for j in np.argsort(sims)[::-1][:NEAREST_SHOWN]:
                    near.append(f'- {accepted[j]["scenario_key"]} (cosine {sims[j]:.2f}): '
                                f'{accepted[j]["business_description"]}')
            reps = pick_representatives(vecs, c["idxs"], texts, st.centroid)
            prompt = PROMPT_LAYER_A_V2_TRIAGE.format(
                keywords=c["keywords"],
                representative_utterances="\n".join(
                    f"- {' '.join(t.split())}" for t in reps),
                distinct_calls=st.distinct_calls, total_calls=total_calls,
                call_coverage=st.call_coverage, n_clauses=st.n_items,
                n_merged=c["n_merged"],
                coverage_note=("- FLAGGED: this cluster spans an unusually large share of the "
                               "corpus. That is characteristic of conversational mechanics, but "
                               "a core business topic can also legitimately appear in most "
                               "calls. Decide from the utterances above which of the two this "
                               "is." if c["verdict"] == cluster_evidence.NEEDS_REVIEW
                               else "- coverage is within the normal range for a specific "
                                    "scenario."),
                nearest_scenarios="\n".join(near)
                or "- (none yet: this is the first cluster considered)")

            # Attempt counted and PERSISTED BEFORE the POST (snap-trial discipline): a
            # kill between the save and the response still shows the spend happened.
            if a.budget and attempts >= a.budget:
                raise SystemExit(f"HARD STOP: {attempts} chat attempts made (frozen "
                                 f"budget {a.budget}). Ask the operator.")
            attempts += 1
            save_checkpoint(CKPT, {"identity": ident, "rows": rows,
                                   "attempts": attempts})
            failed, served, parsed = False, "", {}
            try:
                parsed, meta = gw.chat_json(prompt, model=CHAT_MODEL, temperature=0.2,
                                            no_cache=True)
                served = (meta or {}).get("served_model") or ""
            except Exception as e:                      # noqa: BLE001
                print(f"  ! cluster {i} FAILED: {str(e)[:160]}", flush=True)
                failed = True

            decision = (parsed.get("decision") or "new_scenario").strip()
            kind = _KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)
            key = (parsed.get("scenario_key") or f"cluster_{i}").strip()
            row = {"i": i, "cluster_id": c["cluster_id"],
                   "decision": "FAILED" if failed else decision,
                   # A failed call is NOT a scenario. Recording it as one both inflates the
                   # coachable count and (via `accepted`) perturbs duplicate detection for
                   # every later cluster -- one transport blip reading as a treatment effect.
                   "kind": "failed" if failed
                           else ("merged" if decision == "merge_into" else kind),
                   "failed": failed, "served_model": served,
                   "merge_into_key": parsed.get("merge_into_key"),
                   "scenario_key": key, "business_description": parsed.get("sub_topic") or "",
                   "keyphrases": parsed.get("keyphrases") or [],
                   "soft_skills": parsed.get("soft_skills") or [],
                   "bloom_level": parsed.get("bloom_level") or "",
                   "reason": (parsed.get("reason") or "").strip(),
                   "n_items": st.n_items, "calls": st.distinct_calls,
                   "coverage": float(st.call_coverage), "thin": c["thin"],
                   "n_merged": c["n_merged"], "keywords": c["keywords"],
                   "triage": c["verdict"]}
            rows.append(row)
            if not failed and decision != "merge_into" \
                    and kind == cluster_evidence.KIND_SCENARIO:
                # ONLY these rows are re-read on resume, so only these carry a 3072-float
                # centroid into the checkpoint -- ~6x smaller file, ~6x narrower write window.
                row["_centroid"] = st.centroid.tolist()
                accepted.append({"scenario_key": key,
                                 "business_description": row["business_description"],
                                 "centroid": st.centroid})

            done = i + 1
            rate = done / max(time.time() - t0, 1e-6) if start < done else 0
            print(f"  [{done}/{len(clusters)}] {row['kind'][:4]:<4} {key[:42]:<42} "
                  f"{st.n_items:>5}it {st.call_coverage:>4.0%} "
                  f"eta {(len(clusters)-done)/max(rate,1e-6)/60:>4.1f}m", flush=True)
            save_checkpoint(CKPT, {"identity": ident, "rows": rows,
                                   "attempts": attempts})

    for r in rows:
        r.pop("_centroid", None)
    stats = retention_stats(rows)
    served_tally = dict(Counter(r.get("served_model") or "(unrecorded)" for r in rows))
    OUT.write_text(json.dumps(
        {"arm": a.arm, "members_from": a.members_from or None,
         "clusters_from": a.clusters_from or None,
         "membership": (a.membership if a.clusters_from else None),
         "identity": ident,
         "merge": MERGE, "min_cluster_size": MIN_CLUSTER_SIZE, "chat_model": CHAT_MODEL,
         "representatives": REPRESENTATIVE_RULE, "embed": "gemini-embedding-2@3072",
         "total_calls": total_calls, "limit": a.limit or None,
         "incomplete": bool(stats["failed"] or a.limit),
         "chat_attempts": attempts, "budget": a.budget or None,
         "served_models": served_tally, "stats": stats, "rows": rows},
        indent=1, default=float), encoding="utf-8")
    report_arm(a.arm, stats, served_tally)
    print(f"\nwrote {OUT}")
    print("NOTHING was written to Postgres.")


def report_arm(arm: str, s: dict, served: dict) -> None:
    print("\n" + "=" * 78)
    print(f"ARM {arm}: {s['n']} clusters adjudicated")
    print("=" * 78)
    for k in ("scenario", "merged", "mechanics", "logistics", "failed"):
        if s[k]:
            print(f"  {k:<12}{s[k]:>5}")
    print(f"\n  coachable (raw)      : {s['scenario']}/{s['n']} = {s['share_raw']*100:.1f}%")
    print(f"  coachable (re-based) : {s['scenario']}/{s['n']-s['merged']} = "
          f"{s['share_rebased']*100:.1f}%   <- `merged` means RETAINED, so this is the "
          f"figure comparable to production")
    print(f"  RETAINED             : {s['retained']}/{s['n']} = {s['share_retained']*100:.1f}%")
    if s["failed"]:
        print(f"  !! {s['failed']} FAILED -- artifact stamped incomplete; do not compare "
              f"against an arm with a different failure count")
    print(f"  served by: {served}")


# ---------------------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------------------

def compare(names: list[str]) -> None:
    arts = {}
    for n in names:
        _, out = paths(n)
        if not out.exists():
            raise SystemExit(f"missing artifact for arm {n!r} ({out.name})")
        arts[n] = json.loads(out.read_text(encoding="utf-8-sig"))

    print("\n" + "=" * 92)
    print("PAIRED ADJUDICATION A/B")
    print("=" * 92)
    print(f"  {'arm':<12}{'n':>5}{'scen':>6}{'merg':>6}{'mech':>6}{'logi':>6}{'fail':>6}"
          f"{'coach(rebased)':>16}{'retained':>10}")
    for n in names:
        s = arts[n]["stats"]
        print(f"  {n:<12}{s['n']:>5}{s['scenario']:>6}{s['merged']:>6}{s['mechanics']:>6}"
              f"{s['logistics']:>6}{s['failed']:>6}{s['share_rebased']*100:>15.1f}%"
              f"{s['share_retained']*100:>9.1f}%")

    incomplete = [n for n in names if arts[n].get("incomplete")]
    if incomplete:
        print(f"\n  !! INCOMPLETE arms (failures or --limit): {incomplete}. Not comparable.")

    # THE FULL identity, not just members_sha. `chat_model` is a module constant: edit it
    # between two base arms and members_sha stays byte-identical, so a members_sha-only check
    # would label two differently-judged runs a NOISE FLOOR. Same for merge / min_cluster_size
    # / the representative rule / the three triage knobs.
    ident = {n: arts[n]["identity"]["members_sha"] for n in names}
    print(f"\n  members_sha: {ident}")
    ref = arts[names[0]]["identity"]
    for n in names[1:]:
        other = arts[n]["identity"]
        drift = {k: (ref.get(k), other.get(k)) for k in set(ref) | set(other)
                 if k != "members_sha" and ref.get(k) != other.get(k)}
        if drift:
            print(f"  !! {names[0]} vs {n}: IDENTITY DIFFERS beyond membership -> {drift}\n"
                  f"     These arms are not comparable; something other than the treatment "
                  f"moved.")

    # Model provenance: recording served_model per row is pointless if the comparison never
    # reads it. The gateway can answer with a fallback under rate limits (8-18% of batches in
    # a measured run), which would confound a treatment flip rate against a noise floor.
    tallies = {n: arts[n].get("served_models", {}) for n in names}
    print(f"\n  served_models per arm:")
    for n in names:
        print(f"    {n:<12}{tallies[n]}")
    if len({tuple(sorted(t)) for t in tallies.values()}) > 1:
        print("  !! ARMS WERE JUDGED BY DIFFERENT MODEL SETS -- any flip rate below is "
              "model-confounded, not a treatment effect.")

    same = [n for n in names if ident[n] == ident[names[0]]]
    print(f"\n  arms sharing arm-0's memberships (i.e. NOT the treatment): {same}")

    print("\n  PAIRWISE VERDICT FLIPS (joined on stable cluster_id, never the loop index)")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            d = compare_kinds(arts[a]["rows"], arts[b]["rows"])
            same_members = ident[a] == ident[b]
            tag = "NOISE FLOOR" if same_members else "TREATMENT"
            print(f"\n  {a} -> {b}   [{tag}: memberships "
                  f"{'IDENTICAL' if same_members else 'DIFFER'}]")
            print(f"    shared clusters {d['n_shared']}, flipped {d['n_flipped']} "
                  f"= {d['flip_rate']*100:.1f}%")
            if d["n_only_a"] or d["n_only_b"]:
                print(f"    !! only-in-{a}: {d['n_only_a']}, only-in-{b}: {d['n_only_b']} "
                      f"-- the cluster sets differ, which they must not")
            for t, c in sorted(d["transitions"].items(), key=lambda x: -x[1]):
                print(f"      {t:<26}{c:>4}")
    print("\n  A TREATMENT flip rate must be read against the NOISE FLOOR flip rate above it. "
          "\n  If they are comparable, the treatment did nothing this run can detect.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default="", help="arm name; required to run. Names its own files.")
    p.add_argument("--members-from", default="",
                   help="arm in clustering_bench_members.json whose memberships replace this "
                        "run's (e.g. rescue_centroid). Order and keywords stay the base arm's.")
    p.add_argument("--rescue", default="", choices=("", "centroid"),
                   help="compute the rescue rule IN PROCESS against this pool, instead of "
                        "loading a sidecar keyed to an older one")
    p.add_argument("--clusters-from", default="",
                   help="path to a persisted clustering artifact (union rebuild Stage B); "
                        "loads its memberships instead of fitting, after a pool-sha check")
    p.add_argument("--membership", default="rescued", choices=("base", "rescued"),
                   help="which persisted membership set --clusters-from adjudicates")
    p.add_argument("--budget", type=int, default=0,
                   help="HARD STOP on total chat attempts (0 = historical behaviour). "
                        "Sets max_retries=1 so attempts == POSTs, and persists the "
                        "attempt count BEFORE each POST.")
    p.add_argument("--recordings", default="recordings",
                   help="one directory, or several comma-separated (blocks concatenate "
                        "in the order given; stems asserted non-colliding)")
    p.add_argument("--limit", type=int, default=0, help="PATH TEST only; marks artifact incomplete")
    p.add_argument("--fresh", action="store_true", help="ignore the checkpoint and restart")
    p.add_argument("--compare", default="", help="comma-separated arm names to compare")
    a = p.parse_args()
    if a.compare:
        compare([s.strip() for s in a.compare.split(",") if s.strip()])
    elif a.arm:
        run_arm(a)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
