"""Four-arm read-only trial of client-move segmentation for Layer D.

Pre-registration: docs/superpowers/specs/2026-08-13-layer-d-client-move-segmentation-design.md

NOT PRODUCTION. Nothing here is imported by v1/, v2/, shared/ or preprocessing/.
Zero Gemma calls, zero DB writes (the session is set read-only), zero Pinecone.
Postgres is read once, for the scenario vectors.

The arms differ in ONE thing: what text becomes the trigger for an exchange.

  baseline  the block's LAST TURN, whatever it is                     (production today)
  B         every turn of the last speaker's move, joined
  C         only that move's turns passing _is_substantive (>=5 content words)
  D         only that move's turns whose OWN best match is coachable  (the junk-bin rule)

Everything downstream is production code, imported rather than reimplemented:
signal_check.score_client_turns and signal_check.select_signal make the admit/reject
decision in every arm, so the arms cannot accidentally be measured under a different
rule than production uses. Same precedent as v2/layer_c.build_clause_pool's extraction.

The load-bearing output is NOT the table -- it is the --samples section. Every
count-based metric here improves monotonically as an arm keeps more text, which is the
un-failable-metric shape that has already misled this codebase twice. Only reading what
an arm deleted can catch an arm that binned a real short question.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from config import load_config  # noqa: E402
from ego_trap import csm_registry, scenario_pool  # noqa: E402
from ego_trap.transcript_parser import (  # noqa: E402
    EgoTrapRole, EgoTrapTurn, classify_response_outcome, parse_transcript,
)
from shared import storage  # noqa: E402
from shared.tuning import get_tuning  # noqa: E402
from v1.layer_b import _is_substantive  # noqa: E402
from ego_trap import signal_check  # noqa: E402

BRAIN = Path(__file__).resolve().parent.parent
ARMS = ("baseline", "B", "C", "D")


# ----------------------------------------------------------------- segmentation
def client_blocks(turns: list[EgoTrapTurn]) -> list[list[EgoTrapTurn]]:
    """Maximal runs of consecutive CLIENT turns. The boundary is a Joveo speaker."""
    out: list[list[EgoTrapTurn]] = []
    cur: list[EgoTrapTurn] = []
    for t in turns:
        if t.role == EgoTrapRole.CLIENT:
            cur.append(t)
        else:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def last_speaker_move(block: list[EgoTrapTurn]) -> list[EgoTrapTurn]:
    """All turns in the block spoken by whoever spoke LAST, in order.

    Grouping by speaker rather than by consecutive run is what the anchor probe
    validated: within one speaker's turns the response couples with no particular turn
    (at chance at every k), across speakers it couples with the last one (above chance
    at every k). See the spec's section 2.3.
    """
    last = block[-1].speaker_raw
    return [t for t in block if t.speaker_raw == last]


def load_stems() -> list[str]:
    log = BRAIN / "logs" / "run_ego_trap_100calls.log"
    raw = log.read_bytes()
    text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", "replace")
    stems = sorted(set(m.group(1) for m in re.finditer(r"Processing (\S+)\.txt", text)))
    if not stems:
        raise RuntimeError(f"parsed 0 stems from {log}")
    return stems


# ------------------------------------------------------------------------ scoring
class Scorer:
    """Production admit/reject, memoised per unique text."""

    def __init__(self, scenario_map: dict[str, dict], tuning) -> None:
        self.map = scenario_map
        self.tuning = tuning
        self.keys: list[str] = []
        self.is_sink: list[bool] = []
        self._sims: dict[str, np.ndarray] = {}

    def prime(self, texts: list[str]) -> None:
        todo = sorted({t for t in texts if t and t not in self._sims})
        if not todo:
            return
        keys, is_sink, sims = signal_check.score_client_turns(todo, self.map)
        if not keys:
            raise RuntimeError("score_client_turns returned no scenario keys")
        self.keys, self.is_sink = keys, is_sink
        for i, t in enumerate(todo):
            self._sims[t] = sims[i]

    def verdict(self, text: str) -> tuple[list[str] | None, float, float]:
        """(kept_scenarios_or_None, best_coachable_sim, best_sink_sim)."""
        if not text:
            return None, float("nan"), float("nan")
        row = self._sims[text]
        kept = signal_check.select_signal(
            row, self.keys, self.is_sink,
            margin=self.tuning.similarity_relative_margin,
            cap=self.tuning.max_scenarios_per_signal,
        )
        sink = np.array(self.is_sink)
        best_coach = float(row[~sink].max()) if (~sink).any() else float("nan")
        best_sink = float(row[sink].max()) if sink.any() else float("nan")
        return kept, best_coach, best_sink


# --------------------------------------------------------------------- the trial
def build_exchanges(stems: list[str], mapping: dict, cfg) -> list[dict]:
    """One record per ANSWERED block -- the population is identical across arms."""
    rows: list[dict] = []
    for stem in stems:
        p = BRAIN / "csm_recordings" / f"{stem}.txt"
        if not p.exists() or stem not in mapping:
            continue
        _, csm_name = mapping[stem]
        turns = parse_transcript(str(p), csm_name.strip().lower(), cfg.joveo_speakers_lower)
        by_index = {t.index: t for t in turns}
        for blk in client_blocks(turns):
            nxt = by_index.get(blk[-1].index + 1)
            if nxt is None or nxt.role == EgoTrapRole.CLIENT:
                continue                      # unanswered: last block of the call
            move = last_speaker_move(blk)
            rows.append({
                "stem": stem,
                "block": [t.text for t in blk],
                "speakers": [t.speaker_raw for t in blk],
                "move": [t.text for t in move],
                "block_len": len(blk),
                "outcome": classify_response_outcome(turns, blk[-1].index),
                "baseline_text": blk[-1].text,
            })
    return rows


def arm_text(row: dict, arm: str, scorer: Scorer) -> str:
    if arm == "baseline":
        return row["baseline_text"]
    move = row["move"]
    if arm == "B":
        keep = move
    elif arm == "C":
        keep = [t for t in move if _is_substantive(t)]
    elif arm == "D":
        keep = [t for t in move if (scorer.verdict(t)[0] is not None)]
    else:
        raise ValueError(arm)
    return " ".join(keep)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="transcripts to read; PATH TEST ONLY, not a sample")
    ap.add_argument("--samples", type=int, default=12,
                    help="verbatim cases to print per reading section")
    args = ap.parse_args()

    cfg = load_config()
    tuning = get_tuning().layer_d
    stems = load_stems()
    if args.limit:
        print(f"!! --limit {args.limit} is a PATH TEST, not a sample. Do not believe the numbers.")
        stems = stems[:args.limit]
    mapping = csm_registry.load_mapping(BRAIN / "csm_recordings" / "mapping.csv")

    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:                      # belt and braces: no writes possible
        cur.execute("SET SESSION default_transaction_read_only = on")
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    conn.close()
    print(f"[pool] {scenario_pool.pool_summary(scenario_map)}")
    print(f"[rule] margin={tuning.similarity_relative_margin} cap={tuning.max_scenarios_per_signal}")

    rows = build_exchanges(stems, mapping, cfg)
    print(f"[population] {len(rows)} answered exchanges from {len(stems)} transcripts")

    scorer = Scorer(scenario_map, tuning)
    # Every individual turn must be scored first: arm D needs per-turn verdicts.
    scorer.prime([t for r in rows for t in r["block"]])
    for arm in ARMS:
        scorer.prime([arm_text(r, arm, scorer) for r in rows])

    # ---- evaluate
    for r in rows:
        for arm in ARMS:
            txt = arm_text(r, arm, scorer)
            kept, coach, sink = scorer.verdict(txt)
            r[arm] = {
                "text": txt,
                "admitted": kept is not None,
                "scenario": (kept or [None])[0],
                "best": float(np.nanmax([coach, sink])) if txt else float("nan"),
                "margin": (coach - sink) if txt else float("nan"),
                "n_turns": len(txt.split()) and (
                    1 if arm == "baseline" else len([x for x in r["move"] if x in txt])),
                "substantive": bool(txt) and _is_substantive(txt),
            }

    scored = {a: [r for r in rows if r[a]["admitted"] and r["outcome"] == "csm"] for a in ARMS}
    filler = [r for r in rows
              if not _is_substantive(r["baseline_text"])
              and any(_is_substantive(t) for t in r["block"])]

    print("\n" + "=" * 92)
    print(f"{'arm':9s} {'admitted':>16s} {'empty':>7s} {'scored':>8s} "
          f"{'subst.trig':>11s} {'p50 best':>9s} {'p50 margin':>11s} {'churn':>7s}")
    print("-" * 92)
    base_scen = {id(r): r["baseline"]["scenario"] for r in rows}
    for a in ARMS:
        adm = [r for r in rows if r[a]["admitted"]]
        empty = sum(1 for r in rows if not r[a]["text"])
        sub = sum(1 for r in rows if r[a]["substantive"])
        best = np.array([r[a]["best"] for r in adm], dtype=float)
        marg = np.array([r[a]["margin"] for r in adm], dtype=float)
        churn = sum(1 for r in rows
                    if r[a]["text"] != r["baseline"]["text"]
                    and r[a]["scenario"] != base_scen[id(r)])
        print(f"{a:9s} {len(adm):6d} ({len(adm)/len(rows):5.1%}) {empty:7d} "
              f"{len(scored[a]):8d} {sub:5d} ({sub/len(rows):5.1%}) "
              f"{np.nanpercentile(best,50):9.3f} {np.nanpercentile(marg,50):+11.3f} {churn:7d}")
    print("=" * 92)

    print("\n---- the 177 filler-trigger exchanges (a real question was discarded) ----")
    print(f"population: {len(filler)}")
    for a in ARMS:
        adm = sum(1 for r in filler if r[a]["admitted"])
        sub = sum(1 for r in filler if r[a]["substantive"])
        print(f"  {a:9s} admitted {adm:4d} ({adm/max(len(filler),1):5.1%})   "
              f"substantive trigger {sub:4d} ({sub/max(len(filler),1):5.1%})")

    print("\n---- DILUTION TEST: coachable-minus-sink margin by turns merged ----")
    print("     (if stitching drags text toward the junk bins, this FALLS as turns rise)")
    for a in ARMS:
        line = f"  {a:9s}"
        for lo, hi in ((1, 1), (2, 2), (3, 4), (5, 99)):
            sel = [r for r in rows
                   if r[a]["admitted"] and lo <= r[a]["n_turns"] <= hi]
            if len(sel) < 10:
                line += f"   {lo}-{hi}: n<10   "
                continue
            m = np.nanmean([r[a]["margin"] for r in sel])
            line += f"   {lo}-{hi}: {m:+.3f} (n={len(sel)})"
        print(line)

    print("\n---- cosine band of admitted triggers (calibrated band: p10 .501 p50 .581 p90 .648) ----")
    for a in ARMS:
        b = np.array([r[a]["best"] for r in rows if r[a]["admitted"]], dtype=float)
        print(f"  {a:9s} p10={np.nanpercentile(b,10):.3f} p50={np.nanpercentile(b,50):.3f} "
              f"p90={np.nanpercentile(b,90):.3f}")

    # ---------------------------------------------------------------- READ THIS
    print("\n" + "#" * 92)
    print("# READING SECTIONS -- the aggregates above cannot fail; these can.")
    print("#" * 92)

    for a in ("C", "D"):
        dropped = []
        for r in rows:
            kept_txt = r[a]["text"]
            gone = [t for t in r["move"] if t not in kept_txt]
            if gone:
                dropped.append((r, gone))
        print(f"\n---- arm {a}: exchanges where turns were DELETED: {len(dropped)} ----")
        print(f"     (hunting for a terse-but-real question thrown away)")
        for r, gone in dropped[:args.samples]:
            print(f"\n  [{r['stem'][:40]}]  kept={r[a]['text'][:100]!r}")
            for g in gone[:4]:
                print(f"      DELETED: {g[:110]!r}")

    print(f"\n---- arm D admitted but arm baseline rejected (the recovered exchanges) ----")
    rec = [r for r in rows if r["D"]["admitted"] and not r["baseline"]["admitted"]]
    print(f"     count: {len(rec)}")
    for r in rec[:args.samples]:
        print(f"\n  [{r['stem'][:40]}] -> {r['D']['scenario']}")
        print(f"      baseline trigger: {r['baseline_text'][:110]!r}  (rejected)")
        print(f"      arm D trigger   : {r['D']['text'][:200]!r}")

    print(f"\n---- arm D REJECTED but baseline admitted (the regressions -- read closely) ----")
    reg = [r for r in rows if not r["D"]["admitted"] and r["baseline"]["admitted"]]
    print(f"     count: {len(reg)}")
    for r in reg[:args.samples]:
        print(f"\n  [{r['stem'][:40]}] baseline -> {base_scen[id(r)]}")
        print(f"      baseline trigger: {r['baseline_text'][:110]!r}  (admitted)")
        print(f"      arm D trigger   : {r['D']['text'][:200]!r}  (rejected)")

    out = ARTIFACTS_DIR / "client_move_arms.json"
    out.write_text(json.dumps([
        {k: (v if k in ("stem", "block", "speakers", "move", "outcome",
                        "baseline_text", "block_len") else v)
         for k, v in r.items()} for r in rows
    ], default=str), encoding="utf-8")
    print(f"\n[artifact] {out}")
    print(f"[blocks with >1 distinct speaker] "
          f"{sum(1 for r in rows if len(set(r['speakers'])) > 1)} / {len(rows)}")
    print("[NO production file was modified; no row was written to Postgres.]")


if __name__ == "__main__":
    main()
