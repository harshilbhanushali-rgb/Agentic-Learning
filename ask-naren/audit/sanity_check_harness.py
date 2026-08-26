#!/usr/bin/env python3
"""Exercises build_answer_audit.py's own machinery on hand-built vectors, with a stub
gateway -- no Postgres, no gateway, no VPN, no cost, about a second to run.

    python ask-naren/audit/sanity_check_harness.py     # exits non-zero on any failure

WHY THIS EXISTS RATHER THAN A pytest FILE. Brain's suite covers ask_naren/ (the shipped
service). It cannot cover THIS directory: the audit scripts are measurement apparatus that
lives outside Brain's package, and MaskedPool -- the class that enforces leave-one-call-out
for the whole answer audit -- is defined here, so nothing in tests/ ever touches it.

That gap was not hypothetical. On the first run of this script (2026-08-27, issue #8) it
caught MaskedPool returning the MASKED call as a shortlist candidate: masked rows were
ranked to -inf and then sliced with [:k], so any k reaching past the kept rows put the
held-out call back into the shortlist at cosine -inf. That is a leave-one-call-out
violation inside the class whose only job is to prevent one, and it would have silently
contaminated an arm of the very A/B it was built for. Unit tests could not have seen it.

The check that matters most here is #3: an answer grounded in candidate 2 must CITE
candidate 2. Getting that wrong produces a confident, correctly-quoted answer under
another call's citation -- an ADR 0002 violation that every gate metric reports as a pass.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

_spec = importlib.util.spec_from_file_location("baa", _HERE / "build_answer_audit.py")
baa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baa)

from ask_naren import answering, retrieval          # noqa: E402

OWN, NEAR, FAR = "own_call.txt", "near_call.txt", "far_call.txt"

# Shaped after the real id 28/30 pair recorded in issue #8: the situation's own call says
# "No, not all boards", an adjacent call says "Yes" to a DIFFERENT question, and answering
# from the adjacent one produces a confident answer asserting the opposite of the truth.
PAIRS = [
    {"pair_id": 1, "trigger_text": "do you cover all job boards across the globe",
     "response_text": "No. It's not all job boards across the globe, it is a curated set.",
     "call_filename": OWN, "scenario_key": "coverage_question"},
    {"pair_id": 2, "trigger_text": "does that include the APAC localized boards",
     "response_text": "Yes. That does, we localized those last quarter.",
     "call_filename": NEAR, "scenario_key": "localization_question"},
    {"pair_id": 3, "trigger_text": "when does the integration go live",
     "response_text": "Let me confirm the date with the team today.",
     "call_filename": FAR, "scenario_key": "timeline_question"},
]
VECTORS = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
QUERY = np.array([0.9, 0.4, 0.05])       # nearest OWN, then NEAR, then FAR

_FAILURES: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        _FAILURES.append(f"{label}: got {got!r}, want {want!r}")


def _embed(texts):
    return np.array([QUERY] * len(texts))


class StubGateway:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def chat_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.payloads.pop(0), {}


def main() -> int:
    pool = retrieval.RetrievalPool(PAIRS, VECTORS)
    masked = baa.MaskedPool(pool, OWN)

    print("1. MaskedPool ranks, and NEVER returns the masked call")
    shortlist = masked.topk(QUERY, 3)
    check("k=3 on a 3-pair pool with 1 masked returns 2 candidates",
          [m.pair["pair_id"] for m in shortlist], [2, 3])
    check("nearest first", shortlist[0].cosine > shortlist[1].cosine, True)
    check("top1 agrees with topk[0]", masked.top1(QUERY).pair["pair_id"], 2)

    print("2. the UNMASKED pool retrieves the situation's own exchange at cosine 1.0")
    own = pool.topk(np.array([1.0, 0.0, 0.0]), 3)
    check("rank 1 is the own call", own[0].pair["call_filename"], OWN)
    check("at cosine 1.0 -- what the positive-control filter relies on",
          round(own[0].cosine, 6), 1.0)

    print("3. the shipped path answers through MaskedPool, and cites what it GROUNDED in")
    gw = StubGateway({"declined": False,
                      "answer": "Tell them you will confirm the date today.",
                      "quote": "confirm the date with the team",
                      "cited_call": FAR})
    res = answering.answer_situation("do you cover all job boards across the globe",
                                     masked, gw, embed_query=_embed, k=2)
    check("answered", res["declined"], False)
    check("cites the grounded call, not rank 1", res["citation"]["call_filename"], FAR)
    check("reports the rank it came from", res["match"]["rank"], 2)
    check("every candidate reached the prompt",
          all(name in gw.prompts[0] for name in (NEAR, FAR)), True)

    print("4. the packet would show the GROUNDED exchange beside the answer")
    shown = next(m for m in masked.topk(QUERY, 2)
                 if m.pair["pair_id"] == res["citation"]["pair_id"])
    check("shown reply is the one the answer rests on",
          shown.pair["response_text"].startswith("Let me confirm"), True)

    print("5. k=1 through MaskedPool is the arm issue #7 measured, unchanged")
    gw1 = StubGateway({"declined": False, "answer": "Point out it is a curated set.",
                       "quote": "we localized those last quarter", "cited_call": NEAR})
    res1 = answering.answer_situation("x", masked, gw1, embed_query=_embed, k=1)
    check("answered", res1["declined"], False)
    check("rank is 1", res1["match"]["rank"], 1)
    check("used the single-candidate prompt, byte for byte",
          gw1.prompts[0] == answering.build_prompt("x", PAIRS[1]), True)

    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} FAILURE(S):")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("all harness sanity checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
