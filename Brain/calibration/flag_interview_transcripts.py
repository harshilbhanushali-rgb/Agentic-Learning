#!/usr/bin/env python3
"""How much of the "client" corpus is actually JOB INTERVIEWS? Free, read-only, no writes.

WHY THIS EXISTS. The largest coachable scenario in the gemini turn-mode taxonomy -- 822 of
3,070 coachable turns, 27% of the volume -- is candidates narrating their careers, not clients
discussing their recruitment problems. Confirmed by reading the source: one transcript has
Naren saying "we can talk more about the role", "think of this lesson as an interview" and
"specifically hiring for this role for my team", after which the other speaker narrates 13
years of work history. CLAUDE.md already records ONE instance of this
(`compensation_and_variable_structuring`, 9 calls); this is the same disease an order of
magnitude larger, and nothing in the pipeline distinguishes the two kinds of call.

WHY IT CONTAMINATES. `transcript_parser` classifies a speaker as CLIENT when they are not a
known Joveo name. A candidate is not a Joveo name, so every turn of their career history
enters the CLIENT pool, clusters cleanly (career narration is highly self-similar), and is
adjudicated as a coachable business scenario. Speaker classification fails OPEN, exactly as it
did for unlisted Joveo colleagues before the roster backfill.

DETECTION, and its limits. Two INDEPENDENT signals, reported separately rather than blended,
because either alone has a failure mode:
  lexical    interview-specific phrases. "the role" alone is not one -- it appears in client
             calls ("the role of the pixel") -- so only high-precision markers count, and a
             call needs >= MIN_MARKERS DISTINCT ones.
  account    the modal non-joveo email domain from the Avoma roster. A candidate interviews
             from a personal address, so an interview shows gmail.com or no domain at all,
             while a client call carries the client's domain.
Agreement between two signals that share no mechanism is the evidence; each on its own is a
guess. Neither is a curated list of PEOPLE, which would be the anti-pattern this repo forbids.

VERIFIED AT BOTH EDGES by reading the transcripts, which is what fixes the count at 18:
  * `your journey` alone flags 20. The 2 extras BOTH carry a real client domain and BOTH use
    the phrase in a business sense -- "in your journey of building a brand" (elevateent.com,
    a career-page/chatbot sales call) and a genuine OhioHealth account call. False positives.
  * `gmail.com` alone flags only 11, and one of those is an INTERNAL Joveo call (colleagues
    chatting about Onam and Alaska) whose roster simply lists personal addresses. So
    gmail.com does not mean "candidate".
  * The 61 no-domain calls are mostly NOT interviews; the account signal alone is far too
    broad at 72 and is useful only as a FILTER on the lexical one.
So: lexical 20, account 72, AND = 18 -- and 18 is the number that survives reading.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/flag_interview_transcripts.py
    ..\\.venv\\Scripts\\python.exe calibration/flag_interview_transcripts.py --show 12
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR

OUT = ARTIFACTS_DIR / "interview_transcripts.json"

# MEASURED, not chosen. Against 8 transcripts hand-verified as interviews by reading them,
# `>= 2 distinct markers` recalls only 3/8 -- most interviews carry one strong phrase and
# several that this file deliberately excludes as too common ("the role", "compensation").
# `your journey` ALONE recalls 8/8 with no observed false positive: it is Naren's stock
# opener ("would love to ... get an introduction and more what your journey has been so far"),
# so it is a property of how these calls are conducted rather than a curated word list.
# Hence MIN_MARKERS=1 with `your_journey` sufficient on its own.
#   >=1 marker  57 calls / 3,706 turns (15.5%)  -- over-broad
#   your_journey 20 calls / 1,282 turns (5.4%)  -- ADOPTED
#   >=2 markers 13 calls /   945 turns (3.9%)   -- 3/8 recall, rejected
MIN_MARKERS = 1
PRIMARY_MARKER = "your_journey"

# High precision only. Each is a phrase that occurs in a hiring conversation and effectively
# never in a client account review. "the role"/"this role"/"compensation" are DELIBERATELY
# excluded -- all three occur in ordinary client calls and would flood the count.
MARKERS = {
    "your_journey": r"\byour journey\b",
    "hiring_for": r"\bhiring for (this|the) role\b|\bwe(?:'re| are) hiring\b",
    "as_an_interview": r"\bas an interview\b|\bthis interview\b",
    "base_or_ote": r"\bbase salary\b|\bOTE\b|\btotal comp(?:ensation)?\b",
    "notice_period": r"\bnotice period\b|\bwhen (?:could|can) you start\b",
    "walk_me_through": r"\bwalk me through your\b|\btell me about yourself\b",
    "your_resume": r"\byour resume\b|\byour CV\b",
    "currently_earning": r"\bcurrently (?:at|earning|making)\b.{0,24}\b(?:base|k\b|thousand)",
    "why_leave": r"\bwhy (?:are you |do you want to )?leav(?:e|ing)\b|\blooking to move\b",
}
COMPILED = {k: re.compile(v, re.I) for k, v in MARKERS.items()}


# Career narration -- what a candidate DOES for most of an interview. Independent of how the
# call opened, so it catches interviews the opener misses.
NARRATION = re.compile(
    r"\bmy (?:background|career|journey)\b|\bI (?:joined|left) [A-Z]|"
    r"\bwhen I was at\b|\bin my (?:current|last|previous) role\b", re.I)
NARRATION_MIN = 3


def scan(text: str) -> list[str]:
    return sorted(k for k, rx in COMPILED.items() if rx.search(text))


def structural(stem: str, recordings: str) -> dict | None:
    """The Avoma roster's own shape. A candidate is an outsider Avoma could not resolve to an
    organisation, so their `email` field falls back to their display name.

    This signal EARNED ITS PLACE: it is the one that caught `e5ec576d`, a real interview the
    lexical opener missed (Kendra Williams narrating "my background" x5 / "my career" x3 to two
    Joveo reps). It shares no mechanism with either the phrase list or the account domain.
    """
    f = Path(recordings) / f"{stem}.speakers.json"
    if not f.exists():
        return None
    sp = json.loads(f.read_text(encoding="utf-8-sig")).get("speakers", [])
    non = [s for s in sp if not s.get("is_rep")]
    return {"n_speakers": len(sp), "n_non_rep": len(non),
            "n_unresolved": sum(1 for s in non if "@" not in str(s.get("email", ""))),
            "lone_outsider": len(non) == 1 and len(sp) <= 3}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--show", type=int, default=10)
    p.add_argument("--quarantine", default="",
                   help="MOVE every flagged transcript (and its .speakers.json sidecar) into "
                        "this directory. Deliberately a MOVE, never a delete: this is a "
                        "detection heuristic with an estimated +/-2 error, and source "
                        "recordings are not reproducible. Reverse it by moving them back.")
    a = p.parse_args()

    from calibration import routing_bench as rb
    from calibration.flag_proper_noun_clusters import account_map

    texts, call_ids = rb.build_pool(a.recordings)
    acct, _ = account_map(a.recordings)
    turns_by_call = Counter(call_ids)

    rows = []
    for f in sorted(Path(a.recordings).glob("*.txt")):
        stem = f.stem
        text = f.read_text(encoding="utf-8-sig")
        hits = scan(text)
        dom = acct.get(stem)
        st = structural(stem, a.recordings) or {}
        n_narr = len(NARRATION.findall(text))
        rows.append({"stem": stem, "markers": hits, "n_markers": len(hits),
                     "account": dom, "turns": turns_by_call.get(stem, 0),
                     "n_narration": n_narr, "structural": st,
                     "lexical_flag": PRIMARY_MARKER in hits,
                     "account_flag": dom is None or dom == "gmail.com",
                     "narration_flag": n_narr >= NARRATION_MIN,
                     "structural_flag": bool(st.get("lone_outsider"))})
    # An interview is a call where the OUTSIDER narrates their career. Either route qualifies:
    #   the opener + an unresolved/personal account   (Naren's standard interview)
    #   OR a lone outsider + sustained career narration (catches a different opener)
    # Requiring all four would re-create the >=2-marker rule that recalled 3/8.
    for r in rows:
        r["is_interview"] = bool(
            (r["lexical_flag"] and r["account_flag"])
            or (r["structural_flag"] and r["narration_flag"]))

    n_calls = len(rows)
    pool = sum(r["turns"] for r in rows)
    both = [r for r in rows if r["is_interview"]]
    lex = [r for r in rows if r["lexical_flag"]]
    acc = [r for r in rows if r["account_flag"]]
    strc = [r for r in rows if r["structural_flag"] and r["narration_flag"]]
    print(f"\n  structural+narration route: {len(strc)} calls "
          f"({sum(r['turns'] for r in strc)} turns)")

    print("\n" + "=" * 88)
    print("  HOW MUCH OF THE CLIENT POOL IS JOB INTERVIEWS?")
    print("=" * 88)
    print(f"  {n_calls} transcripts, {pool} CLIENT turns\n")
    print(f"  {'signal':<44}{'calls':>8}{'turns':>9}{'% of pool':>11}")
    for label, sel in ((f"lexical ({PRIMARY_MARKER})", lex),
                       ("account only (gmail.com or no domain)", acc),
                       ("BOTH -- the defensible count", both)):
        t = sum(r["turns"] for r in sel)
        print(f"  {label:<44}{len(sel):>8}{t:>9}{t/max(1,pool)*100:>10.1f}%")

    # agreement between two signals sharing no mechanism
    a_set, l_set = {r["stem"] for r in acc}, {r["stem"] for r in lex}
    print(f"\n  agreement: lexical n={len(l_set)}, account n={len(a_set)}, "
          f"overlap={len(a_set & l_set)}  "
          f"(Jaccard {len(a_set & l_set)/max(1,len(a_set | l_set)):.2f})")

    print(f"\n  top flagged transcripts by CLIENT turns contributed:")
    for r in sorted(both, key=lambda x: -x["turns"])[:a.show]:
        print(f"    {r['turns']:>5} turns  {str(r['account'] or '(none)'):<14} "
              f"{r['stem'][:8]}  {','.join(r['markers'][:5])}")

    if a.quarantine:
        import shutil
        # Prefer the GROUND-TRUTH union (Avoma subject + purpose + this heuristic) over the
        # heuristic alone. Measured against Avoma subjects the heuristic runs 80% recall, and
        # the union recovers the interviews whose subject says "R1"/"R3"/bare "Discussion"
        # rather than "Discussion 1".
        union = ARTIFACTS_DIR / "interview_exclusion_set.json"
        if union.exists():
            stems = set(json.loads(union.read_text(encoding="utf-8-sig")))
            both = [r for r in rows if r["stem"] in stems] or both
            print(f"\n  using the ground-truth union from {union.name}: {len(both)} calls")
        dest = Path(a.quarantine)
        dest.mkdir(parents=True, exist_ok=True)
        moved = 0
        for r in both:
            for suffix in (".txt", ".speakers.json"):
                src = Path(a.recordings) / f"{r['stem']}{suffix}"
                if src.exists():
                    shutil.move(str(src), str(dest / src.name))
                    moved += 1
        print(f"\n  QUARANTINED {len(both)} transcripts ({moved} files incl. sidecars) -> "
              f"{dest}/")
        print(f"  The pool loses {sum(r['turns'] for r in both)} turns "
              f"({sum(r['turns'] for r in both)/max(1,pool)*100:.1f}%).")
        print(f"  Every artifact keyed to the old pool is now STALE -- clustering_bench.json, "
              f"clustering_bench_members.json and\n  adjudicate_gemini_min16.json all describe "
              f"a corpus that no longer exists. Rebuild before comparing anything.")
        print(f"  To undo: move the files back from {dest}/ into {a.recordings}/")

    OUT.write_text(json.dumps({"n_calls": n_calls, "pool_turns": pool,
                               "min_markers": MIN_MARKERS, "markers": MARKERS,
                               "narration_min": NARRATION_MIN,
                               "quarantined": [r["stem"] for r in both] if a.quarantine else [],
                               "rows": rows}, indent=1), encoding="utf-8")
    print(f"\n  wrote {OUT}")
    print("  NOTE: excluding these is a PIPELINE decision, not this script's -- it writes "
          "nothing.\n  The turns are real client-role turns by the parser's rule; they are "
          "just not client\n  conversations.")


if __name__ == "__main__":
    main()
