#!/usr/bin/env python3
"""Issue #14's gate: how often does INTAKE route a message correctly?

    python ask-naren/audit/measure_intake_accuracy.py            # the whole set
    python ask-naren/audit/measure_intake_accuracy.py --limit 6  # smoke test

WHY THIS IS CHEAP, AND WHY THAT MATTERS. Every other quality question in this project needs a
blind reader, two-sided controls and a warning that absolute rates are artifacts of framing.
Routing is not like that: it is a CLASSIFICATION WITH A KNOWABLE CORRECT ANSWER. A message
either does or does not contain the client's own words. So this needs no reader, no
generation of answers, no packet and no gate -- one intake call per message and a comparison
against a label written by hand.

THE NEGATIVE CASES ARE NOT OPTIONAL. Roughly half of these messages must NOT clarify. An
instrument with no negative case measures nothing: an intake that clarified on absolutely
everything would score 100% against a clarify-only set while being useless, and this project
has paid for that lesson twice (`ask-naren/audit/README.md`, ADR 0004). The two rates that
matter are reported separately for exactly that reason.

*** THE FIRST RECORDED SCORE IS FITTED, NOT HELD OUT. *** The initial run scored 10/12 and
the two failures were used to rewrite intake's prompt discriminators (a client asking about
Joveo's product is still a client turn; reported speech with specifics is searchable). The
rerun scored 12/12 ON THE SAME TWELVE CASES. That is a repaired instrument, NOT an accuracy
rate, and quoting it as one would be the same error as comparing two blind reads. n=12.

To get a number worth quoting, add cases that were NOT used to write the prompt and report
them separately. The two failures are worth keeping in mind when writing them, because they
are where the real boundary lies:

  - "Do you guys use WhatsApp?" -- a CLIENT asking about our product, which is a client turn
    Naren has answered, not an out-of-scope internal question.
  - "client is asking why spend went up 40% in March" -- reported speech carrying a specific
    claim. Over-clarifying here is the failure that makes the tool annoying rather than wrong.

WHAT THIS DOES NOT MEASURE. Whether the ANSWER is right. Intake changes which text reaches
retrieval; whether that produces better answers is issue #9's question and needs the blind
read. A perfect routing score here is compatible with no change in answer quality at all.

Needs the VPN (one gateway call per message). No Postgres, no embeddings, no writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

from ask_naren import intake                       # noqa: E402
from config import load_config                     # noqa: E402
from shared.gateway import GatewayClient           # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def _normalize(text: str) -> str:
    """Case- and whitespace-insensitive, so a copied span still counts as copied when
    the model normalises spacing or capitalisation. Quote characters are dropped for the
    same reason: lifting a span out of quotation marks is copying, not rewriting."""
    cleaned = "".join(c for c in (text or "") if c not in "“”\"‘’'")
    return " ".join(cleaned.split()).lower()

# Hand-labelled. Each message says what a CSM would plausibly type and what intake must do
# with it. `note` records WHY the label is what it is, so a disagreement later is a debate
# about the case rather than about what the author meant.
CASES = [
    # -- must route to answering: the client's own words are present ---------------------
    {"message": "A client said this, can you help with how Naren would reply? "
                "\"Our cost per hire is way higher than what you promised in the pitch.\"",
     "expect": "reply_to_client",
     "query_must_not_contain": ["can you help", "Naren would reply"],
     "note": "the operator's own phrasing, with the client's words quoted inside it"},
    {"message": "client just told me \"we never agreed to cap spend at the city level\", "
                "what do i say",
     "expect": "reply_to_client",
     "query_must_not_contain": ["what do i say"],
     "note": "relayed words plus a trailing ask"},
    {"message": "\"Do you guys actually use WhatsApp for candidate outreach?\"",
     "expect": "reply_to_client",
     "note": "bare quoted client turn, no framing at all"},
    {"message": "On the call she said their LinkedIn rotation is every 10 to 20 days and "
                "asked why ours is different",
     "expect": "reply_to_client",
     "note": "reported speech rather than a quote -- still the client's actual content"},
    {"message": "how do i respond when a client says the applications we send are low "
                "quality and they are getting nothing usable",
     "expect": "reply_to_client",
     "note": "hypothetical framing, but the client's position is fully stated"},
    {"message": "client is asking why their spend went up 40% in March when nothing changed "
                "on their side",
     "expect": "reply_to_client",
     "note": "specific enough to retrieve on: a number, a month and a claim"},

    # -- must clarify: a summary where the client's words are needed ---------------------
    {"message": "client is unhappy about pricing",
     "expect": "clarify",
     "note": "the canonical thin message -- a topic label, no content"},
    {"message": "having a tough conversation with an account tomorrow, help",
     "expect": "clarify",
     "note": "no situation at all, only that one exists"},
    {"message": "they are frustrated with performance",
     "expect": "clarify",
     "note": "a mood and a topic; retrieval on this reaches everything and nothing"},

    # -- must decline: not in the corpus, and rewording cannot change that ---------------
    {"message": "what is our list price for a 12 month managed services contract",
     "expect": "out_of_scope",
     "note": "a pricing fact -- Layer B will happily answer this on-topic and wrong"},
    {"message": "does our contract allow a client to terminate for convenience at 30 days",
     "expect": "out_of_scope",
     "note": "a contract fact, same failure shape"},
    {"message": "what integrations do we support with Workday",
     "expect": "out_of_scope",
     "note": "a product fact"},
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="only the first N cases (smoke test)")
    ap.add_argument("--out", default=str(ARTIFACTS / "intake_accuracy.json"))
    args = ap.parse_args()

    load_config()
    cases = CASES[:args.limit] if args.limit else CASES

    rows = []
    with GatewayClient() as gw:
        for n, case in enumerate(cases, 1):
            decision, _ = intake.classify(case["message"], gw)
            leaked = [s for s in case.get("query_must_not_contain", [])
                      if s.lower() in decision.retrieval_query.lower()]
            # Is the query a span COPIED from the message, or prose the model composed?
            # A composed query is how subject inversion gets introduced -- "nothing changed
            # on their side" rewritten to "our side" is near-identical in embedding space
            # and means the opposite, which is the corpus's most common failure shape
            # (docs/findings/answer-failure-modes.md). Checked only where a query is
            # expected at all.
            verbatim = (decision.intent != "reply_to_client"
                        or _normalize(decision.retrieval_query) in _normalize(case["message"]))
            row = {
                "message": case["message"],
                "expect": case["expect"],
                "got": decision.intent,
                "correct": decision.intent == case["expect"],
                "retrieval_query": decision.retrieval_query,
                "question": decision.question,
                "framing_leaked": leaked,
                "verbatim_span": verbatim,
                "note": case["note"],
            }
            rows.append(row)
            mark = "ok  " if row["correct"] else "WRONG"
            print(f"  [{n}/{len(cases)}] {mark} expect={case['expect']:<15} "
                  f"got={decision.intent:<15} {case['message'][:55]!r}", flush=True)
            if leaked:
                print(f"          FRAMING LEAKED INTO THE QUERY: {leaked}", flush=True)

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("ROUTING ACCURACY -- a classification against hand-written labels")
    print("=" * 78)

    overall = sum(r["correct"] for r in rows)
    print(f"  overall: {overall}/{len(rows)}")

    # Reported per class, never pooled. A pooled rate hides the failure that matters: an
    # intake biased toward clarify looks fine overall while making the tool ask questions
    # instead of answering.
    for label in ("reply_to_client", "clarify", "out_of_scope"):
        group = [r for r in rows if r["expect"] == label]
        if group:
            hit = sum(r["correct"] for r in group)
            print(f"  {label:<16} {hit}/{len(group)}")

    answerable = [r for r in rows if r["expect"] != "clarify"]
    over_clarified = [r for r in answerable if r["got"] == "clarify"]
    print(f"\n  NEGATIVE CASE -- messages that must NOT clarify: "
          f"{len(answerable) - len(over_clarified)}/{len(answerable)} held")
    if over_clarified:
        print("  Over-clarifying is the failure that makes the tool annoying rather than "
              "wrong; each of these asked a CSM a question when it could have answered:")
        for r in over_clarified:
            print(f"    - {r['message'][:70]!r}")

    composed = [r for r in rows if not r["verbatim_span"]]
    print(f"\n  VERBATIM -- the query is a span COPIED from the message: "
          f"{len(rows) - len(composed)}/{len(rows)} clean")
    if composed:
        print("  A COMPOSED query is how subject inversion gets in: rewriting \"their side\"")
        print("  to \"our side\" is near-identical in embedding space and means the opposite,")
        print("  which is this corpus's most common failure shape. Each of these was written")
        print("  rather than copied:")
        for r in composed:
            print(f"    - {r['retrieval_query'][:64]!r}")
            print(f"      from {r['message'][:64]!r}")

    leaks = [r for r in rows if r["framing_leaked"]]
    print(f"\n  FRAMING STRIPPED from the retrieval query: "
          f"{len(rows) - len(leaks)}/{len(rows)} clean")
    if leaks:
        print("  Framing left in the query is the exact thing intake exists to remove:")
        for r in leaks:
            print(f"    - {r['framing_leaked']} in {r['retrieval_query'][:60]!r}")

    print(f"\n  -> {args.out}")
    print("\nNOTE: this measures ROUTING, not answer quality. Whether better queries produce "
          "better answers is issue #9 and needs the blind read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
