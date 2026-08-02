# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**CS-platform** — Joveo Customer Success platform. A Next.js 14 (App Router) web application for Joveo's CS team, providing a workspace, learning library, and call simulator.

## Workflow preferences

- Do not invoke the `superpowers:writing-plans` skill itself — the user considers it a waste of time. Writing a plan document is still fine (and often useful) after a design/spec is approved (e.g. via `superpowers:brainstorming`) — just write it directly rather than going through that skill's process.

## Commands

Run all commands from inside the `frontend/` directory:

```bash
cd frontend
npm run dev    # Start dev server at http://localhost:3000
npm run build  # Production build (also runs full TypeScript type-check)
npm start      # Run production build
npm run lint   # ESLint
```

No test framework is configured. `npm run build` is the type-check gate — there is no separate `tsc` script.

## Stack

- **Next.js 14** App Router, **TypeScript** (`strict: true`)
- **Tailwind CSS** for component styling
- **State:** React hooks + `localStorage` + `CustomEvent` — no Redux/Zustand, no data fetching
- **Icons:** inline SVG components in `frontend/src/components/icons/index.tsx` — no icon library
- All data is hardcoded mock in `frontend/src/data/` — no API routes, database, or auth

## Architecture

### Layout & directory shape

All source lives under `frontend/`. `frontend/src/app/layout.tsx` wraps every route in `<AppShell>` (`frontend/src/components/AppShell.tsx`), which renders the sidebar + topbar and owns the mode/theme/sidebar state. Pages are thin composition shells; the UI lives in per-component files:

- `frontend/src/components/workspace/` — workspace cards (one file per card, veteran + newbie variants)
- `frontend/src/components/library/` — library tabs, cards, and modals
- `frontend/src/components/shared/` — components used across pages (`TQItem`, `RadarBriefingPanel`, `RadarRow`, `RadarDeckStack`)
- `frontend/src/data/workspace.ts`, `frontend/src/data/library.ts` — all mock data, typed against `frontend/src/types.ts`
- `frontend/src/hooks/useMode.ts` — the mode subscription hook
- `frontend/src/types.ts` — the single source of domain types (`EgoTrap`, `RadarMeeting`, `CaseStudy`, `FailureEntry`, `Mode`, etc.); annotate new data and props against these

Routing: `/` redirects to `/workspace`. `/workspace` and `/library` are implemented; `/simulator` is a stub.

### Mode system (Veteran / Newbie)

Two personas toggled in the topbar render **completely different component trees** within the same page:

1. `AppShell` persists the choice to `localStorage['cs-mode']` and dispatches a `cs-mode-change` `CustomEvent`.
2. `useMode()` (in `src/hooks`) reads `localStorage` on mount and subscribes to that event; `workspace/page.tsx` and `library/page.tsx` branch on its return value.
3. `AppShell` keeps its own `mode` state separate from `useMode()` (it both controls and is the source of the event), so the switcher lives there, not behind the hook.

### Dark mode

Toggled in `AppShell`, persisted to `localStorage['cs-theme']`, applied as `[data-theme="dark"]` on `document.documentElement`. `layout.tsx` runs a tiny inline `<script>` before paint to set the attribute from `localStorage` (prevents a flash). Tailwind's `darkMode` is configured as the `[data-theme="dark"]` selector.

### Styling: tokens + Tailwind + residual CSS

The design system is **driven by CSS custom properties**, not by Tailwind's config:

- `frontend/src/app/globals.css` `:root` and `[data-theme="dark"]` define all `--color-*`, `--space-*`, `--radius-*`, `--shadow-*`, motion, and `--sb-*` (sidebar palette) tokens in OKLCH. **To change a color, edit globals.css** — `tailwind.config.js` only *references* these via `var(--…)`, so utilities like `bg-surface` / `text-ink` resolve to the CSS variables and dark mode works automatically.
- **Border-color token is named `line` / `line-subtle`** (e.g. `border-line`), not `border` — this avoids clashing with Tailwind's `border` width utility.
- `globals.css` is **not** purely tokens (~1100 lines). It retains CSS that cannot be expressed as inline utilities, and several components legitimately still use these semantic classes:
  - **Radar deck 3D stacking** — `radar-deck-*`, `rdc-*`, `rdn-*`, `radar-prep*` (used by `RadarDeckStack`).
  - **App shell** — the `app-layout` collapse grid and the full `sidebar-*` / `topbar-*` / `oracle-*` / `mode-*` rules (used by `AppShell`).
  - **Expand/collapse** — the `grid-template-rows: 0fr → 1fr` pattern via the custom utilities `.grid-rows-0fr` / `.grid-rows-1fr` (toggled on ego-trap mirror, radar briefings, newbie track).
  - **Keyframes + `.anim-*` wrappers** (`anim-modal`, `anim-backdrop`, `anim-spotlight`, etc.), plus `.lib-section-header` (reveal) and `.lib-fl-card` (hover watermark + read-more arrow).
- Design north star: **"The Mentor's Desk"** — professional, typography-first, no gamification. Amber **accent** color (`--color-accent`) is used sparingly (≤10% of a screen). All animations respect `prefers-reduced-motion` (global rule in globals.css). Fuller design notes are in `DESIGN.md`.

### Path alias

`@/*` maps to `./src/*` (in `tsconfig.json`). Use `@/components/...`, `@/data/...`, `@/types`.

## Conventions

- Components using hooks/state/effects/refs/event handlers need `'use client'` at the top; pure presentational components (most cards, icons) do not.
- Modals (`CaseStudyModal`, `FailureModal`) use `createPortal` to `document.body` and implement their own focus trap + Escape handling — preserve that when editing.
- Match the existing Tailwind translation style: arbitrary values (`text-[11px]`, `tracking-[0.06em]`) and inline `style={{ … }}` with `var(--…)` are used where a token or utility doesn't fit; CSS custom properties in `style` need an `as CSSProperties` cast under strict TS.

---

## Brain/ — Naren's Brain Pipeline

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
python dry_run_layer_a.py --sweep                        # threshold grid (counts only)
python dry_run_layer_a.py --merge-detail 0.75,0.80,0.85  # what each merge threshold collapses
python dry_run_layer_a.py                                # full report + coverage distribution

# Calibrate Layer B matching + Layer C milestones -- also zero Gemma, zero DB/Pinecone
python dry_run_layer_bc.py --limit 30                    # fast smoke test
python dry_run_layer_bc.py                               # full corpus

# Run pipeline
python main.py

# Wipe Postgres + checkpoints before a clean re-run
python clear_data.py
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
- `dry_run_layer_a.py` — read-only taxonomy preview: `--sweep` (threshold grid), `--merge-detail 0.75,0.85` (what each merge threshold actually collapses), plain run (full report + coverage distribution). Zero Gemma calls, zero DB writes
- `dry_run_layer_bc.py` — Layer B/C calibration. Chains off Layer A's clustering, substitutes **c-TF-IDF keywords as pseudo scenario descriptions** (Gemma writes the real ones), then runs the *production* `layer_b.assign_scenarios` and `layer_c._relevance_filter`. Reports sink-absorption rate, assignment concentration, best-match cosine spread, a `relative_margin` sweep, and the milestone-count distribution per `(percentile, fraction)` — including how many scenarios end with **zero** milestones. Zero Gemma, zero Postgres, zero Pinecone
- `main.py` — entry point; asks V1 or V2; generates `run_id`; inits Pinecone index + SQLite checkpoint
- `recordings/` — place `.txt` transcript files here (stem = call_id)
- `db/schema.sql` — Postgres tables only (no vector columns); `db/init_db.py` runs it
- `tests/` — pytest suite (115 tests as of 2026-07-31; this count grows every session, use `pytest tests/ --collect-only -q` for the current number rather than trusting this line). `test_cluster_evidence.py` and `test_tuning.py` cover the triage helpers and the config loader; `test_layer_b_assignment.py` covers relative top-K scenario matching using hand-built orthogonal unit vectors, so it tests the *rule* rather than the embedding model; `test_topic_grouping.py` covers `shared/topic_grouping.py`; `test_two_stage_matching.py` covers `assign_scenarios_two_stage`'s strict/soft/fallback strategies against hand-built vectors (uncalibrated on real data — see below); `test_gemma_retry.py` covers the `httpx.TransportError` retry fix
- `ego_trap/` — gap-analysis pipeline (Steps 0-4 + Layer D) scoring CSM calls against Naren's rubrics; `run_ego_trap.py` is its non-interactive batch entry point, `clear_ego_trap_data.py` resets only its own tables

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

### Gotchas

- `pyproject.toml` build backend must be `setuptools.build_meta` — not `setuptools.backends.legacy:build`
- `conftest.py` has `sys.path.insert(0, os.path.dirname(__file__))` — required for test imports to resolve
- GateGuard's fact-forcing gate fires on every Write/Edit call (new or existing files) and the first Bash call each session — present the 4 facts inline immediately before each retry, every time; creating files via Bash heredoc (`cat > file <<'EOF' ... EOF`) skips the Write-tool gate entirely and is much cheaper for bulk file creation
- `layer_b.extract_pairs` uses `_is_substantive()` on both trigger and Naren response: requires ≥`_MIN_CONTENT_WORDS` (default 5) alphabetic non-stop tokens using spaCy `en_core_web_lg`'s stoplist — no custom filler lists or scheduling regex; `_nlp` loaded once at module level with `parser` and `ner` disabled for speed; tune only `_MIN_CONTENT_WORDS` to adjust aggressiveness
- Always use `load_config()` not `Config()` — `Config` is a frozen dataclass, not self-constructing
- `load_dotenv()` must use an explicit path ? `load_dotenv(Path(__file__).parent / ".env")` in `config.py` ? bare call silently misses `.env` when CWD differs from `Brain/`
- PowerShell: set `$env:DATABASE_URL` and `$env:PYTHONIOENCODING="utf-8"` in the same command block as the Python call — they don't persist across calls
- Inline Python `-c "..."` in PowerShell breaks on `{}`, single quotes, `->` — write a temp script to the scratchpad instead
- All `read_text()` calls must use `encoding="utf-8-sig"` not `"utf-8"` — Windows editors save transcripts and SQL files with a UTF-8 BOM that breaks psycopg and the transcript parser
- PowerShell `Set-Content -Encoding utf8` also writes a BOM ? breaks `python-dotenv` (`.env` silently not loaded) and TOML parsers (`pyproject.toml` build fails); strip with `[System.IO.File]::WriteAllText(path, content, [System.Text.UTF8Encoding]::new($false))`
- `clear_data.py` — run `python clear_data.py` from `Brain/` to wipe all Postgres tables + checkpoints in one step (use before a clean re-run)
- **You cannot keep two pipeline runs in the DB at once — snapshot to a Postgres schema instead.** There is no `run_id` column on `calls` / `scenarios` / `kb_pairs` / `rubrics`, and each has a UNIQUE constraint (`calls.filename`, `scenarios.scenario_key`, `rubrics.scenario_id`, plus a unique index on `kb_pairs(call, turn)`), so a second run collides rather than coexisting. To compare before/after, copy the four tables server-side first — `CREATE SCHEMA baseline_<date>; CREATE TABLE baseline_<date>.<t> AS SELECT * FROM <t>;` — which needs no `pg_dump`, keeps both versions queryable in SQL, and copies rows only (no constraints), then run `clear_data.py`. Existing snapshot: **`baseline_20260728`** = the pre-rework run (calls 416, scenarios 149, kb_pairs 4605, rubrics 148 — note the 149-vs-148 gap that `_reconcile` now prevents).
- **Skipping `clear_data.py` does not preserve a run, it produces a no-op run.** `run_id` is a hash of the sorted transcript stems, so re-running the same 416 transcripts yields the *same* `run_id`; `checkpoints.db` then reports the work as already done and the pipeline skips it. Clearing checkpoints is mandatory for a genuine re-run, which is why `clear_data.py` does both.
- A pre-rework baseline lacks the evidence columns (`is_coachable`, `cluster_kind`, `triage_verdict`, `rubric_status`, milestone support fields), so comparing against it is a "taxonomy before vs after" diff, **not** a controlled A/B of individual knobs. A real A/B needs two *post-rework* runs differing in one knob — double the Gemma spend, so decide deliberately.
- Gemma sometimes returns a bare JSON array `[...]` instead of `{"scenarios": [...]}` — always guard with `result if isinstance(result, list) else result.get("key", [])`
- `llama-text-embed-v2` cosine similarities between short conversational utterances and abstract scenario descriptions are very low in practice (max ~0.14 observed) — `_SIMILARITY_THRESHOLD` in `layer_b.py` is the tuning knob; centroid fallback ensures no pair stays unassigned
- `ego_trap/settings.py` defaults (e.g. `STEP_0_MODE=similarity`) can be silently overridden by `Brain/.env` — always check `.env` before trusting a settings.py default
- `EGO_TRAP_SIMILARITY_THRESHOLD` has the same low-cosine-similarity issue as `layer_b.py`'s `_SIMILARITY_THRESHOLD` — anything above ~0.35-0.4 effectively disables similarity-mode signal detection; tune down, not up
- `storage.get_connection()` must use `autocommit=True` — a bare read left uncommitted holds a transaction open across slow Pinecone/Gemma calls until Neon kills it with `IdleInTransactionSessionTimeout`
- `storage.reconnect_if_closed(conn)` must be explicitly called before DB writes inside any loop with slow work (Gemma/Pinecone) between iterations — it exists but isn't automatic; skipping it causes `OperationalError: SSL connection has been closed unexpectedly`
- Pinecone client/Index objects must be cached at module level (see `preprocessing/embedder.py`) — rebuilding them per call (as `shared/pinecone_store.py` used to) is ruinously slow when called once per transcript turn
- Never grep/cat the whole `.env` file to check one setting — it prints `GEMMA_API_KEY`/`DATABASE_URL` in plaintext; grep for the specific key only (e.g. `grep '^STEP_0_MODE=' .env`)
- `run_ego_trap.py` fires Gemma calls back-to-back across transcripts with no pacing — `STEP_0_MODE=gemma` doubles call volume (Step 0 + Step 3 per transcript) and increases 429/503 retry-backoff stalls (`gemma.py`'s backoff can add up to 62s per call)
- Adding a column to an existing table requires an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `schema.sql` alongside the updated `CREATE TABLE IF NOT EXISTS` literal — `db/init_db.py` only creates missing tables, it never alters existing ones
- **There are TWO separate substantive-text filters and they do not share a knob.** `v1/layer_b._is_substantive` uses its own module constant `_MIN_CONTENT_WORDS = 5`; `shared/cluster_evidence.is_substantive` takes its threshold from `tuning.yaml`'s `layer_a.min_content_words`. Editing `tuning.yaml` does **not** change Layer B pair extraction — change the constant in `layer_b.py` for that
- `storage.get_scenarios` **must** select `is_coachable` and `cluster_kind`. It backs `_load_scenario_map`, which is the checkpoint-resume path — without them a resumed run treats every mechanics sink as coachable and generates rubrics for backchannel
- `layer_c`'s `min_milestone_calls_floor: 3` means a scenario whose responses span fewer than 3 calls can never satisfy the support gate, so it always falls through to the V1 Gemma fallback. That is intended (V1 still produces a rubric), but it means small scenarios are not clustered — don't read it as a bug
- V2 Layer A adjudication deliberately makes **no DB calls inside the Gemma loop**; all scenarios are written in one pass afterwards. Holding a Postgres connection across ~200 sequential Gemma calls invites the `IdleInTransactionSessionTimeout` / SSL-drop failure mode. Don't add an `upsert` back into that loop
- `tuning.yaml` keys are validated on load — an unknown or missing key raises rather than silently falling back to a default. Add the key to both `tuning.yaml` and the dataclass in `shared/tuning.py`, or the loader fails
- A threshold must never be a count of outputs or a curated list. Every knob in `tuning.yaml` is a property of the data (fraction of calls, cosine distance, relative margin, percentile) so that adding transcripts re-derives every bound. `MAX_CLUSTERS=150` is the cautionary tale: a count halts at N whether duplication remains or not

### Brain Schema (current state)

- `kb_pairs` has `scenario_keys TEXT[]` (added 2026-06-29) — multi-scenario array; `scenario_key TEXT` is the primary/display one used by Layer C queries
- Layer D (Ego Trap, added 2026-07-06): `csms`, `milestone_performance`, `signal_recognition_gaps`, `gap_events` — `gap_events.signal_turn_index` is a transcript turn number, not a timestamp (real call recordings have no timestamps)
- `scenarios` evidence columns (added 2026-07-27) — record *why* each scenario exists so the taxonomy is auditable without re-running the pipeline:
  - `is_coachable BOOLEAN` — false ⇒ no rubric; the row acts as a sink for junk Layer B matches
  - `cluster_kind TEXT` — `scenario` | `mechanics` | `logistics`
  - `support_calls INTEGER`, `support_clauses INTEGER`, `call_coverage REAL` — the cluster's evidence
  - `triage_verdict TEXT` — `scenario_candidate` | `needs_review` (pre-LLM routing)
  - `adjudication_reason TEXT` — the LLM's one-sentence justification. **Required reading for any `needs_review` cluster that stayed coachable** — that is the audit trail replacing the old automatic-mechanics rejection
  - `rubric_status TEXT` — `rubric_generated` | `skipped_not_coachable` | `skipped_insufficient_responses` | `failed`
- Milestone JSONB gains `support_calls`, `support_clauses`, `relevance_mean` per milestone (2026-07-27)
- `primary_topics` table (added 2026-07-30, see spec `2026-07-30-layer-a-topic-hierarchy-design.md`): `primary_topic_key TEXT UNIQUE`, `label`, `description`, `keyphrases`, `grouping_method`, `support_calls`, `support_subtopics`, `call_coverage` — a real parent entity for `scenarios.primary_topic_key` (FK), replacing the old free-text `primary_topic` column that Gemma reinvented independently per subtopic cluster with no dedup. `scenarios.primary_topic` stays as a NOT NULL denormalized label copy so existing simple readers need zero changes; `primary_topic_key` is the real FK for grouping/joins. `storage.get_primary_topics()` mirrors `get_scenarios()`.
- `scenarios.sub_topic` renamed to `scenarios.business_description` (2026-07-30) — `shared/storage.py::upsert_scenario`/`get_scenarios` and `shared/scenario_vectors.py::scenario_text` all updated together; grep for `sub_topic` before trusting any old snippet or doc reference to it.

### V2 evidence-triage clustering (2026-07-27)

Design: `docs/superpowers/specs/2026-07-27-evidence-triage-clustering-design.md` (read the **Amendment** section — it corrects the approved design against measured data).

Core principle: **cluster freely, then triage clusters against evidence.** Filtering 74k utterances can never be exhaustive; judging ~200 clusters is cheap enough to afford real evidence. Whatever survives *is* the taxonomy — there is no target count.

- `MAX_CLUSTERS=150` / `reduce_topics` is **deleted**. It merged the *rarest* topics first by c-TF-IDF keyword overlap — the opposite end of the distribution from the backchannel families that duplicate, and blind to them anyway since `"Perfect. Alright then"` and `"yeah that makes sense"` share no vocabulary.
- Layer A: similarity-merge topic centroids → `cluster_evidence.triage` → one Gemma call per surviving cluster via `PROMPT_LAYER_A_V2_TRIAGE`, which sees the cluster's own stats **and the top-3 nearest already-accepted scenarios**, so it can tell it is looking at the 9th acknowledgment variant. Clusters are adjudicated largest-first so the best-evidenced member of a family becomes canonical.
- `triage()` returns `scenario_candidate` | `needs_review` | `insufficient_evidence`. **High coverage is a review flag, never a rejection** — it condemned ~50% of clusters when it was a verdict, because a core business topic legitimately appears in most calls. Only `insufficient_evidence` is terminal (and it saves a Gemma call).
- Non-coachable clusters are **kept** as sinks (`is_coachable=false`, `cluster_kind` `mechanics`/`logistics`), not deleted. Layer B files junk there instead of contaminating a real rubric.
- Layer B: relative top-K (`>= relative_margin * best`, capped) replaces the absolute `_SIMILARITY_THRESHOLD = 0.30`, which did not scale — at 149 scenarios 70% of pairs matched nearly all of them. If the best match is a sink, the pair is filed there **alone**. The centroid fallback is gone: a relative cutoff always keeps at least the best match, so no pair can be unassigned.
- Layer C: scenario-relevance percentile filter on the response clause pool, then a **distinct-call support gate** (`max(floor, ceil(fraction * scenario_call_count))`). `min_cluster_size=2` was the 95-milestone bug — with no provenance, two adjacent clauses of ONE response counted as "recurring". `milestone_hard_cap` is a backstop that logs loudly; if it binds, the support floor is miscalibrated.
- Every scenario ends with a non-null `scenarios.rubric_status`; `v2/pipeline.py::_reconcile` prints the status table and **raises** if any is unset. This is what makes a silent 149-scenarios-vs-148-rubrics gap impossible.

**First production V2 run (2026-07-28)** — `relative_margin 0.95`, `percentile 40`, `fraction 0.10`, `merge 0.85`, `ubiquity 0.60`. Baseline for comparison is Postgres schema `baseline_20260728`.

- 416 calls, **158 scenarios** (85 coachable + 66 mechanics + 7 logistics), 4605 kb_pairs, **85 rubrics**. `rubric_status` = 85 `rubric_generated` + 73 `skipped_not_coachable`, **no NULLs** — `_reconcile` passed. The baseline's 149-vs-148 gap is gone.
- Cheap because sinks skip Layer C entirely: 158 triage calls, but rubric generation ran for 85 scenarios instead of ~148.
- **Coverage-flags-never-rejects is confirmed by the data, in both directions.** 62 of the 73 sinks were `scenario_candidate` with coverage **0.38–0.52, all below the 0.60 ceiling** — triage passed them and only the LLM caught them (`conversational_confirmation_and_fillers`, `generic_greetings_and_pleasantries`, `client_hedging_and_fillers`, …). A coverage-only rule would have admitted every one. Conversely, of 16 `needs_review`, 11 were junk and **5 were real business topics** that the old reject-on-coverage rule would have destroyed: stakeholder roles (0.80), budget/spend (0.77), timeline/feasibility (0.75), technical integration (0.67), client knowledge-gap admission (0.64).
- So **46% non-coachable is not the "~50% mechanics is implausible" failure returning.** That failure was coverage condemning real topics blind; here every rejection carries a specific content justification in `adjudication_reason` and the survivors are genuine. Read the reasons before ever re-litigating this.
- Observed max cluster coverage is now **0.798** (earlier calibration recorded 0.74).
- **Production match width was 63% / 19% / 18% (one/two/three scenarios), not the dry run's predicted 47/25/27, and 39.7% of pairs went to a sink vs 13.3% predicted.** Both follow mechanically from 73 sinks instead of 15 — more pairs hit the sink short-circuit and never reach the margin. Not a margin miscalibration.

**Layer C UMAP+HDBSCAN is not reproducible across separate process launches — confirmed 2026-07-28/29.** The first production V2 run above stored 241 milestones across the 85 rubrics. A Gemma-free replay of Pass 1 clustering (separate process, identical code/config/corpus) predicted 403-407 candidates instead, with only 21 ever flagged for the batch judge — a gap the judge mechanism cannot explain since it's capped at removing 21. Per-scenario evidence made this undeniable: `client_availability_and_scheduling_friction`'s stored rubric had 3 milestones (`support_calls=[8,4,4]`), the replay found 10 candidates (`support_calls=[4,4,4,4,6,6,7,16,15,7]`) where **8 does not appear anywhere in the replay's list**, and a third independent process launch (after adding batched milestone-description, see below) produced yet a third answer: 8 milestones. Config drift, judge-mechanism bugs, and a partial/restarted run were all ruled out first (reconciliation passed cleanly each time; `tuning.yaml` matched byte-for-byte; the printed review-flag threshold line proved Pass 1 ran over the full 85-scenario corpus in one continuous pass). `umap.UMAP(random_state=42)` pins the RNG but evidently does not guarantee byte-identical output across **separate process invocations** — the same failure mode already documented above for Layer A's BERTopic pipeline (241→231→226 raw clusters for one identical corpus), now confirmed for Layer C's own UMAP+HDBSCAN step too. Two independent process launches (the Gemma-free replay and a full rerun with batching) landed within ~2% of each other (403-407 vs 398 actual milestones) — the *original* 241-milestone run was itself the anomalous low outlier, not a bug in the kept-list/judge code downstream of it. **Open design question, not yet resolved:** accept the run-to-run variance and document it, force stricter UMAP determinism (e.g. pin to a single BLAS thread), or run Pass 1 multiple times and take a consensus/union of clusters. Do not "fix" this by re-tuning a `tuning.yaml` threshold — the variance is upstream of every knob in this file, in the clustering algorithm itself.

- Milestone-describe Gemma calls are now **batched** (`_DESCRIBE_BATCH_SIZE = 5` in `v2/layer_c.py`, mirroring the existing milestone-triage batch and Layer A's triage batch): one `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` call per 5 surviving milestones across ALL scenarios, replacing one call per milestone (was the dominant Gemma call count in Layer C, ~241-403 individual calls). `run_layer_c_v2` is now four passes (cluster → judge → sequence/kept → batch-describe → finish), not three — see its docstring. Batching Pass 3 doesn't confound the reproducibility question above: Pass 1 clustering is Gemma-free and unaffected by how Pass 2/3 batch their calls.

**Verdict rendered 2026-07-29 (full detail: design spec's "Verdict" section): the reproducibility question above is resolved — accept the variance, don't engineer determinism.** A clean overnight full pipeline run (`run_full_pipeline_20260722.log` — note the filename dates on the three logs from that day do not reflect actual run order, only this one reached `RECONCILIATION`) produced 158 scenarios / 77 rubrics / **404 total milestones**. That is now 3 of 4 post-UMAP measurements landing within ~2% of ~400 (398, 403-407 predicted, 404), confirming the original 241-milestone production run was the sole anomalous outlier. Quality spot-check (10 rubrics across the full depth range) showed no backchannel/junk leakage. **Adopted as the new live baseline**, snapshotted to schema `v2_overnight_20260729`. Cheap mitigation recommended, not yet implemented: log-warn if a future run's total milestone count falls outside ~[350, 450].

- **New, separate finding from the same run: Layer A's BERTopic clustering geometry is fully reproducible (237 raw -> 171 clusters -> 158 scenarios, identical to the prior production run) now that `embed_cache.db` is warm, but its per-cluster Gemma coachability adjudication is not** — 78 coachable this run vs 85 previously, for the *same* underlying clusters. Comparing by `scenario_key` string is a trap (Gemma generates a fresh name per run — confirmed pairs like `stakeholder_role_identification` vs `stakeholder_role_mapping` are the same cluster renamed); comparing by `support_calls`/`call_coverage` size-signature shows most of the "diff" is renaming, with a real ~5-6% of clusters (roughly 7-10 of 158) actually flipping across the coachable/mechanics boundary between independent runs. Not root-caused — plausible cause is the largest-cluster-first adjudication order cascading through the "top-3 nearest already-accepted scenarios" context each cluster sees. **Open follow-up, unscoped.**
- **The `run_full_pipeline_20260729.log` attempt that same night crashed** on `scenarios_bloom_level_check` (Gemma returned `bloom_level="explain"`, not a valid enum value) — already fixed by a guard in `shared/storage.py::upsert_scenario` (clamps any invalid value to `"understand"` and logs a warning instead of raising) that was sitting uncommitted in the working tree; commit it.

Calibration gotchas:

- `min_call_support_fraction` is **inert** at this corpus size (dropped 0–3 of 226 clusters across the whole sweep grid) because BERTopic's `min_cluster_size` is already 50 clauses. It is a small-corpus safety floor — do not credit it with removing junk.
- `merge_cosine_threshold` and `ubiquity_ceiling` **interact**: merging unions the member call sets, which raises each surviving cluster's coverage. They cannot be tuned independently.
- **`relative_margin` does NOT feed Layer C — measured 2026-07-28.** This was assumed to couple and it does not. Re-running `dry_run_layer_bc.py` at margin 0.95 produced a **byte-identical** Layer C table to the 0.85 run, because Layer C keys off the single primary `scenario_key` (the best match) while `relative_margin` only controls the *additional* entries in `scenario_keys`. So the two knobs are independent and can be calibrated in either order. `relative_margin` is also `layer_b` only — **Layer A never reads it** — so changing it never requires re-running the Layer A dry run either.
- One dry run measures the **whole** Layer C grid: the sweep evaluates every `(percentile, fraction)` combination in a single pass, so selecting a row afterwards needs no re-run. Only changing something *upstream* of the clustering (the clause pool, the merge threshold, the embeddings) invalidates the table.
- Any Layer B sweep **must model the sink short-circuit**. `assign_scenarios` files a pair whose *best* match is a sink to that sink alone, never reaching the margin logic. A sweep that ignores this reports a match width production would never produce (it disagreed with production's own output by 99.7% vs 14% on first attempt).
- **`relative_margin: 0.85` was confirmed too permissive at full scale, and 0.95 is the calibrated value.** The narrow-band prediction held: measured over 416 transcripts, best-match cosine is `p10=0.496 p50=0.550 p90=0.613` (spread 0.117 — the band is real but sits higher than the 30-transcript smoke test suggested). `0.85 × p50 = 0.467` falls below p10, so nearly everything cleared: 64% of pairs hit the 3-scenario cap. `0.95 × p50 = 0.522` lands near p25 and gives 47% one match / 25% two / 27% at cap. Full sweep is recorded inline in `tuning.yaml`.
- Merge threshold must be validated by **reading the groups** (`--merge-detail`), not by cluster count. At 0.80 it fused campaigns + sales team + brand + markets + vendors into one cluster; 0.85 unifies the true duplicate families while leaving distinct business topics separate. Below ~0.85 the centroids of large clause sets converge toward a generic "conversation" direction, so aggressive merging destroys real distinctions *before* it removes duplicates.
- **Layer C is calibrated to `percentile=40`, `fraction=0.10` (2026-07-28).** Measured zero-milestone counts out of 154 coachable scenarios: percentile 40 → 74/74/75/87 across fractions 0.05/0.10/0.15/0.25; percentile 60 → 83/83/86/96; percentile 75 → 80/80/89/99. 40 is the minimum-zero percentile; the old guess of 60 cost 9 extra all-zero scenarios for nothing. Between 0.05 and 0.10 (both 74) pick **0.10**, because the floor of 3 dominates until 30 calls rather than 60, keeping the fraction a live self-scaling term instead of an inert one. `capped` is 0 at every grid point, so `milestone_hard_cap` never binds.
- **The dry run's 48%-zero-milestone forecast did not materialise — production was 3 of 85 (2026-07-28).** The dry run predicted 74 of 154 coachable scenarios would end with no clustered milestone. Production produced 3 empty rubrics out of 85 (distribution 0→3, 1→20, 2→36, 3→21, 4→5). The forecast was wrong because the dry run's pseudo-taxonomy assumed only 15 sinks while Gemma actually sinked 73: the clusters that could not clear `min_milestone_calls_floor: 3` were largely *the junk itself*, so removing it removed the zero-milestone problem. **Lesson: the dry run cannot predict Layer C yield, because it cannot predict coachability** — that is Gemma's call, and it is the dominant term. Treat dry-run Layer C numbers as an upper bound on scenario count, not a forecast of milestone yield.
- **Milestone fallback split is always whole-scenario, never mixed within a rubric — measured 2026-07-31 (previously unmeasured).** Queried `support_calls IS NULL` grouped by `scenario_id` against both full-corpus post-rework snapshots: `v2_alpha_20260728` (82 rubrics with milestones: 87 clustered + 88 fallback → 51 all-clustered / 31 all-fallback / **0 mixed**) and `v2_overnight_20260729` (73 rubrics: 403 clustered + 1 fallback → 72 all-clustered / 1 all-fallback / **0 mixed**). A scenario's milestones are either entirely clustered or entirely Gemma-written, never a blend — the earlier "roughly half fallback" framing was correct in aggregate but never actually implied per-rubric mixing.
- **Never hardcode a near-tie ratio in a Layer B test.** `test_ambiguous_trigger_keeps_the_near_ties` baked in a 0.95 second-match weight, which silently meant "comfortably above the cutoff" only while the margin was 0.85; at 0.95 it landed exactly on the boundary and failed on float rounding. It now derives the tie from `load_tuning().layer_b.relative_margin`, so it tests the rule at any margin. A passing suite proves nothing is broken — it never proves a threshold is *right*; only the sweep does that.

### Layer A primary_topic hierarchy + Layer B two-stage matching (2026-07-30/31)

Designs: `docs/superpowers/specs/2026-07-30-layer-a-topic-hierarchy-design.md`, `2026-07-30-layer-b-two-stage-matching-design.md`, `2026-07-31-layer-a-primary-topic-coachability-split-design.md`.

Problem: `scenarios.primary_topic` was never a real grouping — free text Gemma reinvented per subtopic cluster, no dedup or shared identity across clusters. This work gives it a real parent entity (`primary_topics` table) and, separately, explores whether matching triggers to a `primary_topic` first and a subtopic second (instead of flat subtopic matching) improves Layer B assignment.

**Status — what's actually live vs still a harness, as of 2026-07-31:**

- **Production / wired in:** `v2/layer_a.py::_finalize_primary_topics` builds `primary_topics` rows via `topic_grouping.group_post_hoc`/`group_nested` + `split_by_coachability` (the coachability-mixing fix). This runs in every V2 pipeline execution now, including the full-corpus run described below.
- **NOT production — calibration-only:** `v1/layer_b.py::assign_scenarios_two_stage(strategy=...)` (strict/soft/fallback) is NOT called anywhere in the real pipeline. Its own docstring says so explicitly: *"UNCALIBRATED as of 2026-07-30 — primary_topics is empty until a real [run]... vectors in tests/test_two_stage_matching.py, never dry-run-compared."* The only caller today is `compare_matching_subset.py`, a standalone comparison harness. Production `assign_scenarios` (flat matching) is unchanged. Adopting a strategy means wiring it into `assign_scenarios` (or its caller) deliberately — it will not happen by itself.
- **Zero-Gemma double vector population:** primary_topic vectors (`build_primary_topic_vecs`) are a separate embedded population from scenario vectors, not a subset or reuse — expect `embed_cache.db` growth from this alone the first time a corpus runs through it.

**150-call subset validation (post coachability-split + gemma-retry fix), measured 2026-07-31** — snapshotted to schema `subset150_postfix_20260731` (150 calls, 71 scenarios, 34 primary_topics, 1642 kb_pairs, 35 rubrics):

- Two-stage `fallback` strategy vs flat: 86.6% top-1 agreement, 86.6% recall-proxy, mean Jaccard 0.824 — better than `strict` (79.6%/79.6%/0.760) and roughly matching `soft` (85.9%/91.6%/0.827) but with fewer average matches (1.19 vs 1.29).
- `two_stage_fallback_floor` sweep (857 non-sink pairs): floor 0.30–0.40 barely reroutes anything (reroute% <0.5%, agreement ~79.6-79.8%); floor 0.50 reroutes 9.6% and lifts agreement to 86.6%; floor 0.60+ reroutes 42%+ and pushes agreement past 99% (at which point it's converging back toward flat matching, so the floor is trading away whatever benefit two-stage was supposed to add). **No floor has been chosen for production** — this sweep is input to that decision, not a decision itself.
- This was subset-scale only. Every other threshold in this codebase shifted between subset and full-corpus calibration before (`relative_margin`, `merge_cosine_threshold`) — the equivalent full-416-call validation is the next real step before treating any of these numbers as calibrated.

### Brain Architecture Notes

- `run_id` is a stable sha1 hash of sorted transcript stems — same transcript files across re-runs reuse checkpoints automatically; adding/removing a transcript generates a new run_id
- `assign_scenarios` (v1/layer_b.py): per-pair cosine sim ≥ 0.30 → multi-match into `scenario_keys`; pairs that match nothing fall back to call centroid — no pair is ever left `None`; `_is_substantive()` removes scheduling/filler pairs before they reach assignment
- `v1/layer_a.py` splits into `identify_scenarios()` (Gemma only, no DB) and `store_scenarios()` (DB only); pipeline closes the Postgres connection before the Gemma call and opens a fresh one after — prevents idle SSL drops
- `storage.get_connection()` uses TCP keepalives (idle=30s, interval=10s, count=5) to survive long LLM calls
- `gemma.py` retries (max 5, exponential backoff) on 429/500/503/504/internal/deadline errors; 3-min HTTP timeout. **Fixed 2026-07-31 (uncommitted):** raw `httpx.TransportError` subclasses (SSL read drops, connect timeouts, protocol resets) were falling through the string-marker check and raising immediately instead of retrying — string-matching error text couldn't keep up with how many ways a socket layer phrases a drop (`"_ssl.c:2580"` etc.). Now checked by type (`isinstance(e, httpx.TransportError)`) alongside the marker list.
- Utility scripts (2026-07-30/31): `run_v2_subset.py <dir>` — non-interactive V2 pipeline runner against an arbitrary recordings directory, for calibration on a call subset; use this instead of `main.py` for scripted/unattended runs since `main.py` blocks on an interactive V1-vs-V2 prompt. `compare_matching_subset.py` — zero-Gemma harness comparing flat matching against `assign_scenarios_two_stage`'s strict/soft/fallback strategies on an already-populated DB; `--sweep-floor` sweeps `two_stage_fallback_floor` and reports agreement/recall-proxy/Jaccard against flat per floor value.
- Utility scripts: `backfill_scenarios.py` (reassign scenario_keys on existing pairs), `rerun_layer_c.py` (re-run Layer C for specific scenarios)
- Real CSM call recordings (`csm_recordings/*.txt`) have no timestamps or role tags — same plain blank-line-separated `Name`/`Utterance` format as `recordings/`, not the `[HH:MM:SS] Name (ROLE):` format `Ego_trap.md` specs; `ego_trap/transcript_parser.py` resolves CSM vs OTHER_JOVEO vs CLIENT via `csm_recordings/mapping.csv`'s `csm_name` (must match the transcript speaker line) plus `JOVEO_SPEAKER_NAMES`
- `preprocessing/embedder.py` batches at 96 inputs per call — Pinecone's hard limit for `llama-text-embed-v2`; a single long call transcript (100+ turns) will 400 without it
- `milestone_scoring.score_milestones()`/`score_soft_skills()` make one Gemma call per milestone/per soft-skill name, not one per signal — prefer `score_milestones_batch()`/`score_soft_skills_batch()` with `ego_trap.settings.GEMMA_BATCH_SIZE` (env `EGO_TRAP_GEMMA_BATCH_SIZE`, default 4) to combine multiple signals per Gemma call
- `ego_trap/pipeline.py`'s `run_ego_trap_batch()` runs 5 staged passes per transcript (response-check → rubric lookup → batch-pull response/benchmark text → Gemma batch-score → write) — each stage processes all signals before the next starts, not a single per-signal loop
- `Brain/ego_trap/RUN_NOTES.md` tracks gap-analysis results across pipeline runs/threshold tuning for comparison — update it after Ego Trap tuning runs since clearing data destroys the prior run's DB state
- `signal_check.py`'s response classification is `response_outcome` (`"csm"` / `"other_joveo"` / `"none"`), not a `csm_responded` boolean — computed in code by `transcript_parser.classify_response_outcome` from actual turn roles, never asked of the LLM (even in `STEP_0_MODE=gemma`). `"other_joveo"` (a teammate answered, not the CSM) writes a `Deferred_To_Teammate` gap_event via `gap_output.write_deferred_to_teammate` and is excluded from `signal_recognition_gaps` recognized/missed counters; only `"none"` writes `Signal_Recognition_Failure`
- Milestone scoring (Step 3) returns a 3-tier `verdict` (`full_hit`/`partial_hit`/`miss`) with `quote`/`gap_to_ideal` evidence gated to non-`full_hit`, not a boolean `hit` (changed 2026-07-13, see `docs/superpowers/specs/2026-07-13-milestone-verdict-tiers-design.md`) — `milestone_performance.hits` now means full_hit count only, `partial_hits` tracks partial separately, weighted score = `(hits + 0.5*partial_hits)/attempts` computed at query time, not stored
- A 0% (or near-0%) milestone hit rate is not necessarily a rubric-wording/prompt-bias problem — confirmed on 2026-07-06 by reading actual Gemma `reason` text in `gap_events.gaps`: every miss was a legitimate content critique, none referenced the responder's name/identity. The real cause was the `EGO_TRAP_SIMILARITY_THRESHOLD` (0.35) matching topic-irrelevant small talk (e.g. "I'm good, thank you", calendar chat) to real scenarios — milestone scoring was correctly failing content-empty false-positive signals, not misbehaving. Before assuming a rubric/prompt fix, pull the stored reasons and cross-check a sample against the source transcript at its `signal_turn_index` first
