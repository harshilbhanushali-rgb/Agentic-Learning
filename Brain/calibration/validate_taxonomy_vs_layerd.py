#!/usr/bin/env python3
"""Validate a Layer A taxonomy against what Layer D actually needs. No chat calls, no DB writes.

Everything measured about the turn-mode taxonomy so far is UPSTREAM of the thing that
matters: coherence, content-free share, blind judges. None of it says Layer D works better.
These three tests are the cheapest things that speak to that, and all are read-only.

TEST 1 -- RUBRIC-LOOKUP BEHAVIOUR. Layer D's first action on a CSM call is matching a client
turn to a scenario, against `business_description + keyphrases` -- pure Layer A output. A turn
whose best match is a SINK is rejected as "not a signal"; that rejection is the only mechanism
stopping "Thank you." being scored as coaching. Production rejects 60.7% of client turns and
its top rejections read correctly. This re-runs that decision under both taxonomies.

TEST 2 -- COVERAGE OF KNOWN COACHING MOMENTS. `gap_events` holds real moments the 100-call
Layer D run already identified as coachable. Real client turns from those scenarios are routed
through both taxonomies: a turn the NEW taxonomy sinks is a coaching moment it would silently
stop finding. A taxonomy that cannot home what Layer D already found is worse however clean
its clusters look.

TEST 3 -- RUBRIC-LESS SCENARIOS. A coachable scenario with too little response evidence gets
no rubric (`skipped_insufficient_responses`) and Layer D then emits `Rubric_Coverage_Gap`:
recognised, coachable, unscoreable.

FAIRNESS. Both taxonomies are embedded with the SAME model, so only the taxonomy differs.
Embedding each with its own production embedder would confound taxonomy against embedder --
the asymmetric-comparison trap this codebase has hit repeatedly. `task_type` is inert on this
backend, so bge's embed_query/embed_document split has no analogue and neither side gets it.

CONNECTION DISCIPLINE. Every DB read happens up front and the connection is CLOSED before any
embedding. Holding it across ~6 minutes of embedding is what killed the first attempt -- Neon
drops the idle connection and the next query dies. `storage.reconnect_if_closed` exists for
that failure, but the real fix is not to span slow work with an open connection at all.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/validate_taxonomy_vs_layerd.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

NEW_ARTIFACT = ARTIFACTS_DIR / "adjudicate_gemini_min16.json"
MIN_MILESTONE_CALLS_FLOOR = 3          # layer_c.min_milestone_calls_floor


def _pct(a):
    return "  ".join(f"p{q}={np.percentile(a, q):.3f}" for q in (10, 25, 50, 75, 90))


def load_old(conn):
    """Live production taxonomy. Sinks INCLUDED -- they ARE the rejection mechanism."""
    with conn.cursor() as cur:
        cur.execute("SELECT scenario_key, business_description, keyphrases, is_coachable "
                    "FROM public.scenarios")
        return [{"key": k, "text": (bd or "") + " " + " ".join(kp or []),
                 "coachable": bool(c)} for k, bd, kp, c in cur.fetchall()]


def load_new():
    """Turn-mode taxonomy. `merged` rows are EXCLUDED: a merge_into folds the cluster into an
    existing scenario and the prompt leaves its own description null, so it is not a separate
    matchable entry. Counting merges as sinks is exactly the bug that produced a phantom
    'Gemma over-sinks 14.6% of the corpus' finding earlier in this effort."""
    rows = json.loads(NEW_ARTIFACT.read_text(encoding="utf-8-sig"))["rows"]
    out = []
    for r in rows:
        if r["kind"] == "merged":
            continue
        text = (r["business_description"] or "") + " " + " ".join(r["keyphrases"] or [])
        if text.strip():
            out.append({"key": r["scenario_key"], "text": text,
                        "coachable": r["kind"] == "scenario"})
    return out


def csm_client_turns(cfg):
    from ego_trap import transcript_parser as etp
    base = Path("csm_recordings")
    mapping = {}
    mp = base / "mapping.csv"
    if mp.exists():
        with mp.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                mapping[Path(row.get("filename", "")).stem] = row.get("csm_name", "")
    turns = []
    for f in sorted(base.glob("*.txt")):
        # csm_name_lower is lowercased BY CONTRACT -- _classify compares against a lowered
        # speaker line, so the raw name would silently classify the CSM as THE CLIENT. Same
        # fail-open documented for JOVEO_SPEAKER_NAMES.
        csm = mapping.get(f.stem, "").strip().lower()
        for t in etp.parse_transcript(str(f), csm, cfg.joveo_speakers_lower):
            if t.role is etp.EgoTrapRole.CLIENT:
                s = " ".join((t.text or "").split())
                if s:
                    turns.append(s)
    return turns


def match(turn_vecs, tax, embed):
    vecs = embed([t["text"] for t in tax])
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
    sims = turn_vecs @ vecs.T
    order = np.argsort(-sims, axis=1)
    best, second = order[:, 0], order[:, 1]
    bs = sims[np.arange(len(sims)), best]
    ss = sims[np.arange(len(sims)), second]
    coach = np.array([t["coachable"] for t in tax])
    return {"best": best, "best_sim": bs, "margin": bs - ss,
            "accepted": coach[best], "keys": [t["key"] for t in tax]}


def main() -> None:
    from config import load_config
    from calibration.trial_pool_unit_gemini import embed_cached
    import psycopg

    cfg = load_config()
    url = cfg.database_url + ("&" if "?" in cfg.database_url else "?") + "hostaddr=18.138.49.39"

    print("loading CSM client turns...", flush=True)
    turns = csm_client_turns(cfg)
    print(f"  {len(turns)} CSM client turns from csm_recordings/")

    with psycopg.connect(url, autocommit=True, connect_timeout=20) as conn:
        old = load_old(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.gap_events")
            n_gap = cur.fetchone()[0]
            cur.execute("SELECT scenario_key, count(*) FROM public.gap_events "
                        "GROUP BY 1 ORDER BY 2 DESC")
            gap_by_scen = cur.fetchall()
            cur.execute("SELECT trigger_text FROM public.kb_pairs "
                        "WHERE scenario_key IN (SELECT DISTINCT scenario_key FROM public.gap_events) "
                        "AND length(trim(trigger_text)) > 20 ORDER BY random() LIMIT 600")
            gap_turns = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT rubric_status, count(*) FROM public.scenarios "
                        "GROUP BY 1 ORDER BY 2 DESC")
            rubric_status = cur.fetchall()

    new = load_new()
    print(f"  OLD taxonomy: {len(old)} entries ({sum(t['coachable'] for t in old)} coachable)")
    print(f"  NEW taxonomy: {len(new)} entries ({sum(t['coachable'] for t in new)} coachable)")

    print("embedding CSM turns (cached after the first run)...", flush=True)
    tv = embed_cached(turns, workers=20)
    tv = tv / (np.linalg.norm(tv, axis=1, keepdims=True) + 1e-10)
    emb = lambda texts: embed_cached(texts, workers=20)

    print("=" * 78)
    print("TEST 1 -- RUBRIC LOOKUP: how each taxonomy routes real CSM client turns")
    print("=" * 78)
    res = {}
    for name, tax in (("OLD (production)", old), ("NEW (turn mode)", new)):
        r = match(tv, tax, emb)
        res[name] = r
        acc = r["accepted"]
        print(f"{name}")
        print(f"  accepted as signal : {acc.sum():>5}/{len(acc)} ({acc.mean()*100:>5.1f}%)")
        print(f"  rejected to a sink : {(~acc).sum():>5}/{len(acc)} ({(~acc).mean()*100:>5.1f}%)"
              f"   [production reference: 60.7% rejected]")
        print(f"  best-match cosine  : {_pct(r['best_sim'])}")
        print(f"  top1-top2 margin   : {_pct(r['margin'])}   mean {r['margin'].mean():.4f}")

    a, b = res["OLD (production)"], res["NEW (turn mode)"]
    print(f"  agree on accept/reject for {(a['accepted'] == b['accepted']).mean()*100:.1f}% of turns")
    print(f"  NEW accepts, OLD rejects: {int((b['accepted'] & ~a['accepted']).sum())}")
    print(f"  OLD accepts, NEW rejects: {int((a['accepted'] & ~b['accepted']).sum())}")
    print("  --- 6 turns OLD accepts but NEW rejects (the RISK side) ---")
    for i in np.where(a["accepted"] & ~b["accepted"])[0][:6]:
        print(f"    {turns[i][:92]}")
        print(f"       OLD -> {a['keys'][a['best'][i]][:40]:<40} NEW -> {b['keys'][b['best'][i]][:32]} (sink)")

    print("=" * 78)
    print("TEST 2 -- COVERAGE OF MOMENTS LAYER D ALREADY CALLED COACHABLE")
    print("=" * 78)
    print(f"  gap_events: {n_gap} rows across {len(gap_by_scen)} scenarios")
    for k, c in gap_by_scen[:6]:
        print(f"    {c:>5}  {k}")
    if gap_turns:
        gv = embed_cached([" ".join(t.split()) for t in gap_turns], workers=20)
        gv = gv / (np.linalg.norm(gv, axis=1, keepdims=True) + 1e-10)
        print(f"  {len(gap_turns)} real client turns from scenarios Layer D found coachable:")
        for name, tax in (("OLD (production)", old), ("NEW (turn mode)", new)):
            acc = match(gv, tax, emb)["accepted"]
            print(f"    {name:<20} keeps {acc.sum():>4}/{len(acc)} ({acc.mean()*100:>5.1f}%)")

    print("=" * 78)
    print("TEST 3 -- SCENARIOS THAT WOULD GET NO RUBRIC")
    print("=" * 78)
    for st, c in rubric_status:
        print(f"  OLD  {st:<36}{c:>5}")
    rows = json.loads(NEW_ARTIFACT.read_text(encoding="utf-8-sig"))["rows"]
    co = [r for r in rows if r["kind"] == "scenario"]
    calls = np.array([r["calls"] for r in co])
    thin = sum(1 for r in co if r["calls"] < MIN_MILESTONE_CALLS_FLOOR)
    print(f"  NEW  coachable scenarios                          {len(co):>5}")
    print(f"  NEW  with < {MIN_MILESTONE_CALLS_FLOOR} distinct calls (no rubric possible)   {thin:>5}")
    print(f"  NEW  distinct-call support: min {calls.min()} p25 {np.percentile(calls, 25):.0f} "
          f"med {np.median(calls):.0f} max {calls.max()}")


if __name__ == "__main__":
    main()
