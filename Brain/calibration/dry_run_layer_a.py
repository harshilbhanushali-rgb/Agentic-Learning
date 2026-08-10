"""Preview the evidence-triaged scenario taxonomy without spending a single Gemma call.

Runs the real Layer A clustering over the real corpus, then applies the
similarity merge and evidence triage the production pipeline will use, and
prints what the taxonomy WOULD look like. Nothing is written to Postgres and no
LLM is called.

Clustering is the expensive step, so --sweep does it ONCE and then evaluates
many threshold combinations against that single result. Embeddings are cached
on disk, so the second run onward skips encoding entirely.

Usage (from Brain/, venv active):
    python dry_run_layer_a.py --sweep      # compare threshold combinations
    python dry_run_layer_a.py              # full report for tuning.yaml values
    python dry_run_layer_a.py --limit 50   # quick pass over 50 transcripts
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np

from config import load_config
from preprocessing import embedder
from preprocessing.transcript_parser import parse_transcript, load_roster
from shared import cluster_evidence, topic_grouping
from shared.tuning import load_tuning
from v2.layer_a import build_client_clause_pool, fit_topic_model

_BAR = "=" * 78
_PAD = " " * 31

_SWEEP_MERGE = [0.70, 0.75, 0.80, 0.85, 0.88]
_SWEEP_FRACTION = [0.02, 0.05]
_SWEEP_UBIQUITY = [0.10, 0.15, 0.25, 0.40]

_GROUPING_COMPARE_THRESHOLDS = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recordings", default="recordings", help="transcript directory")
    p.add_argument("--limit", type=int, default=0, help="only read the first N transcripts")
    p.add_argument("--sweep", action="store_true", help="compare threshold combinations")
    p.add_argument("--merge-detail", default="",
                   help="comma-separated merge thresholds; print what each one collapses")
    p.add_argument("--grouping-compare", action="store_true",
                   help="compare post_hoc vs nested primary-topic grouping across loose thresholds")
    p.add_argument("--grouping-thresholds", default="",
                   help="comma-separated loose thresholds for --grouping-compare "
                        f"(default: {_GROUPING_COMPARE_THRESHOLDS})")
    p.add_argument("--exclude-sinks", action="store_true",
                   help="with --grouping-compare: apply a zero-Gemma coachability proxy "
                        "(cluster_evidence.triage on the subtopic level) and exclude sink/thin "
                        "subtopics before grouping, to see whether they were dragging real "
                        "topics into incoherent groups")
    p.add_argument("--review-as", choices=["sink", "scenario"], default="sink",
                   help="with --exclude-sinks: treat needs_review subtopics as sink (default, "
                        "matches dry_run_layer_bc.py's default) or scenario -- Gemma decides "
                        "these for real, this can only approximate")
    p.add_argument("--merge-threshold", type=float, default=None)
    p.add_argument("--support-fraction", type=float, default=None)
    p.add_argument("--ubiquity-ceiling", type=float, default=None)
    p.add_argument("--prefilter", action="store_true",
                   help="apply the cheap min_content_words clause pre-filter")
    p.add_argument("--show", default="30", help="rows per section to print, or all")
    return p.parse_args()


def _load_turns(recordings: str, limit: int, config):
    files = sorted(Path(recordings).glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"No .txt transcripts found in {recordings}")
    if limit:
        files = files[:limit]
    turns = []
    for path in files:
        turns.extend(parse_transcript(
            str(path), config.joveo_speakers_lower, config.naren_name_lower,
            roster=load_roster(str(path)),
        ))
    return turns, len(files)


def _sample(texts: list[str], n: int = 2) -> str:
    picked = [t.strip().replace("\n", " ") for t in texts[:n]]
    return " | ".join(t[:70] for t in picked)


def _verdict_counts(groups, raw_calls, total_calls, min_support, ubiquity):
    """Triage merged groups from call sets alone -- no vector work, so sweeps are fast."""
    counts = {
        cluster_evidence.SCENARIO_CANDIDATE: 0,
        cluster_evidence.NEEDS_REVIEW: 0,
        cluster_evidence.INSUFFICIENT_EVIDENCE: 0,
    }
    for group in groups:
        calls = set()
        for g in group:
            calls |= raw_calls[g]
        distinct = len(calls)
        if distinct < min_support:
            counts[cluster_evidence.INSUFFICIENT_EVIDENCE] += 1
        elif distinct / total_calls > ubiquity:
            counts[cluster_evidence.NEEDS_REVIEW] += 1
        else:
            counts[cluster_evidence.SCENARIO_CANDIDATE] += 1
    return counts


def _run_sweep(centroids, raw_calls, total_calls):
    print(f"\n{_BAR}\nTHRESHOLD SWEEP (one clustering pass, {len(raw_calls)} raw clusters)\n{_BAR}")
    print(" merge  supp%  ubiq%   merged  clean_pass  needs_review  dropped")
    for merge in _SWEEP_MERGE:
        groups = cluster_evidence.merge_by_similarity(centroids, merge)
        for fraction in _SWEEP_FRACTION:
            min_support = cluster_evidence.required_call_support(total_calls, fraction, 4)
            for ubiquity in _SWEEP_UBIQUITY:
                c = _verdict_counts(groups, raw_calls, total_calls, min_support, ubiquity)
                coach = c[cluster_evidence.SCENARIO_CANDIDATE]
                review = c[cluster_evidence.NEEDS_REVIEW]
                drop = c[cluster_evidence.INSUFFICIENT_EVIDENCE]
                print(f"{merge:>6.2f} {fraction:>6.0%} {ubiquity:>6.0%} "
                      f"{len(groups):>8} {coach:>11} {review:>13} {drop:>8}")
    print(f"\n  supp% is a fraction of {total_calls} calls (floor 4).")
    print("  ubiq% only routes a cluster to LLM review -- it discards nothing.")


def _merge_detail(thresholds, centroids, members, raw_ids, raw_calls, clauses,
                  topic_model, total_calls, show):
    """Print what each candidate merge threshold actually collapses, in one pass.

    The sweep table shows only counts, which cannot distinguish a threshold that
    unifies the backchannel families from one that shreds real distinctions. This
    prints the member keyword sets per group so the merge can be judged directly.
    """
    for merge in thresholds:
        groups = cluster_evidence.merge_by_similarity(centroids, merge)
        multi = [g for g in groups if len(g) > 1]
        collapsed = sum(len(g) for g in multi)
        print(f"\n{_BAR}\nMERGE >= {merge:.2f}: {len(raw_ids)} raw -> {len(groups)} groups "
              f"({len(multi)} multi-member, absorbing {collapsed} raw clusters)\n{_BAR}")
        multi.sort(key=lambda g: sum(len(members[raw_ids[i]]) for i in g), reverse=True)
        for group in multi[:show]:
            calls = set()
            for i in group:
                calls |= raw_calls[i]
            n_items = sum(len(members[raw_ids[i]]) for i in group)
            print(f"  [{len(group)} raw -> 1]  {n_items} clauses, "
                  f"{len(calls)} calls ({len(calls) / total_calls:.0%} coverage)")
            for i in group:
                tid = raw_ids[i]
                kws = ", ".join(w for w, _ in topic_model.get_topic(tid)[:5])
                sample = _sample([clauses[j] for j in members[tid]], 1)
                print(f"      - {kws}")
                print(f"          {sample}")
        if len(multi) > show:
            print(f"  ... {len(multi) - show} more multi-member groups (use --show all)")


def _group_detail(groups, title, show):
    """Print group count/size distribution/member keyword lists for one method+threshold.

    Mirrors _merge_detail's judge-by-reading-keywords approach: a group count
    alone cannot distinguish a threshold that unifies related subtopics under a
    coherent umbrella from one that dumps unrelated business topics together.
    """
    sizes = sorted((len(g) for g in groups), reverse=True)
    print(f"\n{title}: {len(groups)} group(s), sizes {sizes[:show]}"
          + (" ..." if len(sizes) > show else ""))
    multi = [g for g in groups if len(g) > 1]
    for g in multi[:show]:
        print(f"  [{len(g)} member(s)]")
        for kw in g[:5]:
            print(f"      - {kw}")
        if len(g) > 5:
            print(f"      ... {len(g) - 5} more")


def _subtopic_verdicts(subtopic_groups, raw_calls, total_calls, ta):
    """Zero-Gemma coachability proxy per subtopic group: the same evidence-only
    rule (cluster_evidence.triage) production applies before ever calling Gemma.
    Approximates, does not replace, the real per-cluster Gemma adjudication --
    same caveat dry_run_layer_bc.py's pseudo-taxonomy already documents.
    """
    min_support = cluster_evidence.required_call_support(
        total_calls, ta.min_call_support_fraction, ta.min_call_support_floor
    )
    verdicts = []
    for group in subtopic_groups:
        calls = set()
        for i in group:
            calls |= raw_calls[i]
        distinct = len(calls)
        if distinct < min_support:
            verdicts.append(cluster_evidence.INSUFFICIENT_EVIDENCE)
        elif distinct / total_calls > ta.ubiquity_ceiling:
            verdicts.append(cluster_evidence.NEEDS_REVIEW)
        else:
            verdicts.append(cluster_evidence.SCENARIO_CANDIDATE)
    return verdicts


def _grouping_compare(centroids, members, raw_ids, topic_model, total_calls,
                       merge_threshold, thresholds, show, raw_calls=None, ta=None,
                       exclude_sinks=False, review_as="sink"):
    """Compare group_post_hoc vs group_nested across candidate loose thresholds.

    Zero Gemma calls, consistent with every dry run in this codebase: judged by
    reading each group's members' actual c-TF-IDF keywords, not by counting
    groups. post_hoc groups subtopic clusters that already exist at today's
    merge_cosine_threshold (the same "clean" cluster set adjudication would see);
    nested groups the RAW topic centroids directly, before any subtopic merge.

    With exclude_sinks: subtopics whose evidence-only proxy verdict isn't
    SCENARIO_CANDIDATE (or NEEDS_REVIEW when review_as="scenario") are dropped
    from BOTH methods' input before grouping, using the SAME subtopic-level
    definition of "sink" for an apples-to-apples comparison -- for post_hoc this
    is exact (it already operates at the subtopic level); for nested this
    restricts which RAW topics are even eligible for the macro-merge, since
    nested has no fixed subtopic level independent of its own loose threshold.
    """
    print(f"\n{_BAR}\nGROUPING COMPARE: post_hoc vs nested primary-topic grouping\n{_BAR}")

    subtopic_groups = cluster_evidence.merge_by_similarity(centroids, merge_threshold)
    subtopic_keywords = []
    subtopic_centroids = []
    for group in subtopic_groups:
        tids = [raw_ids[g] for g in group]
        lead = max(tids, key=lambda t: len(members[t]))
        subtopic_keywords.append(", ".join(w for w, _ in topic_model.get_topic(lead)[:6]))
        sub_centroid = centroids[group].mean(axis=0)
        subtopic_centroids.append(sub_centroid / (np.linalg.norm(sub_centroid) + 1e-10))
    subtopic_centroids = np.stack(subtopic_centroids)
    print(f"Subtopic-level input for post_hoc: {len(raw_ids)} raw -> "
          f"{len(subtopic_groups)} subtopic cluster(s) at merge_cosine_threshold={merge_threshold}.")

    keep_raw = list(range(len(raw_ids)))
    if exclude_sinks:
        verdicts = _subtopic_verdicts(subtopic_groups, raw_calls, total_calls, ta)
        coachable_mask = [
            v == cluster_evidence.SCENARIO_CANDIDATE
            or (v == cluster_evidence.NEEDS_REVIEW and review_as == "scenario")
            for v in verdicts
        ]
        n_kept = sum(coachable_mask)
        subtopic_keywords = [kw for kw, keep in zip(subtopic_keywords, coachable_mask) if keep]
        subtopic_centroids = subtopic_centroids[coachable_mask] if n_kept else subtopic_centroids[:0]
        keep_raw = sorted({i for group, keep in zip(subtopic_groups, coachable_mask) if keep for i in group})
        print(f"--exclude-sinks (review_as={review_as}): kept {n_kept}/{len(subtopic_groups)} subtopic(s) "
              f"as coachable-proxy, {len(keep_raw)}/{len(raw_ids)} raw topic(s) survive into grouping.")
        if not n_kept:
            print("Nothing survived the coachability proxy -- skipping.")
            return

    centroids_for_nested = centroids[keep_raw]

    for threshold in thresholds:
        post_hoc_idx = cluster_evidence.merge_by_similarity(subtopic_centroids, threshold)
        post_hoc_idx.sort(key=len, reverse=True)
        post_hoc_groups = [[subtopic_keywords[i] for i in g] for g in post_hoc_idx]

        nested = topic_grouping.group_nested(centroids_for_nested, threshold, merge_threshold)
        nested_groups = []
        for macro in nested:
            kws = []
            for sub in macro:
                tids = [raw_ids[keep_raw[g]] for g in sub]
                lead = max(tids, key=lambda t: len(members[t]))
                kws.append(", ".join(w for w, _ in topic_model.get_topic(lead)[:6]))
            nested_groups.append(kws)

        _group_detail(post_hoc_groups, f"POST_HOC  loose={threshold:.2f}", show)
        _group_detail(nested_groups, f"NESTED    loose={threshold:.2f} (tight={merge_threshold})", show)

    print(f"\n{_BAR}\nNo Gemma calls made. No database writes. Nothing persisted.")
    print("Pick the (method, threshold) whose groups look coherent by eye -- a group that "
          "fuses unrelated business topics is over-merging; one where every group has 1 "
          "member is under-merging -- then set layer_a.grouping_method / "
          "primary_topic_merge_threshold in tuning.yaml.")


def main() -> None:
    args = _parse_args()
    ta = load_tuning().layer_a

    merge_threshold = args.merge_threshold if args.merge_threshold is not None else ta.merge_cosine_threshold
    support_fraction = args.support_fraction if args.support_fraction is not None else ta.min_call_support_fraction
    ubiquity_ceiling = args.ubiquity_ceiling if args.ubiquity_ceiling is not None else ta.ubiquity_ceiling
    show = 10 ** 6 if args.show == "all" else int(args.show)

    config = load_config()
    all_turns, total_calls = _load_turns(args.recordings, args.limit, config)
    print(f"Parsed {total_calls} transcript(s), {len(all_turns)} turns.")

    min_words = ta.min_content_words if args.prefilter else 0
    clauses, call_ids = build_client_clause_pool(all_turns, min_content_words=min_words)
    if not clauses:
        raise SystemExit("No CLIENT clauses found -- check transcript parsing.")
    note = " (pre-filtered)" if min_words else ""
    print(f"CLIENT clause pool: {len(clauses)} clauses{note}. Embedding...")

    vecs = embedder.embed_query_matrix(clauses)
    topic_model, topics = fit_topic_model(clauses, vecs)

    members: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    n_outliers = sum(1 for t in topics if t == -1)
    print(f"\nBERTopic: {len(raw_ids)} raw cluster(s), {n_outliers} outlier clause(s).")

    raw_calls = []
    raw_centroids = []
    for tid in raw_ids:
        idxs = members[tid]
        raw_calls.append({call_ids[i] for i in idxs})
        stats = cluster_evidence.support_stats(
            [call_ids[i] for i in idxs], vecs[idxs], total_calls
        )
        raw_centroids.append(stats.centroid)
    centroids = np.stack(raw_centroids)

    if args.sweep:
        _run_sweep(centroids, raw_calls, total_calls)
        return

    if args.grouping_compare:
        thresholds = ([float(t) for t in args.grouping_thresholds.split(",")]
                      if args.grouping_thresholds else _GROUPING_COMPARE_THRESHOLDS)
        _grouping_compare(centroids, members, raw_ids, topic_model, total_calls,
                          merge_threshold, thresholds, show, raw_calls=raw_calls, ta=ta,
                          exclude_sinks=args.exclude_sinks, review_as=args.review_as)
        return

    if args.merge_detail:
        thresholds = [float(t) for t in args.merge_detail.split(",")]
        _merge_detail(thresholds, centroids, members, raw_ids, raw_calls, clauses,
                      topic_model, total_calls, show)
        return

    min_support = cluster_evidence.required_call_support(
        total_calls, support_fraction, ta.min_call_support_floor
    )
    groups = cluster_evidence.merge_by_similarity(centroids, merge_threshold)
    print(f"Similarity merge at cosine >= {merge_threshold}: "
          f"{len(raw_ids)} -> {len(groups)} cluster(s).")
    print(f"Requiring >= {min_support} distinct calls "
          f"({support_fraction:.0%} of {total_calls}, floor {ta.min_call_support_floor}).")

    merged = []
    for group in groups:
        tids = [raw_ids[g] for g in group]
        idxs = [i for t in tids for i in members[t]]
        texts = [clauses[i] for i in idxs]
        stats = cluster_evidence.support_stats(
            [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=texts
        )
        merged.append({
            "n_merged": len(tids),
            "stats": stats,
            "keywords": ", ".join(w for w, _ in topic_model.get_topic(tids[0])[:6]),
            "texts": texts,
            "verdict": cluster_evidence.triage(stats, min_support, ubiquity_ceiling),
        })
    merged.sort(key=lambda m: m["stats"].n_items, reverse=True)

    by_verdict: dict[str, list] = defaultdict(list)
    for m in merged:
        by_verdict[m["verdict"]].append(m)

    sections = [
        (cluster_evidence.SCENARIO_CANDIDATE, "CLEAN PASS (straight to LLM labelling)"),
        (cluster_evidence.NEEDS_REVIEW,
         "NEEDS REVIEW (high coverage -- LLM decides scenario vs mechanics)"),
        (cluster_evidence.INSUFFICIENT_EVIDENCE, "DROPPED (too few distinct calls, no Gemma call)"),
    ]
    for verdict, title in sections:
        rows = by_verdict.get(verdict, [])
        print(f"\n{_BAR}\n{title}: {len(rows)}\n{_BAR}")
        print(" clauses  calls    cover  merged  keywords / sample")
        for m in rows[:show]:
            s = m["stats"]
            n_merged = m["n_merged"]
            keywords = m["keywords"]
            print(f"{s.n_items:>8} {s.distinct_calls:>6} {s.call_coverage:>7.1%} "
                  f"{n_merged:>7}  {keywords}")
            print(_PAD + "  " + _sample(m["texts"]))
        if len(rows) > show:
            print(f"  ... {len(rows) - show} more (use --show all)")

    multi = [m for m in merged if m["n_merged"] > 1]
    print(f"\n{_BAR}\nMERGE GROUPS (near-duplicate clusters collapsed): {len(multi)}\n{_BAR}")
    for m in multi[:show]:
        n_merged = m["n_merged"]
        keywords = m["keywords"]
        sample = _sample(m["texts"], 3)
        print(f"  {n_merged} raw clusters -> 1 | {keywords}")
        print("      " + sample)

    kept = len(by_verdict.get(cluster_evidence.SCENARIO_CANDIDATE, []))
    review = len(by_verdict.get(cluster_evidence.NEEDS_REVIEW, []))
    thin = len(by_verdict.get(cluster_evidence.INSUFFICIENT_EVIDENCE, []))
    print(f"\n{_BAR}\nSUMMARY\n{_BAR}")
    print(f"  raw clusters                : {len(raw_ids)}")
    print(f"  after similarity merge      : {len(groups)}")
    print(f"  clean pass                  : {kept}")
    print(f"  needs LLM review            : {review}")
    print(f"  dropped (thin evidence)     : {thin}")
    print(f"  clusters costing a Gemma call: {kept + review}")
    # The ubiquity ceiling must be read off this distribution, not guessed. It
    # selects an audit set for the LLM, so it belongs in the upper tail -- a value
    # that flags most of the taxonomy makes the flag meaningless.
    cov = np.sort([m["stats"].call_coverage for m in merged])
    pcts = [10, 25, 50, 75, 90, 95, 99]
    print(f"\n{_BAR}\nCALL-COVERAGE DISTRIBUTION over {len(cov)} merged cluster(s)\n{_BAR}")
    print("  " + "  ".join(f"p{p}={np.percentile(cov, p):.0%}" for p in pcts))
    print(f"  min={cov[0]:.0%}  max={cov[-1]:.0%}  mean={cov.mean():.0%}")
    flagged = int((cov > ubiquity_ceiling).sum())
    print(f"  at ubiquity_ceiling={ubiquity_ceiling:.0%}: {flagged} of {len(cov)} "
          f"cluster(s) flagged for LLM review ({flagged / len(cov):.0%})")

    print(f"\n  thresholds: merge>={merge_threshold} "
          f"min_calls>={min_support} ubiquity<={ubiquity_ceiling:.0%}")
    print("  No Gemma calls made. No database writes. Nothing persisted.")


if __name__ == "__main__":
    main()
