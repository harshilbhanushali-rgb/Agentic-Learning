#!/usr/bin/env python3
"""READ REAL CLUSTERS from two clustering arms. Blinded. Free, read-only, no writes.

Spec: docs/superpowers/specs/2026-08-16-layer-a-clustering-method-design.md section 7 --
the reading requirement that gates any adoption verdict.

Every number in `clustering_bench.py` is an aggregate, and this repo's record is that the
aggregate misled it repeatedly: coherence-lift turned out to REWARD junk at cluster level, a
72.7% "orphan rate" turned out to be the fix working, and `implementing_and_maintaining_
tracking_pixels` passed every automated check while really being "the Happy Dance account".
Reading real samples is what exposed all three.

*** IT WRITES TWO FILES AND THE SEPARATION IS THE POINT. ***
    clustering_samples_blind.txt   clusters as GROUP 01..NN, arm identity removed, order
                                   shuffled on a fixed seed
    clustering_samples_key.json    which group came from which arm, with its transferred key
A reader shown the arm grades the arm, not the cluster -- the same discipline the head-to-head
trial, the cluster-adjudication trial and `read_routed_samples.py` all used. Read the blind
file, COMMIT to a verdict per group, THEN open the key. There is no way to un-see it.

Also prints the ACCOUNT-CONCENTRATION check the spec requires: per sampled cluster, the share
of its turns from its single most common account (Avoma roster's modal non-joveo email
domain), against a size-matched random null. This is keyword-ACCOUNT concentration, NOT
proper-noun-ness -- measured corr(propn rate, account lift) = 0.047, so the proper-noun check
misses its own confirmed example.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_clustering_samples.py --arms incumbent,leiden_knn
    ..\\.venv\\Scripts\\python.exe calibration/read_clustering_samples.py --arms incumbent,leiden_knn --unblind
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

BLIND_OUT = ARTIFACTS_DIR / "clustering_samples_blind.txt"
KEY_OUT = ARTIFACTS_DIR / "clustering_samples_key.json"
MEMBERS = ARTIFACTS_DIR / "clustering_bench_members.json"
BENCH = ARTIFACTS_DIR / "clustering_bench.json"
SEED = 42
N_CLUSTERS_PER_ARM = 10
N_TURNS_PER_CLUSTER = 8
NULL_REPS = 200


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arms", required=True, help="exactly two, comma separated")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--unblind", action="store_true",
                   help="print the key. Do NOT run this until verdicts are committed.")
    p.add_argument("--added", action="store_true",
                   help="ADDED-TURN mode: compare what two rescue arms ADD to the SAME "
                        "coachable clusters. See _added_mode's docstring for why this is the "
                        "decisive comparison for a rescue arm and cluster sampling is not.")
    return p.parse_args()


def arm_clusters(name: str, bench: dict, members: dict) -> tuple[list[list[int]], list]:
    """Memberships + transferred keys for one arm, from whichever artifact holds them."""
    a = members.get("arms", {}).get(name)
    if a is not None:
        return [list(map(int, c)) for c in a["clusters"]], list(a["mapped"])
    if name == "incumbent" and bench.get("incumbent_clusters"):
        cl = [list(map(int, c["idxs"])) for c in bench["incumbent_clusters"]]
        return cl, [None] * len(cl)
    raise SystemExit(f"no memberships stored for arm {name!r}. Re-run that arm -- the "
                     f"members sidecar {MEMBERS.name} is written by score_arm.")


def account_concentration(idxs: list[int], call_ids: list[str], acct: dict[str, str],
                          pool_labels: np.ndarray, rng) -> dict:
    """Top-account share for a cluster, against a size-matched random null.

    The null matters: the corpus is itself skewed (one domain is ~20% of accounted turns),
    so a raw share is not evidence of account-glue on its own.
    """
    labs = [acct[call_ids[i]] for i in idxs if call_ids[i] in acct]
    if len(labs) < 4:
        return {"n_accounted": len(labs)}
    top, cnt = Counter(labs).most_common(1)[0]
    share = cnt / len(labs)
    null = [Counter(rng.choice(pool_labels, size=len(labs), replace=False)
                    ).most_common(1)[0][1] / len(labs) for _ in range(NULL_REPS)]
    return {"n_accounted": len(labs), "top_account": top, "top_share": share,
            "null_mean": float(np.mean(null)), "null_p99": float(np.percentile(null, 99)),
            "lift": share - float(np.mean(null)),
            "exceeds_null_p99": bool(share > float(np.percentile(null, 99))),
            "n_accounts": len(set(labs))}


def _added_mode(a, names, texts, call_ids, bench, members, acct, pool_labels) -> None:
    """Read what a rescue arm ADDS, against what its volume-matched placebo adds.

    WHY CLUSTER SAMPLING CANNOT ANSWER THIS. A rescue arm keeps the incumbent's 245 clusters
    and only GROWS them, so sampling 10 clusters per arm independently compares two different
    random draws from the SAME cluster set -- with ~2/3 of clusters being sinks, that measures
    which draw happened to be junk-heavy, not which arm is better. (Done once, in this file's
    first run, and it is why this mode exists.)

    The treatment IS the added turns, so those are what must be read. Both arms add the SAME
    NUMBER of turns to the SAME cluster, so the comparison is exactly the selection rule with
    volume, destination and denominator all held fixed -- the symmetric-filtering rule applied
    to a reading rather than to a metric.

    Restricted to COACHABLE clusters, because those are the only populations the gate scores.
    """
    inc = bench["incumbent_clusters"]
    a_cl = members["arms"][names[0]]["clusters"]
    b_cl = members["arms"][names[1]]["clusters"]
    a_map = members["arms"][names[0]]["mapped"]
    if not (len(inc) == len(a_cl) == len(b_cl)):
        raise SystemExit("--added needs two arms that both grow the incumbent's own clusters")

    rng = random.Random(SEED)
    nprng = np.random.default_rng(SEED)
    orig = [set(map(int, c["idxs"])) for c in inc]
    rows = []
    for ci in range(len(inc)):
        if a_map[ci] is None:
            continue
        add_a = [i for i in map(int, a_cl[ci]) if i not in orig[ci]]
        add_b = [i for i in map(int, b_cl[ci]) if i not in orig[ci]]
        if len(add_a) >= 4 and len(add_b) >= 4:
            rows.append((ci, a_map[ci], add_a, add_b))
    # coachable only: a cluster whose transferred key is a sink is not scored by the gate
    coach = {r["scenario_key"] for r in json.loads(
        (ARTIFACTS_DIR / "adjudicate_gemini_min16.json").read_text(encoding="utf-8-sig")
    )["rows"] if r["kind"] == "scenario"}
    rows = [r for r in rows if r[1] in coach]
    print(f"  {len(rows)} coachable clusters where BOTH arms add >= 4 turns")
    pick = rng.sample(rows, min(N_CLUSTERS_PER_ARM, len(rows)))

    groups, lines = [], [
        "BLIND ADDED-TURN READING.",
        "Each SCENARIO below shows the scenario's own name, then TWO SETS of turns that a "
        "rescue rule proposes ADDING to it. One set was chosen by a similarity rule; the "
        "other was drawn at RANDOM from the discarded pool. Same count, same scenario.",
        "For each scenario answer: which set (A or B) is more ON-TOPIC for that scenario "
        "name? Answer TIE only if they are genuinely indistinguishable.",
        "=" * 78, ""]
    for ci, key, add_a, add_b in pick:
        flip = rng.random() < 0.5           # coin-flip A/B per item, fixed seed
        sets = [("A", add_b), ("B", add_a)] if flip else [("A", add_a), ("B", add_b)]
        groups.append({"cluster": ci, "key": key, "A_is": names[1] if flip else names[0],
                       "B_is": names[0] if flip else names[1],
                       "n_added": len(add_a),
                       "account": account_concentration(add_a, call_ids, acct,
                                                        pool_labels, nprng)})
        lines.append(f"SCENARIO: {key}   ({len(add_a)} turns added by each rule)")
        for tag, idxs in sets:
            lines.append(f"  SET {tag}:")
            for i in rng.sample(idxs, min(5, len(idxs))):
                t = " ".join(texts[i].split())
                lines.append(f"     - {t[:260]}{'...' if len(t) > 260 else ''}")
        lines.append("")
    BLIND_OUT.write_text("\n".join(lines), encoding="utf-8")
    KEY_OUT.write_text(json.dumps({"arms": names, "seed": SEED, "mode": "added",
                                   "groups": groups}, indent=1), encoding="utf-8")
    print(f"\nwrote {BLIND_OUT}  ({len(groups)} scenarios)")
    print(f"wrote {KEY_OUT}  -- DO NOT OPEN until verdicts are committed")


def main() -> None:
    a = _args()
    names = [s.strip() for s in a.arms.split(",") if s.strip()]
    if len(names) != 2:
        raise SystemExit("--arms takes exactly two arm names")

    if a.unblind:
        if not KEY_OUT.exists():
            raise SystemExit("no key file -- generate the blind file first")
        key = json.loads(KEY_OUT.read_text(encoding="utf-8-sig"))
        print(f"\nUNBLINDING {KEY_OUT.name}  (arms: {key['arms']})\n" + "=" * 78)
        if key.get("mode") == "added":
            for g in key["groups"]:
                acc = g.get("account") or {}
                flag = ("  ACCOUNT-GLUE?" if acc.get("exceeds_null_p99") else "")
                print(f"  {g['key']:<52} A={g['A_is']:<16} B={g['B_is']:<16} "
                      f"n={g['n_added']}{flag}")
            return
        for g in key["groups"]:
            acc = g.get("account") or {}
            flag = ""
            if acc.get("exceeds_null_p99"):
                flag = (f"   ACCOUNT-GLUE? top={acc['top_account']} "
                        f"{acc['top_share'] * 100:.0f}% vs null {acc['null_mean'] * 100:.0f}% "
                        f"({acc['n_accounts']} accounts)")
            print(f"  GROUP {g['group']:02d}  arm={g['arm']:<14} n={g['n']:<5} "
                  f"key={g['mapped_key']}{flag}")
        return

    from calibration import routing_bench as rb
    from calibration.flag_proper_noun_clusters import account_map

    bench = json.loads(BENCH.read_text(encoding="utf-8-sig")) if BENCH.exists() else {}
    members = json.loads(MEMBERS.read_text(encoding="utf-8-sig")) if MEMBERS.exists() else {}
    texts, call_ids = rb.build_pool(a.recordings)
    acct, _ = account_map(a.recordings)
    pool_labels = np.array([acct[c] for c in call_ids if c in acct])
    print(f"pool {len(texts)} turns; {len(pool_labels)} carry an account "
          f"({len(set(pool_labels.tolist()))} accounts)")

    if a.added:
        _added_mode(a, names, texts, call_ids, bench, members, acct, pool_labels)
        return

    rng = random.Random(SEED)
    nprng = np.random.default_rng(SEED)
    groups = []
    for name in names:
        clusters, mapped = arm_clusters(name, bench, members)
        # sample from clusters big enough to read; seeded, so the sample is reproducible
        elig = [i for i, c in enumerate(clusters) if len(c) >= N_TURNS_PER_CLUSTER]
        pick = rng.sample(elig, min(N_CLUSTERS_PER_ARM, len(elig)))
        print(f"  {name}: {len(clusters)} clusters, {len(elig)} readable, sampled {len(pick)}")
        for ci in pick:
            idxs = clusters[ci]
            groups.append({
                "arm": name, "n": len(idxs), "mapped_key": mapped[ci] if mapped else None,
                "turns": [texts[i] for i in rng.sample(idxs, N_TURNS_PER_CLUSTER)],
                "account": account_concentration(idxs, call_ids, acct, pool_labels, nprng),
            })

    rng.shuffle(groups)
    lines = [
        "BLIND CLUSTER READING -- verdict each group before opening the key.",
        "For each: COHERENT-SITUATION (one recognisable client situation a coach could "
        "train against) / MIXED (two or more unrelated situations fused) / JUNK "
        "(backchannel, logistics, or glued by a name rather than a situation).",
        "=" * 78, ""]
    for n, g in enumerate(groups, 1):
        g["group"] = n
        lines.append(f"GROUP {n:02d}   ({g['n']} turns)")
        for t in g["turns"]:
            t = " ".join(t.split())
            lines.append(f"   - {t[:300]}{'...' if len(t) > 300 else ''}")
        lines.append("")
    BLIND_OUT.write_text("\n".join(lines), encoding="utf-8")
    KEY_OUT.write_text(json.dumps({"arms": names, "seed": SEED, "groups": groups}, indent=1),
                       encoding="utf-8")
    print(f"\nwrote {BLIND_OUT}  ({len(groups)} groups)")
    print(f"wrote {KEY_OUT}  -- DO NOT OPEN until verdicts are committed")


if __name__ == "__main__":
    main()
