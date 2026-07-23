# Naren's Brain — Implementation Plan (LLM-Hybrid Version)
### Layers A, B, C — Full Technical Specification
**Scope:** Layers A, B, C only — pure content extraction from Naren's call transcripts. Layer D, product knowledge ingestion, and Knowledge Gap detection are explicitly deferred (see Section 8).

**Core principle:** Statistics finds the truth, the LLM finds the words. Nothing is asked to invent structure — the LLM only describes, labels, or classifies something that classical methods already discovered and handed to it as grounding context. Where corpus is too thin for classical methods to be reliable, Gemma steps in directly but the statistical approach is fully specced for when the corpus grows.

**Current corpus:** 5 calls. v1 uses Gemma for everything where clustering would normally run. The full statistical pipeline is specced below — see Section 7 for what to build now vs. later.

**Execution model:** Naren's brain is built in **one shot** — a single script, start to finish, populating Layers A, B, C. No DAG, no orchestration.

---

## 0. Shared Preprocessing (feeds all layers)

| Step | Tool | Notes |
|---|---|---|
| Sentence/clause segmentation | `spaCy` (`en_core_web_trf` or `_lg`) | Splits each speaker turn into clean single-idea clauses so embeddings are precise, not averaged across multiple signals |
| Embeddings | `BGE-M3` (via `FlagEmbedding` or `sentence-transformers`) | MIT-licensed, self-hosted. Dense+sparse+multi-vector in one model. Supports asymmetric retrieval natively — query and document sides encoded differently |
| Speaker classification | Transcript name tags | Two buckets: **JOVEO** (Naren + any Joveo colleagues) and **CLIENT** (everyone else — one person or five, all CLIENT). Within JOVEO, identify Naren specifically by name tag |

**Input:** Full transcripts of all 5 calls — not just client utterances. Gemma needs full conversation flow to correctly identify scenarios and understand why Naren said what he said.

**Other Joveo speakers (non-Naren):** Never stored in any layer. Passed to Gemma as read-only context only. For Layer B response extraction: if a colleague interjects mid-Naren-response, skip that line and continue capturing Naren's subsequent turns until the next CLIENT utterance.

---

## 1. Layer A — Relational Metadata (Topics, Sub-topics, Soft Skills)

**Storage:** PostgreSQL

### What spaCy segmentation does here

A speaker turn is one continuous block of speech. spaCy breaks it into individual clauses so each unit carries one idea. Embedding a whole multi-signal turn averages the signals — you lose precision.

**Example:**
Raw client turn: *"We tried programmatic before through an agency and it didn't work. I'm not sure we have the budget either. And our team is pretty small so we'd need a lot of hand-holding."*

After spaCy — 3 clean clauses:
1. *"we tried programmatic before through an agency and it didn't work"*
2. *"I'm not sure we have the budget right now"*
3. *"our team is pretty small so we'd need a lot of hand-holding"*

Each embeds separately → 3 distinct vectors → 3 distinct scenario signals.

### Full Process (v1 and v2)

| # | Step | Tech | LLM? | v1 (5 calls) | v2 (30+ calls) — when to switch |
|---|---|---|---|---|---|
| 1 | Feed full transcripts | — | No | All 5 at once | All calls at once |
| 2 | Segment CLIENT utterances into clauses | spaCy | No | Same | Same |
| 3 | Identify distinct scenario clusters | See v1/v2 split below | — | **Gemma 4 31B** reads full transcripts, identifies all distinct scenarios, groups CLIENT utterances by scenario | **BERTopic** (UMAP + HDBSCAN + c-TF-IDF) — switch when corpus reaches 30+ calls with 10+ instances per scenario |
| 4 | Generate keyphrases per cluster | **Gemma 4 31B** — given raw utterances + full context | Yes | Same | Same — Gemma stays permanently for keyphrases regardless of corpus size |
| 5 | Write `Primary_Topic` / `Sub_Topic` | **Gemma 4 31B** — given raw utterances + keyphrases | Yes — low risk | Same | Same |
| 6 | Tag `Target_Soft_Skills` | **Gemma 4 31B** — classify against a fixed pre-defined soft-skill taxonomy | Yes — low/med risk | Same | Same |
| 7 | Tag `bloom_level` | **Gemma 4 31B** — classify against 6 Bloom levels with definitions in-prompt | Yes — med risk | Same | Same |

### v2 Statistical Approach — Step 3 (BERTopic)

When corpus grows to 30+ calls:
- **UMAP** reduces BGE-M3 embeddings from 1024 dims to ~5 dims for clustering
- **HDBSCAN** finds density-based clusters in reduced space — no need to pre-specify cluster count
- **c-TF-IDF** extracts raw keyword candidates per cluster for Gemma to refine into keyphrases
- Gemma still handles steps 4–7 — BERTopic only replaces the scenario identification in step 3

Why BERTopic at scale: with 5 calls Gemma can read everything and identify scenarios directly. At 100+ calls, dumping everything into one prompt breaks context limits and makes Gemma's job harder. Clustering first gives Gemma tight, grounded bundles of 8-10 utterances per scenario rather than hundreds at once.

### Cluster → Topic hierarchy

One cluster = one scenario = one Sub_Topic row. Multiple clusters can share the same Primary_Topic. In v1 Gemma identifies this hierarchy directly from full transcripts. In v2 HDBSCAN produces flat clusters and Gemma assigns the hierarchy during labelling.

### What keyphrases are used for

Keyphrases are a Layer A only concept — generated here, stored here, never used in gap analysis. Two future production uses:
1. **Runtime scenario detection** — mapping new client utterances to the right Layer C rubric at inference time
2. **Knowledge Oracle** — secondary index only; BGE-M3 vector similarity from Layer B is the primary mechanism

Generate and store now since Gemma is already being called per cluster — costs nothing extra.

---

## 2. Layer B — Dense Vector Store (Trigger→Response Pairs)

**Storage:** `pgvector` (co-located in same Postgres instance as Layer A)

> **Option (replaced):** Pinecone / Qdrant — unnecessary at this corpus size. pgvector handles up to ~10M vectors. Revisit only if corpus grows beyond that, which is unlikely.

### Asymmetric Embedding Approach

Trigger and response are embedded **separately** and stored as distinct vectors linked via metadata. Concatenating them into one vector dilutes both — a CSM searching with a client question would be matching a question-vector against question+answer-vectors, reducing precision. BGE-M3 supports asymmetric retrieval natively.

| Vector type | What gets embedded | Used for |
|---|---|---|
| **Trigger vector** | CLIENT utterance only | Knowledge Oracle query matching, scenario detection |
| **Response vector** | Naren's response only | Knowledge Oracle retrieval, Layer C milestone scoring |

The trigger vector stores metadata pointing to its paired response: `response_chunk_id`, `call_id`, `timestamp`, `topic_id`, `scenario_key`.

### Speaker Handling

| Speaker | Definition | Treatment |
|---|---|---|
| CLIENT | All non-Joveo speakers — one person or five, regardless of role | Utterances = triggers. Stored as trigger vectors. |
| NAREN | Joveo speaker identified by name tag | Consecutive turns after CLIENT utterance = response. Stored as response vectors. |
| Other Joveo | Any Joveo speaker that is not Naren | Skip during extraction. Pass to Gemma as context only. Never stored. |

### Process

| # | Step | Tech | LLM? |
|---|---|---|---|
| 1 | Extract trigger→response pairs via speaker name tags + turn order | Rule-based | No |
| 2 | Embed trigger (CLIENT utterance) separately | BGE-M3 — query/asymmetric mode | No |
| 3 | Embed response (Naren's turns) separately | BGE-M3 — document/asymmetric mode | No |
| 4 | Store both vectors with linking metadata (`topic_id`, `scenario_key`, `call_id`, `timestamp`, `response_chunk_id`) | pgvector | No |
| 5 | *(Optional)* Clean disfluencies in `benchmark_response` for display | **Gemma 4 31B** | Yes — optional, low priority |

### Knowledge Oracle

Pure Layer B vector similarity — no keyphrases involved:
1. CSM types a query mid-call
2. Query embedded with BGE-M3 (query/asymmetric mode)
3. Cosine similarity against trigger vectors
4. Matched trigger metadata points to paired response vector
5. Naren's benchmark response returned

---

## 3. Layer C — Evaluation & Gap Rubric Store (Milestones, Soft Skill Rubric, Anti-Patterns)

**Storage:** PostgreSQL JSONB

### Full Process (v1 and v2)

| # | Step | Tech | LLM? | v1 (5 calls) | v2 (30+ calls) — when to switch |
|---|---|---|---|---|---|
| 1 | Gather every Naren response instance per scenario across all calls | — | No | Same | Same |
| 2 | Identify recurring strategic milestones | See v1/v2 split below | — | **Gemma 4 31B** reads all instances of a scenario directly and identifies the recurring strategic moves | **HDBSCAN** clause clustering — switch when 5+ instances per scenario are available |
| 3 | Order milestones | See v1/v2 split below | — | **Gemma 4 31B** — given all instances, determine the order Naren consistently uses | Median position-in-response per cluster from real turn indices |
| 3b | Sanity-check ordering (v2 only) | **Gemma 4 31B** — triggered when low instance count or high position variance | Yes — low risk | N/A | Confirm fixed vs. conditional order; attach as `sequencing_rationale` |
| 4 | Write milestone description | **Gemma 4 31B** — given all real instances + context | Yes — low risk | Same | Same |
| 5 | Write `detection_hint` | **Gemma 4 31B** — what distinguishes a hit from a near-miss, grounded in real examples | Yes — low risk | Same | Same |
| 6 | Write `soft_skill_rubric.excellent_execution` | **Gemma 4 31B** — what's distinctive across Naren's real instances | Yes — med risk. Human skim recommended | Same | Same |
| 7 | Write `soft_skill_rubric.failing_execution` / `anti_patterns` | **Gemma 4 31B** — inferred, no real negative examples exist | Yes — higher risk. Label `"inferred, unverified"` | Same | Revisit with real non-Naren contrast data |

### v2 Statistical Approach — Steps 2 & 3 (HDBSCAN + Median)

When 5+ instances of a scenario are available:
- **Step 2:** Segment each Naren response into clauses, embed with BGE-M3. Cluster clauses across all instances of the same scenario using HDBSCAN — recurring clusters are candidate milestones.
- **Step 3:** Order milestones using **median position-in-response** per cluster, computed from real turn indices across all instances.

Why median over LLM for ordering at scale: an LLM asked to order milestones reasons about what makes logical sales sense, quietly overwriting Naren's real pattern with sales-textbook logic. Median position is a direct measurement of what he empirically and repeatedly does. Gemma only steps in (step 3b) where the measurement is unreliable — thin samples or high variance.

### Risk Tiering

| Risk | Steps | Why |
|---|---|---|
| Low | 4, 5 | LLM describes something it was literally shown. Every word traces to real transcript content. |
| Medium | 6 | Still grounded, but characterising why something works edges toward judgment. |
| Higher | 7 | No grounding exists — LLM's best guess at a failure mode it has never seen. Treat as draft, not fact. |

**Gap analysis note:** Gap analysis runs entirely on Layer C rubrics. Keyphrases, Layer B vectors, and Layer A metadata play no role in scoring a CSM's response — only milestones and the soft skill rubric matter here.

---

## 4. Gemma 4 31B — Model & API Config

**Primary:** Google AI Studio API

| Parameter | Value |
|---|---|
| Model | `gemma-4-31b` via Google AI Studio |
| API key | Google AI Studio API key |
| Output format | Force structured JSON matching Postgres JSONB schema directly — skip a separate parsing step |
| Context window | Large enough to pass full transcripts of multiple calls per call |
| Throughput | Low — one-shot batch run. Not real-time. Sequential API calls are sufficient. |
| Golden rule | Never call Gemma without real transcript content in the prompt. If nothing to ground it in (Layer C step 7), label output as inferred, not observed |

> **Option (alternative deployment):** Self-hosted Gemma 3 27B on local GPU.
> - Quantization: Q4_K_M (~14–18GB VRAM) — fits single 24GB GPU (RTX 3090/4090)
> - Serving: `vLLM` or `Ollama`
> - Use when: API costs become a concern at scale, or offline/airgapped environment required
> - Tradeoff: quantization reduces precision slightly vs. full API model; local setup overhead vs. API simplicity

---

## 5. Full Tech Stack Summary

| Layer / Process | Storage | Structure (non-LLM) | Prose / Judgment (LLM) |
|---|---|---|---|
| Shared prep | — | spaCy, BGE-M3 | — |
| A — Taxonomy | PostgreSQL | spaCy, BGE-M3; BERTopic (v2, 30+ calls) | Gemma 4 31B — scenario ID (v1), keyphrases, topic/subtopic, soft skills, Bloom level |
| B — Vectors | pgvector | BGE-M3 asymmetric (trigger + response separate), rule-based turn-order pairing | Gemma 4 31B — optional disfluency cleanup only |
| C — Rubrics | PostgreSQL JSONB | HDBSCAN clause clustering, median ordering (v2, 5+ instances per scenario) | Gemma 4 31B — milestone identification (v1), descriptions, detection_hint, soft skill rubric, anti-patterns |
| Execution | — | One-shot script — single run, no orchestration | — |

---

## 6. Runtime Scenario Classifier — Deferred

Maps new client utterances to the right Layer C rubric at inference time. Production concern only — not needed while building the brain.

> **Option v1 (when production comes):** Gemma zero-shot — compare new utterance against stored scenario descriptions and keyphrases from Layer A. Works with small corpus, slower.

> **Option v2 (when corpus grows):** Trained logistic regression / SVM on BGE-M3 cluster embeddings. Fast, cheap, deterministic. Clean swap — same interface, different backend.

---

## 7. What to Build Now vs. Later

### Build now (v1 — 5 calls)

| Component | Approach |
|---|---|
| Layer A — scenario identification | Gemma 4 31B reads full transcripts directly |
| Layer A — keyphrases, topics, soft skills, Bloom | Gemma 4 31B |
| Layer B — trigger/response pairing | Rule-based turn-order extraction |
| Layer B — asymmetric embeddings | BGE-M3, pgvector |
| Layer C — milestone identification | Gemma 4 31B reads all Naren instances per scenario directly |
| Layer C — milestone ordering | Gemma 4 31B |
| Layer C — rubric writing | Gemma 4 31B |
| Model | Gemma 4 31B via Google AI Studio API |

### Do not build yet — spec is written, build when corpus grows

| Component | Trigger to build | What replaces |
|---|---|---|
| BERTopic (Layer A, Step 3) | 30+ calls, 10+ instances per scenario | Gemma direct scenario identification |
| HDBSCAN clause clustering (Layer C, Step 2) | 5+ instances per scenario | Gemma direct milestone identification |
| Median milestone ordering (Layer C, Step 3) | 5+ instances per scenario | Gemma milestone ordering |
| Runtime scenario classifier | When Ego Trap pipeline is being built | N/A — new addition |
| Local Gemma deployment | When API costs become a concern | Google AI Studio API |

---

## 8. Explicitly Out of Scope (this document)

- **Layer D** (LearnerProfile Aggregator) — schema already defined; not built here
- **Runtime Ego Trap pipeline** (Steps 0–5 of gap detection) — sits on top of this foundation
- **Product knowledge ingestion** — adding `source_type = product_doc` to Layer B. Deferred until A/B/C solid
- **Knowledge Gap detection** — NLI cross-encoder fact-checking. Depends on product ingestion, deferred alongside it
- **Anti-pattern v2** — real contrastive failure examples from non-Naren calls to replace inferred anti-patterns
- **Outcome-weighted benchmarking** — shelved; whatever Naren does is the benchmark
- **Other CSM profile building** — V2 concern; may use DAG or cold start

---

*Naren's Brain — Implementation Plan v4 · June 2026 · Engineering · Internal*
