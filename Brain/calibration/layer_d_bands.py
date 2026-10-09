"""C0: gemini@3072 cosine bands + sink-rejection for the redesigned Layer D.

Pre-registration: docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md (stage C0).

NOT PRODUCTION. Nothing in v1/, v2/, shared/, preprocessing/ or layer_d/ imports this.

WHAT IT MEASURES (report-only; C0 has no pass/fail gate -- the operator reads it
before C2 is allowed to spend chat calls):
  * the best-coachable and best-sink cosine bands for every CSM client turn against
    the live scenario vectors, in the SHIPPED embedding space (gateway/gemini@3072).
    Every layer_d number was previously measured in bge space, whose bands are
    inverted here -- this is the re-measurement.
  * the sink-rejection rate under the shipped rule (bge-space reference: 57.3%).
  * admitted signal counts under segmentation arms today/e, and how many land on
    scenarios that have a LIVE playbook (the gradable population C2 samples from).

*** THIS HARNESS SPENDS EMBEDDINGS (deliberately). *** Every unique CSM turn is a
novel text: ~1 gateway request each, paced by shared/gateway.py's limiter, cached
forever in gemini_embed_cache.db -- this run is what makes C1/C2 and the production
run cache-hits. It runs only with --spend; without it, it prints the bill and exits.
Zero chat calls, zero DB writes (session forced read-only), zero Pinecone either way.

Usage (from Brain/, VPN up):
    python calibration/layer_d_bands.py                  # count texts, print the bill
    python calibration/layer_d_bands.py --spend          # embed + measure + artifact
    python calibration/layer_d_bands.py --load artifacts/layer_d_bands.json  # free re-report
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR  # noqa: E402
from config import load_config  # noqa: E402
from ego_trap import csm_registry  # noqa: E402
from ego_trap.transcript_parser import EgoTrapRole, parse_transcript  # noqa: E402
from layer_d import segmentation  # noqa: E402
from shared import storage  # noqa: E402
from shared.tuning import get_tuning  # noqa: E402

BRAIN = Path(__file__).resolve().parent.parent
RECORDINGS = BRAIN / "csm_recordings"
ARTIFACT = ARTIFACTS_DIR / "layer_d_bands.json"


def pct(a: np.ndarray, q: int) -> float:
    return float(np.nanpercentile(a, q)) if len(a) else float("nan")


def band(a: np.ndarray) -> dict:
    return {"n": int(len(a)), "p10": round(pct(a, 10), 4),
            "p50": round(pct(a, 50), 4), "p90": round(pct(a, 90), 4)}


def collect_texts(stems: list[str], mapping: dict, cfg) -> tuple[dict[str, list], list[str]]:
    """Per-stem parsed turns plus every text the two arms could ever score:
    block last-turns, individual block turns (arm e's per-turn verdicts), and the
    upper bound of stitched candidates (the whole last-speaker move joined)."""
    turns_by_stem: dict[str, list] = {}
    texts: set[str] = set()
    for stem in stems:
        p = RECORDINGS / f"{stem}.txt"
        if not p.exists() or stem not in mapping:
            continue
        _, csm_name = mapping[stem]
        turns = parse_transcript(str(p), csm_name.strip().lower(), cfg.joveo_speakers_lower)
        turns_by_stem[stem] = turns
        for blk in segmentation.client_blocks(turns):
            texts.add(blk[-1].text)
            for t in blk:
                texts.add(t.text)
            texts.add(" ".join(t.text for t in segmentation.last_speaker_move(blk)))
    return turns_by_stem, sorted(texts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true",
                    help="actually embed (paced gateway requests, cached forever)")
    ap.add_argument("--load", default="", help="re-report a saved artifact, zero spend")
    ap.add_argument("--limit", type=int, default=0,
                    help="transcripts to read; PATH TEST ONLY, not a sample")
    args = ap.parse_args()

    if args.load:
        report(json.loads(Path(args.load).read_text(encoding="utf-8")))
        return

    cfg = load_config()
    tuning = get_tuning()
    if tuning.embedding.backend != "gateway":
        print(f"!! embedding.backend is {tuning.embedding.backend!r}, not 'gateway'. "
              f"These bands would not describe the shipped space. Refusing.")
        sys.exit(1)

    mapping = csm_registry.load_mapping(RECORDINGS / "mapping.csv")
    stems = sorted(p.stem for p in RECORDINGS.glob("*.txt") if p.stem in mapping)
    if args.limit:
        print(f"!! --limit {args.limit} is a PATH TEST, not a sample.")
        stems = stems[:args.limit]

    turns_by_stem, texts = collect_texts(stems, mapping, cfg)
    n_turns = sum(sum(1 for t in ts if t.role == EgoTrapRole.CLIENT)
                  for ts in turns_by_stem.values())
    print(f"[corpus] {len(turns_by_stem)} transcripts, {n_turns} client turns, "
          f"{len(texts)} unique texts to embed")

    if not args.spend:
        print(f"\nTHE BILL: ~{len(texts)} gateway embedding requests (unbatched by rule, "
              f"paced ~140/min => ~{len(texts) / 140:.0f} minutes), cached forever in "
              f"gemini_embed_cache.db. Re-run with --spend to proceed. Zero chat calls "
              f"either way.")
        return

    conn = storage.get_connection(cfg.database_url)
    with conn.cursor() as cur:                       # belt and braces: no writes possible
        cur.execute("SET SESSION default_transaction_read_only = on")
    scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
    live_keys = {p["scenario_key"] for p in storage.get_playbooks(conn, "live")}
    conn.close()

    from ego_trap import signal_check  # heavy import chain, deferred
    keys, is_sink, sims = signal_check.score_client_turns(texts, scenario_map)
    width_probe = sims.shape  # (n_texts, n_scenarios); width asserted via the map
    assert sims.shape == (len(texts), len(keys)), width_probe
    sink = np.array(is_sink)

    sims_by_text = {t: sims[i] for i, t in enumerate(texts)}
    d = get_tuning().layer_d

    def admit(text: str):
        from ego_trap.signal_check import select_signal
        row = sims_by_text.get(text)
        if row is None:
            return None
        return select_signal(row, keys, list(sink), margin=d.similarity_relative_margin,
                             cap=d.max_scenarios_per_signal)

    best_coach = np.array([row[~sink].max() for row in sims_by_text.values()])
    best_sink = np.array([row[sink].max() for row in sims_by_text.values()])

    per_arm: dict[str, dict] = {}
    for arm in ("today", "e"):
        admitted, on_live = 0, {}
        blocks = 0
        for stem, turns in turns_by_stem.items():
            sigs = segmentation.segment_moves(turns, arm, admit)
            blocks += len(segmentation.client_blocks(turns))
            admitted += len(sigs)
            for s in sigs:
                if s.scenario_keys[0] in live_keys:
                    on_live[s.scenario_keys[0]] = on_live.get(s.scenario_keys[0], 0) + 1
        per_arm[arm] = {"blocks": blocks, "admitted": admitted,
                        "on_live_playbook": on_live,
                        "gradable_moments": sum(on_live.values())}

    art = {
        "identity": {"backend": "gateway", "space": "gemini@3072",
                     "margin": d.similarity_relative_margin,
                     "cap": d.max_scenarios_per_signal,
                     "transcripts": len(turns_by_stem), "unique_texts": len(texts)},
        "bands": {"best_coachable": band(best_coach), "best_sink": band(best_sink),
                  "margin_coach_minus_sink": band(best_coach - best_sink)},
        "sink_rejection_rate": round(float(np.mean(best_sink > best_coach)), 4),
        "arms": per_arm,
    }
    ARTIFACT.write_text(json.dumps(art, indent=2), encoding="utf-8")
    print(f"[artifact] {ARTIFACT}")
    report(art)


def report(art: dict) -> None:
    ident = art["identity"]
    print(f"\n=== C0: Layer D bands in {ident['space']} "
          f"(margin={ident['margin']}, cap={ident['cap']}) ===")
    for name, b in art["bands"].items():
        print(f"  {name:26s} n={b['n']:6d}  p10={b['p10']:+.4f}  "
              f"p50={b['p50']:+.4f}  p90={b['p90']:+.4f}")
    print(f"  sink rejection rate: {art['sink_rejection_rate']:.1%} "
          f"(bge-space reference: 57.3%)")
    for arm, a in art["arms"].items():
        print(f"  arm {arm:6s}: {a['admitted']} admitted of {a['blocks']} blocks; "
              f"{a['gradable_moments']} land on a LIVE playbook "
              f"({len(a['on_live_playbook'])} scenarios)")
    print("\nREAD, do not gate: the operator decides whether these bands and the "
          "gradable-moment count justify C2's chat spend.")
    print("[NO production file modified; no DB row written.]")


if __name__ == "__main__":
    main()
