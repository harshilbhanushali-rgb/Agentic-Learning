from __future__ import annotations
from collections import defaultdict

import numpy as np
import psycopg
from config import Config
from preprocessing import segmenter, embedder
from preprocessing.transcript_parser import Turn, SpeakerRole
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_A_V2_TRIAGE, PROMPT_LAYER_A_PRIMARY_TOPIC_LABEL_BATCH
from shared import storage, cluster_evidence, topic_grouping
from shared.tuning import load_tuning

_NEAREST_SHOWN = 3
_REPRESENTATIVE_SHOWN = 6
_TOPIC_LABEL_BATCH_SIZE = 5


POOL_UNIT_CLAUSE = "clause"
POOL_UNIT_TURN = "turn"
_POOL_UNITS = (POOL_UNIT_CLAUSE, POOL_UNIT_TURN)


def build_client_pool(
    all_turns: list[Turn],
    unit: str = POOL_UNIT_CLAUSE,
    min_content_words: int = 0,
) -> tuple[list[str], list[str]]:
    """Build the CLIENT text pool Layer A clusters, keeping the source call per item.

    Returns parallel lists (texts, call_ids). The call id is what makes every
    evidence check downstream possible -- distinct-call support cannot be computed
    from a flat list of strings.

    `unit` selects what ONE item is, and it is the whole point of this function:

      "clause"  spaCy sentences of >=4 tokens (legacy, shipped default).
      "turn"    one whole CLIENT turn -- the SAME unit Layer B matches against in
                kb_pairs.trigger_text.

    Why the unit matters: clause mode severs a stance sentence from the subject it
    arrived with, so "Yeah. That makes sense. So for the ATS integration, do we need
    a pixel?" enters the pool as TWO items, one carrying no subject at all. 59.1% of
    the clause pool (43,566 of 73,771) is content-free for this reason, and that is
    the raw material every posture scenario ("client_expresses_uncertainty" and
    friends) is built from. Measured 2026-08-14: 21/68 scenarios beat a size-matched random null, and
    20 of those 21 are subject-matter -- 1 of 24 posture scenarios clears it.

    In turn mode this function does NOT call the segmenter at all. That is
    deliberate: segment_into_clauses is shared with v2/layer_c.py, so leaving it
    untouched is what proves Layer C's milestone clause pool cannot shift.

    min_content_words=0 disables the cheap pre-filter (production behaviour --
    note the key layer_a.min_content_words is honoured only by the dry run's
    --prefilter flag, see the spec).
    """
    if unit not in _POOL_UNITS:
        raise ValueError(
            f"layer_a.pool_unit must be one of {_POOL_UNITS}, got {unit!r}"
        )

    texts: list[str] = []
    call_ids: list[str] = []
    for turn in all_turns:
        if turn.role != SpeakerRole.CLIENT:
            continue
        items = ([turn.text] if unit == POOL_UNIT_TURN
                 else segmenter.segment_into_clauses(turn.text))
        for item in items:
            if min_content_words and not cluster_evidence.is_substantive(item, min_content_words):
                continue
            texts.append(item)
            call_ids.append(turn.call_id)
    return texts, call_ids


def fit_topic_model(clauses: list[str], embeddings_matrix: np.ndarray,
                    min_cluster_size: int | None = None):
    """Fit BERTopic over precomputed embeddings. Returns (topic_model, topics).

    min_cluster_size=None keeps the legacy formula, so production is unchanged.

    NOTE the legacy formula is `max(3, min(n // 10, 50))`, and the `n // 10` term is
    capped at 50 for any corpus of >= 500 items -- so for every real corpus it is a
    hardcoded COUNT of 50, not a property of the data. That makes granularity depend
    on pool SIZE: 50 is 0.068% of the 73,771-clause pool but 0.209% of the 23,949-turn
    pool, a 3x stiffer relative bar. Any comparison of two pools with different item
    counts MUST pass a scale-matched override here or it measures the bar, not the
    pools. See docs/superpowers/specs/2026-08-14-layer-a-pool-unit-design.md.
    """
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    n = len(clauses)
    if min_cluster_size is None:
        min_cluster_size = max(3, min(n // 10, 50))
    min_samples = max(2, min_cluster_size // 3)
    umap_model = UMAP(n_components=5, n_neighbors=min(15, n - 1), min_dist=0.0, metric="cosine", random_state=42)
    hdbscan_model = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples,
                             metric="euclidean", cluster_selection_method="eom", prediction_data=True)
    vectorizer_model = CountVectorizer(ngram_range=(1, 2), stop_words="english", min_df=2)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        embedding_model=None,
        calculate_probabilities=False,
        verbose=True,
    )
    topics, _ = topic_model.fit_transform(clauses, embeddings=embeddings_matrix)
    return topic_model, topics


def _raw_topic_data(call_ids, vecs, topics, total_calls):
    """Group clause indices by raw BERTopic topic id, and centroid each one.

    Shared by both grouping mechanisms below: the flat merge (_merged_clusters)
    and the nested merge (_nested_clusters) both start from the same raw
    per-topic members/centroids, they only differ in what they do with them.
    """
    members: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    if not raw_ids:
        return members, raw_ids, np.empty((0, 0), dtype=np.float32)

    raw_centroids = np.stack([
        cluster_evidence.support_stats(
            [call_ids[i] for i in members[t]], vecs[members[t]], total_calls
        ).centroid
        for t in raw_ids
    ])
    return members, raw_ids, raw_centroids


def _build_cluster_record(tids, members, clauses, call_ids, vecs, topic_model, total_calls,
                           macro_group_id=None):
    """One cluster dict from a list of raw topic ids already decided to belong together."""
    idxs = [i for t in tids for i in members[t]]
    texts = [clauses[i] for i in idxs]
    stats = cluster_evidence.support_stats(
        [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=texts
    )
    # Keywords come from the largest member topic, not tids[0], so a merged
    # group is described by its dominant sense.
    lead = max(tids, key=lambda t: len(members[t]))
    record = {
        "n_merged": len(tids),
        "stats": stats,
        "keywords": ", ".join(w for w, _ in topic_model.get_topic(lead)[:10]),
        "texts": texts,
        "call_set": {call_ids[i] for i in idxs},
    }
    if macro_group_id is not None:
        record["macro_group_id"] = macro_group_id
    return record


def _merged_clusters(clauses, call_ids, vecs, topics, topic_model, total_calls, threshold):
    """Cluster BERTopic topics into evidence-bearing groups, largest first.

    Raw topics are merged by centroid cosine similarity. This replaces the old
    MAX_CLUSTERS=150 / reduce_topics() cap, which merged the RAREST topics first
    by c-TF-IDF keyword overlap -- the opposite end of the distribution from the
    backchannel families that actually duplicate, and blind to them anyway since
    "Perfect. Alright then" and "yeah that makes sense" share no vocabulary.

    Largest-first ordering matters downstream: the best-evidenced cluster in a
    family is adjudicated first and becomes the canonical scenario, so later
    variants have something to merge INTO.

    This is the 'post_hoc' grouping method's subtopic path -- unchanged by the
    primary-topic hierarchy. Primary-topic grouping runs AFTER this function's
    output has been fully adjudicated, as a separate pass (see
    _finalize_primary_topics), so this function's behaviour is untouched.
    """
    members, raw_ids, raw_centroids = _raw_topic_data(call_ids, vecs, topics, total_calls)
    if not raw_ids:
        return []

    groups = cluster_evidence.merge_by_similarity(raw_centroids, threshold)
    print(f"[V2 Layer A] Similarity merge at cosine >= {threshold}: "
          f"{len(raw_ids)} raw -> {len(groups)} cluster(s).")

    clusters = [
        _build_cluster_record([raw_ids[g] for g in group], members, clauses, call_ids, vecs,
                               topic_model, total_calls)
        for group in groups
    ]
    clusters.sort(key=lambda c: c["stats"].n_items, reverse=True)
    return clusters


def _nested_clusters(clauses, call_ids, vecs, topics, topic_model, total_calls,
                      loose_threshold, tight_threshold):
    """The 'nested' grouping method's subtopic path.

    Merges RAW topic centroids into macro-groups at loose_threshold FIRST, then
    subtopic-merges within each macro-group at tight_threshold (subtopic
    dedup's own threshold) -- rather than merging already-adjudicated subtopics
    into macro-groups after the fact, as _merged_clusters + post_hoc grouping
    does. Every returned cluster carries macro_group_id so the caller can later
    group by_key entries by macro-group without a second merge pass.

    Ordered macro-group by macro-group (largest macro-group first, largest
    subtopic first within it) rather than one flat globally-sorted list --
    _adjudicate's nearest-accepted-scenario context is therefore built up one
    macro-group at a time.
    """
    members, raw_ids, raw_centroids = _raw_topic_data(call_ids, vecs, topics, total_calls)
    if not raw_ids:
        return []

    nested = topic_grouping.group_nested(raw_centroids, loose_threshold, tight_threshold)
    print(f"[V2 Layer A] Nested merge: {len(raw_ids)} raw -> {len(nested)} macro-group(s) "
          f"(loose>={loose_threshold}, tight>={tight_threshold}).")

    clusters = []
    for macro_idx, sub_groups in enumerate(nested):
        macro_clusters = [
            _build_cluster_record([raw_ids[g] for g in sub], members, clauses, call_ids, vecs,
                                   topic_model, total_calls, macro_group_id=macro_idx)
            for sub in sub_groups
        ]
        macro_clusters.sort(key=lambda c: c["stats"].n_items, reverse=True)
        clusters.extend(macro_clusters)
    return clusters


def _nearest_accepted(centroid, accepted):
    """Top-N already-accepted scenarios by centroid cosine, closest first."""
    if not accepted:
        return []
    mat = np.stack([a["centroid"] for a in accepted])
    sims = mat @ centroid
    order = np.argsort(sims)[::-1][:_NEAREST_SHOWN]
    return [(accepted[i], float(sims[i])) for i in order]


def _adjudicate(cluster, verdict, accepted, total_calls, config):
    """One Gemma call: is this a new scenario, a duplicate, or not coachable?

    Does not ask for a primary_topic -- that is now assigned structurally, once
    per macro-group, by _finalize_primary_topics after this whole loop finishes.
    """
    stats = cluster["stats"]
    nearest = _nearest_accepted(stats.centroid, accepted)
    if nearest:
        nearest_block = "\n".join(
            f'- {a["scenario_key"]} (cosine {sim:.2f}): {a["business_description"]}'
            for a, sim in nearest
        )
    else:
        nearest_block = "- (none yet: this is the first cluster considered)"

    if verdict == cluster_evidence.NEEDS_REVIEW:
        coverage_note = (
            f"- FLAGGED: this cluster spans an unusually large share of the corpus. "
            f"That is characteristic of conversational mechanics, but a core business "
            f"topic can also legitimately appear in most calls. Decide from the "
            f"utterances above which of the two this is."
        )
    else:
        coverage_note = "- coverage is within the normal range for a specific scenario."

    prompt = PROMPT_LAYER_A_V2_TRIAGE.format(
        keywords=cluster["keywords"],
        representative_utterances="\n".join(
            f"- {t}" for t in cluster["texts"][:_REPRESENTATIVE_SHOWN]
        ),
        distinct_calls=stats.distinct_calls,
        total_calls=total_calls,
        call_coverage=stats.call_coverage,
        n_clauses=stats.n_items,
        n_merged=cluster["n_merged"],
        coverage_note=coverage_note,
        nearest_scenarios=nearest_block,
    )
    return call_gemma(prompt, config.gemma_api_keys)


_KIND_BY_DECISION = {
    "new_scenario": cluster_evidence.KIND_SCENARIO,
    "mechanics": cluster_evidence.KIND_MECHANICS,
    "not_coachable": cluster_evidence.KIND_LOGISTICS,
}

_GROUPING_METHOD_TAG = {
    "post_hoc": "post_hoc_merge",
    "nested": "nested_cluster",
}


def _label_primary_topics_batch(groups: list[list[dict]], config: Config) -> list[dict]:
    """One batched Gemma call per _TOPIC_LABEL_BATCH_SIZE macro-groups: name the
    umbrella category each group's members share.

    Zero DB writes -- mirrors v2/layer_c.py's batch-describe/batch-judge
    convention: results held in memory, applied by the caller. Returns one
    {primary_topic_key, label, description, keyphrases} dict per group, in the
    same order as `groups`, with a de-duplicated primary_topic_key (a repeated
    key across groups is a Gemma naming collision, not a real merge -- same
    handling as run_layer_a_v2's own scenario_key collision guard).
    """
    if not groups:
        return []

    results_by_idx: dict[int, dict] = {}
    for i in range(0, len(groups), _TOPIC_LABEL_BATCH_SIZE):
        chunk = list(enumerate(groups))[i:i + _TOPIC_LABEL_BATCH_SIZE]
        items_block = "\n\n".join(
            f"- id: g{idx}\n" + "\n".join(
                f"    - {m['scenario_key']}: {m.get('business_description', '')} "
                f"(keywords: {m['keywords']})"
                for m in members
            )
            for idx, members in chunk
        )
        raw = call_gemma(
            PROMPT_LAYER_A_PRIMARY_TOPIC_LABEL_BATCH.format(items_block=items_block),
            config.gemma_api_keys,
        )
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            gid = r.get("id", "")
            if gid.startswith("g") and gid[1:].isdigit():
                results_by_idx[int(gid[1:])] = r

    used_keys: set[str] = set()
    labels = []
    for idx in range(len(groups)):
        r = results_by_idx.get(idx, {})
        base_key = r.get("primary_topic_key") or f"primary_topic_{idx}"
        key = base_key
        suffix = 1
        while key in used_keys:
            key = f"{base_key}_{suffix}"
            suffix += 1
        used_keys.add(key)
        labels.append({
            "primary_topic_key": key,
            "label": r.get("label") or "Uncategorised",
            "description": r.get("description") or "",
            "keyphrases": r.get("keyphrases") or [],
        })

    # Each batch of _TOPIC_LABEL_BATCH_SIZE groups is labeled by an independent
    # Gemma call, so two different batches can reinvent the same natural-
    # language label for genuinely unrelated groups -- confirmed in production
    # ("Positive Client Sentiment" assigned to both a 5-member and a 1-member
    # group). primary_topic_key already gets a uniqueness suffix above; the
    # label a human actually reads needs the same treatment, or two distinct
    # rows are indistinguishable when browsing the taxonomy.
    label_counts: dict[str, int] = {}
    for entry in labels:
        label_counts[entry["label"]] = label_counts.get(entry["label"], 0) + 1
    seen_labels: dict[str, int] = {}
    for entry in labels:
        base_label = entry["label"]
        if label_counts[base_label] > 1:
            seen_labels[base_label] = seen_labels.get(base_label, 0) + 1
            entry["label"] = f"{base_label} ({seen_labels[base_label]})"
    return labels


def _finalize_primary_topics(by_key: dict[str, dict], tuning, config: Config, total_calls: int) -> list[dict]:
    """Group every subtopic record (coachable AND sink -- sinks get a
    primary_topic_key too, so the taxonomy stays uniform to browse) into
    primary-topic macro-groups, label each via Gemma, and mutate every record
    in-place with primary_topic_key/primary_topic (the denormalized label).

    Dispatches on tuning.grouping_method. Zero DB calls -- called after
    adjudication finishes and before the DB-write loop in run_layer_a_v2, same
    "no DB calls inside the Gemma loop" discipline that loop already follows.

    Returns the primary_topics rows ready for storage.upsert_primary_topic.
    """
    records = list(by_key.values())
    if not records:
        return []

    if tuning.grouping_method == "nested":
        by_macro: dict[int, list[dict]] = defaultdict(list)
        for r in records:
            by_macro[r["macro_group_id"]].append(r)
        groups = [by_macro[k] for k in sorted(by_macro)]
    elif tuning.grouping_method == "post_hoc":
        key_groups = topic_grouping.group_post_hoc(records, tuning.primary_topic_merge_threshold)
        by_scenario_key = {r["scenario_key"]: r for r in records}
        groups = [[by_scenario_key[k] for k in g] for g in key_groups]
    else:
        raise ValueError(
            f"tuning.yaml: layer_a.grouping_method must be 'post_hoc' or 'nested', "
            f"got {tuning.grouping_method!r}"
        )

    groups = topic_grouping.split_by_coachability(groups)
    groups = topic_grouping.tighten_coachable_groups(groups, tuning.merge_cosine_threshold)
    labels = _label_primary_topics_batch(groups, config)
    method_tag = _GROUPING_METHOD_TAG[tuning.grouping_method]

    rows = []
    for group, label_info in zip(groups, labels):
        member_calls: set[str] = set()
        for r in group:
            member_calls |= r["call_set"]
        rows.append({
            "primary_topic_key": label_info["primary_topic_key"],
            "label": label_info["label"],
            "description": label_info["description"],
            "keyphrases": label_info["keyphrases"],
            "grouping_method": method_tag,
            "support_calls": len(member_calls),
            "support_subtopics": len(group),
            "call_coverage": len(member_calls) / total_calls,
        })
        for r in group:
            r["primary_topic_key"] = label_info["primary_topic_key"]
            r["primary_topic"] = label_info["label"]
    return rows


def run_layer_a_v2(
    all_turns: list[Turn],
    config: Config,
    conn: psycopg.Connection,
) -> tuple[dict[str, dict], psycopg.Connection]:
    """V2 scenario identification: cluster freely, then triage clusters on evidence.

    Filtering utterances means judging ~74,000 items and can never be exhaustive.
    Triaging clusters means judging ~200, which is cheap enough to afford real
    evidence -- and costs no more Gemma calls than the old blind labelling loop,
    because thin clusters are dropped before they reach the LLM.

    Whatever survives IS the taxonomy. There is no target count.

    Primary-topic grouping (tuning.grouping_method) runs as a separate pass
    after every subtopic is adjudicated: it never changes which subtopics exist
    or how they were triaged, only which primary_topic each one belongs to.
    """
    tuning = load_tuning().layer_a
    if tuning.grouping_method not in ("post_hoc", "nested"):
        raise ValueError(
            f"tuning.yaml: layer_a.grouping_method must be 'post_hoc' or 'nested', "
            f"got {tuning.grouping_method!r}"
        )
    client_clauses, call_ids = build_client_pool(all_turns, unit=tuning.pool_unit)

    if not client_clauses:
        raise ValueError("No CLIENT text found -- check transcript parsing.")

    total_calls = len(set(call_ids))
    print(f"[V2 Layer A] Pooled {len(client_clauses)} CLIENT item(s) "
          f"[unit={tuning.pool_unit}] from {total_calls} call(s). Embedding...")
    vecs = embedder.embed_query_matrix(client_clauses)

    topic_model, topics = fit_topic_model(client_clauses, vecs)
    if tuning.grouping_method == "nested":
        clusters = _nested_clusters(
            client_clauses, call_ids, vecs, topics, topic_model, total_calls,
            tuning.primary_topic_merge_threshold, tuning.merge_cosine_threshold,
        )
    else:
        clusters = _merged_clusters(
            client_clauses, call_ids, vecs, topics, topic_model,
            total_calls, tuning.merge_cosine_threshold,
        )
    if not clusters:
        raise ValueError("BERTopic produced no clusters -- check min_cluster_size.")

    min_support = cluster_evidence.required_call_support(
        total_calls, tuning.min_call_support_fraction, tuning.min_call_support_floor
    )
    print(f"[V2 Layer A] Requiring >= {min_support} distinct calls; "
          f"coverage > {tuning.ubiquity_ceiling:.0%} routes to LLM review.")

    # Adjudication makes no DB calls: Gemma is slow enough that holding a
    # Postgres connection across ~200 calls invites an idle SSL drop. Everything
    # is written afterwards in one pass.
    accepted: list[dict] = []
    by_key: dict[str, dict] = {}
    n_dropped = n_merged_away = 0

    for cluster in clusters:
        stats = cluster["stats"]
        verdict = cluster_evidence.triage(
            stats, min_support, tuning.ubiquity_ceiling
        )
        if verdict == cluster_evidence.INSUFFICIENT_EVIDENCE:
            n_dropped += 1
            print(f"  - dropped: {stats.distinct_calls} call(s) < {min_support} "
                  f"| {cluster['keywords'][:60]}")
            continue

        result = _adjudicate(cluster, verdict, accepted, total_calls, config)
        decision = (result.get("decision") or "new_scenario").strip()
        reason = (result.get("reason") or "").strip()

        if decision == "merge_into":
            target_key = result.get("merge_into_key")
            target = by_key.get(target_key)
            if target is None:
                # An unmatchable key is a hallucination, not a merge. Falling
                # through to new_scenario is the safe direction: a spurious
                # duplicate is recoverable, silently discarding a real scenario
                # is not.
                print(f"  ! merge_into '{target_key}' matches no accepted scenario "
                      f"-- treating as new_scenario.")
                decision = "new_scenario"
            else:
                n_merged_away += 1
                target["call_set"] |= cluster["call_set"]
                target["support_clauses"] += stats.n_items
                target["support_calls"] = len(target["call_set"])
                target["call_coverage"] = target["support_calls"] / total_calls
                # Re-centre on the union so later near-duplicates compare against
                # the whole family, not just its first member.
                w_old = target["n_items"]
                w_new = stats.n_items
                blended = (target["centroid"] * w_old + stats.centroid * w_new) / (w_old + w_new)
                target["centroid"] = blended / (np.linalg.norm(blended) + 1e-10)
                target["n_items"] = w_old + w_new
                print(f"  = merged into {target_key}: {reason[:80]}")
                continue

        kind = _KIND_BY_DECISION.get(decision, cluster_evidence.KIND_SCENARIO)
        is_coachable = kind == cluster_evidence.KIND_SCENARIO

        base_key = result.get("scenario_key") or f"cluster_{len(by_key)}"
        key = base_key
        suffix = 1
        while key in by_key:
            key = f"{base_key}_{suffix}"
            suffix += 1

        record = {
            "scenario_key": key,
            "business_description": result.get("sub_topic") or "",
            "keyphrases": result.get("keyphrases") or [],
            # Carried through from the raw cluster (not Gemma's response) so
            # _label_primary_topics_batch can describe this subtopic to the
            # LLM by its actual c-TF-IDF keywords, same as the triage prompt.
            "keywords": cluster["keywords"],
            "soft_skills": result.get("soft_skills") or [],
            "bloom_level": result.get("bloom_level") or "understand",
            "is_coachable": is_coachable,
            "cluster_kind": kind,
            "support_calls": stats.distinct_calls,
            "support_clauses": stats.n_items,
            "call_coverage": stats.call_coverage,
            "triage_verdict": verdict,
            "adjudication_reason": reason,
            # Adjudication-only bookkeeping, stripped before the DB write.
            "centroid": stats.centroid,
            "call_set": set(cluster["call_set"]),
            "n_items": stats.n_items,
            "macro_group_id": cluster.get("macro_group_id"),
        }
        by_key[key] = record
        # Sinks are deliberately excluded from the nearest-neighbour list: a real
        # scenario must never be offered "merge into mechanics" as an option.
        if is_coachable:
            accepted.append(record)
        marker = "+" if is_coachable else "~"
        print(f"  {marker} {key} [{kind}] {stats.distinct_calls} calls "
              f"({stats.call_coverage:.0%}) | {reason[:70]}")

    primary_topic_rows = _finalize_primary_topics(by_key, tuning, config, total_calls)
    print(f"[V2 Layer A] Grouped {len(by_key)} subtopic(s) into "
          f"{len(primary_topic_rows)} primary topic(s) via '{tuning.grouping_method}'.")

    conn = storage.reconnect_if_closed(conn)
    for row in primary_topic_rows:
        storage.upsert_primary_topic(conn, row)

    scenario_map: dict[str, dict] = {}
    for key, record in by_key.items():
        row = {k: v for k, v in record.items()
               if k not in ("centroid", "call_set", "n_items", "macro_group_id")}
        scenario_id = storage.upsert_scenario(conn, row)
        scenario_map[key] = {
            "scenario_id": scenario_id,
            "keyphrases": record["keyphrases"],
            "business_description": record["business_description"],
            "primary_topic": record["primary_topic"],
            "primary_topic_key": record["primary_topic_key"],
            "is_coachable": record["is_coachable"],
            "cluster_kind": record["cluster_kind"],
        }

    n_coachable = sum(1 for v in scenario_map.values() if v["is_coachable"])
    print(f"[V2 Layer A] Taxonomy: {n_coachable} coachable, "
          f"{len(scenario_map) - n_coachable} sink(s); "
          f"{n_merged_away} cluster(s) merged as duplicates, "
          f"{n_dropped} dropped on thin evidence.")
    if not n_coachable:
        raise ValueError(
            "No coachable scenarios survived triage -- thresholds in tuning.yaml "
            "are too aggressive for this corpus."
        )
    return scenario_map, conn
