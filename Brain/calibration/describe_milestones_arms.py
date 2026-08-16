#!/usr/bin/env python3
"""Write the MILESTONE CRITERIA for each Layer B/C arm, so quality can be compared. No DB.

Spec: docs/superpowers/specs/2026-08-16-layer-bc-downstream-validation-design.md

WHAT THIS ADDS. `calibration/layer_bc_arms.py` runs Layer C **Pass 1 only**, which is
Gemma-free: it clusters Naren's response clauses and applies the support gate, producing
milestone CANDIDATES -- groups of sentences with a support count and no text. That is enough to
compare EVIDENCE (how many distinct calls back a milestone, how on-topic its clauses are) and
it is what the arms measured.

It is NOT enough to compare CRITERIA -- the sentence a CSM is actually graded against. That
text comes from Layer C's describe step, which is a Gemma call and was deliberately skipped.
This script runs exactly that step, for every arm, and stores the result locally.

*** TWO DIFFERENT "DESCRIBE" STEPS EXIST AND CONFLATING THEM IS EASY. ***
  Layer A adjudication  -> a SCENARIO's business_description + keyphrases. Already run
                           (~195 calls/arm); it is what layer_b matches against.
  Layer C describe      -> a MILESTONE's label + description + detection_hint. THIS FILE.

PRODUCTION-FAITHFUL BY DEFAULT. `tuning.yaml` ships `layer_c.describe_mode: legacy`, so the
default here is `_describe_milestones_batch` -- production's own function, imported, never
paraphrased. `--mode situated` is available because the situated prompt is the one that can see
the client turn, but it is NOT what ships and must not be mixed across arms.

*** THE LEGACY WRITER IS BLIND, IN BOTH ARMS EQUALLY. *** It sees the scenario KEY STRING and
the clause list -- never a client turn, never the scenario's own description. That is the
documented root cause of 234 of 235 criteria coming out `fixed` with the conditional trigger
firing 0 of 226 times. So an absolute quality ceiling applies here that has nothing to do with
the rescue; only the BETWEEN-ARM difference is attributable.

COST. Legacy batches 5 milestones per call across all scenarios, so it is
ceil(n_milestones / 5) calls per arm -- ~35 for a 171-milestone arm, ~25 for a 123-milestone
one. Zero Postgres writes, zero Pinecone.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/describe_milestones_arms.py --arm base_1 --limit 2
    ..\\.venv\\Scripts\\python.exe calibration/describe_milestones_arms.py --arm base_1
    ..\\.venv\\Scripts\\python.exe calibration/describe_milestones_arms.py --arm rescued
    ..\\.venv\\Scripts\\python.exe calibration/describe_milestones_arms.py --read base_1,rescued
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR


_BARE_KEY = None            # compiled lazily in install_tolerant_gemma


def install_tolerant_gemma() -> dict:
    """Wrap `call_gemma` so a JS-style unquoted-key response is repaired, not fatal.

    *** THIS EXISTS BECAUSE OF A LIVE PRODUCTION BUG, AND IT DOES NOT FIX THAT BUG. ***
    Measured 2026-08-16, reproducibly: `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` on the current
    default model returns a JavaScript object literal --

        [ { id: "scenario::3", label: "Clarify Campaign Structure", ... } ]

    -- with BARE KEYS, despite `response_mime_type="application/json"` being set.
    `shared/gemma.py::_call_once` catches `json.JSONDecodeError` and raises `GemmaError`
    IMMEDIATELY: no retry, no repair, no model escalation. So **production Layer C's describe
    step fails on this model**, which matters because `_DEFAULT_MODEL` was changed to
    `gemini-3.5-flash-lite` on 2026-08-13 and Layer C has not been run since.

    The repair is deliberately narrow and confined to THIS harness: production behaviour must
    not change as a side effect of a measurement. It only quotes bare keys at the start of a
    line, which is the exact shape observed -- values are already quoted, so a colon inside a
    string cannot be hit. It is applied ONLY after a genuine parse failure, so a well-formed
    response takes the untouched path.

    Returns a counter so the report can state how many batches needed repairing. If that count
    is high, the production fix is not optional.
    """
    import json as _json
    import re
    import types as _types
    global _BARE_KEY
    from shared import gemma as _g

    # Patched at the PARSE, not at call_gemma: the GemmaError only carries a 500-char
    # truncated echo of the response, so the full text is unrecoverable by the time it
    # surfaces. `shared/gemma.py` does `import json` and calls `json.loads(text)`, so
    # rebinding that module attribute is the narrowest possible interception -- production's
    # control flow, retries and model escalation are all untouched.
    _BARE_KEY = re.compile(r'^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*):', re.MULTILINE)
    stats = {"parsed": 0, "repaired": 0}

    def loads(s, *args, **kw):
        try:
            out = _json.loads(s, *args, **kw)
            stats["parsed"] += 1
            return out
        except _json.JSONDecodeError:
            repaired = _BARE_KEY.sub(r'\1"\2"\3:', s)
            out = _json.loads(repaired, *args, **kw)   # still bad -> gemma's handler runs
            stats["repaired"] += 1
            return out

    _g.json = _types.SimpleNamespace(
        loads=loads, dumps=_json.dumps, JSONDecodeError=_json.JSONDecodeError)
    return stats


def arm_path(arm: str) -> Path:
    return ARTIFACTS_DIR / f"layer_bc_{arm}.json"


def out_path(arm: str) -> Path:
    if not arm or not arm.replace("_", "").replace("-", "").isalnum():
        raise SystemExit(f"--arm must be alphanumeric, got {arm!r}")
    return ARTIFACTS_DIR / f"layer_bc_{arm}_criteria.json"


def build_items(art: dict, limit: int = 0) -> list[dict]:
    """The describe_items shape `run_layer_c_v2` builds, reproduced from a stored arm.

    Order within a scenario is LOAD-BEARING and preserved: `milestone_id` is the array
    POSITION, and `order`/`total` are shown to the model, so a reshuffle would both change the
    prompt and repoint any downstream reference. `milestones` is already sorted by median
    position in pass1, and dict insertion order is preserved on read-back from JSON.
    """
    items = []
    for key in sorted(art["per_scenario"]):
        s = art["per_scenario"][key]
        ms = s["milestones"]
        if limit and len(items) >= limit:
            break
        for order_idx, m in enumerate(ms):
            items.append({
                "id": f"{key}::{m['cluster_id']}",
                "scenario_key": key,
                "order": order_idx + 1,
                "total": len(ms),
                # Production sends the first 5 clauses, not all of them.
                "clauses": m["clauses"][:5],
                "support_calls": m["support_calls"],
                "support_frac": m["support_frac"],
                "relevance_mean": m["relevance_mean"],
                "cluster_id": s.get("cluster_id", ""),
            })
    return items[:limit] if limit else items


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", default="")
    p.add_argument("--mode", default="legacy", choices=("legacy", "situated"),
                   help="legacy = what ships. Never mix modes across arms.")
    p.add_argument("--limit", type=int, default=0,
                   help="PATH TEST: describe only the first N milestones")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--read", default="", help="comma-separated arms: print criteria, free")
    a = p.parse_args()

    if a.read:
        read([s.strip() for s in a.read.split(",") if s.strip()])
        return
    if not a.arm:
        p.print_help()
        return

    src = arm_path(a.arm)
    if not src.exists():
        raise SystemExit(f"{src.name} not found -- run layer_bc_arms.py --arm {a.arm} first")
    dst = out_path(a.arm)
    if dst.exists() and not a.overwrite:
        raise SystemExit(f"{dst.name} exists. --overwrite to replace, or pick another --arm.")

    art = json.loads(src.read_text(encoding="utf-8-sig"))
    items = build_items(art, a.limit)
    if not items:
        raise SystemExit("no milestones to describe")

    from config import load_config
    from v2.layer_c import (_describe_milestones_batch, _describe_situated,
                            _DESCRIBE_BATCH_SIZE, _FAST_DESCRIBE_MODEL)

    n_calls = (math.ceil(len(items) / _DESCRIBE_BATCH_SIZE) if a.mode == "legacy"
               else len({i["scenario_key"] for i in items}))
    print(f"[describe] arm={a.arm} mode={a.mode}: {len(items)} milestone(s) "
          f"-> ~{n_calls} Gemma call(s)", flush=True)
    if a.limit:
        print(f"--limit {a.limit}: PATH TEST ONLY; artifact stamped incomplete", flush=True)

    parse_stats = install_tolerant_gemma()
    cfg = load_config()
    t0 = time.time()
    fn = _describe_milestones_batch if a.mode == "legacy" else _describe_situated
    # model=None keeps call_gemma's default, i.e. exactly what production Layer C sends.
    descriptions = fn(items, cfg)
    print(f"[describe] {len(descriptions)}/{len(items)} described in "
          f"{(time.time()-t0)/60:.1f}m", flush=True)
    print(f"[parse] {parse_stats['parsed']} clean, {parse_stats['repaired']} REPAIRED "
          f"(bare JS keys). Repairs are a PRODUCTION bug, not a harness quirk -- "
          f"call_gemma raises on them with no retry.", flush=True)

    missing = [i["id"] for i in items if i["id"] not in descriptions]
    if missing:
        # Reported, never absorbed -- an undescribed milestone silently becomes an empty
        # criterion, and a differing miss count between arms is an asymmetry.
        print(f"  ! {len(missing)} milestone(s) came back UNDESCRIBED: {missing[:5]}")

    rows = []
    for i in items:
        d = descriptions.get(i["id"], {})
        rows.append({**i,
                     "label": d.get("label", ""),
                     "description": d.get("description", ""),
                     "detection_hint": d.get("detection_hint", ""),
                     "precondition": d.get("precondition") or None})
    dst.write_text(json.dumps({
        "arm": a.arm, "mode": a.mode, "source": src.name,
        "identity": art.get("identity"), "model_default": _FAST_DESCRIBE_MODEL,
        "n_milestones": len(items), "n_described": len(descriptions),
        "n_undescribed": len(missing), "limit": a.limit or None,
        "json_parse": dict(parse_stats),
        "incomplete": bool(a.limit or missing),
        "criteria": rows}, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {dst}")
    print("NOTHING was written to Postgres.")


def read(arms: list[str]) -> None:
    """Print each arm's criteria, joined on cluster_id so the same cluster lines up."""
    arts = {}
    for n in arms:
        pth = out_path(n)
        if not pth.exists():
            raise SystemExit(f"missing {pth.name}; run --arm {n} first")
        arts[n] = json.loads(pth.read_text(encoding="utf-8-sig"))

    print("=" * 100)
    print("MILESTONE CRITERIA BY ARM")
    print("=" * 100)
    for n in arms:
        d = arts[n]
        blank = sum(1 for r in d["criteria"] if not (r["description"] or "").strip())
        pre = sum(1 for r in d["criteria"] if r.get("precondition"))
        print(f"  {n:<12}{d['n_milestones']:>5} milestones  {d['n_undescribed']:>3} undescribed"
              f"  {blank:>3} blank criteria  {pre:>3} with a precondition"
              f"   mode={d['mode']}"
              + ("   !! INCOMPLETE" if d.get("incomplete") else ""))

    by_cid: dict[str, dict] = {}
    for n in arms:
        for r in arts[n]["criteria"]:
            by_cid.setdefault(r["cluster_id"], {}).setdefault(n, []).append(r)
    shared = [c for c, v in by_cid.items() if len(v) == len(arms) and c]

    print(f"\n  clusters present in ALL arms: {len(shared)}  "
          f"(these are the only fair side-by-side reads)\n")
    for cid in sorted(shared, key=lambda c: -max(len(v) for v in by_cid[c].values()))[:4]:
        print("=" * 100)
        print(f"cluster {cid}")
        for n in arms:
            rows = by_cid[cid][n]
            print(f"\n  --- {n}: {rows[0]['scenario_key']} ({len(rows)} milestones) ---")
            for r in rows[:5]:
                print(f"   [{r['support_calls']:>3} calls / frac {r['support_frac']:.2f}] "
                      f"{r['label'][:70]}")
                print(f"       {' '.join((r['description'] or '(none)').split())[:200]}")


if __name__ == "__main__":
    main()
