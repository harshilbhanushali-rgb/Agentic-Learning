#!/usr/bin/env python3
"""Rewrite stored milestone descriptions from narration into coaching criteria.

Run from Brain/:
    python ops/rewrite_milestone_criteria.py --dry-run          # print before/after, write nothing
    python ops/rewrite_milestone_criteria.py --dry-run --show 30
    python ops/rewrite_milestone_criteria.py --apply            # write to rubrics.milestones

WHY THIS EXISTS
Measured 2026-08-10 over the live `rubrics` table: all 405 milestone descriptions are
narration about a person rather than criteria -- 37% name Naren, 63% say "the speaker",
91% use he/she/his/her. Example: "He uses hypothetical numerical examples of job slots to
illustrate how the platform can scale."

Layer D scores a DIFFERENT person's response against those descriptions and detection
hints, so a CSM can handle a situation correctly and still miss every milestone simply by
not reproducing one expert's improvisation. That is the dominant cause of the 93.9% miss
rate measured on 864 attempts.

WHY REWRITE INSTEAD OF RE-RUNNING LAYER C
Re-running Layer C would change the milestone SET, not just its wording: UMAP+HDBSCAN is
not reproducible across process launches (385 / 398 / 403-407 milestones measured for
identical input). That reshuffles clusters, orphans every milestone_performance row --
milestone_id is the array POSITION -- and moves the baseline, all to fix prose. The
clusters themselves are well evidenced (support up to 112 calls / 337 clauses); only the
text is wrong. So this pass rewrites text IN PLACE and touches nothing else:

  * milestone COUNT and ORDER per rubric are preserved exactly, so every milestone_id
    keeps meaning what it meant, and existing milestone_performance rows stay valid.
  * only `description`, `label` and `detection_hint` change. Every evidence field
    (support_calls, support_clauses, relevance_mean, position_variance, sequencing_type,
    source_v) is carried through untouched.
  * `scenarios`, `kb_pairs`, `primary_topics` and the taxonomy are not read or written.

Snapshot first (already done for the 2026-08-10 run, schema pre_criteria_20260810):
    CREATE SCHEMA pre_criteria_<date>;
    CREATE TABLE pre_criteria_<date>.rubrics AS SELECT * FROM public.rubrics;
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from shared import gemma as _gemma
from shared import storage
from shared.gemma import GemmaError, call_gemma

# Same model Layer D scores with: gemma-4-31b-it's 16k TPM cannot hold a batch of these.
_MODEL = "gemini-3.1-flash-lite"
_FALLBACKS = ("gemini-3.5-flash-lite", "gemma-4-31b-it")
# 10, not 20. At 20 one batch in 21 came back as truncated JSON on the 2026-08-10 full
# dry run -- call_gemma raised on the unparseable tail and those 20 milestones were left
# unchanged (correctly, but unrewritten). Output here is larger per item than it looks:
# label + 1-2 sentence description + detection_hint + flag. Halving the batch doubles the
# call count from 21 to 41, which is nothing against a 500/day budget, and buys a clean
# 405/405. Truncation is the binding constraint, not requests.
_BATCH_SIZE = 10
_MAX_OUTPUT_TOKENS = 16384

_PROMPT = """\
You are converting sales-rubric milestones from narration into coaching criteria.

Each item below is a milestone that was written as a description of what one specific
expert did. Rewrite it as the criterion a DIFFERENT person's response must satisfy.

Rules, all of them load-bearing:
- Observable behaviour, present tense, NO subject: "Acknowledges the client's existing
  process before proposing an alternative." NOT "Naren acknowledges...", NOT "The speaker
  acknowledges...".
- Never name any person. Never use he/she/they/his/her. Never write "the speaker".
- Generalise past specifics. If the original cites a particular number, client, tool or
  anecdote, state the underlying behaviour instead ("illustrates the point with a concrete
  worked example"), never the instance ("uses hypothetical job-slot numbers").
- PRESERVE THE MEANING. Do not invent a new requirement and do not broaden the move into
  something vaguer than the original. This is a rephrasing, not a redesign.
- If the original describes something that is NOT a transferable coaching move at all --
  it is only an account of what someone happened to say once -- set
  "not_coachable": true and still supply your best-effort criterion.
- detection_hint: what separates a genuine instance from a near-miss, same person-free
  behavioural terms.

ITEMS:
{items_block}

Respond ONLY with valid JSON -- a single array, exactly one object per id:
[
  {{
    "id": "<id>",
    "label": "2-4 word action label",
    "description": "1-2 sentences, observable behaviour, no subject, no names",
    "detection_hint": "genuine instance vs near-miss",
    "not_coachable": false
  }}
]
"""

_PERSON = re.compile(r"\b(naren|shankar|the speaker|he|she|his|her|him|they|their)\b", re.I)


def has_person_language(text: str) -> bool:
    """Whether a description still reads as narration about a person."""
    return bool(_PERSON.search(text or ""))


def load_milestones(conn) -> list[dict]:
    """Every milestone in every rubric, with its array position."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT rubric_id, scenario_key, milestones
            FROM rubrics ORDER BY rubric_id
        """)
        rows = cur.fetchall()
    out = []
    for rubric_id, scenario_key, milestones in rows:
        for pos, m in enumerate(milestones or []):
            if not isinstance(m, dict):
                continue
            out.append({
                "uid": f"R{rubric_id}_P{pos}",
                "rubric_id": rubric_id,
                "scenario_key": scenario_key,
                "position": pos,
                "milestone": m,
            })
    return out


def rewrite_batch(items: list[dict], config) -> dict[str, dict]:
    """One Gemma call per batch. Returns {uid: rewritten}."""
    lines = []
    for it in items:
        m = it["milestone"]
        lines.append(
            f"- id: {it['uid']}\n"
            f"  SCENARIO: {it['scenario_key']}\n"
            f"  CURRENT LABEL: {m.get('label', '')}\n"
            f"  CURRENT DESCRIPTION: {m.get('description', '')}\n"
            f"  CURRENT DETECTION HINT: {m.get('detection_hint', '')}"
        )
    raw = call_gemma(
        _PROMPT.format(items_block="\n\n".join(lines)), config.gemma_api_keys,
        model=_MODEL, fallback_models=_FALLBACKS, max_output_tokens=_MAX_OUTPUT_TOKENS,
    )
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    return {r["id"]: r for r in raw_list if isinstance(r, dict) and "id" in r}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print before/after, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the rewrites to rubrics")
    ap.add_argument("--show", type=int, default=15, help="before/after pairs to print")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N milestones")
    args = ap.parse_args()

    config = load_config()
    conn = storage.get_connection(config.database_url)
    try:
        items = load_milestones(conn)
        if args.limit:
            items = items[:args.limit]
        n = len(items)
        before_person = sum(
            1 for it in items if has_person_language(it["milestone"].get("description", ""))
        )
        print(f"{n} milestone(s) across {len({i['rubric_id'] for i in items})} rubric(s)")
        print(f"  currently using person language: {before_person} ({before_person / max(n,1):.0%})")
        batches = [items[i:i + _BATCH_SIZE] for i in range(0, n, _BATCH_SIZE)]
        print(f"  {len(batches)} Gemma call(s) at batch {_BATCH_SIZE}\n")

        rewrites: dict[str, dict] = {}
        for b_idx, batch in enumerate(batches, start=1):
            try:
                got = rewrite_batch(batch, config)
            except GemmaError as e:
                print(f"  ! batch {b_idx}/{len(batches)} failed: {e} — skipping {len(batch)}")
                continue
            missing = {it["uid"] for it in batch} - set(got)
            if missing:
                # A milestone the model did not return must keep its ORIGINAL text.
                # Silently dropping it would blank a real rubric entry.
                print(f"  ! batch {b_idx}: {len(missing)} id(s) not returned — left unchanged")
            rewrites.update(got)
            print(f"  batch {b_idx}/{len(batches)} rewritten ({len(got)}/{len(batch)}) "
                  f"via {_gemma.LAST_MODEL_USED}")

        # --- report -------------------------------------------------------------
        after_person = sum(
            1 for uid, r in rewrites.items() if has_person_language(r.get("description", ""))
        )
        flagged = [uid for uid, r in rewrites.items() if r.get("not_coachable")]
        print(f"\n{len(rewrites)}/{n} rewritten")
        print(f"  still using person language: {after_person} "
              f"({after_person / max(len(rewrites),1):.0%})  <- want ~0%")
        print(f"  flagged not_coachable      : {len(flagged)} "
              f"({len(flagged) / max(len(rewrites),1):.0%})")
        print("  (not_coachable means the original was an account of what someone said "
              "once,\n   not a transferable move -- those are worth reading before you "
              "trust their scores.)")

        by_uid = {it["uid"]: it for it in items}
        print(f"\n{'=' * 78}\nBEFORE / AFTER ({min(args.show, len(rewrites))} of {len(rewrites)})\n{'=' * 78}")
        for uid in list(rewrites)[:args.show]:
            it, r = by_uid.get(uid), rewrites[uid]
            if it is None:
                continue
            m = it["milestone"]
            flag = "  [FLAGGED not_coachable]" if r.get("not_coachable") else ""
            print(f"\n{it['scenario_key']} :: M{it['position'] + 1}{flag}")
            print(f"  support_calls={m.get('support_calls')} src={m.get('source_v')}")
            print(f"  OLD desc : {m.get('description', '')}")
            print(f"  NEW desc : {r.get('description', '')}")
            print(f"  OLD hint : {m.get('detection_hint', '')}")
            print(f"  NEW hint : {r.get('detection_hint', '')}")

        if args.dry_run:
            print(f"\n{'=' * 78}\nDRY RUN — nothing written. Re-run with --apply to commit.\n{'=' * 78}")
            return

        # --- apply --------------------------------------------------------------
        # Rebuild each rubric's milestone array in place, preserving order, count and
        # every evidence field. Only the three text fields are replaced, and only when
        # the model actually returned that id.
        conn = storage.reconnect_if_closed(conn)
        by_rubric: dict[int, list[dict]] = {}
        for it in items:
            by_rubric.setdefault(it["rubric_id"], []).append(it)
        updated = changed = 0
        with conn.cursor() as cur:
            for rubric_id, group in by_rubric.items():
                cur.execute("SELECT milestones FROM rubrics WHERE rubric_id = %s", (rubric_id,))
                milestones = cur.fetchone()[0] or []
                touched = False
                for it in group:
                    r = rewrites.get(it["uid"])
                    if not r or it["position"] >= len(milestones):
                        continue
                    m = milestones[it["position"]]
                    if not isinstance(m, dict):
                        continue
                    m["label"] = r.get("label") or m.get("label", "")
                    m["description"] = r.get("description") or m.get("description", "")
                    m["detection_hint"] = r.get("detection_hint") or m.get("detection_hint", "")
                    # Provenance, so a later reader can tell rewritten text from original.
                    m["criteria_rewritten"] = True
                    if r.get("not_coachable"):
                        m["not_coachable_flag"] = True
                    touched = True
                    changed += 1
                if touched:
                    cur.execute(
                        "UPDATE rubrics SET milestones = %s::jsonb WHERE rubric_id = %s",
                        (json.dumps(milestones), rubric_id),
                    )
                    updated += 1
        print(f"\nAPPLIED: {changed} milestone(s) rewritten across {updated} rubric(s).")
        print("Milestone counts and order unchanged, so milestone_performance rows stay valid.")
        print("Next: re-run Layer D on the SAME transcripts and compare the hit rate against")
        print("schema pre_criteria_20260810 (864 attempts, 21 hits = 2.4%, weighted 0.043).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
