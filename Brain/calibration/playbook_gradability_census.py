#!/usr/bin/env python3
"""CENSUS the gradability of every LIVE playbook criterion. ZERO chat calls, ZERO writes.

Handoff: Brain/HANDOFF_LAYER_C_BACKFILLED_2026-08-20.md problem #4.

The finding on record is "roughly half the criteria cannot be graded from a transcript"
(findings §11.4). That was an impression from a blind read of quotes, never a count over
production criteria. This counts it over the WHOLE live population -- so it is a census, not
a probe, and §11.3's "a probe cannot promise a rate" does not apply to it.

TWO INSTRUMENTS, and the first must never stand in for the second:

  A. BANNED-ADJECTIVE SCAN (deterministic, here). Counts criteria containing an adjective
     from the synthesis prompt's OWN banned list. This is a LOWER BOUND on ungradability,
     not the rate: "demonstrate operational relief and proactive partnership value" is
     ungradable on grounds the list cannot see, and a criterion could use "comprehensive"
     inside an otherwise checkable sentence. Reported as a floor, labelled as a floor.
     §11.5 already measured and REJECTED a deterministic filter as a decision rule for
     quotes; the same caution applies here, which is why this one only bounds.

  B. BLIND READ (semantic, elsewhere). `--packet` writes an opaque-id packet of every
     criterion in seeded-random order with the cohort withheld, for a subagent to bucket
     GRADABLE / BORDERLINE / NOT_GRADABLE. That is the rate. The key is written to a
     SEPARATE file that the packet does not reveal.

Also reported, because it reads the same rows for free: SINGLE-ACCOUNT MOVE RATE per cohort
-- the candidate replacement for PB1-as-a-gate (findings §10b, §12).

Cohorts are derived from source_artifact, never hardcoded per scenario:
    pbv_playbooks_snapped.json = the original 5 (old flash-lite config, 63% usable quotes)
    pbf_rest_snapped.json      = the 25 backfilled at the licensed config
    pbf_thin_snapped.json      = the 3 thin documents (16-21 pairs)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

# The synthesis prompt's own banned list, taken from scenario_playbook_trial.py's MAP_RULES
# and reduce rules. Do NOT extend it here -- if this list and the prompt's list diverge, the
# census stops measuring the rule that was actually shipped. Inflected forms are included
# because the prompt bans the adjective, not one spelling of it.
BANNED_ADJECTIVES = (
    "clear", "clearly", "effective", "effectively", "scientific", "aligned",
    "proactive", "proactively", "appropriate", "appropriately", "comprehensive",
    "robust", "meaningful",
)

_BANNED_RE = re.compile(r"\b(" + "|".join(BANNED_ADJECTIVES) + r")\b", re.IGNORECASE)

COHORTS = {
    "pbv_playbooks_snapped.json": "original-5 (old config)",
    "pbf_rest_snapped.json": "backfill-25 (licensed config)",
    "pbf_thin_snapped.json": "thin-3 (16-21 pairs)",
    # Promoted 2026-08-24, superseding the pbv originals. Licensed config + gradability rule.
    "pbq_36flash_medium_grad_snapped.json": "grad-5 (promoted 2026-08-24)",
}


def banned_hits(criterion: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _BANNED_RE.finditer(criterion or "")})


def _connect():
    import psycopg
    from config import load_config
    url = load_config().database_url
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + "hostaddr=18.138.49.39"
    return psycopg.connect(url, autocommit=True)


def collect(status: str = "live") -> list[dict]:
    """One record per key_move across every playbook at `status`. Read-only."""
    from shared import storage
    with _connect() as conn:
        books = storage.get_playbooks(conn, status=status)
    out: list[dict] = []
    for b in books:
        moves = b["playbook"]["key_moves"] or []
        for i, mv in enumerate(moves, start=1):
            ev = mv.get("evidence") or []
            accounts = [e.get("account") for e in ev if e.get("account")]
            out.append({
                "scenario_key": b["scenario_key"],
                "artifact": b["source_artifact"],
                "cohort": COHORTS.get(b["source_artifact"], b["source_artifact"]),
                "move_id": f"M{i}",
                "name": mv.get("name", ""),
                "criterion": mv.get("criterion", ""),
                "n_quotes": len(ev),
                "n_accounts": len(set(accounts)),
                "accounts": sorted(set(accounts)),
                "banned": banned_hits(mv.get("criterion", "")),
            })
    return out


def _cohort_order(by_cohort: dict) -> list[str]:
    known = [c for c in COHORTS.values() if c in by_cohort]
    return known + sorted(c for c in by_cohort if c not in COHORTS.values())


def report(rows: list[dict]) -> None:
    by_cohort: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cohort[r["cohort"]].append(r)

    ndocs = len({r["scenario_key"] for r in rows})
    print(f"\n[census] {len(rows)} key_moves across {ndocs} live playbooks\n")

    print("INSTRUMENT A -- BANNED-ADJECTIVE SCAN (a LOWER BOUND on ungradability, not the rate)")
    print(f"{'cohort':<32} {'docs':>5} {'moves':>6} {'banned':>7} {'rate':>7}")
    print("-" * 62)
    for cohort in _cohort_order(by_cohort):
        rs = by_cohort[cohort]
        hit = [r for r in rs if r["banned"]]
        docs = len({r["scenario_key"] for r in rs})
        print(f"{cohort:<32} {docs:>5} {len(rs):>6} {len(hit):>7} {len(hit) / len(rs):>6.0%}")
    allhit = [r for r in rows if r["banned"]]
    print("-" * 62)
    print(f"{'ALL LIVE':<32} {ndocs:>5} {len(rows):>6} {len(allhit):>7} "
          f"{len(allhit) / len(rows):>6.0%}")

    tally = Counter(w for r in rows for w in r["banned"])
    if tally:
        print("\n  which adjectives: " + ", ".join(f"{w} x{n}" for w, n in tally.most_common()))

    if allhit:
        print("\n  examples (verbatim, most-flagged first):")
        for r in sorted(allhit, key=lambda r: -len(r["banned"]))[:8]:
            print(f"    [{','.join(r['banned'])}] {r['scenario_key']}/{r['move_id']}: "
                  f"{r['criterion'][:110]}")

    print("\nSINGLE-ACCOUNT MOVE RATE (the candidate replacement for PB1-as-a-gate)")
    print(f"{'cohort':<32} {'moves':>6} {'1-acct':>7} {'rate':>7} {'>=3q':>6} {'PB1':>6}")
    print("-" * 70)
    for cohort in _cohort_order(by_cohort):
        rs = by_cohort[cohort]
        one = [r for r in rs if r["n_accounts"] <= 1]
        q3 = [r for r in rs if r["n_quotes"] >= 3]
        pb1 = [r for r in rs if r["n_quotes"] >= 3 and r["n_accounts"] >= 3]
        print(f"{cohort:<32} {len(rs):>6} {len(one):>7} {len(one) / len(rs):>6.0%} "
              f"{len(q3) / len(rs):>5.0%} {len(pb1) / len(rs):>5.0%}")
    one = [r for r in rows if r["n_accounts"] <= 1]
    q3 = [r for r in rows if r["n_quotes"] >= 3]
    pb1 = [r for r in rows if r["n_quotes"] >= 3 and r["n_accounts"] >= 3]
    print("-" * 70)
    print(f"{'ALL LIVE':<32} {len(rows):>6} {len(one):>7} {len(one) / len(rows):>6.0%} "
          f"{len(q3) / len(rows):>5.0%} {len(pb1) / len(rows):>5.0%}")
    print("\n  PB1 = >=3 quotes AND >=3 distinct accounts, per move. The proposed replacement\n"
          "  gate is the '1-acct' column at <=10%.")

    thin = [r for r in rows if r["cohort"].startswith("thin")]
    if thin:
        acct = Counter(a for r in thin for a in r["accounts"])
        n_moves = len(thin)
        print(f"\nTHIN-3 ACCOUNT CONCENTRATION ({n_moves} moves)")
        for a, n in acct.most_common(5):
            print(f"    {a:<28} appears in {n}/{n_moves} moves")


def write_packet(rows: list[dict], packet: Path, key: Path, seed: int = 20260824) -> None:
    """A blind packet: opaque ids, seeded-random order, cohort and scenario WITHHELD.

    The key goes to a separate file. Nothing in the packet correlates id order with cohort
    -- that is the whole point, and it is why the shuffle is seeded rather than left to
    insertion order (which would group each document's moves together and leak the cohort).
    """
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)

    lines = [
        "CRITERION GRADABILITY PACKET",
        "",
        "Each item is one CRITERION from a coaching playbook. It will be used to score a real",
        "sales-call transcript yes/no: did the account manager do this on the call, or not?",
        "",
        "Bucket each item into exactly one of:",
        "  GRADABLE      -- names something CONCRETE that is present or absent in a transcript:",
        "                   a specific artifact, a number, a named mechanism, a required",
        "                   structure. Two careful readers scoring the same transcript agree.",
        "  BORDERLINE    -- names something concrete but hedged, or half-evaluative, so two",
        "                   careful readers could reasonably disagree on the same transcript.",
        "  NOT_GRADABLE  -- rests on an evaluative judgement about an effect on the listener",
        "                   ('was it clear?', 'was it aligned?'), or is too abstract to check",
        "                   against what was actually said.",
        "",
        "Judge ONLY the text of the criterion. Do not guess which document it came from, and",
        "do not reward or penalise an item for length or polish.",
        "",
        "=" * 78,
        "",
    ]
    keymap: dict[str, dict] = {}
    for n, idx in enumerate(order, start=1):
        cid = f"C{n:03d}"
        keymap[cid] = {
            "scenario_key": rows[idx]["scenario_key"],
            "artifact": rows[idx]["artifact"],
            "cohort": rows[idx]["cohort"],
            "move_id": rows[idx]["move_id"],
            "banned": rows[idx]["banned"],
        }
        lines.append(f"{cid}: {rows[idx]['criterion']}")
    lines += ["", "=" * 78, "",
              "Return ONE line per item, every item, no preamble:",
              "  <id> <BUCKET> <reason, 12 words max>", ""]

    packet.write_text("\n".join(lines), encoding="utf-8")
    key.write_text(json.dumps(keymap, indent=2), encoding="utf-8")
    print(f"\n[packet] {len(keymap)} criteria -> {packet}")
    print(f"[key]    withheld -> {key}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="live")
    ap.add_argument("--packet", action="store_true",
                    help="also write the blind-read packet + withheld key")
    ap.add_argument("--dump", type=Path, default=None,
                    help="write the raw per-move records as JSON")
    a = ap.parse_args()

    rows = collect(a.status)
    if not rows:
        raise SystemExit(f"no playbooks at status={a.status!r}")
    report(rows)

    if a.packet:
        write_packet(rows,
                     ARTIFACTS_DIR / "pbg_criteria_packet.txt",
                     ARTIFACTS_DIR / "pbg_criteria_KEY.json")
    if a.dump:
        a.dump.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"[dump] {a.dump}")


if __name__ == "__main__":
    main()
