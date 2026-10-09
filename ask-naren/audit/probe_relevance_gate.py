#!/usr/bin/env python3
"""Issue #9: can a RELEVANCE judgment separate the right answers from the wrong ones, where
cosine, scenario labels and rank all could not?

    python ask-naren/audit/probe_relevance_gate.py            # judge + score
    python ask-naren/audit/probe_relevance_gate.py --score    # re-score from disk, free

THE HYPOTHESIS UNDER TEST. All nine wrong answers across #8's two arms have one shape: the
retrieved exchange is about the right TOPIC and answers a DIFFERENT question (see
../docs/findings/answer-failure-modes.md). Cosine measures aboutness, so it cannot see this
-- the nine wrong pairs score 0.757-0.845, squarely inside the right answers' 0.720-0.858.
The claim is that a judgment about the specific PROPOSITION can see what a similarity score
cannot.

WHY THIS PROBE IS ALMOST FREE, AND WHY THAT MATTERS. It re-judges the 46 answers already
generated and already blind-read in #8. No answer is generated, no packet is built, no
reader is dispatched. If the hypothesis is wrong, it dies for the price of 46 small
judgments rather than another generation pass.

TWO ARMS, because it is not obvious which signal a runtime gate should use:

  trigger   "does the retrieved client turn ask the same kind of question about the same
            subject as the situation?"  -- compares the two CLIENT turns only.
  response  "does Naren's reply here actually answer the question the situation asks?"
            -- compares the situation to the RESPONSE, which is the thing the answer is
            built from and is closer to what the oracle test will ask.

Both are available at request time, so either could become a gate. Running them on the same
items is the only way to learn which is worth building.

WHAT THE JUDGE IS NOT SHOWN. Not the generated answer, and not the blind-read verdict. It
sees the situation and the retrieved exchange, which is exactly what a runtime gate would
have. Showing it the answer would let it infer the outcome from the answer's coherence, and
showing it the verdict would make the whole thing a tautology -- the failure mode this
project has paid for twice (#7's invalid positive control, #8's premise).

HOW TO READ THE RESULT. The 2x2 against the known verdicts is the whole output. A judge that
calls everything relevant scores zero sensitivity and is worthless; a judge that calls
everything irrelevant would gate away 37 right answers to catch 9 wrong ones and is worse
than nothing. Only a judge that separates them is a candidate gate, and the cost side --
right answers it would have blocked -- must be reported next to the benefit, because a
retrieval floor already failed exactly that test (2-3 right answers destroyed per wrong one
removed, ADR 0005).

n = 46, of which 9 are wrong. Every number here is a hypothesis-sized signal, not a finding.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "Brain"))

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
OUT = ARTIFACTS / "relevance_gate_probe.json"

MODEL = "gemini-3.6-flash"
REASONING_EFFORT = "medium"
MAX_TOKENS = 2048

SOURCES = (
    ("arms_key.json", "arms_packet.json", "arms_verdicts.json"),
    ("unpaired_key.json", "unpaired_packet.json", "unpaired_verdicts.json"),
)


def _load(name: str):
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8-sig"))


def _verdict(raw) -> str:
    return "right" if str(raw).strip().lower().startswith("right") else "wrong"


def collect_items() -> list[dict]:
    """The 46 delivered answers from #8's two gated reads, with their verdicts attached.

    The verdict travels with the item for SCORING only and is never put in a prompt.
    """
    items = []
    for key_file, packet_file, verdict_file in SOURCES:
        key = {e["id"]: e for e in _load(key_file)}
        packet = {p["id"]: p for p in _load(packet_file)}
        verdicts = {v["id"]: v for v in _load(verdict_file)}
        for item_id, entry in key.items():
            if entry["kind"] != "real" or item_id not in verdicts:
                continue
            p = packet[item_id]
            items.append({
                "source": key_file,
                "id": item_id,
                "arm": entry.get("arm"),
                "cosine": entry.get("cosine"),
                "situation": p["situation"],
                "retrieved_client_said": p["retrieved_client_said"],
                "retrieved_naren_replied": p["retrieved_naren_replied"],
                "verdict": _verdict(verdicts[item_id]["verdict"]),
            })
    return items


def build_prompt(item: dict) -> str:
    """One prompt, both arms, so the two judgments see identical material.

    Asked as two SEPARATE questions rather than one combined relevance score: the point of
    the probe is to learn which signal discriminates, and a single blended answer would not
    say.
    """
    return "\n".join([
        "You are checking whether a retrieved past conversation is the right source to "
        "answer a colleague's current situation. You are NOT judging any answer -- no answer "
        "is shown to you.",
        "",
        "THE SITUATION a colleague needs help with (a client's own words):",
        f"  {item['situation']}",
        "",
        "A PAST EXCHANGE that was retrieved as the closest match. Naren is a senior "
        "colleague; this is spoken transcript, so it is fragmentary and unpolished.",
        f"  The client said: {item['retrieved_client_said']}",
        f"  Naren replied: {item['retrieved_naren_replied']}",
        "",
        "Answer TWO independent questions about this pair.",
        "",
        "Q1 (same_question): Does the retrieved client turn ask the same kind of question, "
        "about the same subject, as the situation? Being about the same broad topic is NOT "
        "enough. Watch specifically for: the subject being inverted (the situation asks what "
        "WE do, the retrieved turn is about what THEY do, or vice versa); a narrowing "
        "qualifier in the situation that the retrieved turn does not share; and the two turns "
        "asking about different stages or mechanisms of the same system.",
        "",
        "Q2 (reply_answers): Does Naren's reply, as shown, actually answer the question the "
        "situation asks? Judge only what the reply itself contains -- not what a well-briefed "
        "person could construct around it. A reply that answers an adjacent question, however "
        "usefully, does not answer this one.",
        "",
        "Q3 (relation): Classify the retrieved exchange into EXACTLY ONE of three "
        "categories. This is the question that matters, and the middle category is the one "
        "that is easy to lose:",
        "",
        "  \"answers_directly\"    -- the reply answers the situation's question outright.",
        "",
        "  \"usable_basis\"        -- the reply does not answer it outright, but a colleague "
        "could write a correct, useful answer to the situation using ONLY what this reply "
        "says, without adding facts of their own. Spoken transcript is fragmentary and "
        "trails off; a partial or unpolished reply still belongs here if what it does say is "
        "true of the situation and enough to act on.",
        "",
        "  \"different_question\"  -- the reply is about something else. Any answer built from "
        "it would address a DIFFERENT question than the one asked, however fluent it looked. "
        "This is the category that produces a confident, correctly-quoted answer asserting "
        "something the situation never asked about -- including when the subject is inverted "
        "(we/they), when a narrowing qualifier is dropped, or when a specific detail from "
        "this reply would be imported into a situation it does not apply to.",
        "",
        "Respond as JSON with exactly these keys:",
        '  "same_question": boolean,',
        '  "same_question_reason": one sentence naming the specific thing that matches or does not,',
        '  "reply_answers": boolean,',
        '  "reply_answers_reason": one sentence, same discipline,',
        '  "relation": one of "answers_directly", "usable_basis", "different_question",',
        '  "relation_reason": one sentence saying why that category and not the neighbouring one.',
    ])


def judge(items: list[dict]) -> list[dict]:
    from shared.gateway import GatewayClient       # noqa: PLC0415 -- import cost on --score

    results = []
    with GatewayClient() as gateway:
        for n, item in enumerate(items, 1):
            try:
                payload, _meta = gateway.chat_json(
                    build_prompt(item),
                    model=MODEL,
                    reasoning_effort=REASONING_EFFORT,
                    temperature=0.0,
                    max_tokens=MAX_TOKENS,
                    # Same reason as the answer path: the gateway caches completions by
                    # default, and a stale hit from an unrelated experiment would be
                    # indistinguishable from a fresh judgment.
                    no_cache=True,
                )
            except Exception as e:                  # noqa: BLE001 -- recorded, not fatal
                print(f"  [{n}/{len(items)}] FAILED: {e}", flush=True)
                continue
            results.append({**item,
                            "same_question": bool(payload.get("same_question")),
                            "same_question_reason": payload.get("same_question_reason", ""),
                            "reply_answers": bool(payload.get("reply_answers")),
                            "reply_answers_reason": payload.get("reply_answers_reason", ""),
                            "relation": str(payload.get("relation", "")).strip().lower(),
                            "relation_reason": payload.get("relation_reason", "")})
            OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"  [{n}/{len(items)}] verdict={item['verdict']:5s} "
                  f"same_question={results[-1]['same_question']} "
                  f"relation={results[-1]['relation']}", flush=True)
    return results


def _confusion(results: list[dict], field: str) -> None:
    """The 2x2, plus the two numbers that decide whether a gate is worth building."""
    wrong = [r for r in results if r["verdict"] == "wrong"]
    right = [r for r in results if r["verdict"] == "right"]
    caught = sum(1 for r in wrong if not r[field])       # gate would have blocked it: good
    missed = len(wrong) - caught
    blocked = sum(1 for r in right if not r[field])      # gate would have blocked it: cost
    kept = len(right) - blocked

    print(f"\n  {field}")
    print(f"    {'':22s} gate says NOT relevant   gate says relevant")
    print(f"    judged WRONG (n={len(wrong):2d})   {caught:^22d}   {missed:^18d}")
    print(f"    judged RIGHT (n={len(right):2d})   {blocked:^22d}   {kept:^18d}")
    if wrong and right:
        print(f"    catches {caught}/{len(wrong)} of the wrong answers "
              f"({caught / len(wrong):.0%})")
        print(f"    blocks  {blocked}/{len(right)} of the right answers "
              f"({blocked / len(right):.0%})")
        if caught:
            print(f"    COST RATIO: {blocked / caught:.2f} right answers destroyed per wrong "
                  f"one removed")
            print(f"      (a retrieval floor scored 2-3 here and was rejected -- ADR 0005)")
        else:
            print(f"    catches nothing -- this signal is not a gate")


def score(results: list[dict]) -> int:
    print("=" * 78)
    print(f"RELEVANCE GATE PROBE -- {len(results)} items, "
          f"{sum(1 for r in results if r['verdict'] == 'wrong')} judged wrong")
    print("=" * 78)
    print("\nThe judge never saw the generated answer or the blind-read verdict.")

    for field in ("same_question", "reply_answers"):
        _confusion(results, field)

    # THE ARM THAT MATTERS. The binary arms above collapse "a usable basis for a right
    # answer" together with "answers a different question", and the failure mode this ticket
    # is chasing lives ONLY in the second. Gating on the three-way category keeps them apart.
    for r in results:
        r["relation_ok"] = r["relation"] != "different_question"
    _confusion(results, "relation_ok")

    counts: dict[str, int] = {}
    for r in results:
        key = f"{r['relation'] or '(missing)'} / judged {r['verdict']}"
        counts[key] = counts.get(key, 0) + 1
    print("\n  three-way category against the blind-read verdict:")
    for key in sorted(counts):
        print(f"    {key:44s} {counts[key]}")

    print("\n" + "=" * 78)
    print("Items the judge called irrelevant that were nonetheless judged RIGHT --")
    print("the cost side, and worth reading before believing any of the above:")
    print("=" * 78)
    shown = 0
    for r in results:
        if r["verdict"] == "right" and not r["reply_answers"]:
            shown += 1
            print(f"\n  situation: {r['situation'][:110]}")
            print(f"  judge    : {r['reply_answers_reason'][:170]}")
            if shown >= 4:
                break
    if not shown:
        print("\n  none -- the judge blocked no right answer on the reply_answers signal.")
    print(f"\n-> artifacts/{OUT.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--score", action="store_true",
                    help="re-score the existing judgments from disk; costs nothing")
    args = ap.parse_args()

    if args.score:
        if not OUT.exists():
            raise SystemExit(f"ERROR: {OUT} not found -- run without --score first")
        return score(json.loads(OUT.read_text(encoding="utf-8")))

    items = collect_items()
    print(f"[items] {len(items)} delivered answers from #8's two gated reads "
          f"({sum(1 for i in items if i['verdict'] == 'wrong')} judged wrong)", flush=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    results = judge(items)
    if not results:
        raise SystemExit("no judgments returned")
    return score(results)


if __name__ == "__main__":
    sys.exit(main())
