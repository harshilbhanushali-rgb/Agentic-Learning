from __future__ import annotations
import numpy as np
import psycopg
from config import Config
from preprocessing import segmenter, embedder
from preprocessing.transcript_parser import Turn, SpeakerRole
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_A_V2_LABEL
from shared import storage


def run_layer_a_v2(
    all_turns: list[Turn],
    config: Config,
    conn: psycopg.Connection,
) -> dict[str, dict]:
    """V2 scenario identification via BERTopic + Gemma labelling."""
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    client_clauses: list[str] = []
    for turn in all_turns:
        if turn.role == SpeakerRole.CLIENT:
            client_clauses.extend(segmenter.segment_into_clauses(turn.text))

    if not client_clauses:
        raise ValueError("No CLIENT clauses found -- check transcript parsing.")

    print(f"[V2 Layer A] Segmented {len(client_clauses)} CLIENT clauses. Embedding...")
    vecs = embedder.embed_query(client_clauses)
    embeddings_matrix = np.array(vecs)

    n = len(client_clauses)
    min_cluster_size = max(3, n // 10)
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
    topics, _ = topic_model.fit_transform(client_clauses, embeddings=embeddings_matrix)

    topic_info = topic_model.get_topic_info()
    valid_topics = topic_info[topic_info["Topic"] != -1]
    print(f"[V2 Layer A] BERTopic found {len(valid_topics)} cluster(s). Labelling with Gemma...")

    scenario_map: dict[str, dict] = {}
    for _, row in valid_topics.iterrows():
        topic_id = row["Topic"]
        keywords = ", ".join(w for w, _ in topic_model.get_topic(topic_id)[:10])
        cluster_docs = [client_clauses[i] for i, t in enumerate(topics) if t == topic_id]
        representative = "\n".join(f"- {d}" for d in cluster_docs[:5])

        prompt = PROMPT_LAYER_A_V2_LABEL.format(
            cluster_id=topic_id,
            keywords=keywords,
            representative_utterances=representative,
        )
        result = call_gemma(prompt, config.gemma_api_key)

        base_key = result["scenario_key"]
        key = base_key
        suffix = 1
        while key in scenario_map:
            key = f"{base_key}_{suffix}"
            suffix += 1
        result["scenario_key"] = key

        scenario_id = storage.upsert_scenario(conn, result)
        scenario_map[key] = {
            "scenario_id": scenario_id,
            "keyphrases": result.get("keyphrases", []),
            "sub_topic": result.get("sub_topic", ""),
            "primary_topic": result.get("primary_topic", ""),
        }
        print(f"  v cluster {topic_id} -> {key} (scenario_id={scenario_id})")

    return scenario_map
