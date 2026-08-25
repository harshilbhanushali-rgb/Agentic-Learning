#!/usr/bin/env python3
"""Build a BLINDED, COUNTERBALANCED read packet comparing two playbook arms.

Nobody has read any of these documents. PB1 is an evidence-breadth check, not a quality
judgement, so every claim about the new config so far is a claim about citations, not about
whether the coaching is any good. This produces the artifact a blind reader scores.

DESIGN, and it follows the routing-A/B's own hard-won lessons:
  * COUNTERBALANCED. The measured failure of the previous read instrument was position bias --
    readers answered "A" on 12 of 15 votes. Here arm X takes side A on even-indexed scenarios
    and side B on odd ones, so a reader who always says "A" scores exactly 50% and the bias
    is visible in the result rather than hidden in it.
  * BLIND. Side labels are A/B only. No model name, no arm name, no move counts in the header,
    nothing that identifies provenance.
  * The KEY is written to a SEPARATE file that the reader never sees.

Zero spend. Reads local artifacts only.

Usage (from Brain/):
    ..\\.venv\\Scripts\\python.exe calibration/pbq_read_packet.py --x pbq_36flash_medium --y old
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402

PACKET = ARTIFACTS_DIR / "pbq_read_packet.txt"
KEY = ARTIFACTS_DIR / "pbq_read_KEY.json"


def load_arm(tag: str) -> dict:
    """tag 'old' = the shipped live documents; anything else = a pbq_* snapped artifact."""
    if tag == "old":
        d = json.loads((ARTIFACTS_DIR / "pbv_playbooks_snapped.json")
                       .read_text(encoding="utf-8-sig"))
        return {v["scenario"]: v["playbook"] for v in d["documents"].values()
                if v.get("arm") == "real"}
    d = json.loads((ARTIFACTS_DIR / f"{tag}_snapped.json").read_text(encoding="utf-8-sig"))
    return {v["scenario"]: v["playbook"] for v in d["documents"].values()}


def render(pb: dict) -> str:
    """Deterministic plain-text rendering. Identical shape for both arms, so nothing about
    the formatting can identify which arm a document came from."""
    out = ["SITUATION SIGNATURE", "  " + (pb.get("situation_signature") or "").strip(), ""]
    out.append("ARC")
    for i, a in enumerate(pb.get("arc") or [], 1):
        out.append(f"  {i}. {a}")
    out.append("")
    out.append("KEY MOVES")
    for i, m in enumerate(pb.get("key_moves") or [], 1):
        out.append(f"  MOVE {i}: {m.get('name', '')}")
        out.append(f"    criterion: {m.get('criterion', '')}")
        for e in m.get("evidence") or []:
            out.append(f"    - \"{e.get('quote', '')}\"   [{e.get('account', '')}]")
        out.append("")
    sl = pb.get("signature_language") or []
    if sl:
        out.append("SIGNATURE LANGUAGE")
        for e in sl:
            out.append(f"  - {e.get('phrase', '')}  |  \"{e.get('quote', '')}\"")
        out.append("")
    pv = pb.get("pitfalls_and_variants") or []
    if pv:
        out.append("PITFALLS AND VARIANTS")
        for e in pv:
            out.append(f"  - {e.get('text', '')}")
        out.append("")
    ld = pb.get("layer_d_checks") or []
    if ld:
        out.append("GRADER CHECKS")
        for c in ld:
            out.append(f"  - {c}")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--x", default="pbq_36flash_medium")
    p.add_argument("--y", default="old")
    a = p.parse_args()

    X, Y = load_arm(a.x), load_arm(a.y)
    scenarios = sorted(set(X) & set(Y))
    if not scenarios:
        raise SystemExit("no scenarios in common")

    lines, key = [], {}
    lines.append("BLIND PLAYBOOK COMPARISON")
    lines.append("")
    lines.append("Each section below is ONE recurring client situation, with TWO candidate")
    lines.append("coaching playbooks written for it, labelled A and B. They were generated")
    lines.append("from THE SAME underlying call evidence. Judge them on their merits as")
    lines.append("coaching material for a customer-success manager who has NOT handled this")
    lines.append("situation before.")
    lines.append("")
    lines.append("Sides are counterbalanced across sections: neither label is consistently")
    lines.append("the same source. Do not assume A and B mean the same thing twice.")
    lines.append("")
    for i, scen in enumerate(scenarios):
        # counterbalance: X on side A for even index, side B for odd
        x_is_a = (i % 2 == 0)
        side_a, side_b = (X[scen], Y[scen]) if x_is_a else (Y[scen], X[scen])
        key[scen] = {"A": a.x if x_is_a else a.y, "B": a.y if x_is_a else a.x}
        lines.append("=" * 78)
        lines.append(f"SITUATION {i + 1}: {scen}")
        lines.append("=" * 78)
        lines.append("")
        lines.append("---------- DOCUMENT A ----------")
        lines.append(render(side_a))
        lines.append("")
        lines.append("---------- DOCUMENT B ----------")
        lines.append(render(side_b))
        lines.append("")

    PACKET.write_text("\n".join(lines), encoding="utf-8")
    KEY.write_text(json.dumps({"arms": {"x": a.x, "y": a.y}, "sides": key}, indent=1),
                   encoding="utf-8")
    print(f"[write] {PACKET.name}  ({len(scenarios)} situations, "
          f"{sum(len(v) for v in lines) // 1000}k chars)")
    print(f"[write] {KEY.name}  — the reader must NOT see this")
    for scen, k in key.items():
        print(f"   {scen:<50} A={k['A']:<22} B={k['B']}")


if __name__ == "__main__":
    main()
