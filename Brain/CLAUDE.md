# Brain/ — Naren's Brain Pipeline

Separate Python project inside this repo. All commands run from `Brain/` with the venv active.

### Brain Commands

```bash
# Activate venv (from repo root)
.venv\Scripts\activate

# Install / re-install
uv pip install -e ".[dev]"

# First-time spaCy model (must run after install)
python -m spacy download en_core_web_lg

# Run tests (use root venv directly -- `uv run pytest` creates a new Brain/.venv)
..\.venv\Scripts\pytest tests/ -v

# Calibrate the scenario taxonomy -- no Gemma calls, no DB writes, read-only
python calibration/dry_run_layer_a.py --sweep                        # threshold grid (counts only)
python calibration/dry_run_layer_a.py --merge-detail 0.75,0.80,0.85  # what each merge threshold collapses
python calibration/dry_run_layer_a.py                                # full report + coverage distribution

# Calibrate Layer B matching + Layer C milestones -- also zero Gemma, zero DB/Pinecone
python calibration/dry_run_layer_bc.py --limit 30                    # fast smoke test
python calibration/dry_run_layer_bc.py                               # full corpus

# Run pipeline
python main.py

# Wipe Postgres + checkpoints before a clean re-run
python ops/clear_data.py

# Calibrate Layer D (Ego Trap gap analysis) -- zero Gemma, zero writes, zero Pinecone
python calibration/dry_run_ego_trap.py                    # pool split, cosine bands, benchmark diff
python calibration/dry_run_ego_trap.py --step0-gemma      # opt-in: 1 Gemma call/transcript, persisted
python calibration/dry_run_ego_trap.py --load artifacts/ego_trap_dry_run.json   # re-report, free

# Run Layer D. Requires clear_ego_trap_data.py first for a genuine re-run -- gap_events has
# no unique constraint and milestone_performance.attempts increments on conflict.
python ops/clear_ego_trap_data.py
python ops/run_ego_trap.py

# LAYER D REDESIGN (Brain/layer_d/, 2026-08-20) -- gap analysis against PLAYBOOKS.
# The C-stage gates have NOT run yet; do not trust production numbers before they do.
python calibration/layer_d_bands.py            # C0 bill only (zero spend); --spend embeds ~6.5k texts
python ops/run_layer_d.py --report-only        # zero spend: re-rank from stored move_events
python ops/run_layer_d.py --limit 5            # smoke; re-runs are SAFE (natural-key upserts)
python ops/clear_layer_d_data.py               # deliberate wipe only; NOT needed before re-runs
```

Long dry runs must be launched with `PYTHONUNBUFFERED=1` when redirecting to a log — otherwise stdout is block-buffered and the log sits at 0 bytes for minutes, which is indistinguishable from a hung process.

### Brain Stack

- **Python 3.11**, `uv` package manager, venv at `c:\PF\Joveo\CS-platform\.venv`
- **LLM:** `google-genai` → Gemma 4 31B via Google AI Studio (`GEMMA_API_KEY`)
- **Embeddings:** LOCAL `sentence-transformers` running `BAAI/bge-base-en-v1.5` (768 dims, `normalize_embeddings=True`), CUDA if available — see `preprocessing/embedder.py`. Not a hosted embedding API.
- **Vector store:** Pinecone, index `narens-brain` (768 dims, cosine), AWS us-east-1 — storage/retrieval only, it does no embedding
- **Embedding cache:** SQLite at `Brain/embed_cache.db`, float32, keyed `sha256(model|prefix|text)`
- **Sentence splitting:** spaCy `en_core_web_lg`
- **Relational DB:** PostgreSQL via `psycopg[binary]` — no vectors stored here, vectors in Pinecone only
- **Checkpointing:** SQLite at `Brain/checkpoints.db`
- **V2 clustering:** `bertopic` + `umap-learn` + `hdbscan`

### Brain Architecture

- `preprocessing/` — transcript parser → spaCy segmenter → Pinecone embedder
- `shared/` — `gemma.py`, `storage.py` (Postgres CRUD), `pinecone_store.py`, `checkpoint.py`, `prompts.py`
- `v1/` — Gemma-direct pipeline (Layer A: scenario ID, Layer B: pair extraction, Layer C: rubrics)
- `v2/` — BERTopic clustering for Layer A/C; Layer B re-exports v1
- `tuning.yaml` + `shared/tuning.py` — **every clustering/milestone threshold lives here**, not in code. Unknown or missing keys raise at load time, so a typo fails loudly instead of silently reverting to a default. Change values here; never hardcode a threshold in a layer.
- `shared/cluster_evidence.py` — pure, testable triage helpers (`support_stats`, `merge_by_similarity`, `triage`, `required_call_support`, `required_milestone_support`)
- `shared/scenario_vectors.py` — the one definition of "the scenario vector" (`business_description` + `keyphrases`), shared by Layer B matching and Layer C relevance filtering; also `primary_topic_text()`/`build_primary_topic_vecs()` (added 2026-07-30), the analogous vector for a `primary_topics` row (`description` + `keyphrases`) — a distinct embedded population from scenario vectors, not a re-use of them
- `shared/topic_grouping.py` (added 2026-07-30) — pure, Gemma-free, I/O-free grouping of subtopic clusters into primary_topic macro-groups: `group_post_hoc` (merge already-adjudicated subtopic centroids after the fact) and `group_nested` (two-level merge over raw pre-adjudication centroids) are the two calibratable grouping mechanisms; `split_by_coachability` (added 2026-07-31) is a free zero-Gemma correction pass that splits any group mixing coachable and non-coachable members into homogeneous groups, wired into `v2/layer_a.py::_finalize_primary_topics`
- `calibration/dry_run_layer_a.py` — read-only taxonomy preview: `--sweep` (threshold grid), `--merge-detail 0.75,0.85` (what each merge threshold actually collapses), plain run (full report + coverage distribution). Zero Gemma calls, zero DB writes
- `calibration/dry_run_layer_bc.py` — Layer B/C calibration. Chains off Layer A's clustering, substitutes **c-TF-IDF keywords as pseudo scenario descriptions** (Gemma writes the real ones), then runs the *production* `layer_b.assign_scenarios` and `layer_c._relevance_filter`. Reports sink-absorption rate, assignment concentration, best-match cosine spread, a `relative_margin` sweep, and the milestone-count distribution per `(percentile, fraction)` — including how many scenarios end with **zero** milestones. Zero Gemma, zero Postgres, zero Pinecone
- `main.py` — entry point; asks V1 or V2; generates `run_id`; inits Pinecone index + SQLite checkpoint
- `ops/` (moved here 2026-08-08) — maintenance and auxiliary runners (`clear_data.py`, `clear_ego_trap_data.py`, `rerun_layer_c.py`, `backfill_*.py`, `fetch_avoma_recordings.py`, `run_ego_trap.py`, the `.ps1` run recipes). Deliberately **not** a Python package: `clear_data.py` and `clear_ego_trap_data.py` have no `__main__` guard, so *importing* either one wipes live data — with no `ops/__init__.py` there is no `ops.clear_data` to import by accident. Verify them with `py_compile`, never by importing. The move also required re-anchoring 11 `Path(__file__).parent` references to `.parent.parent`, or `clear_data.py` would have looked for `ops/checkpoints.db`. See `ops/README.md`
- `calibration/` (moved here 2026-08-08) — every dry-run/compare/diagnose/replay/analyze harness. **Nothing in `v1/`, `v2/`, `shared/` or `preprocessing/` imports this package**, which is the point: it is the measurement tooling, not the pipeline. Each script carries a 3-line `sys.path` bootstrap so it works both as `python calibration/x.py` and as `from calibration import x` (the form `tests/test_graduate_sink_topics.py` uses). **Run them from `Brain/`, not from inside `calibration/`** — artifact defaults like `Path("Brain/artifacts/sink_pool_clusters.json")` are CWD-relative and resolve against `Brain/`
- `logs/` (moved here 2026-08-08) — all run output. Gitignored via `*.log`; nothing reads these, they are the audit trail the calibration verdicts in this file cite
- `artifacts/` (moved here 2026-08-08) — the JSON blobs calibration scripts write and re-read via `--load`. Resolved through `calibration.ARTIFACTS_DIR`, which is anchored to `Brain/` via `__file__`. **This fixed a latent bug**: the old bare `Path("sink_pool_clusters.json")` defaults were CWD-relative, so launching a script from anywhere but `Brain/` silently wrote to — or failed to find — the wrong path. Gitignored as `Brain/artifacts/*` with **one deliberate exception re-admitted**, `sink_pool_clusters.json`, because it is a real *input* (`graduate_sink_topics.py` and `replay_layer_c_admitted.py` read it) rather than output
- `recordings/` — place `.txt` transcript files here (stem = call_id)
- `db/schema.sql` — Postgres tables only (no vector columns); `db/init_db.py` runs it
- `tests/` — pytest suite (319 tests across 23 files as of 2026-08-10; this count grows every session, use `pytest tests/ --collect-only -q` for the current number rather than trusting this line). `test_cluster_evidence.py` and `test_tuning.py` cover the triage helpers and the config loader; `test_layer_b_assignment.py` covers relative top-K scenario matching using hand-built orthogonal unit vectors, so it tests the *rule* rather than the embedding model; `test_relative_match.py` covers the same rule after its extraction to `shared/relative_match.py`; `test_topic_grouping.py` covers `shared/topic_grouping.py`; `test_two_stage_matching.py` covers `assign_scenarios_two_stage`'s strict/soft/fallback strategies against hand-built vectors (uncalibrated on real data — see below); `test_gemma_retry.py` covers the `httpx.TransportError` retry fix; the six `test_ego_trap_*.py` files cover Layer D, and its similarity-mode tests patch `score_client_turns` with hand-built similarity matrices rather than mocking the embedder and Pinecone — same reasoning as `test_layer_b_assignment.py`
- `ego_trap/` — the RUBRIC-ERA gap-analysis pipeline (Steps 0-4 + Layer D) scoring CSM calls against Naren's rubrics; `ops/run_ego_trap.py` is its non-interactive batch entry point, `ops/clear_ego_trap_data.py` resets only its own tables. **Dark since the union taxonomy replacement** (rubrics is empty) and superseded by `layer_d/`; retires once the redesign passes its gates
- `layer_d/` (added 2026-08-20) — the REDESIGNED gap-analysis pipeline scoring CSM calls against **playbooks** (`key_moves`, positional M1..Mn), with the SAME instrument also scoring Naren's own routed kb_pairs so every gap is a rate difference against a measured benchmark. Key properties, each one a fix for a measured ego_trap defect: client-move segmentation arm E (the 98.6%-artifact fix), mandatory verbatim quotes verified programmatically (`verify_quotes.py`; the 23%-fabrication fix), 4-state verdicts where `unscored` ≠ `miss` (the truncation-manufactures-misses fix), natural-key `move_events` upserts + full-recompute `move_performance` (the double-count fix), checkpoint-on-success-only (the lost-signals fix), fail-closed speaker classification (the internal-chatter-as-client fix), and Naren-rate dead-check flags (the 24%-dead-criteria fix). Both grader arms are built (`checks` binary evidence-gated, `pairwise` order-swapped vs exemplar); `tuning.yaml layer_d.grader_arm` selects, and the C2 head-to-head decides the value. Spec: `docs/superpowers/specs/2026-08-20-layer-d-redesign-design.md`
- `ask_naren/` (added 2026-08-26) — the **Ask Naren** service: a CSM types a live client situation, gets back one answer grounded in Naren's closest real historical response, or a decline. Not part of the mining pipeline — it is a consumer of it, and it **never writes to Postgres** (the read-only connection is closed before the first request is served). `retrieval.py` loads every coachable `kb_pair`, dedupes on normalized (trigger, response) CONTENT (the corpus holds transcripts ingested twice under two filenames — 6528 rows become 6496), and searches by in-memory cosine because `is_coachable` is not in Pinecone's metadata. `grounding.py` is the **grounding gate**: an answer whose quote is not verbatim in the cited response, or that cites a call it was not shown, is regenerated once and then declined — it reuses `layer_d/verify_quotes.py` rather than defining containment twice. `answering.py` orchestrates and passes `no_cache=True` on every generation. `service.py` is stdlib `http.server`, **single-threaded on purpose** (`shared/embed_cache.py` holds a thread-bound SQLite connection) with `Connection: close` on every response. `citations.py` turns a call filename into the label a CSM reads and is deliberately CONSERVATIVE: 68.7% of citable pairs come from dated `YYYYMMDD_<account>_joveo_<subject>_<hash>` filenames, 31.3% from opaque UUIDs with no date anywhere and no recorded meeting subject (issue #4 assumed one existed; the schema, the transcripts and the sidecars all lack it). An account is named only where the recorded data states it unambiguously -- for UUID calls that means exactly ONE external participant domain in the `<stem>.speakers.json` sidecar, because 40 of 323 list several and one measured example carries both a brand and its agency. Everything else falls back to the raw filename: 94.3% of citable pairs resolve, 5.7% do not, and a wrong client name on a citation is worse than an opaque one. The resolver is injected into `answer_situation` as `label_for` (same pattern as `embed_query`) because the sidecar index is built once at startup by the caller, and its absence degrades rather than breaks. Entry point `ops/serve_ask_naren.py`; `--ask "<situation>"` answers one and exits. Context, ADRs and the answer-quality audit live in `../ask-naren/`

### Transcript format

```text
SpeakerName
Utterance text here.

NextSpeaker
Their utterance.
```

No participant header block. Speaker classification is config-driven via `JOVEO_SPEAKER_NAMES` env var.

### Embedding API

Always go through `preprocessing/embedder.py` — never call the model or Pinecone inference directly:

```python
from preprocessing import embedder
vecs = embedder.embed_query(texts)     # CLIENT triggers / search side -> list[list[float]]
vecs = embedder.embed_document(texts)  # responses, scenario descriptions -> list[list[float]]

# Prefer these for large pools -- returns (n, dim) float32 ndarray, no list round-trip
mat = embedder.embed_query_matrix(texts)
mat = embedder.embed_document_matrix(texts)
```

**Use the `_matrix` variants for anything corpus-sized.** The list-returning functions materialise ~56 million Python float objects for a 74k-clause pool, which made a *cache hit* slower than re-embedding the whole corpus on the GPU. `layer_a`, `layer_c` and `dry_run_layer_a` all use the matrix path.

`embed_query` prepends bge's instruction prefix (`"Represent this sentence for searching relevant passages: "`); `embed_document` does not. The cache is keyed on the prefix, so the same string correctly yields two different vectors depending on which function is used. Both return plain `list[list[float]]`, already L2-normalised.

Two namespaces in one Pinecone index: `"triggers"` (CLIENT utterances) and `"responses"` (Naren responses).

**Embeddings are not reproducible across runs unless cached.** CUDA matmul reduction order varies, so the same corpus re-embedded from scratch yields slightly different vectors, and UMAP/HDBSCAN amplify that into different cluster counts (241 → 231 → 226 raw clusters were observed for one identical corpus). The float32 `embed_cache.db` is what pins results — keep it between calibration runs, and delete it only when you intend to re-embed.

### Checkpointing

SQLite `checkpoints.db` — item convention: `"ALL"` for Layer A, call stem (e.g. `"lumbertonisd_2026"`) for Layer B, `scenario_key` for Layer C.

### PRODUCTION STATE AS OF 2026-08-19 — read this before touching Layer A/B/C

**The live taxonomy is `union_base`: 259 scenarios (34 coachable + 225 sinks) in Postgres**,
loaded by `ops/ship_union_taxonomy.py` from `artifacts/adjudication_ab_union_base.json`. The
previous 161-scenario map and everything keyed to it were deleted and are backed up in schema
`pre_union_20260819` (8,295 rows across all ten tables). **Replacing a taxonomy is a REPLACEMENT,
not an upsert** — see `docs/GOTCHAS.md`.

**Routing stays `concat`.** The three-arm routing A/B settled it: `keyphrases` is REFUTED (it
starves the map — the largest scenario goes 771→0 routed pairs and sink share rises 47.5%→60.9%),
and `r1` membership lookup is UNRESOLVED and NOT shipped. Full record:
`docs/findings/layer-b-routing-playbook-ab.md`. **Do not re-run r1 on this map** — it is 71%
control fallback by construction and no clustering exists that is both high-coverage and coherent.

**`layer_b.sink_margin_delta` exists at `0.0`, which is a byte-identical no-op.** It is the one
routing lever the evidence positively endorses (+5.1pp recall for −2.6pp precision at −0.0117).
**Do not set a non-zero value without sweeping it against a judged sample larger than 80 turns.**
**WIRED 2026-08-19** — `v1.layer_b.assign_scenarios` used to carry its own inline copy of the
pick logic and never call `flat_pick`, so the knob was inert on the primary path. It now calls
`flat_pick`, after `calibration/sink_margin_delta_identity.py` proved the substitution
byte-identical on **12,444/12,444 real pairs** (real scenario rows, real triggers, full ordered
`scenario_keys` list — not just the pre-existing 400 synthetic cases). Four tests pin the
wiring, including a tripwire that the shipped value is still 0.0.

**`tuning.yaml` NOW DESCRIBES THE LIVE SYSTEM (repaired 2026-08-19).** It previously did not,
and the gap was destructive rather than cosmetic: the live taxonomy was clustered in **turn**
mode at **merge 0.97** in **gemini@3072**, while the config said `clause` / `0.85` / `local`.
Since Layer A upserts scenarios, running `main.py` would have rebuilt the map on a different
unit, at a floor calibrated for the other unit, in the wrong embedding space — and overwritten
the live taxonomy with it. Three values changed to match reality:

| key | was | now | why |
| --- | --- | --- | --- |
| `layer_a.pool_unit` | `clause` | **`turn`** | what `union_pool_fetch.py` actually clustered |
| `layer_a.merge_cosine_threshold` | `0.85` | **`0.97`** | the artifact's own `identity.merge`; a floor may never cross cosine bands |
| `embedding.backend` | `local` | **`gateway`** | the corpus was paid for in gemini@3072 through the gateway |

**Verified, not asserted:** `calibration/config_reproduces_live.py` runs production
`assign_scenarios` driven ONLY by `tuning.yaml` — no calibration shim — and reproduces the
stored `scenario_key` for **12,444/12,444 live pairs** at sink share 47.5%, with the gateway
transport monkeypatched to raise so a cache miss fails instead of spending. Re-run it after any
change to these keys.

**What this does NOT fix.** `embedding.backend` is GLOBAL. Layer B's *relative* knobs are
scale-invariant and provably unaffected, but **`layer_c` and `layer_d` thresholds were fitted
to bge bands and are now UNCALIBRATED**. Tolerable only because both layers are dark
(`rubrics`/`gap_events`/`milestone_performance` are empty). Do not run Layer C or D against
this backend and trust the numbers.

**Two embedding spaces still coexist and this remains the biggest live hazard.** Calibration
reaches the gemini vectors through
`layer_bc_arms.install_embedder_shim`, which is cache-only and ABORTS on a miss. **A measurement
script that forgets the shim silently compares across the two spaces** — that happened on
2026-08-19 and produced a clean-looking cosine table with a p50 of 0.065; only the absurd
magnitude gave it away. Install the shim before building ANY vector, and assert the width.

**`backend: gateway` (added 2026-08-19) IS NOW THE SHIPPED VALUE.** Three backends:

- `local` — bge@768. The legacy option; every threshold in `tuning.yaml` was originally
  fitted to its bands. No longer shipped.
- `gemini` — Google AI Studio DIRECTLY, ~1k/day, cache `embed_cache.db` keyed
  `sha256(model|prefix|text)`. **Almost never what you want**: the whole corpus was paid for
  through the gateway into a different file, so this re-buys ~25k vectors.
- `gateway` — the same model over the Joveo gateway, cache `gemini_embed_cache.db` keyed
  `sha256(model|NATIVE_dims|text)`. Reads the vectors already paid for. Verified with the
  transport disabled: 300/300 real triggers from cache, zero requests. Transport lives in
  **`shared/gateway.py`**; `calibration/trial_gateway.py` re-exports it.

**Switching to either hosted backend is a RE-CALIBRATION, not a config change**, and there is
now a measured reason: the gemini trigger band is p10=0.653 p50=0.690 p90=0.729 against bge's
p10=0.496 p50=0.550 p90=0.613. That ~0.14 shift **inverts** `sink_rescue_trigger_weak_floor`
(0.65 was chosen to sit above bge's p90 and now sits below gemini's p10). Flagged in
`tuning.yaml`, deliberately NOT re-tuned; nothing is live while `sink_rescue_strategy: none`.
Re-measure with `calibration/gemini_cosine_bands.py`.

**Pinecone: `narens-brain-3072` is the new index** (3072/cosine). The 768-dim `narens-brain` with
52,858 vectors is kept for rollback. Index dimension is immutable after creation.

**LAYER C IS SHIPPED AND BACKFILLED (2026-08-19/20): 33 of 34 coachable scenarios have a live
playbook.** `db/schema.sql` has a `playbooks` table; `ops/load_playbooks.py` (dry run by
default, seven gates) holds 60 rows — **33 live** (5 original + 25 backfill + 3 thin), 5
placebo, 22 trial. `contract_and_legal_review` is the ONLY gap: its snap collapsed at 2 moves
against a floor of 3, and the loader excludes `schema_collapsed` documents automatically.

**UPDATED 2026-08-24 — the original 5 were REPLACED, and the blind read's absolute rates are
RETRACTED.** See `docs/findings/layer-c-playbook-schema-and-gateway.md` §13.

The table that used to sit here ("original 5 = 63% usable, 28 backfilled = 73%") is **not
citable**. A blind-read `usable%` is a property of the instrument, not the documents: the same
59 quotes scored **95% then 78%** across two packets, and the same 123 live criteria scored
**84% then 17%** under two reader framings — which also **inverted** the cohort ranking. **Only
within-packet, counterbalanced, one-reader contrasts are valid.** Never compare a number from
one audit to a number from another, and never quote a level.

On the one clean contrast, the **gradability arm beat the relevance arm 89% vs 78% usable,
winning 4 of 5 situations with ZERO failing quotes** — narrowing criteria made the quotes fit
better rather than trading against them.

**The live 33 are now: 5 `pbq_36flash_medium_grad_snapped.json` + 25 `pbf_rest` + 3 `pbf_thin`.**
The 5 pbv originals are `superseded` (retained for traceability, invisible to production reads).
65 rows total: 33 live / 22 trial / 5 placebo / 5 superseded, all seven loader gates green.
Independently measured by `calibration/playbook_gradability_census.py`, production improved on
every axis: banned adjectives in that cohort 15%→**0%**, single-account across all live
10%→**9%**, quotes>=3 82%→**93%**.

**A taxonomy-wide rollout of the gradability config is NOT licensed** — it fails G-Q1 at census
scale (11% single-account on 18 moves). Only those 5 documents are.

**PB1 IS NO LONGER A GATE** (operator decision, 2026-08-24). It rejected a real improvement
twice, because it counts evidence entries while the relevance and gradability rules deliberately
drop weak ones. Replaced by **single-account moves <= 10%**; **G-Q4 demoted to diagnostic** for
the same reason (the third instance); **G-Q7 added** — a replacement must be no worse than the
incumbent it supersedes, which is a relative question a 5-document probe can actually answer.
A rate bar also needs enough n to be evaluable: at 18 moves the achievable values are 0%, 5.6%,
11.1%, so "11% vs a 10% bar" is one move, not a distinction.

**Backfill config, licensed by a 4-arm A/B (§10b):** `gemini-3.6-flash`,
`reasoning_effort=medium`, `MIN_EVIDENCE_PER_MOVE=3`, hardened `_REQUIRE`, quote-relevance
rule. The MODEL was the lever, not the prompt — `gemini-3.5-flash-lite` ignores the
account-diversity instruction (11%), 3.6-flash follows it (77%).

**TWO KNOWN DEFECTS IN WHAT IS LIVE — read before building on it:**
1. **CRITERION GRADABILITY — the "~half" figure is RETRACTED, and the real number is unknown.**
   Two blind reads of the same 123 live criteria returned **84%** and **17%** gradable depending
   only on how the reader was framed, so no rate can be quoted. What IS established: the 5
   promoted documents carry **0%** banned evaluative adjectives (the other 28 carry 13-16%), and
   ungradability has **two distinct causes that pull opposite ways** — evaluative vagueness
   ("clearly explain business impact") and **bundling** ("name the exact tracking columns AND
   walk through drop-off analysis"). Bundling matters specifically because Layer D's shipped
   `checks` arm asks a strictly binary `performed: true/false` and demands a verbatim quote, so a
   compound criterion does not cause grader disagreement — it causes **HIT INFLATION**, since the
   grader anchors on the easiest clause. **Bundling in the 94 backfill moves has never been
   measured**, and an atomicity rule ("one criterion = one checkable demand") has never been
   probed. Layer D's own `--report-only` pass is zero-spend and is the only instrument that
   measures whether these criteria yield signal on real calls.
2. **Breadth tracks evidence volume, monotonically.** 50-pair scenarios: 75% PB1, 4%
   single-account moves. Under 35 pairs: 41% and 24%. The 3 thin documents (16-21 pairs) are
   11% and 22% — one client dominates them. No prompt fixes absent evidence.

Read this before touching the table:

- **`status` is the safety boundary, not a label.** `live`=33, `placebo`=5
  (the twins), `trial`=22 (routing A/B; the 11 `r1` documents are UNRESOLVED and were never
  shipped). Placebo and trial rows are indistinguishable from production content without the
  filter, so **production reads MUST filter `status='live'`** —
  `storage.get_playbook_for_scenario` defaults to it, and raises rather than returning an
  arbitrary row when a filter matches more than one.
- **One live playbook per scenario is enforced by the DATABASE** (`idx_playbooks_one_live`, a
  partial unique index), verified by attempting the violation. Promote by demoting the
  incumbent to `superseded` first.
- **`move_id` is the ARRAY POSITION (`M1..Mn`)**, assigned by the loader, never taken from the
  model — same rule as `milestone_id`. **`key_moves` order is load-bearing**; reordering
  renumbers, which would repoint any future per-move history.
- **`scenario_id` is a NOT NULL FK**, so `playbooks` is in `ship_union_taxonomy.py`'s
  children-first `DELETE_ORDER` and a taxonomy replacement DELETES the playbooks. The JSON
  artifacts on disk are the archive. That script now filters its table lists through
  `to_regclass`, so it stays runnable on databases predating the table.

`rubrics`/`gap_events`/`milestone_performance` are still EMPTY BY DESIGN (keyed to the old
taxonomy), so the rubric-era Layer D remains regressed and retires with `ego_trap/`.

**THE LAYER D REDESIGN IS CALIBRATED, ALL THREE P0 FIXES ARE SHIPPED, AND THE REGRADE IS
COMPLETE (2026-08-27).** The instrument is
`layer_d_e_pairwise_gemini-3.6-flash_medium_noswap_v3` (the `_v3` suffix is the
interjection-guard/exemplar-filter boundary — `_v2` verdicts are stale and were fully
superseded by the regrade) — every piece a measured verdict: pairwise beat checks at C2
(77.1% vs 53.9% discrimination; checks is DEAD for arc-level moves — the expert's own
per-moment rate is 3–6% under any grader/wording, proven 4x at C3); the order swap was dropped
on a 95% agreement measurement (CSM side randomized per moment); k=1 (zero flips at k=3); C4
blinded reader 11/11. **The three P0 fixes** (interjection guard — fragment/interruption
replies recorded but never graded; substantive-exemplar filter — Naren filler can never be
the benchmark; report grouping — one block per scenario, worst-first, no cutoff) **shipped,
were audited clean, and the full corpus was regraded**: 100 of 106 mapped transcripts, 0
failures, fresh `move_performance` (251 rows). The regraded numbers barely moved from the
pre-fix run (e.g. the top cell's match-or-beat went 23%→22%, attempt counts dropping by
exactly what the interjection guard predicts) — confirming the original run was mostly real
signal, not defect-driven noise. A fresh 40-moment blinded output audit on the regraded data
hit 92.7% agreement (gate ≥70%), consistent with the original run's 97.9%. Full trail:
`HANDOFF_LAYER_D_P0_SHIPPED_2026-08-27.md` (supersedes `HANDOFF_LAYER_D_CALIBRATED_2026-08-25.md`)
and `docs/findings/layer-d-redesign.md` (the arc's full evidence trail, including two
operational bugs the regrade exposed and fixed — a missing connection-reconnect and a
Neon-pooler session-leak that was making the DB look intermittently read-only; see
`docs/GOTCHAS.md`). ~24 of the ~75 rankable cells are blurry (≥80% tie) and form the TARGETED
playbook-rewrite shortlist (P1, not started). `move_events`/`move_performance` key
`(playbook_id, move_id)` and are in `ship_union_taxonomy.py`'s delete chain. The runner
refuses without `csm_recordings/client_speakers.txt` (`ops/build_client_roster.py`
regenerates it from the Avoma rosters).

**New ops scripts** (all dry-run by default, `--apply` required, Neon DNS handled via
`--hostaddr`): `ops/ship_union_taxonomy.py` (snapshot → delete children-first → load 259
scenarios), `ops/ship_layer_b.py` (route → calls → kb_pairs with live DB ids → triggers
namespace → paced response tail) and `ops/load_playbooks.py` (65 playbook documents, seven
gates verified after the write).

**`ship_union_taxonomy.py` IS NOW GENUINELY ONE TRANSACTION (fixed 2026-08-24).** Its docstring
promised that and was false for five days: `storage.upsert_scenario` ended in `conn.commit()`, so
the first of 259 upserts committed the children-first DELETEs, and the post-load `conn.rollback()`
was a no-op that still printed "rolled back". `upsert_scenario` now takes a keyword-only
`commit: bool = True` (the default preserves all 15 call sites) and the script passes
`commit=False`. Pinned by `tests/test_ship_union_taxonomy_transaction.py`, including a source
tripwire — `ops/` is deliberately not a package, so the call site cannot be import-tested.
**`storage.upsert_playbook` still commits per row**, so `load_playbooks.py` is likewise not
atomic; far less dangerous (it deletes nothing and is idempotent) but true.

**A PROMOTION in `load_playbooks.py` is DECLARATIVE, and ARTIFACT_PLAN ORDER IS LOAD-BEARING.**
To replace a live document, flip the incumbent artifact's arm to `superseded` and add the
replacement as `live` — `upsert_playbook` is `ON CONFLICT ... DO UPDATE SET status =
EXCLUDED.status`, so no hand-written UPDATE is needed and it stays idempotent. But documents are
written in plan order and `idx_playbooks_one_live` is a partial unique index, so **the demoting
entry must precede its replacement** or the write is refused. Two tests pin this: the ordering,
and that the promotion is one-for-one (no scenario demoted without a replacement).

**Resuming `ship_layer_b.py`:** use `--apply --resume-vectors`, never a bare re-run (blocked on
purpose). It skips the calls/kb_pairs writes, re-derives routing and REFUSES on any missing pair
or any routing drift. **It also redoes step 4 (the trigger namespace) every time** — `--vectors`
offers only `both|triggers|none`, so there is no responses-only resume. That re-upsert is free
and idempotent (all trigger vectors are cached) but costs a few minutes; a `--vectors responses`
choice would remove it.

**Playbook harnesses (2026-08-20).** `calibration/playbook_backfill.py` synthesizes playbooks
for scenarios lacking one (`--band thin|rest`, dry-run default, own `pbf_*` prefix, writes
NOTHING to Postgres, selection vectors cache-only with a bounded top-up).
`calibration/quote_floor_ab.py` is the paired A/B rig — each (model, effort, prompt-tag)
combination writes its OWN artifact set, so runs never overwrite each other. **`--report` is
free** and re-scores any existing arm from disk; the three arms of the 5-original remake are
`pbq_36flash_medium_*` (licensed), `*_relev_*` (+relevance), `*_grad_*` (+gradability, now LIVE).
`calibration/playbook_backfill_scope.py` is the free scoping pass.

**`calibration/playbook_gradability_census.py`** (added 2026-08-24, zero spend) censuses every
criterion in every live playbook: a deterministic banned-adjective **floor** (explicitly not the
rate), single-account/PB1/quote-floor rates per cohort, thin-band account concentration, and
`--packet` to build a blind packet with opaque ids and the key written to a separate file.
**`calibration/pbg_score_blind_read.py`** joins a returned read back to that key, **REFUSES a
partial read** (a rate over a subset the reader chose is not a rate), and prints the
deterministic-vs-blind confusion so the scan stays honest about being a floor. Both persist
**per-item** labels — the previous session's per-quote labels were never persisted and are
permanently lost, which is why the "236 labelled quotes" a handoff promised do not exist.

**New verification harnesses, all zero-spend and safe to re-run:**
`calibration/sink_margin_delta_identity.py` (12,444-pair byte-identity proof),
`calibration/gateway_backend_check.py` (gateway backend serves the corpus with the transport
DISABLED, so a miss fails instead of spending), `calibration/gemini_cosine_bands.py` (the
gemini-space cosine bands behind the flag above).

### Deep-dive references — read these on demand, not by default

This file only covers what's needed to run and navigate the pipeline. Everything else — every
calibration result, every A/B outcome, every "we tried X and it failed" — lives in separate files
so it doesn't have to load into every session:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the fuller architecture writeup (data flow, module
  responsibilities) than the bullet list above.
- **[docs/GOTCHAS.md](docs/GOTCHAS.md)** — the full list of non-obvious failure modes and rules
  (PowerShell quirks, connection-idle timeouts, encoding traps, threshold-calibration discipline,
  etc.). Skim this before writing any new script that touches the DB, `.env`, or `tuning.yaml`.
- **[docs/SCHEMA.md](docs/SCHEMA.md)** — current Postgres schema state (columns added since the
  original `db/schema.sql`) plus misc. production facts (`run_id` derivation, `assign_scenarios`
  behavior, utility-script inventory).
- **[docs/findings/INDEX.md](docs/findings/INDEX.md)** — index of every calibration/research
  finding to date, one file per topic (Layer A/B/C/D, embeddings, corpus quality, etc.). Read the
  relevant file **before** re-proposing a threshold change, a new clustering method, or a matching
  strategy — most ideas here have already been tried and measured, with the reason recorded.
- **[PROBLEMS_AND_FIXES.md](PROBLEMS_AND_FIXES.md)** — long-form incident narratives (what broke,
  how it was found, how it was fixed) that some findings files reference for full detail.
- `tuning.yaml` itself carries the calibration history for every live threshold inline — check
  there first for "why is this value X" before searching the findings docs.

