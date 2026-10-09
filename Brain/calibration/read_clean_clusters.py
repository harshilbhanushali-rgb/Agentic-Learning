#!/usr/bin/env python3
"""Read real turns from the CLEANED-corpus adjudication arms. Free, read-only, no writes.

The adjudication artifacts store each cluster's verdict, keywords and counts but NOT its
member turn indices, so membership is recovered by re-running the SAME production clustering
path (`adjudication_ab.build_clusters`, imported rather than reimplemented) and joining on the
stable `cluster_id`. The join is asserted, not assumed.

ONE UMAP FIT for both arms: the base clusters are built once, sampled, then the rescue rule is
applied to the same objects in place and sampled again. Two separate fits would re-partition
and the two readings would not be of the same clusters.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/read_clean_clusters.py
    ..\\.venv\\Scripts\\python.exe calibration/read_clean_clusters.py --kind mechanics --n 6
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

SEED = 42


def _args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-arm", default="clean_base_b")
    p.add_argument("--rescued-arm", default="clean_rescued")
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--kind", default="scenario,mechanics")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--turns", type=int, default=6)
    return p.parse_args()


def rows_of(arm: str) -> dict:
    f = ARTIFACTS_DIR / f"adjudication_ab_{arm}.json"
    return {r["cluster_id"]: r for r in json.loads(f.read_text(encoding="utf-8-sig"))["rows"]}


def show(tag: str, clusters, rows, texts, call_ids, kinds, n, n_turns, rng, acct):
    from collections import Counter
    by_cid = {c["cluster_id"]: c for c in clusters}
    for kind in kinds:
        sel = [cid for cid, r in rows.items() if r["kind"] == kind and cid in by_cid]
        sel.sort(key=lambda cid: -rows[cid]["n_items"])
        print(f"\n{'=' * 92}\n  {tag}: {len(sel)} clusters of kind '{kind}' -- showing {min(n, len(sel))} largest\n{'=' * 92}")
        for cid in sel[:n]:
            r, c = rows[cid], by_cid[cid]
            labs = [acct[call_ids[i]] for i in c["idxs"] if call_ids[i] in acct]
            top, share = ("-", 0.0)
            if labs:
                t, k = Counter(labs).most_common(1)[0]
                top, share = t, k / len(labs)
            print(f"\n[{r['n_items']:>4} turns / {r['calls']:>3} calls]  {r['scenario_key']}")
            print(f"   desc : {(r['business_description'] or '(none)')[:150]}")
            print(f"   kw   : {r['keywords'][:105]}")
            print(f"   top account: {top} {share*100:.0f}%")
            for i in rng.sample(c["idxs"], min(n_turns, len(c["idxs"]))):
                print(f"     - {' '.join(texts[i].split())[:185]}")


def main() -> None:
    a = _args()
    from calibration.adjudication_ab import build_clusters, compute_rescue
    from calibration.flag_proper_noun_clusters import account_map

    kinds = [k.strip() for k in a.kind.split(",") if k.strip()]
    base_rows, resc_rows = rows_of(a.base_arm), rows_of(a.rescued_arm)
    acct, _ = account_map(a.recordings)

    clusters, texts, call_ids, vecs, total_calls, ta = build_clusters(a.recordings, "", "")
    got = {c["cluster_id"] for c in clusters}
    missing = set(base_rows) - got
    if missing:
        raise SystemExit(f"JOIN FAILED: {len(missing)} cluster_ids in {a.base_arm} are absent "
                         f"from the rebuilt clustering. Membership cannot be trusted.")
    print(f"[join] {len(got)}/{len(base_rows)} cluster_ids reproduced exactly")

    rng = random.Random(SEED)
    show(f"BASE ({a.base_arm})", clusters, base_rows, texts, call_ids, kinds,
         a.n, a.turns, rng, acct)

    n_added = compute_rescue(clusters, vecs, len(texts))
    print(f"\n\n### rescue applied in place: +{n_added} turns ###")
    show(f"RESCUED ({a.rescued_arm})", clusters, resc_rows, texts, call_ids, kinds,
         a.n, a.turns, rng, acct)


if __name__ == "__main__":
    main()
