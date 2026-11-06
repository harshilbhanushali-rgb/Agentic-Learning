#!/usr/bin/env python3
"""BRAIN REBUILD, STAGE C head-to-head: regenerated playbooks vs the live ones.

Spec: docs/superpowers/specs/2026-10-10-brain-rebuild-staged-design.md §C (frozen).

The regenerated set (`pbf_<tag>_snapped.json`, written by playbook_backfill.py on the current
prompts, so the gradability rule is in every document) is compared WITHIN ONE PACKET with the
live document for the same scenario -- the only valid contrast (findings §13: the same items
scored 84% then 17% under two framings, so levels never compare across packets). On
`union_base36` the incumbent is the live document of the scenario's unique old counterpart.

Readers judge every criterion (gradable from a transcript?) and every quote (demonstrates
the move?). 5 planted quotes from other scenarios' documents are the validity check.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/rebuild_stage_c_h2h.py --build --tag rebuild --taxonomy union_base
    # 3 blinded sonnet readers write artifacts/rebuild_c_h2h_judgments_r*.json, ONE AT A TIME
    ..\\.venv\\Scripts\\python.exe calibration/rebuild_stage_c_h2h.py --score --tag rebuild --taxonomy union_base

Zero requests, zero writes outside artifacts/.
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

# ---- frozen (spec §C) -----------------------------------------------------------------
SEED = 42
N_SITUATIONS = 10
STRATA = (4, 3, 3)             # situations per evidence-size tercile, largest first
N_NEG = 5
NEG_REJECT_MIN = 4             # reader VALID iff >= 4/5 planted quotes judged N
N_VALID_READERS = 3
MAJORITY = 2
PROMOTE_MIN = {"union_base": 7, "union_base36": 5}   # situations new must win, of 10
SINGLE_ACCOUNT_MAX = 0.10
COVERAGE_MIN = 0.90
EXCLUDED = ("contract_and_legal_review",)            # on the record: not a retry

LIVE_ARTIFACTS = ("pbf_rest_snapped.json", "pbf_thin_snapped.json",
                  "pbq_36flash_medium_grad_snapped.json")
PACKET = ARTIFACTS_DIR / "rebuild_c_h2h_packet.txt"
KEY = ARTIFACTS_DIR / "rebuild_c_h2h_KEY.json"
JUDGMENTS_GLOB = "rebuild_c_h2h_judgments_*.json"
RESULT_OUT = ARTIFACTS_DIR / "rebuild_c_h2h_result.json"


def _docs(filename: str) -> dict[str, dict]:
    """scenario -> {"playbook", "n_evidence"} for every non-collapsed 'real' document."""
    art = json.loads((ARTIFACTS_DIR / filename).read_text(encoding="utf-8-sig"))
    out = {}
    for d in art["documents"].values():
        if d.get("arm") == "real" and not d.get("snap_log", {}).get("schema_collapsed"):
            out[d["scenario"]] = {"playbook": d["playbook"], "n_evidence": d["n_evidence"]}
    return out


def live_docs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in LIVE_ARTIFACTS:                 # order matters: the grad remakes replace pbv
        out.update(_docs(f))
    return out


def incumbent_of(taxonomy: str, new_keys: list[str]) -> dict[str, str]:
    """new scenario key -> the old key whose live document is its incumbent."""
    if taxonomy == "union_base":
        return {k: k for k in new_keys}
    from calibration.layer_bc_arms import scenario_map_from_rows
    from calibration.rebuild_stage_a_h2h import counterparts
    load = lambda a: json.loads((ARTIFACTS_DIR / f"adjudication_ab_{a}.json")
                                .read_text(encoding="utf-8-sig"))["rows"]
    old_rows, new_rows = load("union_base"), load(taxonomy)
    om, ocok = scenario_map_from_rows(old_rows)
    nm, ncok = scenario_map_from_rows(new_rows)
    cp = counterparts(ocok, new_rows, nm, ncok)
    back: dict[str, list[str]] = {}
    for old, new in cp.items():
        if new and om[old]["is_coachable"]:
            back.setdefault(new, []).append(old)
    return {k: v[0] for k, v in back.items() if len(v) == 1 and k in new_keys}


def floors(tag: str, n_coachable: int) -> dict:
    rows = json.loads((ARTIFACTS_DIR / f"pbf_{tag}_report.json")
                      .read_text(encoding="utf-8-sig"))["rows"]
    kept = [r for r in rows if r["moves"] >= 3]
    moves = sum(r["moves"] for r in kept)
    single = sum(r["single_account"] for r in kept)
    out = {"documents": len(kept), "coachable": n_coachable,
           "coverage": len(kept) / n_coachable if n_coachable else 0.0,
           "pb0_all": all(r["pb0"] for r in kept),
           "single_account_share": single / moves if moves else 1.0}
    out["pass"] = (out["pb0_all"] and out["single_account_share"] <= SINGLE_ACCOUNT_MAX
                   and out["coverage"] >= COVERAGE_MIN)
    return out


# ---------------------------------------------------------------------------------------

def build(tag: str, taxonomy: str) -> None:
    for p in (PACKET, KEY):
        if p.exists():
            raise SystemExit(f"{p.name} exists -- the packet is frozen once built")
    new = _docs(f"pbf_{tag}_snapped.json")
    live = live_docs()
    inc = incumbent_of(taxonomy, sorted(new))
    eligible = sorted(k for k, o in inc.items() if o in live and k not in EXCLUDED)
    if len(eligible) < N_SITUATIONS:
        raise SystemExit(f"only {len(eligible)} situations have both documents; "
                         f"need {N_SITUATIONS}")
    rng = random.Random(SEED)
    ranked = sorted(eligible, key=lambda k: -new[k]["n_evidence"])
    third = len(ranked) // 3
    bands = (ranked[:third], ranked[third:2 * third], ranked[2 * third:])
    picked = []
    for band, n in zip(bands, STRATA):
        picked += rng.sample(band, n)

    items, key_docs, blocks = {}, {}, []
    quote_pool = [(k, ev["quote"]) for k in live if k not in picked
                  for m in live[k]["playbook"]["key_moves"] for ev in m["evidence"]]
    plant_into = set(rng.sample(range(2 * N_SITUATIONS), N_NEG))
    planted = [q for _, q in rng.sample(quote_pool, N_NEG)]
    doc_no = 0
    for s_no, k in enumerate(picked, 1):
        sides = [("new", new[k]["playbook"]), ("old", live[inc[k]]["playbook"])]
        rng.shuffle(sides)
        blocks.append("=" * 74 + f"\nSITUATION {s_no}\n" + "=" * 74)
        for letter, (side, pb) in zip("ab", sides):
            did = f"D{s_no}{letter}"
            key_docs[did] = {"side": side, "situation": s_no, "scenario": k,
                             "incumbent_scenario": inc[k]}
            lines = [f"\n----- DOCUMENT {did} -----"]
            for m_no, m in enumerate(pb["key_moves"], 1):
                cid = f"{did}-M{m_no}-C"
                items[cid] = {"doc": did, "kind": "criterion"}
                lines.append(f"  MOVE {m_no}: {m['name']}\n    [{cid}] CRITERION: {m['criterion']}")
                quotes = [ev["quote"] for ev in m["evidence"]]
                if doc_no in plant_into and m_no == 1:
                    quotes.insert(rng.randrange(len(quotes) + 1), planted.pop())
                    plant = quotes
                else:
                    plant = None
                for q_no, q in enumerate(quotes, 1):
                    qid = f"{did}-M{m_no}-Q{q_no}"
                    is_neg = plant is not None and q not in [ev["quote"] for ev in m["evidence"]]
                    items[qid] = {"doc": did, "kind": "neg" if is_neg else "quote"}
                    lines.append(f"    [{qid}] \"{' '.join(q.split())}\"")
            blocks.append("\n".join(lines))
            doc_no += 1

    header = (
        "PLAYBOOK READ -- coaching moves for recurring client situations in B2B programmatic "
        "job advertising.\n\nEach DOCUMENT lists MOVES. Each move has a CRITERION (what a "
        "customer-success manager's reply must satisfy) and QUOTES from real calls meant to "
        "show an expert making that move. Two documents per situation; ids are opaque.\n\n"
        "Answer every bracketed id:\n"
        "  CRITERION ids: Y if you could grade a real call transcript yes/no against it "
        "(it names something concrete that is present or absent), else N.\n"
        "  QUOTE ids: Y if the quote DEMONSTRATES its move's criterion, else N.\n\n"
        "Return JSON exactly: {\"answers\": {\"<id>\": \"Y\"|\"N\", ...}} covering ALL "
        f"{len(items)} ids.\n\n")
    PACKET.write_text(header + "\n".join(blocks), encoding="utf-8")
    KEY.write_text(json.dumps({"seed": SEED, "tag": tag, "taxonomy": taxonomy,
                               "docs": key_docs, "items": items}, indent=1), encoding="utf-8")
    print(f"wrote {PACKET.name} ({len(items)} ids, {len(picked)} situations) and "
          f"{KEY.name} (KEEP FROM READERS)")


def score(key: dict, judgments: list[dict]) -> dict:
    items, docs = key["items"], key["docs"]
    neg = [i for i, v in items.items() if v["kind"] == "neg"]
    readers = []
    for j in judgments:
        ans = j["answers"]
        missing = [i for i in items if i not in ans]
        if missing:
            raise SystemExit(f"{j['_file']}: PARTIAL read ({len(missing)} missing) -- refused")
        ok = sum(ans[i] == "N" for i in neg)
        readers.append({"file": j["_file"], "neg_ok": ok, "valid": ok >= NEG_REJECT_MIN,
                        "answers": ans})
    valid = [r for r in readers if r["valid"]][:N_VALID_READERS]
    out = {"readers": [{k: r[k] for k in ("file", "neg_ok", "valid")} for r in readers]}
    if len(valid) < N_VALID_READERS:
        out["verdict"] = "INSTRUMENT_INCOMPLETE"
        return out
    situations: dict[int, dict] = {}
    for r in valid:
        share = {}
        for did in docs:
            ids = [i for i, v in items.items() if v["doc"] == did and v["kind"] != "neg"]
            share[did] = sum(r["answers"][i] == "Y" for i in ids) / len(ids)
        for s in {v["situation"] for v in docs.values()}:
            a, b = f"D{s}a", f"D{s}b"
            new_d, old_d = (a, b) if docs[a]["side"] == "new" else (b, a)
            pref = ("new" if share[new_d] > share[old_d] else
                    "old" if share[new_d] < share[old_d] else "none")
            situations.setdefault(s, {"scenario": docs[a]["scenario"], "votes": []})
            situations[s]["votes"].append(pref)
    wins = {"new": 0, "old": 0, "split": 0}
    for s in situations.values():
        side = ("new" if s["votes"].count("new") >= MAJORITY else
                "old" if s["votes"].count("old") >= MAJORITY else "split")
        s["winner"] = side
        wins[side] += 1
    need = PROMOTE_MIN[key["taxonomy"]]
    fl = floors(key["tag"], _n_coachable(key["taxonomy"]))
    out.update({"situations": situations, "wins": wins, "need_new_wins": need,
                "floors": fl,
                "verdict": ("PROMOTE_REGENERATED" if wins["new"] >= need and fl["pass"]
                            else "KEEP_INCUMBENT")})
    return out


def _n_coachable(taxonomy: str) -> int:
    from calibration.layer_bc_arms import scenario_map_from_rows
    rows = json.loads((ARTIFACTS_DIR / f"adjudication_ab_{taxonomy}.json")
                      .read_text(encoding="utf-8-sig"))["rows"]
    m, _ = scenario_map_from_rows(rows)
    return sum(1 for k, v in m.items() if v["is_coachable"] and k not in EXCLUDED)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--tag", default="rebuild")
    p.add_argument("--taxonomy", default="union_base", choices=tuple(PROMOTE_MIN))
    a = p.parse_args()
    if a.build:
        build(a.tag, a.taxonomy)
    elif a.score:
        key = json.loads(KEY.read_text(encoding="utf-8"))
        js = []
        for f in sorted(ARTIFACTS_DIR.glob(JUDGMENTS_GLOB)):
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            d["_file"] = f.name
            js.append(d)
        res = score(key, js)
        RESULT_OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res, indent=1))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
