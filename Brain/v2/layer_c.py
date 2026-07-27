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
from shared import storage, checkpoint

_GEMMA_CALL_DELAY = 5  # seconds between calls -- free-tier quota is 16000 input tokens/minute
_MAX_RUBRIC_RESPONSES = 12  # cap responses fed into one rubric prompt -- some scenarios match 50+ instances


def run_layer_c_v2(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
    run_id: str = "",
) -> None:
    """V2: HDBSCAN clause clustering + median ordering + Gemma prose generation."""
    from hdbscan import HDBSCAN

    for scenario_key, info in scenario_map.items():
        if run_id and checkpoint.is_done(run_id, scenario_key, "layer_c"):
            print(f"[V2 Layer C] {scenario_key} already done — skipping.")
            continue
        print(f"[V2 Layer C] Processing scenario: {scenario_key}")
        responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
        if len(responses) < 2:
            print(f"  ! Fewer than 2 responses -- falling back to V1 Gemma approach.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            continue

        all_clauses: list[str] = []
        clause_positions: list[float] = []
        for resp in responses:
            clauses = segmenter.segment_into_clauses(resp["response_text"])
            n = max(len(clauses) - 1, 1)
            for pos_idx, clause in enumerate(clauses):
                all_clauses.append(clause)
                clause_positions.append(pos_idx / n)

        if len(all_clauses) < 6:
            print(f"  ! Too few clauses ({len(all_clauses)}) -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            continue

        vecs = np.array(embedder.embed_document(all_clauses))
        clusterer = HDBSCAN(min_cluster_size=2, metric="euclidean", cluster_selection_method="eom")
        labels = clusterer.fit_predict(vecs)

        clusters: dict[int, dict] = {}
        for i, label in enumerate(labels):
            if label == -1:
                continue
            if label not in clusters:
                clusters[label] = {"clauses": [], "positions": []}
            clusters[label]["clauses"].append(all_clauses[i])
            clusters[label]["positions"].append(clause_positions[i])

        if not clusters:
            print(f"  ! HDBSCAN found no clusters -- falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn, run_id)
            continue

        ordered = sorted([
            {
                "cluster_id": label,
                "clauses": data["clauses"],
                "median_position": float(np.median(data["positions"])),
                "position_variance": float(np.var(data["positions"])),
            }
            for label, data in clusters.items()
        ], key=lambda x: x["median_position"])

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
        if run_id:
            checkpoint.mark_done(run_id, scenario_key, "layer_c")
        print(f"  v Rubric stored (id={rubric_id}), {len(milestones)} milestone(s).")


def _fallback_v1(scenario_key, info, responses, config, conn, run_id=""):
    from v1.layer_c import run_layer_c
    run_layer_c({scenario_key: info}, config, conn, run_id)
