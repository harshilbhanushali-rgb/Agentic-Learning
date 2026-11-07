"""Build a blind grading packet: the golden cases' prod baseline + any number of replay runs.

For every case the answers are shuffled under labels A, B, C... and written WITHOUT anything
that says which version wrote them. The reader gets the question, the conversation before it,
and the case's `expected` (must / must_not / also_acceptable) -- never `naren_said`, which
describes the baseline's faults and so would unblind it. The label -> source map goes to a
separate key file the reader must not see.

The baseline is also the reader's calibration: Naren already graded it, so a reader that
disagrees with him on the baseline is not trusted on the new answers (see score_blind_packet.py).

Usage (repo root):
  python ask-naren/golden/build_blind_packet.py <golden.json> <run1.json> [<run2.json> ...] \
      --out ask-naren/golden/recordings/runs/<name> [--seed N]
Writes <name>.packet.json (for the reader) and <name>.key.json (not for the reader).
Runs are converse.py output; their message order must match the golden case order.
"""
import argparse
import json
import random
import string


def answer_text(response):
    o = response.get("outcome")
    if o == "answered":
        return response["answer"]
    if o == "clarify":
        return "[ASKED A CLARIFYING QUESTION] " + response.get("question", "")
    if o == "declined":
        return "[DECLINED] " + response.get("message", "")
    if o == "rendered":
        return f"[RENDERED {response.get('kind')}] " + json.dumps(response)[:1500]
    return "[NO ANSWER -- error or timeout] " + json.dumps(response)[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("golden")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1104)
    a = ap.parse_args()

    golden = json.load(open(a.golden, encoding="utf-8"))
    cases = golden["cases"]
    runs = [json.load(open(p, encoding="utf-8")) for p in a.runs]
    for p, run in zip(a.runs, runs):
        if len(run) != len(cases):
            raise SystemExit(f"{p}: {len(run)} messages, golden has {len(cases)} cases")
        for c, r in zip(cases, run):
            if r["message"] != c["question"]:
                raise SystemExit(f"{p}: order mismatch at {c['id']}")

    rng = random.Random(a.seed)
    packet, key = [], {}
    for i, c in enumerate(cases):
        sources = [("baseline", c["baseline"]["answer"] if c["baseline"]["outcome"] == "answered"
                    else "[DECLINED] " + c["baseline"].get("message", ""))]
        for p, run in zip(a.runs, runs):
            sources.append((p.rsplit("/", 1)[-1].removesuffix(".json"), answer_text(run[i]["response"])))
        rng.shuffle(sources)
        labels = string.ascii_uppercase[:len(sources)]
        before = [{"asked": cases[j]["question"]} for j in range(max(0, i - 1), i)] if "FOLLOW-UP" in c["context"] else []
        packet.append({
            "case": c["id"],
            "question": c["question"],
            "conversation_before": before,
            "note_for_reader": "This message is a follow-up to the one before it." if before else "",
            # `note` and `needs_outside_calls` talk about the baseline and Naren's view of it.
            "expected": {k: v for k, v in c["expected"].items() if k not in ("note", "needs_outside_calls")},
            "answers": {lab: text for lab, (_, text) in zip(labels, sources)},
        })
        key[c["id"]] = {lab: src for lab, (src, _) in zip(labels, sources)}
    json.dump(packet, open(a.out + ".packet.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(key, open(a.out + ".key.json", "w", encoding="utf-8"), indent=2)
    print(f"{len(packet)} cases x {len(runs) + 1} answers -> {a.out}.packet.json / .key.json")


if __name__ == "__main__":
    main()
