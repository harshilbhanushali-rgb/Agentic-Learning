from __future__ import annotations
import math
import time
import numpy as np
import psycopg
from config import Config
from preprocessing import segmenter, embedder
from shared.gemma import call_gemma
from shared.prompts import (
    PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH,
    PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH,
    PROMPT_LAYER_C_V2_ORDER,
    PROMPT_LAYER_C_V1,
)
from shared import storage, checkpoint, cluster_evidence, scenario_vectors
from shared.tuning import load_tuning

_GEMMA_CALL_DELAY = 5  # seconds between calls -- free-tier quota is 16000 input tokens/minute
_MAX_RUBRIC_RESPONSES = 12  # cap responses fed into one rubric prompt -- some scenarios match 50+ instances
_TRIAGE_BATCH_SIZE = 5  # flagged milestones per PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH call
_DESCRIBE_BATCH_SIZE = 5  # milestones per PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH call

STATUS_GENERATED = "rubric_generated"
STATUS_NOT_COACHABLE = "skipped_not_coachable"
STATUS_INSUFFICIENT = "skipped_insufficient_responses"
STATUS_FAILED = "failed"


def build_clause_pool(
    responses: list[dict],
) -> tuple[list[str], list[float], list[str]]:
    """Segment each response into clauses, keeping per-clause position and source call.

    Extracted from _pass1_cluster_scenario (unchanged behaviour) so an offline
    replay can build a byte-identical pool instead of reimplementing this loop.
    dry_run_layer_c_clustering.py keeps its own private copy of the relevance
    filter and that is exactly the drift risk worth avoiding -- a Layer B sweep
    that reimplemented the sink short-circuit once disagreed with production by
    99.7% vs 14%.

    clause_calls is the load-bearing return value: without the source call there
    is no way to tell a move repeated across many calls from two adjacent
    clauses of a single response, and min_cluster_size=2 accepted both. That was
    the 95-milestone bug.

    n = max(len(clauses) - 1, 1) normalises position to [0, 1] and keeps a
    single-clause response at 0.0 rather than dividing by zero.
    """
    all_clauses: list[str] = []
    clause_positions: list[float] = []
    clause_calls: list[str] = []
    for resp in responses:
        clauses = segmenter.segment_into_clauses(resp["response_text"])
        n = max(len(clauses) - 1, 1)
        for pos_idx, clause in enumerate(clauses):
            all_clauses.append(clause)
            clause_positions.append(pos_idx / n)
            clause_calls.append(resp["call_filename"])
    return all_clauses, clause_positions, clause_calls


def _relevance_filter(clauses, vecs, positions, calls, info, percentile):
    """Drop response clauses that are not about the scenario they were filed under.

    A response to "how do we measure quality of hire" contains the strategic
    answer AND "thanks so much for your time" AND "sorry, can you hear me". All
    three become milestone candidates because all three are clauses of a matched
    response, and generic moves cluster tightly precisely because they recur
    verbatim everywhere. That is how "Expressing Gratitude" became a milestone of
    job_board_advertising_strategy.

    The filter is relative to each scenario's OWN relevance distribution, not an
    absolute cosine floor -- scenarios differ in how close their responses sit to
    their description, so one global number would over-cut some and under-cut
    others. It reuses embeddings already computed, so it adds no hand-maintained
    artifact and nothing to keep current as the corpus grows.
    """
    svec = np.asarray(scenario_vectors.scenario_vec(info), dtype=np.float32)
    svec = svec / (np.linalg.norm(svec) + 1e-10)
    normed = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)
    relevance = normed @ svec

    cutoff = float(np.percentile(relevance, percentile))
    keep = [i for i in range(len(clauses)) if relevance[i] >= cutoff]
    return (
        [clauses[i] for i in keep],
        vecs[keep],
        [positions[i] for i in keep],
        [calls[i] for i in keep],
        {clauses[i]: float(relevance[i]) for i in keep},
    )


def _cluster_milestones(vecs: np.ndarray, min_cluster_size: int, n_components_ceiling: int) -> np.ndarray:
    """UMAP dimensionality reduction before HDBSCAN, mirroring Layer A's own
    bertopic+umap+hdbscan pipeline.

    MEASURED 2026-07-28: raw HDBSCAN on 768-dim bge embeddings hit 100% noise
    (zero clusters) on 28 of 85 coachable scenarios regardless of clause pool
    size (10 to 680 clauses) -- distance concentration in raw high-dimensional
    space. UMAP(n_components<=5, metric='cosine', random_state=42) -> HDBSCAN
    rescued 26/28 with lower mean noise (37.9% vs 71.4%), validated by reading
    cluster contents for coherence, not just counting. See
    docs/superpowers/specs/2026-07-28-layer-c-rubric-depth-design.md.

    n_components is capped below the pool size -- UMAP needs strictly fewer
    components than samples, so the tuning.yaml ceiling only applies once the
    pool is large enough to support it.
    """
    import umap
    from hdbscan import HDBSCAN

    n_components = min(n_components_ceiling, max(2, vecs.shape[0] - 2))
    reducer = umap.UMAP(n_components=n_components, metric="cosine", random_state=42)
    reduced = reducer.fit_transform(vecs)
    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                        cluster_selection_method="eom")
    return clusterer.fit_predict(reduced)


def _sink_centroids(scenario_map: dict[str, dict]) -> tuple[list[str], np.ndarray]:
    """Sink-scenario (is_coachable=false) description vectors, normalized, in the
    same embedding space as milestone clause centroids -- built from this run's
    own scenario_map, so no extra DB query is needed. Used only as a soft
    review-flag signal, never a rejection filter.
    """
    sinks = {k: v for k, v in scenario_map.items() if not v.get("is_coachable", True)}
    if not sinks:
        return [], np.empty((0, 0), dtype=np.float32)
    keys, vecs = scenario_vectors.build_scenario_vecs(sinks)
    arr = np.asarray(vecs, dtype=np.float32)
    normed = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-10)
    return keys, normed


def _pass1_cluster_scenario(
    scenario_key: str,
    info: dict,
    tuning,
    sink_keys: list[str],
    sink_centroids: np.ndarray,
    conn: psycopg.Connection,
    run_id: str,
) -> dict | None:
    """Cluster one scenario's response clauses into milestone candidates. Makes
    ZERO Gemma calls -- the batch judge needs every scenario's candidates before
    it can compute a run-wide review-flag threshold, so nothing here can call
    the milestone-describe or sequencing prompts yet.

    Returns None if the scenario is already fully handled (a terminal status was
    written, or the checkpoint says it's done). Otherwise returns a dict for the
    caller to finish in a later pass:
      {"kind": "fallback", "info": ..., "responses": ...}
        -- too few responses/clauses, or clustering/the call-support gate found
           nothing. v1 free-text milestone generation is unrelated to clustering
           evidence, so it is deferred to Pass 2 rather than run here, keeping
           this pass Gemma-free without complicating its control flow.
      {"kind": "clustered", "info": ..., "responses": ..., "candidates": [...]}
        -- >=1 milestone candidate survived the call-support gate, ordered by
           median position, each carrying a sink_similarity/nearest_sink score
           (None if this run has no sink scenarios to compare against).
    """
    if not info.get("is_coachable", True):
        print(f"[V2 Layer C] {scenario_key} is a {info.get('cluster_kind')} sink "
              f"-- no rubric.")
        storage.set_rubric_status(conn, scenario_key, STATUS_NOT_COACHABLE)
        return None
    if run_id and checkpoint.is_done(run_id, scenario_key, "layer_c"):
        print(f"[V2 Layer C] {scenario_key} already done — skipping.")
        return None

    print(f"[V2 Layer C] Clustering scenario: {scenario_key}")
    responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
    if not responses:
        print(f"  ! No Naren responses matched {scenario_key} -- no rubric.")
        storage.set_rubric_status(conn, scenario_key, STATUS_INSUFFICIENT)
        return None
    if len(responses) < 2:
        print(f"  ! Fewer than 2 responses -- will fall back to V1 Gemma approach.")
        return {"kind": "fallback", "info": info, "responses": responses}

    all_clauses, clause_positions, clause_calls = build_clause_pool(responses)

    if len(all_clauses) < 6:
        print(f"  ! Too few clauses ({len(all_clauses)}) -- will fall back to V1.")
        return {"kind": "fallback", "info": info, "responses": responses}

    scenario_calls = len({r["call_filename"] for r in responses})
    vecs = embedder.embed_document_matrix(all_clauses)

    n_before = len(all_clauses)
    all_clauses, vecs, clause_positions, clause_calls, relevance_by_clause = _relevance_filter(
        all_clauses, vecs, clause_positions, clause_calls, info,
        tuning.milestone_relevance_percentile,
    )
    print(f"  Relevance filter (>{tuning.milestone_relevance_percentile}th pct): "
          f"{n_before} -> {len(all_clauses)} clause(s) over {scenario_calls} call(s).")
    if len(all_clauses) < 6:
        print(f"  ! Too few relevant clauses -- will fall back to V1.")
        return {"kind": "fallback", "info": info, "responses": responses}

    # min_cluster_size=2 was the bug behind the 95-milestone rubrics: with no
    # provenance, two adjacent near-identical clauses of ONE response in ONE
    # call qualified as a "recurring strategic move".
    min_cluster_size = cluster_evidence.milestone_min_cluster_size(
        len(all_clauses), tuning.min_cluster_size_fraction,
        tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
    )
    labels = _cluster_milestones(vecs, min_cluster_size, tuning.umap_n_components)

    clusters: dict[int, dict] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        if label not in clusters:
            clusters[label] = {"clauses": [], "positions": [], "calls": [], "vecs": []}
        clusters[label]["clauses"].append(all_clauses[i])
        clusters[label]["positions"].append(clause_positions[i])
        clusters[label]["calls"].append(clause_calls[i])
        clusters[label]["vecs"].append(vecs[i])

    if not clusters:
        print(f"  ! HDBSCAN found no clusters -- will fall back to V1.")
        return {"kind": "fallback", "info": info, "responses": responses}

    candidates = [
        {
            "cluster_id": label,
            "clauses": data["clauses"],
            "vecs": data["vecs"],
            "support_calls": len(set(data["calls"])),
            "median_position": float(np.median(data["positions"])),
            "position_variance": float(np.var(data["positions"])),
            "relevance_mean": float(np.mean(
                [relevance_by_clause[c] for c in data["clauses"]]
            )),
        }
        for label, data in clusters.items()
    ]

    # "Recurring" finally means something: a milestone must appear across a
    # share of THIS scenario's calls. Self-scaling, so a 200-call scenario
    # clears a proportionally higher bar than a 6-call one and cannot
    # accumulate milestones merely by being large.
    required = cluster_evidence.required_milestone_support(
        scenario_calls, tuning.min_milestone_call_fraction,
        tuning.min_milestone_calls_floor,
    )
    surviving = [c for c in candidates if c["support_calls"] >= required]
    print(f"  Call-support gate (>= {required} of {scenario_calls} calls): "
          f"{len(candidates)} -> {len(surviving)} milestone(s).")

    if not surviving:
        print(f"  ! No milestone recurs in >= {required} call(s) -- will fall back to V1.")
        return {"kind": "fallback", "info": info, "responses": responses}

    # Backstop, not the mechanism. If this binds, the support floor above is
    # miscalibrated -- say so loudly rather than quietly truncating.
    if len(surviving) > tuning.milestone_hard_cap:
        print(f"  !! HARD CAP BOUND on {scenario_key}: {len(surviving)} milestones "
              f"exceed the cap of {tuning.milestone_hard_cap}. Ranking by "
              f"distinct-call support and truncating. Recalibrate "
              f"min_milestone_call_fraction -- the cap is not meant to fire.")
        surviving.sort(key=lambda c: (-c["support_calls"], -c["relevance_mean"]))
        surviving = surviving[:tuning.milestone_hard_cap]

    ordered = sorted(surviving, key=lambda x: x["median_position"])

    for cand in ordered:
        if len(sink_centroids):
            centroid = cluster_evidence.milestone_cluster_centroid(np.stack(cand["vecs"]))
            sink_idx, sim = cluster_evidence.nearest_sink_index(centroid, sink_centroids)
            cand["sink_similarity"] = sim
            cand["nearest_sink"] = sink_keys[sink_idx]
        else:
            cand["sink_similarity"] = None
            cand["nearest_sink"] = None

    return {"kind": "clustered", "info": info, "responses": responses, "candidates": ordered}


def _judge_flagged_milestones(flagged: list[dict], config: Config) -> dict[str, dict]:
    """Batched Gemma judge for review-flagged milestone candidates. Mirrors Layer
    A's NEEDS_REVIEW -> PROMPT_LAYER_A_V2_TRIAGE precedent: a flag is not a
    dangling field, it is resolved with a Gemma call in the same run. Batched
    (up to _TRIAGE_BATCH_SIZE per call) because flagged candidates are sparse
    (~5% of clusters, measured) and scattered thinly across scenarios.

    Zero DB writes -- mirrors Layer A's "no DB calls inside the Gemma loop"
    rule. Verdicts are held in memory and applied by the caller in Pass 2.
    """
    verdicts: dict[str, dict] = {}
    for i in range(0, len(flagged), _TRIAGE_BATCH_SIZE):
        chunk = flagged[i:i + _TRIAGE_BATCH_SIZE]
        items_block = "\n\n".join(
            f"- id: {item['id']}\n"
            f"  SCENARIO: {item['scenario_key']} ({item['business_description']})\n"
            f"  NEAREST SINK: {item['nearest_sink']}\n"
            f"  SAMPLE CLAUSES:\n" + "\n".join(f"    - {c}" for c in item["sample_clauses"])
            for item in chunk
        )
        raw = call_gemma(
            PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH.format(items_block=items_block),
            config.gemma_api_keys,
        )
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            if "id" in r:
                verdicts[r["id"]] = r
    return verdicts


def _sequence_milestones(
    scenario_key: str, responses: list[dict], ordered: list[dict], config: Config
) -> dict[int, str]:
    """Gemma call to reclassify high-position-variance milestones as
    'conditional' vs 'fixed'. Unchanged from before the describe-batching
    change -- already scoped to one call per scenario (all its high-variance
    milestones together), so there is nothing to batch further here.
    """
    high_var = [m for m in ordered if m["position_variance"] > 0.3]
    sequencing_map: dict[int, str] = {}
    if high_var and len(responses) >= 3:
        ms_text = "\n".join(
            f"- Cluster {m['cluster_id']} (variance={m['position_variance']:.2f}): "
            f"{'; '.join(m['clauses'][:2])}"
            for m in high_var
        )
        hv_result = call_gemma(
            PROMPT_LAYER_C_V2_ORDER.format(
                scenario_key=scenario_key,
                n_instances=len(responses),
                milestones_text=ms_text,
            ),
            config.gemma_api_keys,
        )
        for item in hv_result.get("milestone_sequencing", []):
            for m in high_var:
                if item["label"].lower() in " ".join(m["clauses"][:2]).lower():
                    sequencing_map[m["cluster_id"]] = item["sequencing_type"]
        time.sleep(_GEMMA_CALL_DELAY)
    return sequencing_map


def _describe_milestones_batch(items: list[dict], config: Config) -> dict[str, dict]:
    """Batched Gemma description for every surviving milestone candidate across
    ALL scenarios in this run. Replaces one PROMPT_LAYER_C_MILESTONE_DESCRIBE
    call per milestone (up to milestone_hard_cap per scenario, ~241-403 calls
    measured across a full run) with groups of _DESCRIBE_BATCH_SIZE, mirroring
    _judge_flagged_milestones's batching of the sparser triage step.

    Zero DB writes, same as the judge -- results held in memory and applied by
    the caller when it assembles each scenario's final rubric.
    """
    descriptions: dict[str, dict] = {}
    for i in range(0, len(items), _DESCRIBE_BATCH_SIZE):
        chunk = items[i:i + _DESCRIBE_BATCH_SIZE]
        items_block = "\n\n".join(
            f"- id: {item['id']}\n"
            f"  SCENARIO: {item['scenario_key']}\n"
            f"  MILESTONE: {item['order']} of {item['total']}\n"
            f"  Clauses grouped into this cluster:\n" +
            "\n".join(f"    - {c}" for c in item["clauses"])
            for item in chunk
        )
        raw = call_gemma(
            PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH.format(items_block=items_block),
            config.gemma_api_keys,
        )
        time.sleep(_GEMMA_CALL_DELAY)
        raw_list = raw if isinstance(raw, list) else raw.get("results", [])
        for r in raw_list:
            if "id" in r:
                descriptions[r["id"]] = r
    return descriptions


def _finish_rubric(
    scenario_key: str,
    info: dict,
    responses: list[dict],
    ordered: list[dict],
    sequencing_map: dict[int, str],
    descriptions: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
    run_id: str,
) -> None:
    """Pass 3 finish for a clustered scenario: assemble milestones from the
    already-computed batch descriptions, then the rubric-level Gemma call and
    the DB write.
    """
    milestones = []
    for order_idx, cluster in enumerate(ordered):
        desc = descriptions.get(f"{scenario_key}::{cluster['cluster_id']}", {})
        milestones.append({
            "order": order_idx + 1,
            "label": desc.get("label", f"Milestone {order_idx+1}"),
            "description": desc.get("description", ""),
            "detection_hint": desc.get("detection_hint", ""),
            "sequencing_type": sequencing_map.get(cluster["cluster_id"], "fixed"),
            "position_variance": cluster["position_variance"],
            # The evidence behind this milestone, stored so a reviewer can ask
            # "how do we know this recurs?" without re-running the pipeline.
            "support_calls": cluster["support_calls"],
            "support_clauses": len(cluster["clauses"]),
            "relevance_mean": cluster["relevance_mean"],
            "source_v": "v2_hdbscan",
        })

    sample_responses = responses[:_MAX_RUBRIC_RESPONSES]
    responses_text = "\n\n".join(
        f"[{r['call_filename']}]\n{r['response_text']}" for r in sample_responses
    )
    rubric_result = call_gemma(
        PROMPT_LAYER_C_V1.format(
            scenario_key=scenario_key,
            sub_topic=info["business_description"],
            primary_topic=info["primary_topic"],
            n_instances=len(sample_responses),
            responses_text=responses_text,
        ),
        config.gemma_api_keys,
    )
    time.sleep(_GEMMA_CALL_DELAY)

    conn = storage.reconnect_if_closed(conn)  # Gemma calls above can idle-drop the SSL connection
    rubric_id = storage.upsert_rubric(conn, {
        "scenario_id": info["scenario_id"],
        "scenario_key": scenario_key,
        "milestones": milestones,
        "soft_skill_rubric": rubric_result.get("soft_skill_rubric", {}),
        "anti_patterns": rubric_result.get("anti_patterns", []),
        "pipeline_version": "v2",
    })
    storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
    if run_id:
        checkpoint.mark_done(run_id, scenario_key, "layer_c")
    print(f"  v Rubric stored (scenario={scenario_key}, id={rubric_id}), "
          f"{len(milestones)} milestone(s).")


def run_layer_c_v2(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
    run_id: str = "",
) -> None:
    """V2: HDBSCAN clause clustering + median ordering + Gemma prose generation.

    Four passes, because both the review-flag threshold and the milestone
    description step are computed over the WHOLE run's population and can't be
    done scenario-by-scenario without paying for one Gemma call each:

      Pass 1 (per scenario, zero Gemma calls): cluster via UMAP+HDBSCAN, apply
        the call-support gate, compute each surviving milestone's sink_similarity.
      Batch judge (whole run, zero DB writes): p95-style threshold over every
        collected sink_similarity, then one PROMPT_LAYER_C_MILESTONE_TRIAGE_BATCH
        call per 5 flagged candidates. Verdicts held in memory.
      Pass 2 (per scenario): drop any milestone judged "mechanics", fall back to
        V1 if nothing survives, else compute the sequencing map.
      Batch describe (whole run, zero DB writes): one PROMPT_LAYER_C_MILESTONE_
        DESCRIBE_BATCH call per 5 surviving milestones across ALL scenarios.
      Pass 3 (per scenario): assemble milestones from the batch descriptions,
        make the rubric-level Gemma call, and write the rubric.

    Every scenario leaves this function with a non-null rubric_status, so a
    scenario count that exceeds the rubric count can no longer happen silently.
    """
    tuning = load_tuning().layer_c
    sink_keys, sink_centroids = _sink_centroids(scenario_map)

    pending: dict[str, dict] = {}
    for scenario_key, info in scenario_map.items():
        result = _pass1_cluster_scenario(
            scenario_key, info, tuning, sink_keys, sink_centroids, conn, run_id
        )
        if result is not None:
            pending[scenario_key] = result

    all_sims = [
        cand["sink_similarity"]
        for result in pending.values() if result["kind"] == "clustered"
        for cand in result["candidates"] if cand["sink_similarity"] is not None
    ]

    flagged: list[dict] = []
    if all_sims:
        threshold = cluster_evidence.review_flag_threshold(
            all_sims, tuning.milestone_sink_similarity_percentile
        )
        print(f"[V2 Layer C] Review-flag threshold (p{tuning.milestone_sink_similarity_percentile} "
              f"over {len(all_sims)} milestone candidate(s)): {threshold:.3f}")
        for scenario_key, result in pending.items():
            if result["kind"] != "clustered":
                continue
            for cand in result["candidates"]:
                if cand["sink_similarity"] is not None and cand["sink_similarity"] >= threshold:
                    flagged.append({
                        "id": f"{scenario_key}::{cand['cluster_id']}",
                        "scenario_key": scenario_key,
                        "business_description": result["info"].get("business_description", ""),
                        "nearest_sink": cand["nearest_sink"],
                        "sample_clauses": cand["clauses"][:5],
                    })

    verdicts = _judge_flagged_milestones(flagged, config)
    if flagged:
        n_calls = math.ceil(len(flagged) / _TRIAGE_BATCH_SIZE)
        print(f"[V2 Layer C] {len(flagged)} milestone candidate(s) flagged for review "
              f"-- batched into {n_calls} Gemma call(s).")

    # Pass 2: resolve fallback vs kept per scenario, and compute each kept
    # scenario's sequencing map. Zero milestone-description Gemma calls yet --
    # those are batched globally below, across every scenario at once.
    to_finish: dict[str, dict] = {}
    for scenario_key, result in pending.items():
        conn = storage.reconnect_if_closed(conn)

        if result["kind"] == "fallback":
            _fallback_v1(scenario_key, result["info"], result["responses"], config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            if run_id:
                checkpoint.mark_done(run_id, scenario_key, "layer_c")
            continue

        kept = []
        for cand in result["candidates"]:
            verdict = verdicts.get(f"{scenario_key}::{cand['cluster_id']}")
            if verdict and verdict.get("verdict") == "mechanics":
                print(f"  ! Gemma judge dropped milestone cluster {cand['cluster_id']} "
                      f"in {scenario_key} as mechanics: {verdict.get('reason', '')}")
                continue
            kept.append(cand)

        if not kept:
            print(f"  ! Every milestone candidate for {scenario_key} was judged "
                  f"mechanics -- falling back to V1.")
            _fallback_v1(scenario_key, result["info"], result["responses"], config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            if run_id:
                checkpoint.mark_done(run_id, scenario_key, "layer_c")
            continue

        sequencing_map = _sequence_milestones(scenario_key, result["responses"], kept, config)
        to_finish[scenario_key] = {
            "info": result["info"],
            "responses": result["responses"],
            "ordered": kept,
            "sequencing_map": sequencing_map,
        }

    # Batch judge (whole run): describe every surviving milestone across every
    # scenario in groups of _DESCRIBE_BATCH_SIZE, instead of one call each.
    describe_items = [
        {
            "id": f"{scenario_key}::{cluster['cluster_id']}",
            "scenario_key": scenario_key,
            "order": order_idx + 1,
            "total": len(state["ordered"]),
            "clauses": cluster["clauses"][:5],
        }
        for scenario_key, state in to_finish.items()
        for order_idx, cluster in enumerate(state["ordered"])
    ]
    descriptions = _describe_milestones_batch(describe_items, config)
    if describe_items:
        n_calls = math.ceil(len(describe_items) / _DESCRIBE_BATCH_SIZE)
        print(f"[V2 Layer C] {len(describe_items)} milestone(s) to describe "
              f"-- batched into {n_calls} Gemma call(s).")

    # Pass 3: rubric-level Gemma call + DB write, per scenario.
    for scenario_key, state in to_finish.items():
        conn = storage.reconnect_if_closed(conn)
        _finish_rubric(
            scenario_key, state["info"], state["responses"], state["ordered"],
            state["sequencing_map"], descriptions, config, conn, run_id,
        )


def _fallback_v1(scenario_key, info, responses, config, conn, run_id=""):
    from v1.layer_c import run_layer_c
    run_layer_c({scenario_key: info}, config, conn, run_id)
