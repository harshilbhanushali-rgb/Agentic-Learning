from __future__ import annotations
import time
import numpy as np
import psycopg
from config import Config
from preprocessing import segmenter, embedder
from shared.gemma import call_gemma
from shared.prompts import (
    PROMPT_LAYER_C_MILESTONE_DESCRIBE,
    PROMPT_LAYER_C_V2_ORDER,
    PROMPT_LAYER_C_V1,
)
from shared import storage, checkpoint, cluster_evidence, scenario_vectors
from shared.tuning import load_tuning

_GEMMA_CALL_DELAY = 5  # seconds between calls -- free-tier quota is 16000 input tokens/minute
_MAX_RUBRIC_RESPONSES = 12  # cap responses fed into one rubric prompt -- some scenarios match 50+ instances

STATUS_GENERATED = "rubric_generated"
STATUS_NOT_COACHABLE = "skipped_not_coachable"
STATUS_INSUFFICIENT = "skipped_insufficient_responses"
STATUS_FAILED = "failed"


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


def run_layer_c_v2(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
    run_id: str = "",
) -> None:
    """V2: HDBSCAN clause clustering + median ordering + Gemma prose generation.

    Every scenario leaves this function with a non-null rubric_status, so a
    scenario count that exceeds the rubric count can no longer happen silently.
    """
    from hdbscan import HDBSCAN

    tuning = load_tuning().layer_c

    for scenario_key, info in scenario_map.items():
        if not info.get("is_coachable", True):
            print(f"[V2 Layer C] {scenario_key} is a {info.get('cluster_kind')} sink "
                  f"-- no rubric.")
            storage.set_rubric_status(conn, scenario_key, STATUS_NOT_COACHABLE)
            continue
        if run_id and checkpoint.is_done(run_id, scenario_key, "layer_c"):
            print(f"[V2 Layer C] {scenario_key} already done — skipping.")
            continue
        print(f"[V2 Layer C] Processing scenario: {scenario_key}")
        responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
        if not responses:
            print(f"  ! No Naren responses matched {scenario_key} -- no rubric.")
            storage.set_rubric_status(conn, scenario_key, STATUS_INSUFFICIENT)
            continue
        if len(responses) < 2:
            print(f"  ! Fewer than 2 responses -- falling back to V1 Gemma approach.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            continue

        # clause_calls keeps the source call for every clause. Without it there is
        # no way to tell a move repeated across many calls from two adjacent
        # clauses of a single response -- and min_cluster_size=2 accepts both.
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

        if len(all_clauses) < 6:
            print(f"  ! Too few clauses ({len(all_clauses)}) -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            continue

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
            print(f"  ! Too few relevant clauses -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            continue

        # min_cluster_size=2 was the bug behind the 95-milestone rubrics: with no
        # provenance, two adjacent near-identical clauses of ONE response in ONE
        # call qualified as a "recurring strategic move".
        min_cluster_size = cluster_evidence.milestone_min_cluster_size(
            len(all_clauses), tuning.min_cluster_size_fraction,
            tuning.min_cluster_size_floor, tuning.min_cluster_size_ceiling,
        )
        clusterer = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                            cluster_selection_method="eom")
        labels = clusterer.fit_predict(vecs)

        clusters: dict[int, dict] = {}
        for i, label in enumerate(labels):
            if label == -1:
                continue
            if label not in clusters:
                clusters[label] = {"clauses": [], "positions": [], "calls": []}
            clusters[label]["clauses"].append(all_clauses[i])
            clusters[label]["positions"].append(clause_positions[i])
            clusters[label]["calls"].append(clause_calls[i])

        if not clusters:
            print(f"  ! HDBSCAN found no clusters -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            continue

        candidates = [
            {
                "cluster_id": label,
                "clauses": data["clauses"],
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
            print(f"  ! No milestone recurs in >= {required} call(s) -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            storage.set_rubric_status(conn, scenario_key, STATUS_GENERATED)
            continue

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

        milestones = []
        for order_idx, cluster in enumerate(ordered):
            clauses_text = "\n".join(f"  - {c}" for c in cluster["clauses"][:5])
            desc = call_gemma(
                PROMPT_LAYER_C_MILESTONE_DESCRIBE.format(
                    scenario_key=scenario_key,
                    order=order_idx + 1,
                    total=len(ordered),
                    cluster_clauses=clauses_text,
                ),
                config.gemma_api_keys,
            )
            time.sleep(_GEMMA_CALL_DELAY)
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
                sub_topic=info["sub_topic"],
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
        print(f"  v Rubric stored (id={rubric_id}), {len(milestones)} milestone(s).")


def _fallback_v1(scenario_key, info, responses, config, conn, run_id=""):
    from v1.layer_c import run_layer_c
    run_layer_c({scenario_key: info}, config, conn, run_id)
