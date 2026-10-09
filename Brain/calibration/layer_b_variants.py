#!/usr/bin/env python3
"""Layer B pair-extraction VARIANTS: the S (segmentation) and A (admission) knobs.

Spec: docs/superpowers/specs/2026-08-16-layer-b-redesign-design.md sections 3.4-3.7

Deliberately a separate module from `layer_b_arms.py`, which holds the METRIC. Mechanism and
yardstick must not live in one file: a change to how pairs are built should never be able to
touch how they are scored, and the two are audited independently.

*** THIS IS THE ONE PLACE THIS TRIAL PARAPHRASES PRODUCTION, AND IT IS PAID FOR BY A PROOF. ***
The repo rule is "import production code, never paraphrase it" -- two scratchpad
reimplementations of the transcript parse disagreed with the real thing by ~20%. But the S and
A knobs vary the INTERIOR of `v1/layer_b.extract_pairs`, so there is nothing to import: a hook
would mean editing production, which this trial forbids. The discipline that replaces the rule
is an equivalence PROOF -- at the control setting (`s0`, `a0`) this function must return
byte-identical pairs to `extract_pairs` over every transcript in the corpus, asserted by
`verify_equivalence()` and re-run before any treatment arm is read. A paraphrase that is proven
equal at the control is not a paraphrase risk; an unproven one is.

WHAT IS AND IS NOT VARIED. Everything outside the two knobs is production's, verbatim:
the response window's break rule, the JOVEO_OTHER step-over, the `if response_parts:` gate, and
the `i = j` advance. Only the trigger's EXTENT (S) and the two admission predicates (A) move.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/layer_b_variants.py --verify
    ..\\.venv\\Scripts\\python.exe calibration/layer_b_variants.py --funnel --segment s1 --admit a4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.path and sys.path[0] not in ("", "."):
    sys.path[0] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEGMENTS = ("s0", "s1")
ADMITS = ("a0", "a1", "a3", "a4")


# ---------------------------------------------------------------------------------------
# admission predicates -- Knob A
# ---------------------------------------------------------------------------------------

def _always(_text: str) -> bool:
    return True


def admission_predicates(admit: str, floors: dict | None = None):
    """(trigger_ok, response_ok) for one Knob A setting.

    `_is_substantive` is imported from production and is applied to BOTH sides there --
    `v1/layer_b.py:45` gates the trigger and `:54` gates each Naren turn. That second
    application had never been named in any spec or handoff in this repo, and it is the one
    that deletes evidence from the ONLY text Layer C consumes.

      a0  production: both sides gated by >=5 non-stop alphabetic tokens
      a1  trigger floor removed; response floor untouched
      a4  RESPONSE floor removed; trigger floor untouched
      a3  both floors replaced by a corpus-percentile rule with NO stoplist

    `a3` needs the corpus-derived floors, which is why it takes `floors`; every other setting
    ignores it. Passing `a3` without them RAISES rather than silently falling back to a0 --
    a default here would be a threshold nobody chose, which is the failure mode
    `ego_trap/settings.py` was deleted for.
    """
    from v1.layer_b import _is_substantive

    if admit == "a0":
        return _is_substantive, _is_substantive
    if admit == "a1":
        return _always, _is_substantive
    if admit == "a4":
        return _is_substantive, _always
    if admit == "a3":
        if not floors or "client" not in floors or "naren" not in floors:
            raise ValueError(
                "a3 requires corpus-derived floors {'client': n, 'naren': m}. There is no "
                "defensible default: a percentile floor is a property of THIS corpus, and a "
                "hardcoded fallback would be a threshold nobody chose.")
        return (_alpha_floor(floors["client"]), _alpha_floor(floors["naren"]))
    raise ValueError(f"unknown admit setting {admit!r}; expected one of {ADMITS}")


def _alpha_floor(floor: int):
    """Predicate: at least `floor` alphabetic tokens, STOPLIST NOT CONSULTED.

    This is the `Indeed` fix, and it fixes it by deletion rather than by a whitelist. spaCy's
    stoplist contains `indeed` while `ziprecruiter`, `greenhouse`, `workday` and `linkedin` are
    absent, so production's filter is inconsistent across direct competitors in a
    recruitment-advertising corpus -- and `"Indeed has $3 cost per API call."` keeps two content
    words and is DROPPED. Adding a domain whitelist would be the "a threshold must never be a
    curated list" anti-pattern; dropping the stoplist entirely removes the vocabulary dependence
    at its source.
    """
    from v1.layer_b import _nlp

    def ok(text: str) -> bool:
        return sum(1 for t in _nlp(text) if t.is_alpha) >= floor

    return ok


def derive_alpha_floors(turns_by_call, target_client: float, target_naren: float) -> dict:
    """Percentile floors chosen so `a3` admits the SAME FRACTION production does.

    *** a3 IS VOLUME-NEUTRAL BY CONSTRUCTION, AND THAT IS THE WHOLE POINT. *** If it admitted
    a different number of turns, the comparison against a0 would measure the volume change, not
    the stoplist dependence -- and it would need its own placebo. Matching the admitted fraction
    makes it a pure "which turns" test: same count, different selection, so any difference in
    the outcome is attributable to WHICH turns the two rules pick.

    `target_*` are production's own admitted fractions, measured on this corpus, so the floor is
    derived from the data rather than guessed.
    """
    from preprocessing.transcript_parser import SpeakerRole
    from v1.layer_b import _nlp

    counts = {"client": [], "naren": []}
    for turns in turns_by_call:
        for t in turns:
            if t.role == SpeakerRole.CLIENT:
                key = "client"
            elif t.role == SpeakerRole.NAREN:
                key = "naren"
            else:
                continue
            counts[key].append(sum(1 for tok in _nlp(t.text) if tok.is_alpha))
    out = {}
    for key, target in (("client", target_client), ("naren", target_naren)):
        vals = sorted(counts[key])
        if not vals:
            raise ValueError(f"no {key} turns -- the a3 floor cannot be derived")
        # Keep the top `target` fraction: the floor is the value at the (1 - target) quantile.
        idx = min(len(vals) - 1, max(0, int(round((1.0 - target) * (len(vals) - 1)))))
        out[key] = vals[idx]
    return out


# ---------------------------------------------------------------------------------------
# segmentation -- Knob S
# ---------------------------------------------------------------------------------------

def client_move(turns, i: int, segment: str) -> tuple[str, int, int]:
    """(trigger_text, trigger_turn_index, index after the move) for the move starting at i.

      s0  production: exactly one CLIENT turn.
      s1  a MAXIMAL RUN OF ADJACENT CLIENT TURNS, joined in order.

    An `UNATTRIBUTED` turn ends an s1 move for the same reason it can never be a trigger: the
    speaker is unidentified, so it cannot be asserted to be the client continuing. A
    `JOVEO_OTHER` turn ends it too -- once a Joveo voice has spoken, the client's move is over.

    `trigger_turn_index` is the FIRST turn of the run, which keeps `pair_id` unique per move
    (`layer_bc_arms.build_pairs` stamps `f"{stem}:{turn_index}"`) and points a reader at where
    the move began rather than where it ended.

    Measured: 7,480 CLIENT turns (36.0% of the corpus) are NOT last in their block, so today
    their text is discarded outright -- production only ever pairs the last turn of a run.
    """
    from preprocessing.transcript_parser import SpeakerRole

    if segment == "s0":
        return turns[i].text, turns[i].index, i + 1
    if segment != "s1":
        raise ValueError(f"unknown segment setting {segment!r}; expected one of {SEGMENTS}")
    j, parts = i, []
    while j < len(turns) and turns[j].role == SpeakerRole.CLIENT:
        parts.append(turns[j].text)
        j += 1
    return " ".join(parts), turns[i].index, j


# ---------------------------------------------------------------------------------------
# the variant extractor
# ---------------------------------------------------------------------------------------

def extract_pairs_variant(turns, db_call_id: int, segment: str = "s0",
                          admit: str = "a0", floors: dict | None = None) -> list[dict]:
    """`v1/layer_b.extract_pairs` with the S and A knobs exposed. Defaults ARE production.

    Everything outside the knobs is production's, and the pieces are called out because each
    one is a decision somebody could think was arbitrary:

      * the response window accumulates NAREN turns and STEPS OVER `JOVEO_OTHER` without
        capturing its text -- that discard is defect 2.4 and is Knob S2's territory, NOT
        varied here.
      * any other role BREAKS the window, `UNATTRIBUTED` included.
      * `if response_parts:` -- no reply, no pair. Untouched.
      * the advance is `i = j` on a hit and `i = after` otherwise, which for `s0` is exactly
        production's `i = j if response_parts else i + 1`, and for `s1` skips the whole
        consumed run rather than re-entering it mid-move.
    """
    from preprocessing.transcript_parser import SpeakerRole

    trigger_ok, response_ok = admission_predicates(admit, floors)
    pairs: list[dict] = []
    i = 0
    while i < len(turns):
        if turns[i].role != SpeakerRole.CLIENT:
            i += 1
            continue
        trigger_text, trigger_index, after = client_move(turns, i, segment)
        if not trigger_ok(trigger_text):
            i = after
            continue
        response_parts = []
        j = after
        while j < len(turns):
            t = turns[j]
            if t.role == SpeakerRole.NAREN:
                if response_ok(t.text):
                    response_parts.append(t.text)
                j += 1
            elif t.role == SpeakerRole.JOVEO_OTHER:
                j += 1
            else:
                break
        if response_parts:
            pairs.append({
                "call_id": db_call_id,
                "scenario_id": None,
                "scenario_key": None,
                "turn_index": trigger_index,
                "trigger_text": trigger_text,
                "response_text": " ".join(response_parts),
            })
        i = j if response_parts else after
    return pairs


# ---------------------------------------------------------------------------------------
# the proof
# ---------------------------------------------------------------------------------------

def verify_equivalence(recordings: str = "recordings", limit: int = 0) -> dict:
    """At (s0, a0) this module MUST return byte-identical pairs to production. Prove it.

    This is what buys the right to paraphrase `extract_pairs` at all. It compares every field
    of every pair, in order, over every transcript -- not a count, because two different
    extractions can agree on how many pairs they produce while disagreeing about which.

    Run before any treatment arm is read, and re-run after any edit to this module.
    """
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster
    from v1.layer_b import extract_pairs

    cfg = load_config()
    files = sorted(Path(recordings).glob("*.txt"))
    if limit:
        files = files[:limit]
    if not files:
        raise SystemExit(f"no transcripts in {recordings}/")

    n_pairs = 0
    mismatches = []
    for n, path in enumerate(files, 1):
        turns = parse_transcript(str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
                                 roster=load_roster(str(path)))
        prod = extract_pairs(turns, n)
        mine = extract_pairs_variant(turns, n, "s0", "a0")
        n_pairs += len(prod)
        if prod != mine:
            mismatches.append({"file": path.name, "prod": len(prod), "variant": len(mine)})
        if n % 100 == 0 or n == len(files):
            print(f"  {n}/{len(files)} calls, {n_pairs} pairs, "
                  f"{len(mismatches)} mismatched", flush=True)
    return {"files": len(files), "pairs": n_pairs, "mismatches": mismatches}


def funnel(recordings: str, segment: str, admit: str, floors: dict | None = None) -> dict:
    """Pair counts for one (S, A) setting. The `--funnel` half of the symmetric-filtering diff.

    Printing this per arm BEFORE any Layer C run is the mechanical form of "for every arm, list
    what was filtered and diff the lists" -- a guard this repo has grown four separate times
    and never written down as one rule.
    """
    from config import load_config
    from preprocessing.transcript_parser import parse_transcript, load_roster

    cfg = load_config()
    files = sorted(Path(recordings).glob("*.txt"))
    n_pairs = calls_with_pairs = 0
    trig_chars = resp_chars = 0
    for n, path in enumerate(files, 1):
        turns = parse_transcript(str(path), cfg.joveo_speakers_lower, cfg.naren_name_lower,
                                 roster=load_roster(str(path)))
        got = extract_pairs_variant(turns, n, segment, admit, floors)
        n_pairs += len(got)
        calls_with_pairs += 1 if got else 0
        trig_chars += sum(len(p["trigger_text"]) for p in got)
        resp_chars += sum(len(p["response_text"]) for p in got)
        if n % 100 == 0 or n == len(files):
            print(f"  {n}/{len(files)} calls, {n_pairs} pairs", flush=True)
    return {"segment": segment, "admit": admit, "pairs": n_pairs,
            "calls_with_pairs": calls_with_pairs,
            "mean_trigger_chars": (trig_chars / n_pairs) if n_pairs else 0.0,
            "mean_response_chars": (resp_chars / n_pairs) if n_pairs else 0.0}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recordings", default="recordings")
    p.add_argument("--verify", action="store_true",
                   help="prove (s0,a0) is byte-identical to production over the whole corpus")
    p.add_argument("--funnel", action="store_true", help="pair counts for one (S,A) setting")
    p.add_argument("--segment", default="s0", choices=SEGMENTS)
    p.add_argument("--admit", default="a0", choices=ADMITS)
    p.add_argument("--limit", type=int, default=0, help="verify only: first N transcripts")
    a = p.parse_args()

    if a.verify:
        r = verify_equivalence(a.recordings, a.limit)
        print(f"\n{r['files']} transcripts, {r['pairs']} production pairs")
        if r["mismatches"]:
            print(f"!! {len(r['mismatches'])} FILE(S) DIFFER -- the variant is NOT production "
                  f"at (s0,a0), so no treatment arm built on it is readable:")
            for m in r["mismatches"][:10]:
                print(f"   {m}")
            raise SystemExit(1)
        print("EQUIVALENT: every pair matches production field-for-field at (s0, a0).")
    elif a.funnel:
        r = funnel(a.recordings, a.segment, a.admit)
        print(f"\n{r}")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
