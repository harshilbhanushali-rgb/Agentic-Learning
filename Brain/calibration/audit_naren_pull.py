#!/usr/bin/env python3
"""Contamination funnel + account-diversity comparison for a fresh Naren pull. Read-only.

Runs EVERY corpus-hygiene filter this repo built during the 2026-08-16 contamination work
over recordings_pull_4yr/, then puts the surviving new-unique calls side by side with the
curated recordings/ corpus on the axis that actually matters (client-account diversity —
the metric no pipeline change has ever moved; new ACCOUNTS are the one input that moves it).

Filters applied, each with its provenance:
  interview   three independent signals, reported separately and combined with the
              VALIDATED rule (subject-shape OR (your_journey AND no client domain)):
              subject shape from fetch_avoma_meeting_meta.SUBJECT_HIRE, lexical markers
              from flag_interview_transcripts, structural roster shape (lone unresolved
              outsider) from the same file.
  internal    no non-joveo real-email domain anywhere on the roster (RTX Prep-class calls
              contribute zero client turns by construction).
  staff       repair_speaker_rosters' rule, applied IN MEMORY (this script never rewrites
              a sidecar): is_rep=false entries with an @joveo.com address are staff; names
              PROVEN Joveo elsewhere (an @joveo.com address on any meeting in either
              corpus, plus the recorded EXTRA_PROVEN set) whose `email` field is not an
              email are staff. Guards identical to the applied repair: a real client
              address is never overridden, unproven names are left alone.
  phantom     production parse_transcript with the (repaired) roster; calls contributing
              ZERO CLIENT turns are flagged (the 9-calls-of-pure-Unknown-Speaker class).

Account attribution is the SAME code path as every published diversity number
(flag_proper_noun_clusters.account_map via layer_b_arms.load_account_map), with sibling
domains collapsed over the UNION so both sides fold identically.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/audit_naren_pull.py
    ..\\.venv\\Scripts\\python.exe calibration/audit_naren_pull.py --pull-dir recordings_pull_4yr
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
from calibration.fetch_avoma_meeting_meta import SUBJECT_HIRE
from calibration.flag_interview_transcripts import scan, PRIMARY_MARKER, NARRATION, NARRATION_MIN

OUT = ARTIFACTS_DIR / "naren_pull_audit.json"
EXTRA_PROVEN = {"kj"}  # repair_speaker_rosters' recorded extra, same evidence trail


def sidecars(d: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(d.glob("*.speakers.json")):
        out[f.name[: -len(".speakers.json")]] = json.loads(
            f.read_text(encoding="utf-8-sig"))
    return out


def real_email(e) -> bool:
    return isinstance(e, str) and "@" in e


def client_domains(speakers: list[dict]) -> Counter:
    doms = Counter()
    for s in speakers:
        e = str(s.get("email", "")).lower()
        if real_email(e) and not e.endswith("@joveo.com"):
            doms[e.split("@", 1)[1]] += 1
    return doms


def neff(counts: Counter) -> float:
    tot = sum(counts.values())
    if not tot:
        return 0.0
    return 1.0 / sum((c / tot) ** 2 for c in counts.values())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pull-dir", default="recordings_pull_4yr")
    p.add_argument("--baseline", default="recordings")
    a = p.parse_args()

    from config import load_config
    from preprocessing.transcript_parser import parse_transcript
    from calibration.layer_b_arms import collapse_sibling_domains, load_account_map

    pull = Path(a.pull_dir)
    base = Path(a.baseline)
    manifest = json.loads((pull / "_manifest.json").read_text(encoding="utf-8-sig"))
    pull_side = sidecars(pull)
    base_side = sidecars(base)

    base_uuids = {rec.get("meeting_uuid") for rec in base_side.values()}
    # The quarantined interviews keep their sidecars too -- a re-pulled interview must
    # count as OVERLAP (already known and excluded), not as a new call.
    excl = Path("recordings_excluded_interviews")
    excl_uuids = ({rec.get("meeting_uuid") for rec in sidecars(excl).values()}
                  if excl.exists() else set())

    new = {s: rec for s, rec in pull_side.items()
           if rec.get("meeting_uuid") not in base_uuids | excl_uuids}
    overlap = len(pull_side) - len(new)
    print(f"[pull] {len(pull_side)} calls fetched; {overlap} overlap the existing corpora "
          f"({len(base_uuids)} curated + {len(excl_uuids)} quarantined); "
          f"{len(new)} are NEW", flush=True)

    # names proven Joveo anywhere in either corpus (the repair rule's evidence base)
    proven: set[str] = set(EXTRA_PROVEN)
    for rec in list(base_side.values()) + list(pull_side.values()):
        for s in rec.get("speakers", []):
            if str(s.get("email", "")).lower().endswith("@joveo.com"):
                proven.add(str(s.get("name", "")).strip().lower())

    cfg = load_config()
    funnel = Counter()
    rows: dict[str, dict] = {}
    for stem, rec in sorted(new.items()):
        speakers = rec.get("speakers", [])
        subject = (manifest.get(stem) or {}).get("subject") or ""
        cdoms = client_domains(speakers)

        subj_hit = bool(SUBJECT_HIRE.search(subject))
        text = (pull / f"{stem}.txt").read_text(encoding="utf-8-sig")
        markers = scan(text)
        lex_hit = PRIMARY_MARKER in markers
        narration = len(NARRATION.findall(text)) >= NARRATION_MIN
        non_rep = [s for s in speakers if not s.get("is_rep")]
        structural = (len(non_rep) == 1 and len(speakers) <= 3
                      and not real_email(non_rep[0].get("email", "")) if non_rep else False)
        interview = subj_hit or ((lex_hit or (structural and narration)) and not cdoms)

        # in-memory staff repair, exactly the applied rule's two guards
        repaired = []
        n_repaired = 0
        for s in speakers:
            e = str(s.get("email", "")).lower()
            nm = str(s.get("name", "")).strip().lower()
            s2 = dict(s)
            if not s.get("is_rep") and (
                    e.endswith("@joveo.com")
                    or (not real_email(e) and nm in proven)):
                s2["is_rep"] = True
                n_repaired += 1
            repaired.append(s2)

        internal = not cdoms and not interview

        turns = parse_transcript(str(pull / f"{stem}.txt"), cfg.joveo_speakers_lower,
                                 cfg.naren_name_lower, roster=repaired)
        n_client = sum(1 for t in turns
                       if str(getattr(t, "role", "")).upper().endswith("CLIENT"))
        n_unattr = sum(1 for t in turns
                       if "UNATTRIBUTED" in str(getattr(t, "role", "")).upper())

        verdict = ("interview" if interview else
                   "internal" if internal else
                   "zero_client_turns" if n_client == 0 else "KEEP")
        funnel[verdict] += 1
        if subj_hit:
            funnel["signal_subject"] += 1
        if lex_hit:
            funnel["signal_your_journey"] += 1
        if structural and narration:
            funnel["signal_structural"] += 1
        if n_repaired:
            funnel["calls_with_staff_repair"] += 1
        rows[stem] = {"subject": subject, "verdict": verdict,
                      "client_turns": n_client, "unattributed_turns": n_unattr,
                      "staff_entries_repaired": n_repaired,
                      "signals": {"subject": subj_hit, "your_journey": lex_hit,
                                  "structural": bool(structural and narration)},
                      "client_domain": (cdoms.most_common(1)[0][0] if cdoms else None)}

    keep = [s for s, r in rows.items() if r["verdict"] == "KEEP"]
    print(f"\n[funnel] of {len(new)} new calls: KEEP {len(keep)} | "
          f"interview {funnel['interview']} (subject {funnel['signal_subject']}, "
          f"your_journey {funnel['signal_your_journey']}, structural "
          f"{funnel['signal_structural']}) | internal {funnel['internal']} | "
          f"zero-client {funnel['zero_client_turns']} | staff repairs touched "
          f"{funnel['calls_with_staff_repair']} call(s)", flush=True)

    # ------- diversity, side by side, one attribution method ---------------------------
    base_acct, base_reason, _ = load_account_map(a.baseline)
    kept_acct_raw = {s: rows[s]["client_domain"] for s in keep if rows[s]["client_domain"]}
    union_raw = dict(base_acct) | kept_acct_raw
    union_acct, merges = collapse_sibling_domains(union_raw)
    base_c = Counter(union_acct[s] for s in base_acct)
    new_c = Counter(union_acct[s] for s in kept_acct_raw)
    uni_c = base_c + new_c
    new_accounts = sorted(set(new_c) - set(base_c), key=lambda d: -new_c[d])

    def line(lbl, c, extra=""):
        top = ", ".join(f"{d} {n}" for d, n in c.most_common(5))
        print(f"  {lbl:<26}{sum(c.values()):>6} calls{len(c):>7} accts"
              f"{neff(c):>9.1f} N_eff   top5: {top}{extra}")

    print(f"\n[diversity] sibling merges over the union: {merges or 'none'}")
    line("existing corpus", base_c)
    line("new KEEP (accounted)", new_c,
         extra=f"   (+{len(keep) - len(kept_acct_raw)} kept calls with no account)")
    line("union", uni_c)
    print(f"\n  NEW accounts not in the existing corpus: {len(new_accounts)}")
    for d in new_accounts[:25]:
        print(f"    {d:<34} {new_c[d]} call(s)")
    added_client_turns = sum(rows[s]["client_turns"] for s in keep)
    print(f"\n  CLIENT turns added by KEEP calls: {added_client_turns} "
          f"(existing corpus: 20,788)")

    OUT.write_text(json.dumps({
        "pull_dir": a.pull_dir, "n_pulled": len(pull_side), "n_overlap": overlap,
        "n_new": len(new), "funnel": dict(funnel), "n_keep": len(keep),
        "sibling_merges": merges,
        "diversity": {
            "existing": {"calls": sum(base_c.values()), "accounts": len(base_c),
                         "neff": neff(base_c), "top": base_c.most_common(10)},
            "new_keep": {"calls": sum(new_c.values()), "accounts": len(new_c),
                         "neff": neff(new_c), "top": new_c.most_common(10)},
            "union": {"calls": sum(uni_c.values()), "accounts": len(uni_c),
                      "neff": neff(uni_c), "top": uni_c.most_common(10)}},
        "new_accounts": {d: new_c[d] for d in new_accounts},
        "added_client_turns": added_client_turns,
        "rows": rows,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nwrote {OUT.name}. Read-only: no corpus file was modified.")


if __name__ == "__main__":
    main()
