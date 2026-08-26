#!/usr/bin/env python3
"""Issue #7, first task: is "retrieval landed in the same scenario 10/24" a real retrieval
failure, or an artifact of how it was measured?

The 10/24 figure compares `kb_pairs.scenario_key` -- the PRIMARY label -- on the held-out
item against the retrieved neighbour. But db/schema.sql documents scenario_key as "primary
scenario (first multi-match, or centroid fallback)" and scenario_keys as "all scenarios this
pair matched above the similarity threshold", and 74% of coachable pairs carry 2 or 3 labels
(1709 single / 1721 double / 3098 triple of 6528, measured). A neighbour that shares a
SECONDARY label with the held-out item is counted as a miss by the primary-only comparison,
which would overstate the failure rate -- possibly by a lot.

This script tests three hypotheses against the corrected prototype artifact, read-only:

  H1 MEASUREMENT (multi-label). How many of the primary-key mismatches share any label at
     all? Reported four ways, because "same topic" has four defensible definitions here and
     they disagree: primary==primary, any-label overlap, retrieved-primary in held-out's
     labels, held-out-primary in retrieved's labels.

  H2 MEASUREMENT (mask starvation). Leave-one-call-out masks the held-out item's WHOLE
     call. Where a scenario's evidence is concentrated in a few calls, the mask can remove
     most of that scenario's own pairs, so a mismatch would be the harness starving
     retrieval rather than retrieval failing. Reports, per item, how much of its own
     scenario survived its own mask.

  H3 REAL FAILURE. Whatever is left after H1 and H2 are accounted for.

This script decides nothing about answer quality -- it only establishes whether the number
that motivated #7 means what it appeared to mean.

    python ask-naren/audit/diagnose_scenario_mismatch.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from config import load_config          # noqa: E402
from shared import storage              # noqa: E402

HOSTADDR = "18.138.49.39"
ARTIFACT = _ROOT / "ask-naren" / "prototype" / "artifacts" / "eval_pairs_vs_playbook_v2.json"
OUT = Path(__file__).resolve().parent / "artifacts" / "scenario_mismatch_diagnosis.json"


def _connect_read_only(url: str):
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={HOSTADDR}"
    conn = storage.get_connection(url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    setting = conn.execute(
        "SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if setting != "on":
        raise RuntimeError(f"read-only enforcement failed: {setting!r}")
    return conn


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def _labels_by_pair_id(conn, pair_ids: list[int]) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT p.pair_id, p.scenario_key, p.scenario_keys, c.filename "
        "FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id "
        "WHERE p.pair_id = ANY(%s)", (pair_ids,)).fetchall()
    return {r[0]: {"primary": r[1], "labels": list(r[2] or []), "call": r[3]} for r in rows}


def _find_retrieved(conn, call_filename: str, trigger: str, response: str) -> list[dict]:
    """The artifact records the retrieved neighbour by text, not by pair_id. Match on
    (call, trigger, response) content. More than one hit means a content duplicate, which
    the corpus is known to contain -- reported rather than silently collapsed."""
    rows = conn.execute(
        "SELECT p.pair_id, p.scenario_key, p.scenario_keys, p.trigger_text, p.response_text "
        "FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id WHERE c.filename = %s",
        (call_filename,)).fetchall()
    want = (_norm(trigger), _norm(response))
    return [{"pair_id": r[0], "primary": r[1], "labels": list(r[2] or [])}
            for r in rows if (_norm(r[3]), _norm(r[4])) == want]


def _scenario_call_spread(conn, scenario_keys: list[str]) -> dict[str, dict]:
    """For each scenario: how many coachable pairs it has, and across how many distinct
    calls. A scenario living in two calls cannot survive its own leave-one-call-out mask."""
    out = {}
    for key in scenario_keys:
        row = conn.execute(
            "SELECT count(*), count(DISTINCT p.call_id) FROM kb_pairs p WHERE p.scenario_key = %s",
            (key,)).fetchone()
        out[key] = {"pairs": row[0], "calls": row[1]}
    return out


def _pairs_left_after_mask(conn, scenario_key: str, call_filename: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id "
        "WHERE p.scenario_key = %s AND c.filename <> %s",
        (scenario_key, call_filename)).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", default=str(ARTIFACT))
    args = ap.parse_args()

    art = json.loads(Path(args.artifact).read_text(encoding="utf-8-sig"))
    results = art["results"]
    print(f"artifact: {Path(args.artifact).name}  n={len(results)}")

    conn = _connect_read_only(load_config().database_url)
    try:
        held_ids = [r["held_out"]["pair_id"] for r in results]
        held = _labels_by_pair_id(conn, held_ids)
        rows = []
        for r in results:
            h = held[r["held_out"]["pair_id"]]
            ret = r["retrieved"]
            cands = _find_retrieved(conn, ret["call_filename"], ret["trigger_text"],
                                    ret["response_text"])
            if not cands:
                rows.append({"pair_id": r["held_out"]["pair_id"], "resolved": False})
                continue
            # A content duplicate has identical labels by construction; take the first and
            # record the count so a surprise is visible rather than assumed away.
            rmatch = cands[0]
            declined = r["scores"]["pairs_only"]["declined"]
            h_labels, r_labels = set(h["labels"]), set(rmatch["labels"])
            rows.append({
                "resolved": True,
                "pair_id": r["held_out"]["pair_id"],
                "duplicate_matches": len(cands),
                "declined": declined,
                "cosine": ret["cosine"],
                "held_primary": h["primary"],
                "held_labels": sorted(h_labels),
                "ret_primary": rmatch["primary"],
                "ret_labels": sorted(r_labels),
                "primary_match": h["primary"] == rmatch["primary"],
                "any_label_overlap": bool(h_labels & r_labels),
                "ret_primary_in_held_labels": rmatch["primary"] in h_labels,
                "held_primary_in_ret_labels": h["primary"] in r_labels,
                "held_call": r["held_out"]["call_filename"],
            })

        resolved = [x for x in rows if x["resolved"]]
        spread = _scenario_call_spread(conn, sorted({x["held_primary"] for x in resolved}))
        for x in resolved:
            x["own_scenario_pairs"] = spread[x["held_primary"]]["pairs"]
            x["own_scenario_calls"] = spread[x["held_primary"]]["calls"]
            x["own_scenario_pairs_after_mask"] = _pairs_left_after_mask(
                conn, x["held_primary"], x["held_call"])
    finally:
        conn.close()

    n = len(resolved)
    unresolved = len(rows) - n
    print(f"resolved {n}/{len(rows)} retrieved neighbours back to a kb_pairs row"
          + (f"  ({unresolved} unresolved)" if unresolved else ""))
    dups = [x for x in resolved if x["duplicate_matches"] > 1]
    if dups:
        print(f"  note: {len(dups)} retrieved neighbour(s) matched >1 kb_pairs row "
              f"(known content duplicates)")

    print("\n" + "=" * 78)
    print("H1 -- how much of the mismatch is the PRIMARY-ONLY comparison?")
    print("=" * 78)
    defs = [("primary == primary (the 10/24 figure)", "primary_match"),
            ("any shared label", "any_label_overlap"),
            ("retrieved primary is a label of the held-out item", "ret_primary_in_held_labels"),
            ("held-out primary is a label of the retrieved item", "held_primary_in_ret_labels")]
    for label, field in defs:
        k = sum(1 for x in resolved if x[field])
        print(f"  {label:52s} {k:2d}/{n}  ({k / n:.0%})")

    answered = [x for x in resolved if not x["declined"]]
    if answered:
        print(f"\n  among the {len(answered)} ANSWERED items (the ones a CSM would have seen):")
        for label, field in defs:
            k = sum(1 for x in answered if x[field])
            print(f"    {label:50s} {k:2d}/{len(answered)}  ({k / len(answered):.0%})")

    print("\n" + "=" * 78)
    print("H2 -- did leave-one-call-out starve the held-out item's own scenario?")
    print("=" * 78)
    starved = [x for x in resolved if x["own_scenario_pairs_after_mask"] == 0]
    thin = [x for x in resolved if 0 < x["own_scenario_pairs_after_mask"] <= 5]
    print(f"  own scenario had ZERO pairs left after masking its own call: {len(starved)}/{n}")
    print(f"  own scenario had 1-5 pairs left:                            {len(thin)}/{n}")
    print(f"  scenario call-spread (distinct calls per held-out scenario): "
          f"min={min(x['own_scenario_calls'] for x in resolved)} "
          f"max={max(x['own_scenario_calls'] for x in resolved)}")
    for x in starved + thin:
        print(f"    {x['held_primary'][:44]:46s} pairs={x['own_scenario_pairs']:4d} "
              f"calls={x['own_scenario_calls']:3d} left_after_mask="
              f"{x['own_scenario_pairs_after_mask']}")

    print("\n" + "=" * 78)
    print("H3 -- what is left as genuine retrieval failure")
    print("=" * 78)
    real = [x for x in resolved
            if not x["any_label_overlap"] and x["own_scenario_pairs_after_mask"] > 5]
    print(f"  no label overlap AND its own scenario was not starved: {len(real)}/{n}")
    for x in real:
        print(f"    held={x['held_primary'][:34]:36s} -> ret={x['ret_primary'][:34]:36s} "
              f"cos={x['cosine']:.3f} {'DECLINED' if x['declined'] else 'ANSWERED'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
