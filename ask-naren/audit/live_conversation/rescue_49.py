"""Issue #25: issue #49's six questions through the SHIPPED retry code, scored by #49's
blind-judge oracle. Arms: k=1 only (today), wide retry, wide retry + thread-aware prompt.

Usage (from Brain/): python <this> <oracle_dir> <out.json> [runs]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "ops"))

import serve_ask_naren as s  # noqa: E402
from ask_naren import answering, responding  # noqa: E402

ORACLE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
ONLY = sys.argv[4].split(",") if len(sys.argv) > 4 else None
key = json.loads((ORACLE / "key.json").read_text(encoding="utf-8"))
A = json.loads((ORACLE / "verdicts_A.json").read_text(encoding="utf-8"))
B = json.loads((ORACLE / "verdicts_B.json").read_text(encoding="utf-8"))


def verdict(qid, pair_id):
    c = next((c for c in key[qid]["candidates"] if c["pair_id"] == pair_id), None)
    if c is None:
        return None, "UNJUDGED (outside top 50)"
    n = c["cid"].split("-")[1]
    a, b = A[qid][n]["v"], B[qid][n]["v"]
    return c["rank"], ("RIGHT" if a == b == "YES" else ("maybe" if "YES" in (a, b) else "WRONG"))


ARMS = {"k1": dict(wide_retry=False, conversation=False),
        "wide": dict(wide_retry=True, conversation=False),
        "wide+thread": dict(wide_retry=True, conversation=True)}


async def main():
    pool, *_ = await s.build_pool(None)
    label_for, _ = s.build_label_resolver()
    gateway = s.AsyncGatewayClient()
    embed_query = s._embed_query(gateway)
    rows = []
    try:
        for arm, cfg in ARMS.items():
            if ONLY and arm not in ONLY:
                continue
            for qid, v in key.items():
                for run in range(RUNS):
                    q = v["question"]
                    t = time.monotonic()
                    r = await responding._answer_searched(
                        q, pool=pool, gateway=gateway, embed_query=embed_query, k=1,
                        label_for=label_for, moves_for=None,
                        conversation=answering.Conversation(q, ()) if cfg["conversation"] else None,
                        wide_retry=cfg["wide_retry"], time_left=None)
                    dt = time.monotonic() - t
                    row = {"arm": arm, "q": qid, "run": run + 1, "seconds": round(dt, 1),
                           "outcome": r["outcome"], "reason": r.get("reason"),
                           "retries": r.get("retries", [])}
                    if r["outcome"] == "answered":
                        row["rank"], row["verdict"] = verdict(qid, r["citation"]["pair_id"])
                        row["answer"] = r["answer"]
                    else:
                        row["verdict"] = "declined"
                    rows.append(row)
                    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
                    print(f"{arm:<12} {qid} run{run+1}: {row['verdict']:<26} "
                          f"rank={row.get('rank')} {row['retries']} {dt:.1f}s", flush=True)
    finally:
        await gateway.aclose()
        await pool.aclose()


asyncio.run(main())
