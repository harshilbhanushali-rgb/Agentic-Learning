#!/usr/bin/env python3
"""Issue #7: build a BLIND packet asking the question nothing measured so far answers --
given the CSM's situation and the exchange retrieved for it, is the ANSWER right?

WHAT THE EARLIER DIAGNOSTICS DID AND DID NOT SETTLE. Both premises that motivated #7 turned
out to be my own measurement errors, not defects: the "10/24 wrong scenario" figure was a
primary-label-only comparison (20/24 share a label, 12/12 among answered --
diagnose_scenario_mismatch.py), and the similarity metric does discriminate its target
(+0.073 at d=1.35 against a transplant null -- diagnose_similarity_metric.py). Neither
touches correctness. Worse, neither CAN: scenario labels and retrieval both come from
cosine in the same embedding space, so using one to validate the other is close to
circular. Human-style judgment on situation-vs-answer is the only non-circular instrument
left, which is what this packet is for.

WHY THERE ARE CONTROLS IN BOTH DIRECTIONS. A blind reader's absolute rate is an artifact of
framing -- measured on this project: two blind reads of the same 123 criteria returned 84%
and 17% gradable, differing only in how the reader was framed. So an unanchored "N% of
answers are right" is not a result. The packet therefore carries known-wrong AND known-right
plants, and the audit reports their detection rates BEFORE any rate over the real items:

  control_wrong    a REAL (retrieval, answer) pair shown under a DIFFERENT situation.
                   Known-wrong. The naive version of this control -- transplanting the
                   answer onto a different RETRIEVAL -- is detectable by noticing the quote
                   is missing from the shown reply, which tests quote-checking rather than
                   judgment. Pairing a coherent, correctly-quoted answer with the wrong
                   SITUATION is detectable only by the judgment being measured.

  control_right    the tool's own answer generated with retrieval UNMASKED, so the
                   situation retrieves its own call and the grounding is exactly on target.
                   Known-right because the retrieval cannot be off-topic (it is the same
                   conversation) and the answer is generated from the exchange the auditor
                   is shown.

                   *** THE FIRST VERSION OF THIS CONTROL WAS INVALID AND THE AUDIT CAUGHT
                   IT. *** It used Naren's OWN real reply as the answer. That fails on two
                   counts, both fatal: (1) his raw reply is spoken transcript -- mid-sentence
                   fragments that genuinely are NOT a usable answer to hand a CSM, so
                   "known-right" was never true; it was known to be WHAT HE SAID, not known
                   to be a right answer as delivered. (2) It fails the auditor's own rubric
                   BY CONSTRUCTION: the rubric asks whether the answer is supported by the
                   retrieved reply, and that plant came from a different call than the
                   retrieval shown. A blind reader rejected 6/6 of them and was RIGHT to.
                   The lesson generalises: a positive control has to satisfy the rubric it
                   is scored against, or it measures the control's defect, not the reader's.

A reader that misses the wrong-plants is credulous; one that rejects the right-plants is
indiscriminate. Only a reader that separates both earns a reading on the real items.

Generation is the SHIPPED path -- ask_naren.answering.answer_situation, same prompt, same
model, same grounding gate -- so this audits what was committed rather than the prototype.
Retrieval masks the situation's own call (leave-one-call-out), since situations are drawn
from the corpus. Read-only Postgres, no writes anywhere.

    python ask-naren/audit/build_answer_audit.py --n 36 --controls 6
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from ask_naren import answering, retrieval          # noqa: E402
from config import load_config                      # noqa: E402
from preprocessing import embedder                  # noqa: E402
from shared import storage                          # noqa: E402
from shared.gateway import GatewayClient            # noqa: E402

SEED = 20260826
MIN_TRIGGER_LEN = 40
MIN_RESPONSE_LEN = 60
HOSTADDR = "18.138.49.39"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


class MaskedPool:
    """A RetrievalPool view with one call masked out. Wraps rather than modifies the
    production pool: leave-one-call-out is a property of THIS measurement (the situation is
    a corpus row), not of the service, which never sees a situation it already contains."""

    def __init__(self, pool: retrieval.RetrievalPool, exclude_call: str):
        self._pool = pool
        self._keep = np.array([p["call_filename"] != exclude_call for p in pool.pairs])

    def top1(self, query_vec) -> retrieval.Match:
        q = np.asarray(query_vec, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        sims = np.where(self._keep, self._pool.vectors @ q, -np.inf)
        best = int(np.argmax(sims))
        return retrieval.Match(pair=self._pool.pairs[best], cosine=float(sims[best]))


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


def _sample(pairs: list[dict], rng, n: int) -> list[dict]:
    """Rotate across coachable scenarios rather than concentrating in the biggest one -- a
    rate dominated by one scenario is a fact about that scenario, not about the tool."""
    by_scenario: dict[str, list[dict]] = {}
    for p in pairs:
        if (len(p["trigger_text"] or "") >= MIN_TRIGGER_LEN
                and len(p["response_text"] or "") >= MIN_RESPONSE_LEN):
            by_scenario.setdefault(p["scenario_key"], []).append(p)
    keys = sorted(by_scenario)
    rng.shuffle(keys)
    picked: list[dict] = []
    i = 0
    while len(picked) < n and i < 20 * max(len(keys), 1):
        bucket = by_scenario[keys[i % len(keys)]]
        if bucket:
            picked.append(bucket.pop(int(rng.integers(0, len(bucket)))))
        i += 1
    return picked[:n]


def _generate(items, pool, gw, out_path):
    records = []
    for n, item in enumerate(items, 1):
        masked = MaskedPool(pool, item["call_filename"])
        match = masked.top1(embedder.embed_query_matrix([item["trigger_text"]])[0])
        try:
            result = answering.answer_situation(
                item["trigger_text"], masked, gw,
                embed_query=embedder.embed_query_matrix)
        except Exception as e:                        # noqa: BLE001 -- recorded, not fatal
            print(f"  [{n}/{len(items)}] FAILED: {e}", flush=True)
            continue
        records.append({
            "situation": item["trigger_text"],
            "own_real_reply": item["response_text"],
            "held_out_scenario": item["scenario_key"],
            "retrieved_scenario": match.pair["scenario_key"],
            "retrieved_trigger": match.pair["trigger_text"],
            "retrieved_response": match.pair["response_text"],
            "cosine": match.cosine,
            "same_scenario": item["scenario_key"] == match.pair["scenario_key"],
            "result": result,
        })
        out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        state = "DECLINED" if result["declined"] else "answered"
        print(f"  [{n}/{len(items)}] {state} cos={match.cosine:.3f} "
              f"same_scenario={records[-1]['same_scenario']}", flush=True)
    return records


def _assemble(answered, positives, n_controls, rng):
    packet, key = [], []

    def add(situation, client_said, naren_replied, answer, meta):
        packet.append({"situation": situation, "retrieved_client_said": client_said,
                       "retrieved_naren_replied": naren_replied, "answer": answer})
        key.append(meta)

    for r in answered:
        add(r["situation"], r["retrieved_trigger"], r["retrieved_response"],
            r["result"]["answer"],
            {"kind": "real", "same_scenario": r["same_scenario"], "cosine": r["cosine"],
             "held_out_scenario": r["held_out_scenario"],
             "retrieved_scenario": r["retrieved_scenario"]})

    half = max(len(answered) // 2, 1)
    for i in range(min(n_controls, len(answered))):
        donor = answered[i]
        other = answered[(i + half + 1) % len(answered)]
        if other["situation"] == donor["situation"]:
            continue
        add(other["situation"], donor["retrieved_trigger"], donor["retrieved_response"],
            donor["result"]["answer"], {"kind": "control_wrong"})

    for r in positives:
        add(r["situation"], r["retrieved_trigger"], r["retrieved_response"],
            r["result"]["answer"], {"kind": "control_right",
                                    "cosine": r["cosine"]})

    order = rng.permutation(len(packet))
    blind = [{"id": n + 1, **packet[j]} for n, j in enumerate(order)]
    answer_key = [{"id": n + 1, **key[j]} for n, j in enumerate(order)]
    return blind, answer_key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=36)
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--from-raw", action="store_true",
                    help="reuse answer_audit_raw.json instead of regenerating "
                         "the real items -- for rebuilding the packet after a "
                         "control-design fix without re-rolling the sample")
    args = ap.parse_args()

    conn = _connect_read_only(load_config().database_url)
    try:
        pairs = retrieval.load_coachable_pairs(conn)
    finally:
        conn.close()
    print(f"[pool] {len(pairs)} coachable pairs after dedup", flush=True)
    vectors = embedder.embed_query_matrix([p["trigger_text"] for p in pairs])
    pool = retrieval.RetrievalPool(pairs, vectors)

    rng = np.random.default_rng(args.seed)
    items = _sample(pairs, rng, args.n)
    print(f"[sample] {len(items)} situations across "
          f"{len({i['scenario_key'] for i in items})} scenarios", flush=True)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    raw_path = ARTIFACTS / "answer_audit_raw.json"
    if args.from_raw:
        # Reuse the already-paid-for generations so a control-design fix does not re-roll
        # the real items under test. Changing the sample and the control in one step would
        # leave no way to tell which moved the result.
        records = json.loads(raw_path.read_text(encoding="utf-8"))
        print(f"[reused] {len(records)} generations from {raw_path.name}", flush=True)
    else:
        with GatewayClient() as gw:
            records = _generate(items, pool, gw, raw_path)

    answered = [r for r in records if not r["result"]["declined"]]
    print(f"\n[generated] {len(records)} items, {len(answered)} answered, "
          f"{len(records) - len(answered)} declined", flush=True)
    if not answered:
        raise SystemExit("every item declined -- no answers to audit")

    # Positive controls: same situations, retrieval UNMASKED. With the full pool the
    # situation retrieves its own call (it IS a corpus trigger), so grounding is exactly on
    # target and a wrong answer here would be the model's fault, not retrieval's.
    print(f"[positives] generating {args.controls} self-retrieval controls "
          f"(unmasked pool)...", flush=True)
    positives = []
    with GatewayClient() as gw:
        for r in answered[:args.controls]:
            try:
                res = answering.answer_situation(
                    r["situation"], pool, gw, embed_query=embedder.embed_query_matrix)
            except Exception as e:                    # noqa: BLE001
                print(f"  positive FAILED: {e}", flush=True)
                continue
            if res["declined"]:
                print("  positive declined -- skipped (a declined positive is not a "
                      "known-right item)", flush=True)
                continue
            match = pool.top1(embedder.embed_query_matrix([r["situation"]])[0])
            positives.append({"situation": r["situation"],
                              "retrieved_trigger": match.pair["trigger_text"],
                              "retrieved_response": match.pair["response_text"],
                              "cosine": match.cosine, "result": res})
    print(f"[positives] {len(positives)} usable", flush=True)

    blind, answer_key = _assemble(answered, positives, args.controls, rng)
    (ARTIFACTS / "answer_audit_packet.json").write_text(
        json.dumps(blind, indent=2), encoding="utf-8")
    (ARTIFACTS / "answer_audit_key.json").write_text(
        json.dumps(answer_key, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for k in answer_key:
        counts[k["kind"]] = counts.get(k["kind"], 0) + 1
    print(f"[packet] {len(blind)} items {counts} -> artifacts/answer_audit_packet.json",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
