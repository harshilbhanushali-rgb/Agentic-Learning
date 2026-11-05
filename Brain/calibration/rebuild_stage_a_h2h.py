#!/usr/bin/env python3
"""BRAIN REBUILD, STAGE A head-to-head: does the gemini-3.6-flash map route pairs better?

Spec: docs/superpowers/specs/2026-10-10-brain-rebuild-staged-design.md §A (frozen before
any Stage A request).

`union_base36` re-adjudicates the SAME 307 base clusters as the live `union_base`, so the
cluster geometry is identical and only the model's prose (keys, descriptions, keyphrases --
which ARE the routing vector -- and its coachable/merge calls) differs. The frozen G-R1..G-R4
gates are absolute floors; a G-R4 score from one packet cannot be compared with another
packet's (docs/findings/layer-c-playbook-schema-and-gateway.md §13). This harness is the
within-packet comparison: route every union pair under BOTH maps, keep the pairs whose
assignment CHANGED, and ask blinded readers which of the two labels fits the client turn.

COUNTERPART. Both arms adjudicate the same clusters in the same order, so an old key's home
cluster names its counterpart in the new map: the new key of that cluster, or, when the new
run folded that cluster into another scenario, the scenario it was merged into. A pair is
UNCHANGED iff its new key is its old key's counterpart.

Usage (from Brain/; --g2g3 for base36 must have run first -- it prewarms the new texts):
    ..\\.venv\\Scripts\\python.exe calibration/rebuild_stage_a_h2h.py --build
    # 3 blinded sonnet readers write artifacts/rebuild_a_h2h_judgments_r*.json, ONE AT A TIME
    ..\\.venv\\Scripts\\python.exe calibration/rebuild_stage_a_h2h.py --score

Zero chat requests. --build embeds nothing new if --g2g3 ran (cache-only shim aborts on a miss).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

# ---- frozen (spec §A) -----------------------------------------------------------------
SEED = 42
OLD_ARM, NEW_ARM = "union_base", "union_base36"
N_CHANGED = 60                 # items shown, stratified across the three categories
N_NEG = 6                      # agreed pairs vs their WORST-fitting coachable label
NEG_REJECT_MIN = 5             # reader VALID iff >= 5/6 negatives answered correctly
N_VALID_READERS = 3
MAJORITY = 2                   # an item is decided iff >= 2 of 3 valid readers agree
MIN_CHANGED_SHARE = 0.05       # below this the maps route alike: keep union_base
MIN_DECIDED = 20
WIN_SHARE = 0.60               # new map wins iff >= 60% of decided items AND p < ALPHA
ALPHA = 0.05
CATEGORIES = ("gained", "lost", "moved")   # sink->coachable, coachable->sink, coachable->other
TRIGGER_CHARS = 600

PACKET = ARTIFACTS_DIR / "rebuild_a_h2h_packet.txt"
KEY = ARTIFACTS_DIR / "rebuild_a_h2h_KEY.json"
BUILD_OUT = ARTIFACTS_DIR / "rebuild_a_h2h_build.json"
JUDGMENTS_GLOB = "rebuild_a_h2h_judgments_*.json"
RESULT_OUT = ARTIFACTS_DIR / "rebuild_a_h2h_result.json"


# ---------------------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------------------

def counterparts(old_cluster_of_key: dict[str, str], new_rows: list[dict],
                 new_map: dict[str, dict], new_cluster_of_key: dict[str, str]
                 ) -> dict[str, str | None]:
    """old key -> the new map's key for the same home cluster (None if it failed)."""
    new_key_of_cluster = {c: k for k, c in new_cluster_of_key.items()}
    row_of_cluster = {r.get("cluster_id"): r for r in new_rows}
    coach_by_raw: dict[str, str] = {}
    for k, v in new_map.items():                    # first coachable key per raw key
        if v["is_coachable"]:
            coach_by_raw.setdefault(v["primary_topic"], k)
    out: dict[str, str | None] = {}
    for old_key, cluster in old_cluster_of_key.items():
        r = row_of_cluster.get(cluster)
        if r is None or r.get("failed"):
            out[old_key] = None
        elif r.get("kind") == "merged":
            out[old_key] = coach_by_raw.get(r.get("merge_into_key") or "")
        else:
            out[old_key] = new_key_of_cluster.get(cluster)
    return out


def categorise(old_key: str, new_key: str, old_map: dict, new_map: dict,
               cp: dict[str, str | None]) -> str:
    # Coachability first: a counterpart the new run re-labelled a sink is a LOST pair,
    # however faithfully the key carried over.
    co, cn = old_map[old_key]["is_coachable"], new_map[new_key]["is_coachable"]
    if cn and not co:
        return "gained"
    if co and not cn:
        return "lost"
    if cp.get(old_key) == new_key:
        return "same"
    return "moved" if co else "sink_to_sink"


def stratified(by_cat: dict[str, list], total: int, rng: random.Random) -> list:
    """Equal share per category, topped up from whatever is left when one runs short."""
    cats = [c for c in CATEGORIES if by_cat.get(c)]
    picked, rest = [], []
    per = total // max(len(cats), 1)
    for c in cats:
        pool = by_cat[c][:]
        rng.shuffle(pool)
        picked += pool[:per]
        rest += pool[per:]
    rng.shuffle(rest)
    return picked + rest[:max(total - len(picked), 0)]


def binom_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    pk = [math.comb(n, i) / 2 ** n for i in range(n + 1)]
    obs = pk[k]
    return min(1.0, sum(p for p in pk if p <= obs + 1e-12))


def score(key: dict, judgments: list[dict]) -> dict:
    items = key["items"]
    neg_ids = [i for i, v in items.items() if v["type"] == "neg"]
    readers = []
    for j in judgments:
        ans = j["answers"]
        missing = [i for i in items if i not in ans]
        if missing:
            raise SystemExit(f"{j['_file']}: PARTIAL read ({len(missing)} items missing) -- "
                             f"refused; a rate over a reader-chosen subset is not a rate")
        neg_ok = sum(ans[i] == items[i]["correct"] for i in neg_ids)
        readers.append({"file": j["_file"], "neg_ok": neg_ok,
                        "valid": neg_ok >= NEG_REJECT_MIN, "answers": ans})
    valid = [r for r in readers if r["valid"]][:N_VALID_READERS]
    out = {"readers": [{k: r[k] for k in ("file", "neg_ok", "valid")} for r in readers]}
    if len(valid) < N_VALID_READERS:
        out["verdict"] = "INSTRUMENT_INCOMPLETE"
        return out
    tally = Counter()
    by_cat: dict[str, Counter] = {c: Counter() for c in CATEGORIES}
    for i, v in items.items():
        if v["type"] != "changed":
            continue
        votes = Counter()
        for r in valid:
            a = r["answers"][i]
            votes["new" if a == v["new_side"] else "old" if a in ("A", "B") else "same"] += 1
        side = ("new" if votes["new"] >= MAJORITY else
                "old" if votes["old"] >= MAJORITY else "undecided")
        tally[side] += 1
        by_cat[v["category"]][side] += 1
    decided = tally["new"] + tally["old"]
    share = tally["new"] / decided if decided else 0.0
    p = binom_two_sided(tally["new"], decided)
    win = decided >= MIN_DECIDED and share >= WIN_SHARE and p < ALPHA
    out.update({"tally": dict(tally), "by_category": {c: dict(x) for c, x in by_cat.items()},
                "decided": decided, "new_share": share, "p_two_sided": p,
                "verdict": "NEW_MAP_WINS" if win else "KEEP_UNION_BASE"})
    return out


# ---------------------------------------------------------------------------------------
# --build
# ---------------------------------------------------------------------------------------

def _load(arm: str) -> dict:
    p = ARTIFACTS_DIR / f"adjudication_ab_{arm}.json"
    return json.loads(p.read_text(encoding="utf-8-sig"))


def build() -> None:
    for p in (PACKET, KEY, BUILD_OUT):
        if p.exists():
            raise SystemExit(f"{p.name} exists -- the packet is frozen once built; "
                             f"delete it deliberately to rebuild")
    import numpy as np
    from calibration.layer_bc_arms import (build_pairs, install_embedder_shim,
                                           parse_corpus, prewarm, scenario_map_from_rows)
    from preprocessing import embedder
    from shared.scenario_vectors import scenario_text
    from v1.layer_b import assign_scenarios

    old_art, new_art = _load(OLD_ARM), _load(NEW_ARM)
    if new_art.get("stats", {}).get("failed"):
        print(f"[note] {NEW_ARM} has failed rows; they are excluded from its map")
    old_map, old_cok = scenario_map_from_rows(old_art["rows"])
    new_map, new_cok = scenario_map_from_rows(new_art["rows"])
    cp = counterparts(old_cok, new_art["rows"], new_map, new_cok)

    parsed_old = parse_corpus("recordings")
    parsed_new = parse_corpus("recordings_pull_keep")
    base_pairs = (build_pairs("recordings", "s0", "a0", parsed=parsed_old)
                  + build_pairs("recordings_pull_keep", "s0", "a0", parsed=parsed_new))
    prewarm([scenario_text(v) for v in list(old_map.values()) + list(new_map.values())], 20)
    install_embedder_shim(3072)
    pairs_old = [dict(p) for p in base_pairs]
    pairs_new = [dict(p) for p in base_pairs]
    print(f"[route] {len(base_pairs)} pairs under {OLD_ARM} and {NEW_ARM}...", flush=True)
    assign_scenarios(pairs_old, old_map, None)
    assign_scenarios(pairs_new, new_map, None)

    by_cat: dict[str, list] = {}
    seen: set[str] = set()                    # the corpus holds calls ingested twice
    counts = Counter()
    relevant = 0
    for po, pn in zip(pairs_old, pairs_new):
        cat = categorise(po["scenario_key"], pn["scenario_key"], old_map, new_map, cp)
        counts[cat] += 1
        if (old_map[po["scenario_key"]]["is_coachable"]
                or new_map[pn["scenario_key"]]["is_coachable"]):
            relevant += 1                     # the pairs the product can see, either map
        norm = " ".join(po["trigger_text"].lower().split())
        if norm in seen:
            continue
        seen.add(norm)
        by_cat.setdefault(cat, []).append((po["trigger_text"], po["scenario_key"],
                                           pn["scenario_key"]))
    changed = sum(counts[c] for c in CATEGORIES)
    share = changed / relevant if relevant else 0.0
    summary = {"pairs": len(base_pairs), "counts": dict(counts),
               "coachable_relevant": relevant, "changed": changed, "changed_share": share,
               "coachable_old": sum(v["is_coachable"] for v in old_map.values()),
               "coachable_new": sum(v["is_coachable"] for v in new_map.values()),
               "frozen": {"min_changed_share": MIN_CHANGED_SHARE}}
    print(json.dumps(summary, indent=1))
    if share < MIN_CHANGED_SHARE:
        summary["verdict"] = "NO_MATERIAL_CHANGE_KEEP_UNION_BASE"
        BUILD_OUT.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(f"\n{share:.1%} of coachable-relevant pairs change (< {MIN_CHANGED_SHARE:.0%}): "
              f"the maps route alike. KEEP union_base; no read needed.")
        return

    rng = random.Random(SEED)
    sample = stratified(by_cat, N_CHANGED, rng)
    same_coach = [x for x in by_cat.get("same", []) if old_map[x[1]]["is_coachable"]]
    rng.shuffle(same_coach)
    negs = same_coach[:N_NEG]
    coach_old = [k for k, v in old_map.items() if v["is_coachable"]]
    cvecs = embedder.embed_document_matrix([scenario_text(old_map[k]) for k in coach_old])
    tvecs = embedder.embed_query_matrix([t for t, _, _ in negs])

    def label(s: dict) -> str:
        kp = ", ".join(s.get("keyphrases") or [])
        return f"{s['business_description']}" + (f" (keyphrases: {kp})" if kp else "")

    items, blocks = {}, []
    entries = [("changed", x) for x in sample] + [("neg", x) for x in negs]
    rng.shuffle(entries)
    for n, (kind, (trig, ko, kn)) in enumerate(entries, 1):
        iid = f"q{n:02d}"
        if kind == "changed":
            sides = [("new", label(new_map[kn])), ("old", label(old_map[ko]))]
            rng.shuffle(sides)
            new_side = "A" if sides[0][0] == "new" else "B"
            cat = categorise(ko, kn, old_map, new_map, cp)
            items[iid] = {"type": "changed", "new_side": new_side, "category": cat,
                          "old_key": ko, "new_key": kn}
        else:
            t = tvecs[negs.index((trig, ko, kn))]
            worst = coach_old[int(np.argmin(cvecs @ t))]
            sides = [("right", label(old_map[ko])), ("wrong", label(old_map[worst]))]
            rng.shuffle(sides)
            items[iid] = {"type": "neg", "correct": "A" if sides[0][0] == "right" else "B",
                          "agreed_key": ko, "distractor": worst}
        trig_s = " ".join(trig.split())[:TRIGGER_CHARS]
        blocks.append(f"### {iid}\nCLIENT SAID: \"{trig_s}\"\n"
                      f"A: {sides[0][1]}\nB: {sides[1][1]}\n")

    header = (
        "BLIND READ -- which topic label fits what the client is talking about?\n\n"
        "Each item is one thing a client said on a call with a Joveo customer-success "
        "manager, and two candidate topic labels, A and B. Answer which label better "
        "describes what the CLIENT is talking about in that turn. Answer `same` only when "
        "the two are genuinely equally good or equally bad. Judge the fit of the label to "
        "the turn, not how well the label is written.\n\n"
        "Return JSON exactly: {\"answers\": {\"q01\": \"A\"|\"B\"|\"same\", ...}} covering "
        f"ALL {len(items)} items.\n\n")
    PACKET.write_text(header + "\n".join(blocks), encoding="utf-8")
    KEY.write_text(json.dumps({"seed": SEED, "old": OLD_ARM, "new": NEW_ARM,
                               "items": items}, indent=1), encoding="utf-8")
    summary["n_items"] = len(items)
    BUILD_OUT.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nwrote {PACKET.name} ({len(items)} items) and {KEY.name} (KEEP FROM READERS)")


def score_cmd() -> None:
    key = json.loads(KEY.read_text(encoding="utf-8"))
    js = []
    for f in sorted(ARTIFACTS_DIR.glob(JUDGMENTS_GLOB)):
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        d["_file"] = f.name
        js.append(d)
    res = score(key, js)
    RESULT_OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", action="store_true")
    p.add_argument("--score", action="store_true")
    a = p.parse_args()
    if a.build:
        build()
    elif a.score:
        score_cmd()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
