#!/usr/bin/env python3
"""Flag milestones that no CSM could ever satisfy, so they stop being scored.

Run from Brain/:
    python ops/flag_uncoachable_milestones.py --dry-run
    python ops/flag_uncoachable_milestones.py --dry-run --show 40
    python ops/flag_uncoachable_milestones.py --apply

WHAT THIS IS, AND WHAT IT IS NOT

It is a MEASUREMENT-CORRECTNESS fix, not a performance improvement. Excluding a milestone
from scoring removes it from the denominator, which mechanically raises the hit rate. That
is only legitimate because scoring somebody against a criterion they CANNOT satisfy is not
measurement in the first place -- it is noise that drags every aggregate down. Any report
built on this must quote both numbers: the rate over all milestones and the rate over
coachable ones. Do not present the difference as the CSM improving.

WHY IT IS NEEDED

ops/rewrite_milestone_criteria.py's own rewriter volunteered `not_coachable: true` on 4 of
405 milestones. Reading them showed a clear pattern of things a CSM cannot do by
construction:
  * AUTHORITY / RELATIONSHIP moves -- "leverage professional relationships to explore
    industry overlap" (support 15 calls), "highlight strategic partnerships and technical
    expertise ... to establish authority" (support 18). These work because of who the
    speaker is; a CSM has neither the relationships nor the standing.
  * UNSCORABLE moves -- "share a relatable, vulnerable personal story to humanize the
    interaction". There is no observable criterion for having told a personal story.
  * SINK LEAKS -- "address immediate technical hurdles regarding communication quality",
    i.e. "can you hear me?" mechanics that reached a coachable rubric despite Layer C's
    milestone_sink_similarity_percentile triage.

Those 4 were only found incidentally, as a side effect of the rewrite. This pass asks the
question deliberately, of all 405.

DESIGN NOTES
  * Sets `not_coachable_flag` on the milestone JSON. Changes NOTHING else: milestone count,
    order, ids and every evidence field are untouched, so existing milestone_performance
    rows stay valid and the flag is trivially reversible by clearing one key.
  * Also records `not_coachable_reason` so a human can overrule the judgement rather than
    having to re-derive it.
  * Deliberately does NOT delete anything. A flagged milestone is still real evidence about
    how an expert behaves -- it is just not a fair test of a CSM.
  * Layer D honours the flag via tuning.yaml's layer_d.skip_uncoachable_milestones.

Snapshot first (done for this run: pre_coachability_20260810).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from shared import gemma as _gemma
from shared import storage
from shared.gemma import GemmaError, call_gemma

_MODEL = "gemini-3.1-flash-lite"
_FALLBACKS = ("gemini-3.5-flash-lite", "gemma-4-31b-it")
# 10, matching ops/rewrite_milestone_criteria.py: at 20 a batch came back as truncated JSON.
_BATCH_SIZE = 10
_MAX_OUTPUT_TOKENS = 16384

_CATEGORIES = ("coachable", "requires_authority", "unscorable", "mechanics")

_PROMPT = """\
You are auditing a sales-coaching rubric. Each milestone below is scored against a Customer
Success Manager's response to a client. Decide whether a CSM could satisfy it AT ALL.

Classify each into exactly one category:

- "coachable": a normal skill a CSM can learn and demonstrate. This is the DEFAULT --
  choose it unless one of the three below clearly applies.
- "requires_authority": only satisfiable by someone with specific seniority, personal
  relationships, or reputation the CSM does not have. Examples: leveraging one's own
  professional network, citing one's own status as a top-tier partner, establishing
  authority from personal expertise. NOTE: merely MENTIONING company partnerships or
  product capabilities is coachable -- any CSM can do that. Reserve this for moves whose
  force comes from WHO IS SPEAKING.
- "unscorable": no observable criterion exists, so no response could be judged against it.
  Examples: sharing a vulnerable personal anecdote, building rapport in general, having
  good instincts.
- "mechanics": call logistics or troubleshooting rather than a coaching move. Examples:
  screen sharing, audio quality, "can you hear me", scheduling the next call, confirming
  attendance.

Be conservative. A milestone that is merely HARD, or that requires product knowledge, or
that a CSM might often fail, is still "coachable". Only use the other three when the CSM
is structurally unable to satisfy the criterion no matter how well they perform.

MILESTONES:
{items_block}

Respond ONLY with valid JSON -- a single array, exactly one object per id:
[
  {{"id": "<id>", "category": "coachable", "reason": "one short clause"}}
]
"""


def load_milestones(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT rubric_id, scenario_key, milestones FROM rubrics ORDER BY rubric_id")
        rows = cur.fetchall()
    out = []
    for rubric_id, scenario_key, milestones in rows:
        for pos, m in enumerate(milestones or []):
            if isinstance(m, dict):
                out.append({
                    "uid": f"R{rubric_id}_P{pos}", "rubric_id": rubric_id,
                    "scenario_key": scenario_key, "position": pos, "milestone": m,
                })
    return out


def classify_batch(items: list[dict], config) -> dict[str, dict]:
    lines = []
    for it in items:
        m = it["milestone"]
        lines.append(
            f"- id: {it['uid']}\n"
            f"  SCENARIO: {it['scenario_key']}\n"
            f"  LABEL: {m.get('label', '')}\n"
            f"  CRITERION: {m.get('description', '')}\n"
            f"  DETECTION HINT: {m.get('detection_hint', '')}"
        )
    raw = call_gemma(
        _PROMPT.format(items_block="\n\n".join(lines)), config.gemma_api_keys,
        model=_MODEL, fallback_models=_FALLBACKS, max_output_tokens=_MAX_OUTPUT_TOKENS,
    )
    raw_list = raw if isinstance(raw, list) else raw.get("results", [])
    out = {}
    for r in raw_list:
        if not isinstance(r, dict) or "id" not in r:
            continue
        cat = r.get("category")
        # An unrecognised category must default to coachable, never to excluded --
        # wrongly excluding a milestone silently shrinks the denominator.
        r["category"] = cat if cat in _CATEGORIES else "coachable"
        out[r["id"]] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=25, help="flagged milestones to print")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    config = load_config()
    conn = storage.get_connection(config.database_url)
    try:
        items = load_milestones(conn)
        if args.limit:
            items = items[:args.limit]
        n = len(items)
        batches = [items[i:i + _BATCH_SIZE] for i in range(0, n, _BATCH_SIZE)]
        print(f"{n} milestone(s) across {len({i['rubric_id'] for i in items})} rubric(s)")
        print(f"{len(batches)} Gemma call(s) at batch {_BATCH_SIZE}\n")

        verdicts: dict[str, dict] = {}
        for b_idx, batch in enumerate(batches, start=1):
            try:
                got = classify_batch(batch, config)
            except GemmaError as e:
                print(f"  ! batch {b_idx}/{len(batches)} failed: {e} — treating as coachable")
                continue
            missing = {it["uid"] for it in batch} - set(got)
            if missing:
                print(f"  ! batch {b_idx}: {len(missing)} id(s) not returned — left coachable")
            verdicts.update(got)
            if b_idx % 10 == 0 or b_idx == len(batches):
                print(f"  {b_idx}/{len(batches)} classified via {_gemma.LAST_MODEL_USED}")

        counts = Counter(v["category"] for v in verdicts.values())
        excluded = {u: v for u, v in verdicts.items() if v["category"] != "coachable"}
        print(f"\n{len(verdicts)}/{n} classified")
        for cat in _CATEGORIES:
            c = counts.get(cat, 0)
            print(f"  {cat:<20} {c:>4}  ({c / max(len(verdicts),1):.0%})")
        print(f"\n  -> {len(excluded)} milestone(s) would stop being scored "
              f"({len(excluded) / max(len(verdicts),1):.0%} of the rubric library)")

        by_uid = {it["uid"] for it in items}
        idx = {it["uid"]: it for it in items}
        print(f"\n{'=' * 80}\nFLAGGED ({min(args.show, len(excluded))} of {len(excluded)})\n{'=' * 80}")
        for uid, v in list(excluded.items())[:args.show]:
            it = idx.get(uid)
            if it is None:
                continue
            m = it["milestone"]
            print(f"\n[{v['category']}] {it['scenario_key']} :: M{it['position'] + 1}"
                  f"   support_calls={m.get('support_calls')}")
            print(f"  criterion : {(m.get('description') or '')[:190]}")
            print(f"  reason    : {v.get('reason', '')}")

        if args.dry_run:
            print(f"\n{'=' * 80}\nDRY RUN — nothing written. Re-run with --apply.\n{'=' * 80}")
            return

        conn = storage.reconnect_if_closed(conn)
        by_rubric: dict[int, list[dict]] = {}
        for it in items:
            by_rubric.setdefault(it["rubric_id"], []).append(it)
        flagged = cleared = updated = 0
        with conn.cursor() as cur:
            for rubric_id, group in by_rubric.items():
                cur.execute("SELECT milestones FROM rubrics WHERE rubric_id = %s", (rubric_id,))
                milestones = cur.fetchone()[0] or []
                touched = False
                for it in group:
                    v = verdicts.get(it["uid"])
                    if not v or it["position"] >= len(milestones):
                        continue
                    m = milestones[it["position"]]
                    if not isinstance(m, dict):
                        continue
                    if v["category"] == "coachable":
                        # Clear a stale flag (e.g. the rewriter's incidental guess) so this
                        # pass is authoritative and re-runnable in both directions.
                        if m.pop("not_coachable_flag", None) is not None:
                            m.pop("not_coachable_reason", None)
                            m.pop("not_coachable_category", None)
                            cleared += 1
                            touched = True
                        continue
                    m["not_coachable_flag"] = True
                    m["not_coachable_category"] = v["category"]
                    m["not_coachable_reason"] = v.get("reason", "")
                    flagged += 1
                    touched = True
                if touched:
                    cur.execute(
                        "UPDATE rubrics SET milestones = %s::jsonb WHERE rubric_id = %s",
                        (json.dumps(milestones), rubric_id),
                    )
                    updated += 1
        print(f"\nAPPLIED: {flagged} flagged, {cleared} stale flag(s) cleared, "
              f"{updated} rubric(s) updated.")
        print("Milestone counts, order and ids unchanged — milestone_performance stays valid.")
        print("Layer D skips flagged milestones only when")
        print("tuning.yaml layer_d.skip_uncoachable_milestones is true.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
