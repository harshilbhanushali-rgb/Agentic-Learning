#!/usr/bin/env python3
"""Issue #9: a CSM does not paste a transcript -- they RELAY what the client said inside a
request frame. Does that frame change what retrieval reaches?

    python ask-naren/audit/probe_query_framing.py

WHERE THIS CAME FROM. Every Ask Naren measurement so far embeds a bare verbatim client turn
as the query. The operator pointed out what a CSM would actually type:

    "A client said this thing, so can you help on how would Naren reply to this situation?"

That is the client's words RELAYED inside a request frame -- not a paraphrase of them. So the
content of the existing eval queries is closer to production than assumed; what is missing is
the frame. And a frame is not neutral: the same boilerplate on every query adds a shared
component to every query vector, which can compress the cosine range and reorder neighbours.

WHY THIS IS THE CHEAP EXPERIMENT TO RUN FIRST. It needs no generation, no blind read, and no
human labour -- only embeddings. If framing does not move retrieval, the existing numbers
stand on the retrieval side and the framing question is closed for the price of a few hundred
embeddings. If it DOES move retrieval, then every accuracy number so far was measured on a
retrieval distribution production will never see, and there is an obvious cheap fix to test:
strip the frame before embedding and keep it only for generation.

WHAT IS HELD CONSTANT. The pool, the masking rule (leave-one-call-out, as in the audit), and
the situations. Only the query text changes. The comparison is per-situation and paired, so
the reported movement is attributable to the frame rather than to which situations were drawn.

THREE FRAMES, not one, because a single template cannot tell a frame-specific effect from a
general dilution effect. If all three move retrieval the same way, the mechanism is dilution
by boilerplate. If only one does, it is that wording.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from ask_naren import retrieval          # noqa: E402
from config import load_config           # noqa: E402
from preprocessing import embedder       # noqa: E402
from shared import storage               # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
HOSTADDR = "18.138.49.39"

# The operator's own words first -- that is the one that matters. The others vary length and
# wording to separate "this template" from "any boilerplate".
FRAMES = {
    "bare": "{turn}",
    "operator": "A client said this: {turn} — can you help on how would Naren reply to this "
                "situation?",
    "terse": "Client said: {turn} How should I respond?",
    "verbose": "I'm on a call with a client and I need help. This is what the client just "
               "said to me: {turn} I need to know how Naren would have replied to this "
               "situation, and what I should say back to them right now.",
}


def _connect_read_only(url: str):
    if "hostaddr=" not in url:
        url += ("&" if "?" in url else "?") + f"hostaddr={HOSTADDR}"
    conn = storage.get_connection(url)
    conn.execute("SET SESSION default_transaction_read_only = on")
    setting = conn.execute(
        "SELECT current_setting('default_transaction_read_only')").fetchone()[0]
    if setting != "on":
        raise RuntimeError(f"read-only enforcement failed: {setting!r}")
    # close() resets the setting first: left in place it leaks through Neon's POOLED endpoint
    # onto whichever unrelated client is handed this backend next. Same wrapper as the other
    # harnesses here -- see Brain/docs/GOTCHAS.md.
    real_close = conn.close

    def _close_and_reset():
        try:
            conn.execute("SET SESSION default_transaction_read_only = off")
        except Exception:
            pass
        real_close()

    conn.close = _close_and_reset
    return conn


class MaskedPool:
    """Leave-one-call-out, matching build_answer_audit.py. Masked rows are EXCLUDED from the
    ranking rather than sorted last, so a request larger than the kept pool returns fewer
    candidates and never the held-out call."""

    def __init__(self, pool: retrieval.RetrievalPool, exclude_call: str):
        self._pool = pool
        self._keep = np.array([p["call_filename"] != exclude_call for p in pool.pairs])

    def top1(self, query_vec):
        q = np.asarray(query_vec, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        sims = self._pool.vectors @ q
        order = [i for i in np.argsort(-sims) if self._keep[i]]
        best = int(order[0])
        return self._pool.pairs[best], float(sims[best])


def main() -> int:
    # The situations, and the call each one came from (needed for masking). Taken from the
    # committed audit raw file so this probe runs on exactly the eval sample.
    raw = json.loads((ARTIFACTS / "answer_audit_raw.json").read_text(encoding="utf-8"))
    situations = []
    seen = set()
    for record in raw:
        turn = record["situation"]
        if turn in seen:
            continue
        seen.add(turn)
        # The situation IS a corpus trigger, so its own call is recoverable from the pool.
        situations.append({"turn": turn, "held_out_scenario": record["held_out_scenario"]})
    print(f"[situations] {len(situations)} distinct eval situations", flush=True)

    conn = _connect_read_only(load_config().database_url)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    print(f"[pool] {len(pairs)} coachable pairs", flush=True)
    vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    pool = retrieval.RetrievalPool(pairs, vectors)

    # Which call each situation belongs to -- match the trigger text back to its pair.
    by_trigger = {p["trigger_text"]: p for p in pairs}
    for s in situations:
        own = by_trigger.get(s["turn"])
        s["own_call"] = own["call_filename"] if own else None

    results: dict[str, list] = {}
    for name, template in FRAMES.items():
        queries = [template.format(turn=s["turn"]) for s in situations]
        print(f"[embed] {name}: {len(queries)} queries", flush=True)
        qvecs = embedder.embed_query_matrix(queries)
        rows = []
        for s, qv in zip(situations, qvecs):
            masked = MaskedPool(pool, s["own_call"])
            pair, cos = masked.top1(qv)
            rows.append({"pair_id": pair["pair_id"], "cosine": cos,
                         "scenario_key": pair["scenario_key"],
                         "same_scenario": pair["scenario_key"] == s["held_out_scenario"]})
        results[name] = rows

    base = results["bare"]
    print("\n" + "=" * 78)
    print("DOES THE CSM'S REQUEST FRAME CHANGE WHAT RETRIEVAL REACHES?")
    print("=" * 78)
    print(f"{'frame':10s} {'top-1 changed':>14s} {'mean cosine':>12s} "
          f"{'cosine range':>16s} {'same-scenario':>14s}")
    for name, rows in results.items():
        changed = sum(1 for a, b in zip(base, rows) if a["pair_id"] != b["pair_id"])
        cosines = [r["cosine"] for r in rows]
        same = sum(1 for r in rows if r["same_scenario"])
        print(f"{name:10s} {changed:>10d}/{len(rows):<3d} {np.mean(cosines):>12.3f} "
              f"{min(cosines):>7.3f}-{max(cosines):<7.3f} {same:>10d}/{len(rows):<3d}")

    print("\nHOW TO READ THIS")
    print("  top-1 changed  -- how many situations retrieve a DIFFERENT exchange once the")
    print("                    frame is added. This is the number that matters: it is how")
    print("                    much of the existing eval's retrieval production would not")
    print("                    reproduce.")
    print("  cosine range   -- boilerplate shared by every query pulls all queries toward")
    print("                    each other. A compressed range means the score is carrying")
    print("                    less information, which is what would make a floor even")
    print("                    less usable than ADR 0005 already found it to be.")
    print("  same-scenario  -- a weak and near-circular proxy (#7), reported only because a")
    print("                    large move in it would be worth noticing.")

    out = ARTIFACTS / "query_framing_probe.json"
    out.write_text(json.dumps(
        {"frames": FRAMES,
         "situations": [s["turn"] for s in situations],
         "results": results}, indent=2), encoding="utf-8")
    print(f"\n-> artifacts/{out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
