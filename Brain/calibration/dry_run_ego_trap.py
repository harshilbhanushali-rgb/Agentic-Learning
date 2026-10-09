#!/usr/bin/env python3
"""Zero-cost measurement of the Layer D (Ego Trap) realignment, against live data.

Run from Brain/:  python calibration/dry_run_ego_trap.py

The default invocation makes ZERO Gemma calls, ZERO DB writes and ZERO Pinecone
queries -- Postgres reads plus embed-cache reads only. That is what lets the
similarity-mode margin be calibrated from the real corpus instead of guessed.

Every rule it measures is IMPORTED from production code, never reimplemented:
ego_trap.signal_check's score_client_turns / select_signal / format_scenarios_block /
resolve_signals / find_turn_index, ego_trap.scenario_pool, ego_trap.rubric_lookup's
rank_benchmark_responses, and shared.storage's readers. A harness that copies the rule
measures the copy -- see the merge-blind _match_milestones episode, where a harness
bug produced a recommendation that had to be withdrawn.

Sections:
  [A] scenario pool split, and today's already-stored signals retro-classified
  [B] similarity mode: cosine distribution, sink-rejection rate, margin sweep
  [C] gemma mode: shortlist recall + turn-match A/B  (needs --step0-gemma or --load)
  [D] benchmark selection: multilabel gain + cosine ranking vs pair_id order

Two things are honestly NOT free and are opt-in flags:
  --step0-gemma      one Gemma call per transcript, once. Persisted, so --load makes
                     section [C] free forever afterwards.
  --pinecone-compare read-only Pinecone queries, to record how far the exemplar route
                     disagrees with the scenario-vector route.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

# Brain/ is this file's parent -- put it on sys.path so the shared packages
# (config, shared, v1, v2, preprocessing, ego_trap) resolve whether this script is run
# directly (python calibration/x.py) or imported (from calibration import x).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from calibration import ARTIFACTS_DIR, BRAIN_DIR
from config import load_config
from ego_trap import csm_registry, rubric_lookup, scenario_pool, signal_check
from ego_trap.transcript_parser import EgoTrapRole, parse_transcript
from shared import storage
from shared.tuning import load_tuning

_DEFAULT_OUTPUT = ARTIFACTS_DIR / "ego_trap_dry_run.json"
_DEFAULT_MARGINS = "0.85,0.90,0.93,0.95,0.97,0.99"
_DEFAULT_SHORTLISTS = "5,10,20,30,40"
# The absolute floor this realignment removes. Kept only so the sweep can report the
# before/after on an identical turn set.
_OLD_ABSOLUTE_FLOOR = 0.35
_PCTS = (10, 25, 50, 75, 90)


def _pct_line(values: list[float]) -> str:
    if not values:
        return "no data"
    qs = np.percentile(values, _PCTS)
    return "  ".join(f"p{p}={q:.3f}" for p, q in zip(_PCTS, qs))


def _header(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# --------------------------------------------------------------------------- [A]

def report_pool(scenario_map: dict[str, dict]) -> dict:
    _header("[A] Scenario pool")
    coachable = scenario_pool.coachable_only(scenario_map)
    sinks = scenario_pool.sink_keys(scenario_map)
    print(scenario_pool.pool_summary(scenario_map))

    crosstab = Counter(
        (v.get("cluster_kind") or "?", v.get("rubric_status") or "MISSING")
        for v in scenario_map.values()
    )
    print("\n  cluster_kind x rubric_status:")
    for (kind, status), n in sorted(crosstab.items()):
        print(f"    {kind:<12} {status:<32} {n:>4}")

    # Prompt-size delta is the direct cost of the sink leak: these are the tokens
    # currently spent inviting Gemma to detect backchannel.
    all_block = signal_check.format_scenarios_block(scenario_map)
    coachable_block = signal_check.format_scenarios_block(coachable)
    print(
        f"\n  Step 0 gemma prompt menu: {len(all_block):,} chars for all "
        f"{len(scenario_map)} scenarios -> {len(coachable_block):,} chars for "
        f"{len(coachable)} coachable "
        f"({100 * (1 - len(coachable_block) / max(len(all_block), 1)):.0f}% smaller)"
    )

    no_rubric = sorted(
        k for k, v in coachable.items() if v.get("rubric_status") != "rubric_generated"
    )
    print(
        f"\n  Coachable scenarios with NO rubric ({len(no_rubric)}). These are the "
        f"Rubric_Coverage_Gap surface --\n  a signal on one of these used to vanish "
        f"with no DB row at all:"
    )
    for key in no_rubric:
        print(f"    - {key}  [{coachable[key].get('rubric_status') or 'MISSING'}]")

    return {
        "total": len(scenario_map),
        "coachable": len(coachable),
        "sinks": len(sinks),
        "crosstab": {f"{k}|{s}": n for (k, s), n in crosstab.items()},
        "prompt_chars_all": len(all_block),
        "prompt_chars_coachable": len(coachable_block),
        "coachable_without_rubric": no_rubric,
    }


def report_stored_signals(conn, scenario_map: dict[str, dict]) -> dict:
    _header("[A] Today's already-stored signals, retro-classified")
    print(
        "  UNDERCOUNTS BY CONSTRUCTION: a sink-matched signal that reached the old\n"
        "  UNMAPPED_SCENARIO path was never persisted anywhere, so it cannot appear\n"
        "  here. Treat these as a floor on the sink leak, not a measurement of it.\n"
    )
    rows = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.scenario_key, COUNT(*)
            FROM gap_events g GROUP BY 1 ORDER BY 2 DESC
        """)
        rows = cur.fetchall()
    if not rows:
        print("  gap_events is empty — no prior Layer D run to classify.")
        return {"gap_events": []}

    buckets: Counter = Counter()
    detail = []
    for key, n in rows:
        info = scenario_map.get(key)
        if info is None:
            bucket = "not_in_taxonomy"
        elif not scenario_pool.is_coachable(info):
            bucket = f"SINK/{info.get('cluster_kind') or '?'}"
        elif info.get("rubric_status") != "rubric_generated":
            bucket = "coachable_no_rubric"
        else:
            bucket = "coachable_with_rubric"
        buckets[bucket] += n
        detail.append({"scenario_key": key, "events": n, "bucket": bucket})

    total = sum(buckets.values())
    for bucket, n in buckets.most_common():
        print(f"    {bucket:<26} {n:>5} event(s)  ({100 * n / total:.0f}%)")
    return {"gap_events": detail}


# --------------------------------------------------------------------------- [B]

def load_transcripts(recordings_dir: Path, mapping_path: Path) -> list[dict]:
    mapping = csm_registry.load_mapping(str(mapping_path))
    config = load_config()
    out = []
    for txt_path in sorted(recordings_dir.glob("*.txt")):
        stem = txt_path.stem
        if stem not in mapping:
            continue
        _, csm_name = mapping[stem]
        turns = parse_transcript(
            str(txt_path), csm_name.strip().lower(), config.joveo_speakers_lower
        )
        out.append({
            "stem": stem,
            "csm_name": csm_name,
            "turns": turns,
            "client_turns": [t for t in turns if t.role == EgoTrapRole.CLIENT],
        })
    return out


def report_similarity(
    transcripts: list[dict], scenario_map: dict[str, dict], margins: list[float],
    cap: int, show: int,
) -> dict:
    _header("[B] similarity mode against the real CSM corpus")
    client_texts = [t.text for tr in transcripts for t in tr["client_turns"]]
    if not client_texts:
        print("  No client turns found.")
        return {}

    keys, is_sink, sims = signal_check.score_client_turns(client_texts, scenario_map)
    best = sims.max(axis=1)
    best_j = sims.argmax(axis=1)
    sink_best = [bool(is_sink[int(j)]) for j in best_j]

    print(f"  {len(client_texts)} client turn(s) across {len(transcripts)} transcript(s).")
    print(f"\n  Best-match cosine, all client turns:  {_pct_line(list(best))}")
    print(
        "  layer_b's calibrated trigger-vs-scenario band, for comparison:  "
        "p10=0.496  p50=0.550  p90=0.613"
    )
    print(
        f"\n  The retired absolute floor ({_OLD_ABSOLUTE_FLOOR}) sits at percentile "
        f"{100 * float((best < _OLD_ABSOLUTE_FLOOR).mean()):.1f} of this distribution\n"
        f"  -- i.e. it admits {100 * float((best >= _OLD_ABSOLUTE_FLOOR).mean()):.1f}% "
        f"of ALL client turns, backchannel included. That is why it is gone."
    )

    n_sink = sum(sink_best)
    print(
        f"\n  Best match is a SINK for {n_sink}/{len(client_texts)} turns "
        f"({100 * n_sink / len(client_texts):.1f}%). Under the new rule those are\n"
        f"  rejected as 'not a signal' -- this is the rejection mechanism the sinks "
        f"exist to provide."
    )
    kinds = Counter(
        scenario_map[keys[int(j)]].get("cluster_kind") or "?"
        for j, s in zip(best_j, sink_best) if s
    )
    for kind, n in kinds.most_common():
        print(f"      {kind:<12} {n:>5}")

    print(f"\n  Margin sweep (cap={cap}):")
    print(f"    {'margin':>7}  {'signals':>8}  {'%turns':>7}  {'mean kept':>10}  {'at cap':>7}")
    sweep = []
    for margin in margins:
        kept_lists = [
            signal_check.select_signal(sims[i], keys, is_sink, margin=margin, cap=cap)
            for i in range(len(client_texts))
        ]
        hits = [k for k in kept_lists if k]
        mean_kept = float(np.mean([len(k) for k in hits])) if hits else 0.0
        at_cap = sum(1 for k in hits if len(k) >= cap)
        print(
            f"    {margin:>7.2f}  {len(hits):>8}  {100 * len(hits) / len(client_texts):>6.1f}%"
            f"  {mean_kept:>10.2f}  {at_cap:>7}"
        )
        sweep.append({
            "margin": margin, "signals": len(hits), "mean_kept": mean_kept, "at_cap": at_cap,
        })
    old_count = int((best >= _OLD_ABSOLUTE_FLOOR).sum())
    print(
        f"\n    For reference, the OLD absolute floor {_OLD_ABSOLUTE_FLOOR} on this "
        f"same turn set: {old_count} signals ({100 * old_count / len(client_texts):.1f}%)."
    )

    # Verbatim samples. Read these -- the counts above cannot tell you whether a kept
    # signal is real, and "more signals" is the known failure mode of this knob.
    order = np.argsort(best)[::-1]
    print(
        f"\n  --- {show} highest-scoring KEPT turns (best match is coachable) ---\n"
        f"  Read for false positives: chatter here means the margin is too loose."
    )
    shown = 0
    for i in order:
        i = int(i)
        if sink_best[i] or shown >= show:
            continue
        print(f"    [{best[i]:.3f}] {keys[int(best_j[i])]}")
        print(f"            {client_texts[i][:150]!r}")
        shown += 1

    print(
        f"\n  --- {show} highest-scoring REJECTED turns (best match is a sink) ---\n"
        f"  Read for false negatives: real business content here means the sink "
        f"taxonomy is over-broad."
    )
    shown = 0
    for i in order:
        i = int(i)
        if not sink_best[i] or shown >= show:
            continue
        print(f"    [{best[i]:.3f}] {keys[int(best_j[i])]}")
        print(f"            {client_texts[i][:150]!r}")
        shown += 1

    return {
        "n_client_turns": len(client_texts),
        "best_cosine_percentiles": dict(
            zip((f"p{p}" for p in _PCTS), [float(x) for x in np.percentile(best, _PCTS)])
        ),
        "sink_best_fraction": n_sink / len(client_texts),
        "old_absolute_floor_signals": old_count,
        "margin_sweep": sweep,
        "turns": [
            {"text": client_texts[i], "best": float(best[i]),
             "best_key": keys[int(best_j[i])], "best_is_sink": sink_best[i]}
            for i in range(len(client_texts))
        ],
    }


# --------------------------------------------------------------------------- [C]

def collect_step0_gemma(
    transcripts: list[dict], coachable_map: dict[str, dict], recordings_dir: Path
) -> dict:
    """One Gemma call per transcript. The only non-free part of this harness.

    Persisted into the artifact so every later --load run replays the SAME raw
    response through the real resolver for free.
    """
    from shared.gemma import call_gemma
    from shared.prompts import PROMPT_STEP0_SIGNAL_CHECK

    config = load_config()
    raw_by_stem = {}
    for tr in transcripts:
        text = (recordings_dir / f"{tr['stem']}.txt").read_text(
            encoding="utf-8-sig"
        ).replace("\r\n", "\n")
        prompt = PROMPT_STEP0_SIGNAL_CHECK.format(
            transcript_text=text,
            scenarios_text=signal_check.format_scenarios_block(coachable_map),
        )
        print(f"  [Gemma] Step 0 for {tr['stem']}...")
        result = call_gemma(prompt, config.gemma_api_keys)
        raw_by_stem[tr["stem"]] = (
            result if isinstance(result, list) else result.get("signals_detected", [])
        )
    return raw_by_stem


def report_gemma_mode(
    transcripts: list[dict], coachable_map: dict[str, dict],
    raw_by_stem: dict, shortlists: list[int], min_ratio: float, show: int,
) -> dict:
    _header("[C] gemma mode: shortlist recall + turn matching")
    if not raw_by_stem:
        print(
            "  No stored Gemma Step 0 output. Run once with --step0-gemma (1 call per\n"
            "  transcript) to populate it; every later --load run replays it for free."
        )
        return {}

    by_stem = {tr["stem"]: tr for tr in transcripts}

    # Shortlist recall. A shortlist can only ever LOSE scenarios Gemma would have
    # named, so recall is the whole question -- and it is answerable with zero new
    # Gemma calls, because we already know what it named with the full menu.
    print("  Shortlist recall (fraction of keys Gemma actually returned that survive top-K):")
    print(f"    {'K':>5}  {'recall':>7}  {'kept/total':>12}")
    recall_rows = []
    for k in shortlists:
        kept = total = 0
        for stem, raw in raw_by_stem.items():
            tr = by_stem.get(stem)
            if tr is None:
                continue
            listed = signal_check.shortlist_scenarios(
                coachable_map, [t.text for t in tr["client_turns"]], k
            )
            for s in raw:
                key = s.get("scenario_key")
                if key in coachable_map:
                    total += 1
                    kept += key in listed
        recall = kept / total if total else 0.0
        print(f"    {k:>5}  {recall:>6.1%}  {kept:>5}/{total:<6}")
        recall_rows.append({"k": k, "recall": recall, "kept": kept, "total": total})
    print(
        "\n    Recall below 100% means real detected signals would be lost. "
        "layer_d.gemma_scenario_shortlist_k\n    ships at 0 (no shortlist) precisely "
        "because this table, not a guess, has to justify raising it."
    )

    # Turn-match A/B through the real resolver.
    print("\n  Turn-match mode A/B (through the production resolve_signals):")
    print(f"    {'mode':>12}  {'resolved':>9}  {'dropped':>8}  drop reasons")
    mode_rows = []
    baseline_resolved: set[tuple[str, str]] = set()
    for mode in ("exact", "normalized", "ratio"):
        resolved_n = dropped = 0
        reasons: Counter = Counter()
        resolved_set: set[tuple[str, str]] = set()
        for stem, raw in raw_by_stem.items():
            tr = by_stem.get(stem)
            if tr is None:
                continue
            res, unres = signal_check.resolve_signals(
                tr["turns"], raw, mode=mode, min_ratio=min_ratio
            )
            resolved_n += len(res)
            dropped += len(unres)
            reasons.update(u["reason"] for u in unres)
            resolved_set.update((stem, s["client_utterance"]) for s in res)
        reason_text = ", ".join(f"{r}={n}" for r, n in reasons.most_common()) or "-"
        print(f"    {mode:>12}  {resolved_n:>9}  {dropped:>8}  {reason_text}")
        mode_rows.append({
            "mode": mode, "resolved": resolved_n, "dropped": dropped,
            "reasons": dict(reasons),
        })
        if mode == "exact":
            baseline_resolved = resolved_set
        else:
            gained = resolved_set - baseline_resolved
            for stem, utterance in list(gained)[:show]:
                tr = by_stem[stem]
                idx, _ = signal_check.find_turn_index(
                    tr["turns"], utterance, mode=mode, min_ratio=min_ratio
                )
                matched = next((t for t in tr["turns"] if t.index == idx), None)
                print(f"      + {mode} newly matched, turn {idx}:")
                print(f"          gemma quoted: {utterance[:130]!r}")
                print(f"          turn text:    {(matched.text if matched else '')[:130]!r}")

    print(
        "\n    Read every '+' pair above. A mode that resolves MORE signals is only "
        "better if the\n    pairs it newly matched are genuinely the same utterance."
    )
    return {"shortlist_recall": recall_rows, "turn_match_modes": mode_rows}


# --------------------------------------------------------------------------- [D]

def report_benchmarks(conn, coachable_map: dict[str, dict], show: int) -> dict:
    _header("[D] Benchmark reference selection")
    limit = rubric_lookup._MAX_BENCHMARK_EXAMPLES
    gained = changed = array_only_chosen = 0
    counts_before, counts_after = [], []
    chosen_sims, discarded_sims = [], []
    samples = []

    for key, info in sorted(coachable_map.items()):
        old = storage.get_naren_responses_for_scenario(conn, key)
        new = storage.get_responses_for_scenario_multilabel(conn, key)
        if not new:
            continue
        counts_before.append(len(old))
        counts_after.append(len(new))
        if len(new) > len(old):
            gained += 1

        old_pick = [r["pair_id"] for r in old[:limit]]
        ranked = rubric_lookup.rank_benchmark_responses(new, info, limit)
        new_pick = [r["pair_id"] for r in ranked]
        if old_pick != new_pick:
            changed += 1
        array_only_chosen += sum(1 for r in ranked if not r.get("is_primary", True))
        chosen_ids = set(new_pick)
        # Score the WHOLE pool in one ranked pass and split it by what was chosen,
        # rather than re-ranking the leftovers on their own. Asking
        # rank_benchmark_responses for exactly as many rows as it was given hits its
        # own <= limit short-circuit, which returns the rows unranked and WITHOUT a
        # scenario_similarity key -- so the discarded band silently read "no data" and
        # the chosen-vs-discarded comparison, the only check that the ranking separates
        # anything at all, quietly measured nothing.
        if len(new) > 1:
            scored = rubric_lookup.rank_benchmark_responses(new, info, len(new) - 1)
            for r in scored:
                sim = r.get("scenario_similarity")
                if sim is None:
                    continue
                (chosen_sims if r["pair_id"] in chosen_ids else discarded_sims).append(sim)

        if old_pick != new_pick and len(samples) < show:
            samples.append({
                "scenario_key": key,
                "old": [
                    {"pair_id": r["pair_id"], "text": r["response_text"][:180]}
                    for r in old[:limit]
                ],
                "new": [
                    {"pair_id": r["pair_id"], "text": r["response_text"][:180],
                     "similarity": r.get("scenario_similarity"),
                     "is_primary": r.get("is_primary")}
                    for r in ranked
                ],
            })

    n = len(counts_after)
    if not n:
        print("  No responses found for any coachable scenario — is kb_pairs populated?")
        return {}
    print(f"  {n} coachable scenario(s) with at least one response.")
    print(
        f"  Candidate pool: {sum(counts_before)} response(s) via the scalar "
        f"scenario_key -> {sum(counts_after)} via scenario_keys[] "
        f"(+{sum(counts_after) - sum(counts_before)}); "
        f"{gained} scenario(s) gained candidates."
    )
    print(
        f"  Chosen top-{limit} changes for {changed}/{n} scenario(s); "
        f"{array_only_chosen} chosen response(s) are secondary-label only\n"
        f"  (invisible to the old query entirely)."
    )
    print(f"\n  Response-vs-scenario cosine, CHOSEN:    {_pct_line(chosen_sims)}")
    print(f"  Response-vs-scenario cosine, DISCARDED: {_pct_line(discarded_sims)}")
    print(
        "  A clear gap means the ranking is separating on-topic from off-topic. "
        "Overlap means it is not,\n  and the old pair_id order was no worse."
    )

    for s in samples:
        print(f"\n  --- {s['scenario_key']} ---")
        for r in s["old"]:
            print(f"    OLD (pair {r['pair_id']}): {r['text']!r}")
        for r in s["new"]:
            sim = f"{r['similarity']:.3f}" if r["similarity"] is not None else "  n/a"
            flag = "primary" if r["is_primary"] else "SECONDARY"
            print(f"    NEW [{sim}, {flag}] (pair {r['pair_id']}): {r['text']!r}")

    return {
        "scenarios": n,
        "candidates_before": sum(counts_before),
        "candidates_after": sum(counts_after),
        "scenarios_gained": gained,
        "scenarios_changed": changed,
        "array_only_chosen": array_only_chosen,
        "chosen_sim_percentiles": dict(
            zip((f"p{p}" for p in _PCTS),
                [float(x) for x in np.percentile(chosen_sims, _PCTS)] if chosen_sims else [])
        ),
        "samples": samples,
    }


# --------------------------------------------------------------------------- main

def report_pinecone(transcripts: list[dict], scenario_map: dict[str, dict], show: int) -> dict:
    _header("[B'] Pinecone exemplar route vs scenario-vector route (opt-in)")
    from preprocessing import embedder
    from shared import pinecone_store

    config = load_config()
    client_texts = [t.text for tr in transcripts for t in tr["client_turns"]]
    keys, is_sink, sims = signal_check.score_client_turns(client_texts, scenario_map)
    if not keys:
        return {}
    vecs = embedder.embed_query_matrix(client_texts)

    agree = exemplar_sink = 0
    exemplar_scores = []
    for i, vec in enumerate(vecs):
        matches = pinecone_store.query_triggers(
            config.pinecone_api_key, config.pinecone_index_name, list(vec), top_k=1
        )
        if not matches:
            continue
        top = matches[0]
        score = top.get("score", 0.0) if isinstance(top, dict) else getattr(top, "score", 0.0)
        meta = top.get("metadata", {}) if isinstance(top, dict) else getattr(top, "metadata", {})
        ex_key = (meta or {}).get("scenario_key")
        exemplar_scores.append(float(score))
        if ex_key in scenario_map and not scenario_pool.is_coachable(scenario_map[ex_key]):
            exemplar_sink += 1
        if ex_key == keys[int(sims[i].argmax())]:
            agree += 1

    n = len(exemplar_scores)
    if not n:
        print("  No Pinecone matches returned.")
        return {}
    print(f"  Top-1 agreement between the two routes: {agree}/{n} ({100 * agree / n:.1f}%)")
    print(f"  Exemplar (utterance-vs-utterance) score band: {_pct_line(exemplar_scores)}")
    print(
        f"  Exemplar's key is a SINK for {exemplar_sink}/{n} turns "
        f"({100 * exemplar_sink / n:.1f}%).\n"
        f"  Pinecone metadata carries no is_coachable, so the sink-rejection rule is "
        f"not expressible\n  against this route without a per-match DB round trip -- "
        f"which is why production uses scenario vectors."
    )
    return {
        "agreement": agree / n,
        "exemplar_score_percentiles": dict(
            zip((f"p{p}" for p in _PCTS), [float(x) for x in np.percentile(exemplar_scores, _PCTS)])
        ),
        "exemplar_sink_fraction": exemplar_sink / n,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--recordings", default=str(BRAIN_DIR / "csm_recordings"))
    ap.add_argument("--mapping", default=None, help="defaults to <recordings>/mapping.csv")
    ap.add_argument("--margin-sweep", default=_DEFAULT_MARGINS)
    ap.add_argument("--shortlist-sweep", default=_DEFAULT_SHORTLISTS)
    ap.add_argument("--show", type=int, default=10, help="verbatim samples per bucket")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--load", default=None, help="re-report from an artifact, zero DB/Gemma")
    ap.add_argument("--step0-gemma", action="store_true",
                    help="OPT-IN: 1 Gemma call per transcript, persisted for --load")
    ap.add_argument("--pinecone-compare", action="store_true",
                    help="OPT-IN: read-only Pinecone queries")
    args = ap.parse_args()

    margins = [float(x) for x in args.margin_sweep.split(",") if x.strip()]
    shortlists = [int(x) for x in args.shortlist_sweep.split(",") if x.strip()]
    tuning = load_tuning().layer_d

    recordings_dir = Path(args.recordings)
    mapping_path = Path(args.mapping) if args.mapping else recordings_dir / "mapping.csv"

    stored_raw: dict = {}
    if args.load:
        prior = json.loads(Path(args.load).read_text(encoding="utf-8-sig"))
        stored_raw = prior.get("step0_gemma_raw") or {}
        print(f"Loaded prior artifact: {args.load}")

    config = load_config()
    conn = storage.get_connection(config.database_url)
    artifact: dict = {}
    try:
        scenario_map = {r["scenario_key"]: r for r in storage.get_scenarios(conn)}
        coachable_map = scenario_pool.coachable_only(scenario_map)
        if not scenario_map:
            print("ERROR: `scenarios` is empty — run the main pipeline first.")
            sys.exit(1)

        artifact["pool"] = report_pool(scenario_map)
        artifact["stored_signals"] = report_stored_signals(conn, scenario_map)

        if not recordings_dir.exists():
            print(f"\n! {recordings_dir} not found — skipping sections [B] and [C].")
            transcripts = []
        elif not mapping_path.exists():
            print(f"\n! {mapping_path} not found — skipping sections [B] and [C].")
            transcripts = []
        else:
            transcripts = load_transcripts(recordings_dir, mapping_path)

        if transcripts:
            artifact["similarity"] = report_similarity(
                transcripts, scenario_map, margins,
                tuning.max_scenarios_per_signal, args.show,
            )
            if args.step0_gemma:
                stored_raw = collect_step0_gemma(transcripts, coachable_map, recordings_dir)
            artifact["step0_gemma_raw"] = stored_raw
            artifact["gemma_mode"] = report_gemma_mode(
                transcripts, coachable_map, stored_raw, shortlists,
                tuning.turn_match_min_ratio, args.show,
            )
            if args.pinecone_compare:
                artifact["pinecone"] = report_pinecone(transcripts, scenario_map, args.show)

        conn = storage.reconnect_if_closed(conn)
        artifact["benchmarks"] = report_benchmarks(conn, coachable_map, args.show)
    finally:
        conn.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
    _header("Done")
    print(f"  Artifact: {out}")
    print(f"  Re-report with zero DB/Gemma cost:  --load {out}")
    print(
        "\n  Before setting layer_d.similarity_relative_margin, READ the verbatim "
        "samples in [B].\n  A higher signal count is the known failure mode of this "
        "knob, not evidence of success."
    )


if __name__ == "__main__":
    main()
