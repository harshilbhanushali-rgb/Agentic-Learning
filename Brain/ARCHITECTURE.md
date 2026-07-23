# Brain Pipeline Architecture

## Overview

The Brain pipeline transforms raw call transcripts into a structured knowledge base of
**scenario → trigger-response pairs → evaluation rubrics**. Two versions exist:
V1 (LLM-first, top-down) and V2 (cluster-first, bottom-up). V2 reuses V1's Layer B
entirely and falls back to V1's Layer C when there is too little data.

---

## V1 — Current Approach

### How it works

```
recordings/*.txt
      │
      ▼  parse_transcript()
  list[Turn]  (NAREN / CLIENT / JOVEO_OTHER)
      │
      ▼  Layer A  ──► Gemma sees ALL transcripts at once
  scenarios table  (scenario_key, sub_topic, keyphrases, …)
      │
      ▼  Layer B  ──► sliding window over turns, cosine sim to scenarios
  kb_pairs table + Pinecone (triggers / responses namespaces)
      │
      ▼  Layer C  ──► Gemma sees all Naren responses for a scenario
  rubrics table  (milestones, soft_skill_rubric, anti_patterns)
```

### Layer A — Top-down scenario identification

Gemma receives the full text of every transcript in one prompt and returns a JSON list
of distinct client-facing scenarios it observed.  
Produces: `scenario_key`, `primary_topic`, `sub_topic`, `keyphrases`, `soft_skills`, `bloom_level`.

**Strength:** holistic — Gemma can see patterns across calls.  
**Weakness:** single LLM call, so quality depends entirely on prompt quality and Gemma's
attention; small or unusual scenarios get folded into broader categories.

### Layer B — Pair extraction + scenario assignment

1. Slide a window over `Turn` objects. A CLIENT turn that passes `_is_substantive()` opens
   a window; all following substantive NAREN turns (until the next CLIENT) are collected
   as the response.
2. Each trigger is embedded and cosine-compared to scenario description vectors
   (`sub_topic + keyphrases`). Pairs above the threshold (0.30) get multi-assigned;
   everything else falls back to the call centroid's nearest scenario.

### Layer C — Rubric generation

Gemma receives all of Naren's responses for one scenario and produces:
- `milestones` — ordered communicative moves seen in ≥2 responses
- `soft_skill_rubric` — observable excellent vs failing behaviours
- `anti_patterns` — failure modes (tagged `[inferred, unverified]`)

**Weakness:** ordering and number of milestones are entirely LLM-decided; no statistical
anchor from actual response structure.

---

## V2 — Planned Improvement

### What changes

```
recordings/*.txt
      │
      ▼  parse_transcript()  (unchanged)
  list[Turn]
      │
      ▼  Layer A V2  ──► segment CLIENT turns into clauses
                     ──► embed all clauses
                     ──► BERTopic (UMAP + HDBSCAN) clusters them
                     ──► Gemma labels each cluster (small, focused prompt)
  scenarios table  (same schema, bottom-up keys)
      │
      ▼  Layer B  (identical to V1 — shared code)
  kb_pairs table + Pinecone
      │
      ▼  Layer C V2  ──► segment Naren responses into clauses
                     ──► embed + HDBSCAN → milestone clusters
                     ──► median clause position → ordering
                     ──► Gemma describes each milestone (one call per cluster)
                     ──► Gemma soft_skill_rubric + anti_patterns (same V1 prompt)
  rubrics table  (pipeline_version = 'v2', source_v = 'v2_hdbscan')
```

### Why each layer improves

| | V1 | V2 |
|---|---|---|
| **Layer A** | One prompt, all transcripts, LLM decides categories | Data clusters first; Gemma only labels what the embeddings found |
| **Layer A granularity** | 5–10 coarse scenarios | One scenario per dense cluster; rare edge-cases surface naturally |
| **Layer C milestone order** | LLM guesses order | Median position of clause clusters across all instances |
| **Layer C sequencing** | `fixed` for everything | High-variance clusters get `conditional` tag via a second Gemma call |
| **Fallback** | — | If <2 responses or <6 clauses, falls back to V1 Layer C |

---

## Extracted Fields — What Each One Does

### `scenarios` table

| Field | Produced by | Used by |
|---|---|---|
| `scenario_key` | Layer A (Gemma) | Checkpoint key in SQLite; FK in `kb_pairs`; Pinecone vector metadata; Layer C query; scenario_map dict key |
| `primary_topic` | Layer A (Gemma) | Layer C prompt context (provides Gemma with the high-level category) |
| `sub_topic` | Layer A (Gemma) | `_build_scenario_vecs()` — concatenated with keyphrases before embedding to form the scenario comparison vector |
| `keyphrases` | Layer A (Gemma) | `_build_scenario_vecs()` — appended to sub_topic string; also stored for GIN-index text search |
| `soft_skills` | Layer A (Gemma) | Stored only; feeds display layer and Layer C rubric framing |
| `bloom_level` | Layer A (Gemma) | Stored only; metadata for scenario cognitive complexity |

### `calls` table

| Field | Produced by | Used by |
|---|---|---|
| `call_id` | `upsert_call()` | FK in `kb_pairs`; uniqueness anchor for (call_id, turn_index) |
| `filename` | transcript stem | `get_naren_responses_for_scenario()` returns it as `call_filename` so Layer C can label which call each response came from |

### `kb_pairs` table

| Field | Produced by | Used by |
|---|---|---|
| `pair_id` | Postgres SERIAL | Pinecone vector IDs (`trigger_<pair_id>`, `response_<pair_id>`) |
| `call_id` | `upsert_call()` | Joins to `calls.filename` in Layer C; uniqueness constraint with `turn_index` |
| `scenario_id` | `assign_scenarios()` | FK to `scenarios`; stored but queries use `scenario_key` |
| `scenario_key` | `assign_scenarios()` best match | `get_naren_responses_for_scenario()` WHERE clause; Pinecone metadata filter in `query_triggers()` |
| `scenario_keys` | `assign_scenarios()` multi-match | All scenarios this pair matched ≥0.30; stored for future multi-label analysis |
| `turn_index` | `extract_pairs()` | (call_id, turn_index) unique index — prevents duplicate inserts on re-runs |
| `trigger_text` | `extract_pairs()` | Embedded as a query vector → Pinecone `triggers` namespace; Pinecone metadata `text` snippet |
| `response_text` | `extract_pairs()` | Embedded as a passage vector → Pinecone `responses` namespace; Layer C collects these per scenario |
| `benchmark_response` | — (reserved) | Not yet populated; intended for a gold-standard answer per pair |

### `rubrics` table

| Field | Produced by | Used by |
|---|---|---|
| `milestones` | Layer C Gemma (V1) / HDBSCAN + Gemma (V2) | Evaluation rubric; each milestone has `order`, `label`, `description`, `detection_hint`, `sequencing_type` |
| `soft_skill_rubric` | Layer C Gemma | `excellent_execution` and `failing_execution` observable behaviours |
| `anti_patterns` | Layer C Gemma | Failure modes with `[inferred]` prefix so consumers know they are not directly observed |
| `pipeline_version` | hardcoded `"v1"` / `"v2"` | Lets downstream consumers know which extraction method produced the rubric |

### Pinecone vector metadata

Each vector (in `triggers` or `responses` namespace) carries:

| Metadata key | Source field | Used by |
|---|---|---|
| `pair_id` | `kb_pairs.pair_id` | Link back to Postgres row |
| `call_id` | `kb_pairs.call_id` | Provenance / filtering |
| `scenario_key` | `kb_pairs.scenario_key` | `query_triggers()` metadata filter |
| `turn_index` | `kb_pairs.turn_index` | Ordering within a call |
| `text` | `trigger_text` / `response_text` (truncated 500 chars) | Preview without a Postgres round-trip |

---

## Function Map

### `preprocessing/transcript_parser.py`

| Function | Input → Output | Role |
|---|---|---|
| `_classify()` | speaker name string → `SpeakerRole` | Maps raw speaker token to NAREN / JOVEO_OTHER / CLIENT; config-driven via `JOVEO_SPEAKER_NAMES` env var |
| `parse_transcript()` | .txt path → `list[Turn]` | Splits on blank lines, assigns roles; `Turn.role` is the gate for all downstream speaker-based logic |

### `preprocessing/segmenter.py`

| Function | Input → Output | Role |
|---|---|---|
| `segment_into_clauses()` | utterance text → `list[str]` | spaCy sentence splitting; output feeds V2 Layer A (CLIENT clauses for BERTopic) and V2 Layer C (Naren response clauses for HDBSCAN) |

### `preprocessing/embedder.py`

| Function | Input → Output | Role |
|---|---|---|
| `embed_query()` | `list[str]` → `list[list[float]]` | Pinecone `llama-text-embed-v2`, `input_type="query"` — used for trigger texts and scenario matching |
| `embed_document()` | `list[str]` → `list[list[float]]` | Same model, `input_type="passage"` — used for response texts and scenario description vectors |

### `v1/layer_a.py`

| Function | Input → Output | Role |
|---|---|---|
| `identify_scenarios()` | full transcript text → `list[dict]` | Single Gemma call; returns raw scenario list with no DB side-effects — safe to call before closing the Postgres connection |
| `store_scenarios()` | raw scenario list → `scenario_map` dict | Upserts each scenario to DB; builds the `{scenario_key: {scenario_id, keyphrases, sub_topic, primary_topic}}` dict that Layer B and Layer C use |
| `run_layer_a()` | text + conn → `scenario_map` | Convenience wrapper combining the two; use split functions when connection lifecycle matters (pipeline.py uses them separately) |

### `v2/layer_a.py`

| Function | Input → Output | Role |
|---|---|---|
| `run_layer_a_v2()` | `list[Turn]` → `scenario_map` dict | Segments CLIENT turns → embeds clauses → BERTopic clustering → Gemma labels each cluster → upserts to DB; returns same shape `scenario_map` as V1 so the rest of the pipeline is unchanged |

### `v1/layer_b.py` (also used by V2 via `v2/layer_b.py`)

| Function | Input → Output | Role |
|---|---|---|
| `_is_substantive()` | text → bool | spaCy stoplist filter; requires ≥5 alphabetic non-stop tokens — gates which CLIENT turns become triggers and which NAREN turns count as a response |
| `_build_scenario_vecs()` | `scenario_map` → `(keys, vecs)` | Embeds `sub_topic + keyphrases` as document vectors; forms the scenario matrix for cosine similarity in `assign_scenarios()` |
| `extract_pairs()` | `list[Turn]`, `call_id` → `list[dict]` | Sliding window: substantive CLIENT turn opens a window, all following substantive NAREN turns (until next CLIENT) close it; one pair per window |
| `assign_scenarios()` | pairs + scenario_map → trigger_vecs | Stage 1: cosine sim ≥ 0.30 → multi-assign; Stage 2: centroid fallback for unmatched; populates `scenario_key`, `scenario_id`, `scenario_keys` on each pair dict; returns trigger vecs so `embed_and_store_pairs()` can reuse them without re-embedding |
| `embed_and_store_pairs()` | pairs + conn → `list[pair_id]` | Inserts to Postgres; embeds triggers (query) and responses (passage); upserts both to Pinecone; attaches `pair_id`, `trigger_vec`, `response_vec` to each pair dict |

### `v1/layer_c.py`

| Function | Input → Output | Role |
|---|---|---|
| `run_layer_c()` | `scenario_map` + conn → (side effects) | Per scenario: fetches Naren responses from `kb_pairs`, builds a single Gemma prompt, parses milestones + soft_skill_rubric + anti_patterns, upserts rubric |

### `v2/layer_c.py`

| Function | Input → Output | Role |
|---|---|---|
| `run_layer_c_v2()` | `scenario_map` + conn → (side effects) | Per scenario: segments all Naren responses into clauses → embeds → HDBSCAN clusters → median position ordering → one Gemma call per milestone cluster for label/description/detection_hint → one Gemma call for soft_skill_rubric + anti_patterns; falls back to V1 if <2 responses or <6 clauses |
| `_fallback_v1()` | scenario_key + info + responses → (side effects) | Delegates to `v1.layer_c.run_layer_c` when V2 has insufficient data |

### `shared/storage.py`

| Function | Input → Output | Role |
|---|---|---|
| `get_connection()` | database_url → conn | TCP keepalive postgres connection (idle=30s, interval=10s, count=5); caches URL for `reconnect_if_closed()` |
| `reconnect_if_closed()` | conn → conn | Probes with `SELECT 1`; returns fresh connection if dead — used after long Gemma calls that can idle-drop the SSL connection |
| `upsert_call()` | filename → call_id | Registers a transcript file; idempotent — safe to call on every run |
| `upsert_scenario()` | scenario dict → scenario_id | ON CONFLICT UPDATE — re-running updates keyphrases/sub_topic in place |
| `insert_kb_pair()` | pair dict → pair_id | ON CONFLICT DO NOTHING on (call_id, turn_index) — duplicate pairs from re-runs are silently skipped |
| `upsert_rubric()` | rubric dict → rubric_id | ON CONFLICT UPDATE — replacing a V1 rubric with a V2 one updates all JSONB fields |
| `get_scenarios()` | conn → `list[dict]` | Loads scenario_map from DB when Layer A checkpoint is already done |
| `get_naren_responses_for_scenario()` | scenario_key → `list[dict]` | JOIN kb_pairs + calls WHERE scenario_key; returns `{pair_id, response_text, call_filename}` — Layer C's primary data source |

### `shared/pinecone_store.py`

| Function | Input → Output | Role |
|---|---|---|
| `init_index()` | api_key, index_name → (side effect) | Creates the Pinecone serverless index (2048 dims, cosine, AWS us-east-1) if it does not exist |
| `upsert_pairs()` | pairs list → (side effect) | Writes trigger vectors to `triggers` namespace and response vectors to `responses` namespace; batches in groups of 100 |
| `query_triggers()` | query_vec → matches | Top-k nearest triggers with optional `scenario_key` metadata filter; the runtime query path for the call simulator |

### `shared/gemma.py`

| Function | Input → Output | Role |
|---|---|---|
| `call_gemma()` | prompt → parsed JSON | Calls Gemma 4 31B via Google AI Studio; exponential backoff retries (max 5) on 429/500/503/504/internal/deadline errors; 3-min HTTP timeout |

### `v1/pipeline.py`

| Function | Input → Output | Role |
|---|---|---|
| `run_v1()` | recordings_dir + config + conn + run_id → (side effect) | Top-level orchestrator: parse all transcripts → Layer A → Layer B (per file, checkpointed) → Layer C |
| `_load_scenario_map()` | conn → `scenario_map` | DB-only load used when Layer A is already checkpointed; skips Gemma entirely |

### `v2/pipeline.py`

| Function | Input → Output | Role |
|---|---|---|
| `run_v2()` | recordings_dir + config + conn + run_id → (side effect) | Same structure as V1 but Layer A calls `run_layer_a_v2()` and Layer C calls `run_layer_c_v2()`; Layer B is shared |

---

## Data Flow Summary

```
.txt file
  └─ parse_transcript()
       ├─ Turn.role = CLIENT → [Layer A] scenario identification input
       │                       [Layer B] trigger candidate (if substantive)
       └─ Turn.role = NAREN  → [Layer B] response candidate (if substantive)

Layer A
  └─ scenario_map {scenario_key → {scenario_id, sub_topic, keyphrases, primary_topic}}
       └─ [Layer B] _build_scenario_vecs() → cosine sim matrix
       └─ [Layer C] prompt context (sub_topic, primary_topic, n_instances)

Layer B
  └─ kb_pairs row {trigger_text, response_text, scenario_key, scenario_keys, turn_index}
       └─ Pinecone triggers/{trigger_<pair_id>}  ← runtime similarity search
       └─ Pinecone responses/{response_<pair_id>}
       └─ [Layer C] get_naren_responses_for_scenario() input

Layer C
  └─ rubrics row {milestones[], soft_skill_rubric{}, anti_patterns[]}
       └─ evaluation rubric for the call simulator UI
```
