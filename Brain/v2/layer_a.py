from __future__ import annotations
from collections import defaultdict

import numpy as np
import psycopg
from config import Config
from preprocessing import segmenter, embedder
from preprocessing.transcript_parser import Turn, SpeakerRole
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_A_V2_TRIAGE
from shared import storage, cluster_evidence
from shared.tuning import load_tuning

_NEAREST_SHOWN = 3
_REPRESENTATIVE_SHOWN = 6


def build_client_clause_pool(
    all_turns: list[Turn],
    min_content_words: int = 0,
) -> tuple[list[str], list[str]]:
    """Segment CLIENT turns into clauses, keeping the source call for each one.

    Returns parallel lists (clause_texts, call_ids). The call id is what makes
    every evidence check downstream possible -- distinct-call support cannot be
    computed from a flat list of strings.

    min_content_words=0 disables the cheap pre-filter (current behaviour).
    """
    texts: list[str] = []
    call_ids: list[str] = []
    for turn in all_turns:
        if turn.role != SpeakerRole.CLIENT:
            continue
        for clause in segmenter.segment_into_clauses(turn.text):
            if min_content_words and not cluster_evidence.is_substantive(clause, min_content_words):
                continue
            texts.append(clause)
            call_ids.append(turn.call_id)
    return texts, call_ids


def fit_topic_model(clauses: list[str], embeddings_matrix: np.ndarray):
    """Fit BERTopic over precomputed embeddings. Returns (topic_model, topics)."""
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    n = len(clauses)
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
    """
    members: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(topics):
        if t != -1:
            members[int(t)].append(i)
    raw_ids = sorted(members)
    if not raw_ids:
        return []

    raw_centroids = np.stack([
        cluster_evidence.support_stats(
            [call_ids[i] for i in members[t]], vecs[members[t]], total_calls
        ).centroid
        for t in raw_ids
    ])
    groups = cluster_evidence.merge_by_similarity(raw_centroids, threshold)
    print(f"[V2 Layer A] Similarity merge at cosine >= {threshold}: "
          f"{len(raw_ids)} raw -> {len(groups)} cluster(s).")

    clusters = []
    for group in groups:
        tids = [raw_ids[g] for g in group]
        idxs = [i for t in tids for i in members[t]]
        texts = [clauses[i] for i in idxs]
        stats = cluster_evidence.support_stats(
            [call_ids[i] for i in idxs], vecs[idxs], total_calls, texts=texts
        )
        # Keywords come from the largest member topic, not tids[0], so a merged
        # group is described by its dominant sense.
        lead = max(tids, key=lambda t: len(members[t]))
        clusters.append({
            "n_merged": len(tids),
            "stats": stats,
            "keywords": ", ".join(w for w, _ in topic_model.get_topic(lead)[:10]),
            "texts": texts,
            "call_set": {call_ids[i] for i in idxs},
        })
    clusters.sort(key=lambda c: c["stats"].n_items, reverse=True)
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
    """One Gemma call: is this a new scenario, a duplicate, or not coachable?"""
    stats = cluster["stats"]
    nearest = _nearest_accepted(stats.centroid, accepted)
    if nearest:
        nearest_block = "\n".join(
            f'- {a["scenario_key"]} (cosine {sim:.2f}): {a["sub_topic"]}'
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
    """
    tuning = load_tuning().layer_a
    client_clauses, call_ids = build_client_clause_pool(all_turns)

    if not client_clauses:
        raise ValueError("No CLIENT clauses found -- check transcript parsing.")

    total_calls = len(set(call_ids))
    print(f"[V2 Layer A] Segmented {len(client_clauses)} CLIENT clauses "
          f"from {total_calls} call(s). Embedding...")
    vecs = embedder.embed_query_matrix(client_clauses)

    topic_model, topics = fit_topic_model(client_clauses, vecs)
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
            "primary_topic": result.get("primary_topic") or "Uncategorised",
            "sub_topic": result.get("sub_topic") or "",
            "keyphrases": result.get("keyphrases") or [],
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
        }
        by_key[key] = record
        # Sinks are deliberately excluded from the nearest-neighbour list: a real
        # scenario must never be offered "merge into mechanics" as an option.
        if is_coachable:
            accepted.append(record)
        marker = "+" if is_coachable else "~"
        print(f"  {marker} {key} [{kind}] {stats.distinct_calls} calls "
              f"({stats.call_coverage:.0%}) | {reason[:70]}")

    conn = storage.reconnect_if_closed(conn)
    scenario_map: dict[str, dict] = {}
    for key, record in by_key.items():
        row = {k: v for k, v in record.items()
               if k not in ("centroid", "call_set", "n_items")}
        scenario_id = storage.upsert_scenario(conn, row)
        scenario_map[key] = {
            "scenario_id": scenario_id,
            "keyphrases": record["keyphrases"],
            "sub_topic": record["sub_topic"],
            "primary_topic": record["primary_topic"],
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
