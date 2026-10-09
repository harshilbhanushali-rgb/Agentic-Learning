#!/usr/bin/env python3
"""Is the milestone hit rate real, or is the scorer broken? Read the evidence.

Run from Brain/:  python calibration/read_gap_reasons.py

Zero Gemma, zero writes, zero Pinecone -- Postgres reads plus the transcript files.

Layer D has returned a ~0% milestone hit rate in every run on record. That is either a
genuine finding about the CSM or a defect in Step 0 / Step 3, and the two are
indistinguishable from the aggregate. The 2026-07-06 investigation settled the same
question by pulling the stored `reason` text and cross-checking a sample against the
source transcript at signal_turn_index -- it found the misses legitimate and refuted the
rubric-wording hypothesis. This script automates exactly that, so the check is cheap
enough to repeat after every run.

What to look for in the output, in order:
  1. Is the CLIENT TURN a real business signal, or backchannel? Backchannel here means
     Step 0 is over-detecting and the milestone scores are meaningless -- fix detection
     before reading anything else.
  2. Is the CSM RESPONSE substantive, or empty/one-word? An empty response cannot hit any
     milestone, and a miss against it is correct but uninformative.
  3. Does the MILESTONE actually apply to this exchange? If a rubric for a different
     situation is being applied, that is a Layer B/scenario-matching problem.
  4. Only then: does Gemma's `reason` describe a real omission?
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import BRAIN_DIR
from config import load_config
from ego_trap import csm_registry
from ego_trap.transcript_parser import EgoTrapRole, parse_transcript
from shared import storage


def _load_turns(stem: str, cfg, mapping) -> list | None:
    path = BRAIN_DIR / "csm_recordings" / f"{stem}.txt"
    if not path.exists() or stem not in mapping:
        return None
    _, csm_name = mapping[stem]
    return parse_transcript(str(path), csm_name.strip().lower(), cfg.joveo_speakers_lower)


def _window(turns: list, turn_index: int, before: int = 1, after: int = 4) -> list[tuple[str, str]]:
    """The exchange around a signal: the client turn plus what followed it."""
    out = []
    for t in turns:
        if turn_index - before <= t.index <= turn_index + after:
            out.append((t.role.name, t.text))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--show", type=int, default=12, help="sampled gaps to print in full")
    ap.add_argument("--csm-id", default=None)
    ap.add_argument("--verdict", default="miss", choices=["miss", "partial_hit", "any"],
                    help="which verdict to sample (default: miss)")
    args = ap.parse_args()

    cfg = load_config()
    mapping = csm_registry.load_mapping(str(BRAIN_DIR / "csm_recordings" / "mapping.csv"))
    conn = storage.get_connection(cfg.database_url)
    try:
        with conn.cursor() as cur:
            # --- aggregate truth -------------------------------------------------
            cur.execute("""
                SELECT SUM(attempts), SUM(hits), SUM(partial_hits), COUNT(*)
                FROM milestone_performance
                WHERE (%s::text IS NULL OR csm_id = %s::text)
            """, (args.csm_id, args.csm_id))
            attempts, hits, partial, rows = cur.fetchone()
            if not attempts:
                print("milestone_performance is empty -- run ops/run_ego_trap.py first.")
                return
            partial = partial or 0
            print("=" * 78)
            print("MILESTONE PERFORMANCE (aggregate)")
            print("=" * 78)
            print(f"  {rows} (csm, rubric, milestone) rows, {attempts} attempts")
            print(f"  full hits    : {hits:>5}  ({hits / attempts:.1%})")
            print(f"  partial hits : {partial:>5}  ({partial / attempts:.1%})")
            print(f"  misses       : {attempts - hits - partial:>5}"
                  f"  ({(attempts - hits - partial) / attempts:.1%})")
            print(f"  weighted score = {(hits + 0.5 * partial) / attempts:.3f}")

            # --- where the signals came from -------------------------------------
            cur.execute("""
                SELECT g->>'gap_type', COUNT(*)
                FROM gap_events, jsonb_array_elements(gaps) g
                GROUP BY 1 ORDER BY 2 DESC
            """)
            print("\n  gap types recorded:")
            for gtype, n in cur.fetchall():
                print(f"    {gtype:<32} {n:>6}")

            # A response the CSM never gave cannot hit a milestone. If this is a large
            # share, the hit rate is measuring silence, not skill.
            cur.execute("""
                SELECT COUNT(*) FROM gap_events
                WHERE gaps @> '[{"gap_type": "Signal_Recognition_Failure"}]'
            """)
            srf = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM gap_events")
            total_ev = cur.fetchone()[0]
            print(f"\n  {srf}/{total_ev} gap_events are Signal_Recognition_Failure "
                  f"({srf / max(total_ev, 1):.0%}) -- no CSM response existed to score.")

            # --- most-missed milestones ------------------------------------------
            cur.execute("""
                SELECT mp.scenario_key, mp.milestone_id, mp.attempts, mp.hits, mp.partial_hits
                FROM milestone_performance mp
                WHERE (%s::text IS NULL OR mp.csm_id = %s::text)
                ORDER BY mp.attempts DESC, mp.hits ASC
                LIMIT 15
            """, (args.csm_id, args.csm_id))
            print("\n  most-attempted milestones (attempts / hits / partial):")
            for key, mid, a, h, p in cur.fetchall():
                print(f"    {a:>3} / {h:>2} / {p:>2}   {key} :: {mid}")

            # --- the actual evidence ---------------------------------------------
            verdict_filter = "" if args.verdict == "any" else "AND g->>'verdict' = %(v)s"
            cur.execute(f"""
                SELECT e.call_id, e.scenario_key, e.signal_turn_index,
                       g->>'milestone_id', g->>'milestone_description', g->>'verdict',
                       g->>'confidence', g->>'reason', g->>'quote', g->>'gap_to_ideal',
                       g->'evidence', g->>'rubric_pipeline_version'
                FROM gap_events e, jsonb_array_elements(e.gaps) g
                WHERE g->>'gap_type' = 'Milestone_Omission' {verdict_filter}
                ORDER BY random()
                LIMIT %(n)s
            """, {"v": args.verdict, "n": args.show})
            samples = cur.fetchall()

        print("\n" + "=" * 78)
        print(f"SAMPLED EVIDENCE ({len(samples)} x verdict={args.verdict})")
        print("=" * 78)
        print("Read all four checks from this file's docstring for each one.\n")

        turns_cache: dict[str, list] = {}
        for (call_id, skey, turn_idx, mid, mdesc, verdict, conf,
             reason, quote, gap_to_ideal, evidence, pv) in samples:
            if call_id not in turns_cache:
                turns_cache[call_id] = _load_turns(call_id, cfg, mapping) or []
            turns = turns_cache[call_id]

            print("-" * 78)
            print(f"{skey} :: {mid}   verdict={verdict} confidence={conf} rubric={pv}")
            print(f"  call {call_id} @ turn {turn_idx}")
            ev = evidence or {}
            sc, scl = ev.get("support_calls"), ev.get("support_clauses")
            print(f"  milestone evidence: support_calls={sc} support_clauses={scl} "
                  f"relevance_mean={ev.get('relevance_mean')} src={ev.get('source_v')}")
            print(f"  MILESTONE : {mdesc}")
            if turns and turn_idx is not None:
                print("  --- transcript around the signal ---")
                for role, text in _window(turns, turn_idx):
                    tag = {"CLIENT": "CLIENT", "CSM": "CSM   ", "OTHER_JOVEO": "JOVEO "}[role]
                    print(f"    {tag} | {text[:220]}")
            else:
                print("  (transcript unavailable -- cannot verify this one)")
            print(f"  GEMMA REASON : {reason}")
            if quote:
                print(f"  GEMMA QUOTE  : {quote[:220]}")
            if gap_to_ideal:
                print(f"  GAP TO IDEAL : {gap_to_ideal[:220]}")
    finally:
        conn.close()

    print("\n" + "=" * 78)
    print("If the CLIENT turns above are backchannel, the hit rate is measuring Step 0")
    print("false positives and no milestone conclusion is available yet. If they are real")
    print("and the CSM responses are substantive, the misses are a finding about coaching.")
    print("=" * 78)


if __name__ == "__main__":
    main()
