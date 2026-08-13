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
- `ego_trap/` — gap-analysis pipeline (Steps 0-4 + Layer D) scoring CSM calls against Naren's rubrics; `ops/run_ego_trap.py` is its non-interactive batch entry point, `ops/clear_ego_trap_data.py` resets only its own tables

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
- `ops/clear_data.py` — run `python ops/clear_data.py` from `Brain/` to wipe all Postgres tables + checkpoints in one step (use before a clean re-run)
- **You cannot keep two pipeline runs in the DB at once — snapshot to a Postgres schema instead.** There is no `run_id` column on `calls` / `scenarios` / `kb_pairs` / `rubrics`, and each has a UNIQUE constraint (`calls.filename`, `scenarios.scenario_key`, `rubrics.scenario_id`, plus a unique index on `kb_pairs(call, turn)`), so a second run collides rather than coexisting. To compare before/after, copy the four tables server-side first — `CREATE SCHEMA baseline_<date>; CREATE TABLE baseline_<date>.<t> AS SELECT * FROM <t>;` — which needs no `pg_dump`, keeps both versions queryable in SQL, and copies rows only (no constraints), then run `ops/clear_data.py`. Existing snapshot: **`baseline_20260728`** = the pre-rework run (calls 416, scenarios 149, kb_pairs 4605, rubrics 148 — note the 149-vs-148 gap that `_reconcile` now prevents).
- **Skipping `ops/clear_data.py` does not preserve a run, it produces a no-op run.** `run_id` is a hash of the sorted transcript stems, so re-running the same 416 transcripts yields the *same* `run_id`; `checkpoints.db` then reports the work as already done and the pipeline skips it. Clearing checkpoints is mandatory for a genuine re-run, which is why `ops/clear_data.py` does both.
- A pre-rework baseline lacks the evidence columns (`is_coachable`, `cluster_kind`, `triage_verdict`, `rubric_status`, milestone support fields), so comparing against it is a "taxonomy before vs after" diff, **not** a controlled A/B of individual knobs. A real A/B needs two *post-rework* runs differing in one knob — double the Gemma spend, so decide deliberately.
- Gemma sometimes returns a bare JSON array `[...]` instead of `{"scenarios": [...]}` — always guard with `result if isinstance(result, list) else result.get("key", [])`
- `llama-text-embed-v2` cosine similarities between short conversational utterances and abstract scenario descriptions are very low in practice (max ~0.14 observed) — `_SIMILARITY_THRESHOLD` in `layer_b.py` is the tuning knob; centroid fallback ensures no pair stays unassigned
- **`ego_trap/settings.py` no longer exists (deleted 2026-08-10).** It was the only config surface in Brain reading bare `os.environ` at import time, which is what let a `.env` line silently override a value the reader believed they had set in code — and it had already produced a live divergence (settings.py default `0.75` vs `.env`'s actual `0.35`). Every Layer D knob is now a validated `tuning.yaml` key under `layer_d:`, read once via `get_tuning().layer_d` at the entry point and threaded as a parameter. `ops/run_ego_trap.py::_reject_retired_env` **exits 1** if `STEP_0_MODE`, `ENABLE_GAP_EVENTS`, `EGO_TRAP_SIMILARITY_THRESHOLD` or `EGO_TRAP_GEMMA_BATCH_SIZE` is still set in `.env` — a stale line there reads as authoritative while doing nothing, which is worse than either state
- **`EGO_TRAP_SIMILARITY_THRESHOLD`'s "tune down, not up" advice is retired — the knob is gone, and the reason is measured.** The absolute cosine floor was replaced by the relative rule in `shared/relative_match.py`. Measured 2026-08-10 against the real 201-client-turn CSM corpus, best-match cosine is `p10=0.501 p25=0.540 p50=0.581 p75=0.615 p90=0.648` — so the live `0.35` sat **below the entire distribution and admitted 100.0% of client turns**, "Thank you." included. (That band also confirms Layer D shares layer_b's embedding band: `p10=0.496 p50=0.550 p90=0.613` over 416 transcripts.) In similarity mode the accept/reject decision is now made **entirely by the sink comparison** — a turn is a signal iff its best match is coachable rather than a sink. Measured rejection rate 122/201 (60.7%), 108 to mechanics + 14 to logistics, and the highest-scoring rejections read correctly ("Thank you.", "Yeah. That makes sense.", "Good.")
- **`layer_d.similarity_relative_margin` is INERT at the shipped `max_scenarios_per_signal: 1` — do not try to tune it there.** The dry run's sweep returned exactly 79 signals at every value 0.85→0.99. That is arithmetic, not a bug: `topk_pick` takes `candidates[:cap]` and `sims[best] >= margin * sims[best]` holds for every `margin <= 1`, so the margin only governs how many *additional* near-ties survive and at cap 1 there are none. Same class of finding as `min_call_support_fraction` being inert at this corpus size. Pinned by `tests/test_relative_match.py::test_margin_is_inert_at_cap_one` so the note cannot quietly stop being true
- `storage.get_connection()` must use `autocommit=True` — a bare read left uncommitted holds a transaction open across slow Pinecone/Gemma calls until Neon kills it with `IdleInTransactionSessionTimeout`
- `storage.reconnect_if_closed(conn)` must be explicitly called before DB writes inside any loop with slow work (Gemma/Pinecone) between iterations — it exists but isn't automatic; skipping it causes `OperationalError: SSL connection has been closed unexpectedly`
- Pinecone client/Index objects must be cached at module level (see `preprocessing/embedder.py`) — rebuilding them per call (as `shared/pinecone_store.py` used to) is ruinously slow when called once per transcript turn
- Never grep/cat the whole `.env` file to check one setting — it prints `GEMMA_API_KEY`/`DATABASE_URL` in plaintext; grep for the specific key only (e.g. `grep '^STEP_0_MODE=' .env`)
- `ops/run_ego_trap.py` fires Gemma calls back-to-back across transcripts with no pacing — `STEP_0_MODE=gemma` doubles call volume (Step 0 + Step 3 per transcript) and increases 429/503 retry-backoff stalls (`gemma.py`'s backoff can add up to 62s per call)
- Adding a column to an existing table requires an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `schema.sql` alongside the updated `CREATE TABLE IF NOT EXISTS` literal — `db/init_db.py` only creates missing tables, it never alters existing ones
- **There are TWO separate substantive-text filters and they do not share a knob.** `v1/layer_b._is_substantive` uses its own module constant `_MIN_CONTENT_WORDS = 5`; `shared/cluster_evidence.is_substantive` takes its threshold from `tuning.yaml`'s `layer_a.min_content_words`. Editing `tuning.yaml` does **not** change Layer B pair extraction — change the constant in `layer_b.py` for that
- `storage.get_scenarios` **must** select `is_coachable` and `cluster_kind`. It backs `_load_scenario_map`, which is the checkpoint-resume path — without them a resumed run treats every mechanics sink as coachable and generates rubrics for backchannel
- `layer_c`'s `min_milestone_calls_floor: 3` means a scenario whose responses span fewer than 3 calls can never satisfy the support gate, so it always falls through to the V1 Gemma fallback. That is intended (V1 still produces a rubric), but it means small scenarios are not clustered — don't read it as a bug
- V2 Layer A adjudication deliberately makes **no DB calls inside the Gemma loop**; all scenarios are written in one pass afterwards. Holding a Postgres connection across ~200 sequential Gemma calls invites the `IdleInTransactionSessionTimeout` / SSL-drop failure mode. Don't add an `upsert` back into that loop
- `tuning.yaml` keys are validated on load — an unknown or missing key raises rather than silently falling back to a default. Add the key to both `tuning.yaml` and the dataclass in `shared/tuning.py`, or the loader fails
- A threshold must never be a count of outputs or a curated list. Every knob in `tuning.yaml` is a property of the data (fraction of calls, cosine distance, relative margin, percentile) so that adding transcripts re-derives every bound. `MAX_CLUSTERS=150` is the cautionary tale: a count halts at N whether duplication remains or not
- `.gitignore` never applies to already-tracked files. `Brain/*.log` sat in `.gitignore` while 19 logs stayed tracked — they were committed before the rule existed, so 5.2MB of run output rode along in git. If run output appears in `git status` as tracked, the fix is `git rm --cached <file>` (leaves it on disk); editing `.gitignore` does nothing
- **Running the whole suite in one process is unreliable on 16GB Windows; run it file-by-file instead.** spaCy `en_core_web_lg` needs a **contiguous** 392MiB vector table, and four test files load it (`test_layer_b_assignment`, `test_layer_b_v1`, `test_sink_rescue`, `test_two_stage_matching`). Collection dies with any of `numpy._core._exceptions._ArrayMemoryError`, `MemoryError`, `ValueError: Could not reserve memory`, or torch's `OSError [WinError 1455] The paging file is too small`. **Free-MB is not the predictor and none of the obvious fixes work** — measured 2026-08-08/09: failed at 2.1GB free *and* at 2.7GB free, with a 20GB pagefile and 4.7GB commit free; killing 4 stale python processes freed only ~76MB and changed nothing. It is address-space fragmentation, not exhaustion, so don't resize the pagefile or hunt for a memory hog. One file per process always works (each releases its memory on exit) and yields the same 219 passed — in bash: `for f in tests/test_*.py; do ../.venv/Scripts/python.exe -m pytest "$f" -q; done`
- Before moving any Brain script into a subdirectory: grep `__file__` in it (every `Path(__file__).parent / "x"` silently re-resolves to the new subdirectory and needs `.parent.parent`) and confirm it has a `sys.path` bootstrap so `from config import ...` still resolves. Both bit the 2026-08-08 `ops/` move — 11 broken paths and 3 missing bootstraps
- Design specs under `docs/superpowers/specs/` still cite pre-2026-08-08 script paths (`dry_run_layer_a.py`, not `calibration/dry_run_layer_a.py`). Deliberately left alone as dated historical records — CLAUDE.md and each script's own docstring carry the live paths. Don't treat a stale path in a spec as a bug

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
- `response_taxonomy_candidates` table (added 2026-08-07, see below) — the only Brain table besides `scenarios`/`primary_topics` this pass ever writes to; tracks candidates across runs, never stores vectors (matched by pair-id Jaccard overlap, not embedding similarity).

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

**Verdict rendered 2026-07-29 (full detail: design spec's "Verdict" section): the reproducibility question above is resolved — accept the variance, don't engineer determinism.** A clean overnight full pipeline run (`Brain/logs/run_full_pipeline_20260722.log` — note the filename dates on the three logs from that day do not reflect actual run order, only this one reached `RECONCILIATION`) produced 158 scenarios / 77 rubrics / **404 total milestones**. That is now 3 of 4 post-UMAP measurements landing within ~2% of ~400 (398, 403-407 predicted, 404), confirming the original 241-milestone production run was the sole anomalous outlier. Quality spot-check (10 rubrics across the full depth range) showed no backchannel/junk leakage. **Adopted as the new live baseline**, snapshotted to schema `v2_overnight_20260729`. Cheap mitigation recommended, not yet implemented: log-warn if a future run's total milestone count falls outside ~[350, 450].

- **New, separate finding from the same run: Layer A's BERTopic clustering geometry is fully reproducible (237 raw -> 171 clusters -> 158 scenarios, identical to the prior production run) now that `embed_cache.db` is warm, but its per-cluster Gemma coachability adjudication is not** — 78 coachable this run vs 85 previously, for the *same* underlying clusters. Comparing by `scenario_key` string is a trap (Gemma generates a fresh name per run — confirmed pairs like `stakeholder_role_identification` vs `stakeholder_role_mapping` are the same cluster renamed); comparing by `support_calls`/`call_coverage` size-signature shows most of the "diff" is renaming, with a real ~5-6% of clusters (roughly 7-10 of 158) actually flipping across the coachable/mechanics boundary between independent runs. Not root-caused — plausible cause is the largest-cluster-first adjudication order cascading through the "top-3 nearest already-accepted scenarios" context each cluster sees. **Open follow-up, unscoped.**
- **The `Brain/logs/run_full_pipeline_20260729.log` attempt that same night crashed** on `scenarios_bloom_level_check` (Gemma returned `bloom_level="explain"`, not a valid enum value) — already fixed by a guard in `shared/storage.py::upsert_scenario` (clamps any invalid value to `"understand"` and logs a warning instead of raising) that was sitting uncommitted in the working tree; commit it.

Calibration gotchas:

- **NEVER calibrate on the first N scenarios. Alphabetical is not a sample — measured 2026-08-13.** `--limit 8` on `calibration/trial_layer_c_arms.py` returned `ai_capability_discovery`, `application_conversion_flow_discovery`, `ats_*` (four of them), `backend_workflow_logic_discovery` and `budget_and_performance_strategy_optimization` — **every one a subject-matter scenario and not a single client-posture one**, because those all begin `client_` and sort after `budget`. The ceiling run measured those two populations behaving differently (subject-matter mean gap +0.057, 2/25 inverted; posture −0.019, **5/15 inverted**), so an alphabetical prefix silently tests a fix on the half that already worked and reports it as a general result. Four arm comparisons were run this way before the bias was noticed. Use `--sample N` (seeded, stratified, preserves the corpus's posture/subject mix) for any number you intend to believe; `--limit` is a path test only and now prints a warning saying so. **15–20 scenarios is the practical floor** — below that a stratum can hold one or two members and per-population conclusions stop being safe. The report prints the sample's composition and shouts if a stratum is empty. Generalises beyond this harness: every subset selector in `calibration/` should be checked for what it *excludes*, not just how many it keeps.
- `min_call_support_fraction` is **inert** at this corpus size (dropped 0–3 of 226 clusters across the whole sweep grid) because BERTopic's `min_cluster_size` is already 50 clauses. It is a small-corpus safety floor — do not credit it with removing junk.
- `merge_cosine_threshold` and `ubiquity_ceiling` **interact**: merging unions the member call sets, which raises each surviving cluster's coverage. They cannot be tuned independently.
- **`relative_margin` does NOT feed Layer C — measured 2026-07-28.** This was assumed to couple and it does not. Re-running `calibration/dry_run_layer_bc.py` at margin 0.95 produced a **byte-identical** Layer C table to the 0.85 run, because Layer C keys off the single primary `scenario_key` (the best match) while `relative_margin` only controls the *additional* entries in `scenario_keys`. So the two knobs are independent and can be calibrated in either order. `relative_margin` is also `layer_b` only — **Layer A never reads it** — so changing it never requires re-running the Layer A dry run either.
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

- **Production / wired in:** `v2/layer_a.py::_finalize_primary_topics` builds `primary_topics` rows via `topic_grouping.group_post_hoc`/`group_nested` + `split_by_coachability` (the coachability-mixing fix) + `tighten_coachable_groups` (2026-08-02, see below). This runs in every V2 pipeline execution now, including the full-corpus run described below.
- **NOT production — calibration-only:** `v1/layer_b.py::assign_scenarios_two_stage(strategy=...)` (strict/soft/fallback) is NOT called anywhere in the real pipeline. Its own docstring says so explicitly: *"UNCALIBRATED as of 2026-07-30 — primary_topics is empty until a real [run]... vectors in tests/test_two_stage_matching.py, never dry-run-compared."* The only caller today is `calibration/compare_matching_subset.py`, a standalone comparison harness. Production `assign_scenarios` (flat matching) is unchanged. Adopting a strategy means wiring it into `assign_scenarios` (or its caller) deliberately — it will not happen by itself.
- **Zero-Gemma double vector population:** primary_topic vectors (`build_primary_topic_vecs`) are a separate embedded population from scenario vectors, not a subset or reuse — expect `embed_cache.db` growth from this alone the first time a corpus runs through it.

**First full-corpus production run (2026-08-02), `public` schema:** 416 calls, 157 scenarios (81 coachable / 66 mechanics / 10 logistics), 80 `primary_topics`, 4605 kb_pairs, 80 rubrics — `grouping_method: nested` throughout. This is the run that surfaced the two bugs below; both are subtopic/label bugs in `_finalize_primary_topics`, not adjudication or matching bugs.

- **Loose primary-topic grouping fused unrelated coachable scenarios into a mega-blob — confirmed, then fixed.** 26% of coachable scenarios (21 of 81) landed in one `client_discovery_and_requirements` primary_topic spanning budget disclosure, ATS integration, job-board ecosystem, URL redirection config, and market landscape — content with nothing in common beyond a generic "discovery" direction under centroid averaging, the same failure mode `merge_cosine_threshold`'s own calibration already documents above one level down the hierarchy. Fix: `shared/topic_grouping.py::tighten_coachable_groups(groups, tight_threshold)` re-clusters every all-coachable group at the tight threshold (reuses `merge_cosine_threshold`, no new tuning key) instead of the loose one; sinks are left untouched (coarse sink grouping is harmless). Deliberately **not** gated on group size — a member-count ceiling is the exact `MAX_CLUSTERS=150` anti-pattern this file already warns against; coachability alone decides eligibility, so a small cohesive group just survives unchanged. Validated Gemma-free against the real 416-call corpus via `calibration/dry_run_layer_a.py`'s own clustering path (zero Gemma calls, zero DB writes, warm embed cache): 59 primary-topic groups (largest 28, an equivalent mega-blob) → 146 groups (largest 4), with the surviving multi-member groups reading as genuinely coherent themes on inspection.
- **Gemma-generated primary_topic labels can collide across separate batch calls.** `_label_primary_topics_batch` batches `_TOPIC_LABEL_BATCH_SIZE` groups per Gemma call, so two different calls can independently invent the same label string for unrelated groups — confirmed in production ("Positive Client Sentiment" assigned to both a 5-member and a 1-member group). `primary_topic_key` already had a uniqueness-suffix guard; the human-readable `label` did not. Fixed with the same suffix treatment (`"Label (1)"` / `"Label (2)"`) applied post-batch.

**150-call subset validation (post coachability-split + gemma-retry fix), measured 2026-07-31** — snapshotted to schema `subset150_postfix_20260731` (150 calls, 71 scenarios, 34 primary_topics, 1642 kb_pairs, 35 rubrics):

- Two-stage `fallback` strategy vs flat: 86.6% top-1 agreement, 86.6% recall-proxy, mean Jaccard 0.824 — better than `strict` (79.6%/79.6%/0.760) and roughly matching `soft` (85.9%/91.6%/0.827) but with fewer average matches (1.19 vs 1.29).
- `two_stage_fallback_floor` sweep (857 non-sink pairs): floor 0.30–0.40 barely reroutes anything (reroute% <0.5%, agreement ~79.6-79.8%); floor 0.50 reroutes 9.6% and lifts agreement to 86.6%; floor 0.60+ reroutes 42%+ and pushes agreement past 99% (at which point it's converging back toward flat matching, so the floor is trading away whatever benefit two-stage was supposed to add). **No floor has been chosen for production** — this sweep is input to that decision, not a decision itself.
- This was subset-scale only. Every other threshold in this codebase shifted between subset and full-corpus calibration before (`relative_margin`, `merge_cosine_threshold`) — the equivalent full-416-call validation is the next real step before treating any of these numbers as calibrated.

**Full-416-call validation, measured 2026-08-03 (`calibration/compare_matching_subset.py --sweep-floor` against the live `public` schema — no code change needed, the script has no hardcoded subset filter): the subset numbers did not hold, and got worse, not better.** Recall-proxy dropped for every strategy: strict 69.9%→61.3%, soft 83.6%→77.0%, fallback(floor 0.50) 82.1%→71.4%. Mechanically consistent with the design's own "central risk" — going from 69 scenarios/28 primary_topics (subset) to 157/80 (full corpus) gives the coarse first stage far more ways to pick the wrong parent category. The floor-sweep gaming pathology also reproduces at full scale (floor 0.50→11.5% reroute/71.4% agreement; floor 0.70→59.3% reroute/100% agreement — still just reverting to flat, not getting more accurate). **Verdict: full-scale data argues against adopting two-stage matching, not for it.** `matching_strategy` stays `flat`. See design spec's "Status update 4" for full detail.

### Layer B sink-rescue: response_only / or_rule / blended (2026-08-04)

Design: `docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`.

Problem: `assign_scenarios` decides sink-vs-real using only the trigger's embedding — if the
trigger's own best match is a non-coachable sink (mechanics/backchannel/logistics), the pair is
filed there alone and permanently excluded from every rubric, even when the trigger is filler
("I'm fine with whatever you guys think") but the response that follows is long and substantive (an
entire analytics-dashboard walkthrough). Reading real sink-filed pairs found this discards real
content at a materially high rate (39.7%–45.8% of pairs across the two production runs, roughly
half of a 30-pair manual sample judged genuinely coachable). `assign_scenarios_with_sink_rescue`
(`v1/layer_b.py`) adds a second, already-computed signal — the response's own embedding — that flat
matching ignores, via three strategies selected by a `strategy` argument exactly like
`assign_scenarios_two_stage`'s: `response_only` (only reconsiders pairs that are sink-bound today,
via the response's own top-K match), `or_rule` (also reconsiders any pair, sink or not, whose
trigger's own top-1 similarity is below a floor), and `blended` (replaces the matching vector for
*every* pair with a weighted trigger+response average, so it can flip the sink decision itself).
**NOT production** — `assign_scenarios` (flat) is unchanged; the only caller of the new function is
`calibration/compare_sink_rescue.py`, a new standalone calibration script (added alongside
`calibration/compare_matching_subset.py` in the Utility scripts list below) that re-runs all three strategies
against the real, already-embedded `kb_pairs`/`scenarios` and prints rescue rates plus verbatim
sample pairs for manual reading.

**Measured 2026-08-04 against the live `public` schema** (157 scenarios, 4,605 pairs, 1,865
sink-bound; full output `Brain/logs/compare_sink_rescue_20260804.log`):

- **Response-vs-scenario similarity is a genuinely different, higher band than the trigger-vs-
  scenario band `relative_margin` was calibrated against** — p10=0.552, p25=0.598, p50=0.635,
  p75=0.664, p90=0.688, vs. the trigger band's p10=0.496, p50=0.550, p90=0.613. This is why the two
  floors this design needs are two separate tuning keys, not one: `sink_rescue_response_min_similarity`
  (response-vs-scenario, document-vs-document) and `sink_rescue_trigger_weak_floor`
  (trigger-vs-scenario, query-vs-document, the same band `relative_margin` uses) — sharing one value
  between them silently breaks whichever wasn't the one being tuned.

- **`response_only` over-rescues badly at the 0.50 placeholder** — 95.2% of sink-bound pairs
  (1,775/1,865) get rescued, and reading the 20 samples confirms most are wrong (goodbyes filed as
  `client_direct_denial`, a "can you hear me?" check filed as `feasibility_and_implementation_request`).
  Absorption concentrates hard in 3 scenarios (798 of 1,775 rescues, nearly half) — the same
  "gravity well" category-collapse pattern already seen at the primary-topic and duplicate-scenario
  levels of this pipeline. Needs `sink_rescue_response_min_similarity` raised toward the measured
  band (p50/p75, not the current 0.50) before this rate means anything.

- **`or_rule` is the only one that isn't obviously broken, but its low 8.5% rescue rate (159/1,865)
  is largely a gating artifact, not evidence of better precision.** ~1,616 of the 1,865 sink-bound
  pairs never reach the response check at all — their trigger's own similarity to the sink is
  already ≥ `sink_rescue_trigger_weak_floor` (0.50), so the trigger-weak gate excludes them before
  the response is ever looked at. That means `or_rule` **structurally cannot address this design's
  own headline motivating case** — a trigger that CONFIDENTLY matches a sink while its response
  carries real content — it only ever helps the narrower, different case of a trigger that is itself
  weak. Also touches 4.7% of already-non-sink pairs (the risk surface the design named). Of the 20
  rescued samples, ~8-9 read as genuinely correct, including recovering the exact case the original
  sink-absorption audit flagged as real lost content.

- **`blended` is not viable at `alpha=0.6`** — rescues 22.4% of sink-bound pairs but destabilizes
  47.6% of pairs that were already matching correctly under flat matching, with no evidence the new
  answers are better.

- **Bottom line: none of the three is wired into production.** `matching_strategy` and
  `sink_rescue_strategy` both stay at their non-adopting defaults (`flat` / `none`) in `tuning.yaml`.
  `or_rule` is the only one worth a second calibration pass — and that pass must move its two floors
  independently: `sink_rescue_response_min_similarity` toward the response band (p50=0.635/p75=0.664),
  while `sink_rescue_trigger_weak_floor` is tuned against the trigger band (p10=0.496/p50=0.550) and
  raising it further would only shrink `or_rule`'s already-narrow qualifying population, not fix its
  precision on the population it does touch.

**Verdict (2026-08-05, after three more rounds): sink-rescue is exhausted — no gating signal tried
separates real content from junk at a usable operating point.** Round 2 raised `or_rule`'s two
floors toward the measured bands and reproduced `blended`'s exact fatal flaw (39.5% rescue rate but
41.9% collateral churn on already-correct non-sink pairs) — confirming this is a signal problem, not
a threshold-tuning problem. The design then pivoted to non-embedding content signals in
`shared/trigger_quality.py`: `concrete_content_density(response)` — measured against a real
150-pair Gemma-labeled ground-truth sample via `calibration/label_trigger_quality_sample.py` — showed almost
total distribution overlap (coachable/not-coachable medians 0.400/0.400, AUC 0.523, indistinguishable
from chance). The two remaining functions in that module were then measured against the same
labeled sample: `sink_real_margin` points the statistically correct direction but is far too weak
(AUC 0.437) — real/sink scenario centroids both sit too close together in embedding space relative
to any one trigger to leave a usable margin — and `trigger_response_coupling` (cosine between a
pair's own trigger and response embeddings) is the best of everything tried, a real and consistent
signal (AUC 0.617), but still nowhere near a value any threshold elsewhere in this codebase was ever
adopted at (compare `response_word_count`'s own AUC of 0.853 in the same sample — a real signal, just
not one that fits this design's content-specificity hypothesis, and not adopted either). Four signal
families — absolute cosine floors (rounds 1-2), content density, and embedding-relationship signals
— have now all failed to reach a usable operating point. `sink_rescue_strategy` stays `none`;
`matching_strategy` stays `flat`; no further signal search is planned. `calibration/label_trigger_quality_sample.py`
now persists its full labeled sample (text, label, reason, every signal, raw embeddings) to
`Brain/artifacts/labeled_trigger_quality_sample.json` and accepts `--load PATH` to re-report with zero DB/Gemma
calls — so a future signal idea against this same ground truth is free. Full detail:
`docs/superpowers/specs/2026-08-04-layer-b-sink-rescue-design.md`'s Status updates 2-5.

**Sibling design also written off, before any code was built (2026-08-05).** A second design,
`docs/superpowers/specs/2026-08-04-layer-b-trigger-quality-gate-design.md` (drop a junk pair between
`extract_pairs` and `assign_scenarios` instead of rerouting it), shared the same labeled sample and
leaned on the same functions — its own combining rule names `concrete_content_density(response)` as
"what the drop decision actually hinges on." That signal's AUC (0.523) and its trigger-side
counterpart's AUC (0.519) are both chance-level, so the rule can't be built. `filter_junk_pairs` and
`compare_trigger_quality_gate.py` were never written — the effort stopped at the design's own
"read the labeled sample first" checkpoint. Both sink-discarding designs are now closed.

**A third, follow-up design (`2026-08-05-layer-b-combined-signal-analysis-design.md`) tried
combining the strongest signals instead of searching for a new one — also closed.** Combining
`response_word_count`, `trigger_response_coupling`, and a new `length_ratio` feature via logistic
regression scored AUC 0.845, *below* `response_word_count` alone (0.853), despite the two core
signals being nearly uncorrelated (r=0.087). Adopting length alone was then reconsidered on its
own merits (its aggregate precision/recall looked decent) and rejected after reading real
samples: it systematically flags long administrative/logistics/small-talk as coachable, and
systematically discards short, sharp strategic pivots and discovery questions as junk — actively
penalizing the terse expert-brevity coaching moves this pipeline exists to capture. Six signal
shapes total, each measured and each failed for a specific, sample-verified reason.

**Approach B (turn position in the call) found one more real signal, still insufficient.**
`edge_distance` (distance from the nearest edge of the call) alone scores AUC 0.636 and is
qualitatively confirmed — pairs right at a call's start/end are predominantly logistics/wrap-up.
Combined with length (near-zero correlation, r=-0.034) it reaches AUC 0.876, the first
combination in this whole effort to beat a single signal (0.853) — but reading its false
negatives found the *same* terse strategic pivots misclassified as before; the aggregate gain
doesn't fix length's core bias. Eight signal shapes measured total, all either failed outright or
carry a disqualifying bias found only by reading real samples. Full detail:
`docs/superpowers/specs/2026-08-05-layer-b-combined-signal-analysis-design.md`.

### Sink-pool population diagnostic — the unit of decision was the bug (2026-08-05)

Design: `docs/superpowers/specs/2026-08-05-sink-pool-population-diagnostic-design.md`. Stopped
searching for a ninth per-pair signal and changed the **unit of decision** to the cluster — the unit
Layer A already adjudicates ~200 of instead of judging 74k clauses. Two new read-only scripts
(`calibration/diagnose_sink_pool.py`, `calibration/replay_layer_c_admitted.py`), plus
`v2/layer_c.build_clause_pool` extracted (behaviour-preserving, `tests/test_layer_c_clause_pool.py`)
so the replay reproduces Pass 1 by **importing** production code rather than copying it.
**Nothing wired into production**: `sink_rescue_strategy` stays `none`, `matching_strategy` stays
`flat`, no `tuning.yaml` change, no scenario added, no pair rerouted.

- **Three facts read out of the code reframed the problem, and two of them point away from Layer B.**
  (1) Sink-filing is *one SQL predicate* — `storage.get_naren_responses_for_scenario`'s
  `WHERE p.scenario_key = %s`; nothing is deleted, Layer C just never queries those rows, and it never
  reads the `scenario_keys` array at all. (2) Layer C already has four aggregate junk defenses, and
  `_relevance_filter`'s own docstring names the exact contamination the sink gate is justified by —
  the justification is pre-rework, from the `min_cluster_size=2` 95-milestone era. (3) **`v2/layer_a.py`
  builds the taxonomy from CLIENT clauses only** (line 34 skips every non-CLIENT turn) — responses never
  vote, so an expert behaviour whose client cues are filler-like has *no scenario it could ever be
  routed to*. Fact 3 is why all eight signals were asked an unanswerable question.

- **Half A (cluster the sink pool, three-way Gemma verdict per cluster) separated what eight per-pair
  signals could not.** 1,865 sink-bound pairs clustered against a **volume-matched control of 1,865
  coachable-filed pairs**; 9 clusters, 47.3% HDBSCAN noise. `genuine_sink` 2 clusters/609 pairs,
  `belongs_to_existing` 5/199, `new_coachable_topic` 2/175. Cross-checked against the *independent*
  150-pair per-pair labeled sample the two verdict families agree in the predicted direction —
  21% / 71% / 80% labeled-coachable respectively. Junk concentrates: one cluster holds 535 pairs at 9%.
  Two homeless topics found with real support: `strategic_performance_consulting` (94 pairs/115 calls)
  and `technical_operational_alignment` (81/113) — **direct confirmation of fact 3**.

- **`real_minus_sink_margin` has no relationship to the verdict even at CLUSTER level** (best margin
  +0.036 is `genuine_sink`; −0.015 is `belongs_to_existing`). Cluster-level averaging was the strongest
  remaining embedding idea. **The embedding-signal search is closed, not merely paused.**

- **Half B (three-arm Layer C Pass-1 replay, zero Gemma, all arms in ONE process) is the first time
  this problem was measured against rubrics instead of a per-pair AUC proxy — and it rejected the
  cheapest fix outright.** Baseline reproduced 385 milestones (inside the documented ~[350,450] band,
  so the replay is faithful). **Deleting the sink short-circuit destroys 82 of 385 milestones (21%) and
  its placebo gained MORE than it did (98 vs 84)** — the entire apparent gain is a pool-size clustering
  artifact. `by_response`: 87 lost. `by_cluster` (route only clusters judged `belongs_to_existing`)
  *appeared* to be the only viable method — 383/385 matched, 1 lost vs its placebo's 6 lost / 0 gained,
  with large support jumps read as "evidence thickening". **That reading was FALSIFIED the same day by
  `calibration/check_milestone_thickening.py` — see the next bullet. `by_cluster` is NOT validated and NOT
  recommended.**

- **`replay_layer_c_admitted._match_milestones` is MERGE-BLIND, and it inflated `by_cluster`'s result.**
  It maps each baseline milestone to its best-overlapping arm cluster *independently*, so when N
  baseline milestones collapse into ONE arm cluster it scores N clean "matched + thickened" milestones
  instead of one destructive merge. Measured in `client_requests_operational_visualization`: three
  baseline milestones (45, 54 and 337 clauses; support 22, 28, 112) all matched the *same* 532-clause
  treatment cluster at support 133 — byte-identical clause lists, i.e. three distinct coaching moves
  fused into one blob. **The admitted content was only 15% of that cluster**, so the merge was driven by
  the clause pool growing (2,315 → 3,239) and UMAP re-partitioning — the same mechanism that destroyed
  82 milestones in `by_trigger_nonsink`, just silent. Milestone count went 6 → 7, which is exactly how
  it hid. Two further traps: **support as a raw count is not comparable across arms** (the 112 → 133 jump
  is 73% → 72% *as a fraction of the scenario's calls*, since 31 new calls arrive with the admitted
  pairs), and the dilution indicator that *was* coded (`support >= 90% of all calls`) reported 0/7 and
  missed it entirely — the correct indicator is "do multiple baseline milestones map to the same arm
  cluster". **Any future Layer C A/B must report a `merged` outcome and normalise support by call count.**
  **Fixed and re-run 2026-08-06/07** — see the next bullet for the corrected result.

- **A placebo arm is mandatory for any future Layer C A/B, and "zero milestones lost" is an
  unachievable bar.** Perturbing a clause pool *at all* costs ~6 milestones to UMAP/HDBSCAN sensitivity
  regardless of content quality — so a loss count is only interpretable against a volume-matched
  placebo. The bar as originally written would have rejected a fix that beats the noise floor.

- **`_match_milestones` merge-blindness fixed and Half B re-run against live data (2026-08-06/07) —
  `by_cluster` is far cleaner than the other two arms but still not a clean win, and no method is
  recommended for production.** Fix: a fourth outcome `merged` (2+ baseline milestones claiming the
  same arm cluster mark all of them `merged`, not `matched`), plus support reported as a fraction of
  each arm's own scenario call count. Sanity-tested against synthetic cases (including the exact
  45/54/337→532-clause example above) before the real re-run. **The fix reproduces the prior update's
  own prediction exactly**: `matched + merged` equals the old inflated `matched` count in both rejected
  arms (`by_trigger_nonsink` 172+83=255, `by_response` 172+92=264) — strong evidence the fix measures
  the right thing. Corrected per-arm counts (of 385 baseline milestones): `by_trigger_nonsink` 172
  matched / 83 merged / 48 split / 82 lost; `by_response` 172/92/34/87; `by_cluster` 375/8/1/1.
  `by_trigger_nonsink` and `by_response` are now rejected *more* decisively — roughly a third of their
  apparent matches were destructive merges, some absorbing up to **10 baseline milestones into one
  cluster** (worse than anything in `by_cluster`), confirmed by reading samples (e.g. `by_response`'s
  `budget_and_spend_disclosure` fuses literal filler — "What are you trialing?", "Does that answer your
  question?" — into a real spend-strategy cluster). `by_cluster` beats its own placebo on lost (1 vs 6)
  and gained (4 genuine new milestones — Scale AI partnership, LinkedIn CPC/CPA, landing-page
  follow-up — vs 0), but **not** on merged (8 vs placebo's 0) — its worst case is a previously
  undetected **5-into-1** collapse in `media_channel_and_retargeting_discovery` fusing genuinely
  distinct sub-topics (which job boards, ATS integration, a pricing model, a generic optimization
  claim). **Verdict, unsoftened: no rescue method is validated for production.** `by_cluster` is the
  least damaging by a wide margin and wins its placebo comparison on every axis except merge count, but
  1 lost + 8 merged is nonzero real damage, not proof of a clean fix. Full detail, including the
  multiplicity distributions and verbatim merged/gained samples: design spec's "Status update
  (2026-08-06/07)" section; raw output `Brain/logs/replay_layer_c_admitted_postfix.log` /
  `Brain/artifacts/layer_c_admitted_replay_postfix.json`.

- **The two proposed scenarios are necessary but NOT sufficient, and Half B could not test them.**
  Routing can only place content into scenarios that exist. And adding them alone captures nothing —
  Layer B matches on the CLIENT trigger, and these pairs were sunk *because* their triggers look like
  filler, so a new scenario attracts nothing. They must be paired with cluster-verdict routing, which
  does not depend on trigger matching at all.

- **New open finding, unrelated to sinks: Layer C's relevance filter barely discriminates by topic.**
  Deliberately wrong placebo clauses survived the p40 cut at 53.9-57.2% vs 57.7-63.0% for real rescued
  content — a ~6-point gap on a filter the pipeline leans on to keep off-topic clauses out of rubrics.

- Also open: **47.3% of the sink pool is HDBSCAN noise**, capping any cluster-based fix at ~53% of the
  problem. `min_cluster_size` resolved to 25 **by hitting the `min_cluster_size_ceiling`** (0.02 × 3730
  = 74.6, clamped), so the clustering is coarse — a finer rerun would likely split the 535-pair junk
  cluster and cut noise. Untested.

### Response-taxonomy auto-pass: closing the sink-pool gap permanently (2026-08-07/08)

Designs: `docs/superpowers/specs/2026-08-07-layer-a-response-taxonomy-gap-design.md`,
`docs/superpowers/specs/2026-08-07-response-taxonomy-auto-pass-design.md`. Full narrative
(problems found, fixes, real-run result) in `Brain/PROBLEMS_AND_FIXES.md`.

Two manual, one-time scripts proved the fix first: `calibration/graduate_sink_topics.py` (graduated
2 known homeless topics from `Brain/artifacts/sink_pool_clusters.json`) and `calibration/dry_run_response_taxonomy.py`
(zero-write corpus-wide measurement, found a 3rd candidate blocked on a field-name mismatch
and non-sink-only membership). This session built the permanent version.

- New module `Brain/response_taxonomy_auto_pass.py` — entry point
  `run_auto_pass(config, conn, run_id)`, called from `v2/pipeline.py` immediately after
  `run_layer_c_v2`, wrapped in try/except that logs and swallows (must never fail the
  overall pipeline run). Gated by `tuning.yaml`'s `layer_a.response_taxonomy_auto_pass_enabled`
  (default `false`, currently `false` in the live file — pending further review after the
  first real run below).

- `Brain/shared/response_taxonomy.py` (new) extracted from `calibration/dry_run_response_taxonomy.py`
  (which now imports from it) — clustering/pair-loading/adjudication shared between the
  dry-run script and the permanent pass, same precedent as `build_clause_pool`'s extraction.

- **Fixed a real orphaning bug, retroactively too:** `calibration/graduate_sink_topics.py` used to write
  `primary_topic_key = None` for every scenario it created — a real, permanent orphan, since
  `primary_topics` is only ever built once, during Layer A's main pass. New pure helper
  `shared/topic_grouping.py::match_existing_primary_topic` (nearest-neighbor match against
  the existing `primary_topics` population) resolves a real key at graduation time instead —
  reuses `merge_cosine_threshold` (existing tight threshold), not `primary_topic_merge_threshold`
  (the loose one), since stored `primary_topics` rows are already tight-cohesion groups.
  Both `calibration/graduate_sink_topics.py` and the new auto-pass call it.

- New table `response_taxonomy_candidates` (`db/schema.sql`): `status`
  tracking/graduated/discarded; `member_pair_ids` is the latest raw cluster snapshot,
  `stable_pair_ids` is the running **intersection** across every run a candidate has been
  seen in — graduation reads `stable_pair_ids`, not the latest snapshot, specifically so a
  pair that only appeared in one noisy clustering run drops out automatically instead of
  riding along. A candidate must reappear (Jaccard overlap of `member_pair_ids`, **not**
  embedding similarity — this Postgres never stores vectors) across
  `response_taxonomy_consensus_runs` (3, pre-registered) consecutive runs before it
  graduates — the same UMAP/HDBSCAN run-to-run instability this file already documents
  elsewhere is exactly why a single run's cluster can't be trusted on its own.

- **The real run (2026-08-08), snapshotted first to `baseline_20260808`:** 3 manual
  invocations against the live `public` schema (no re-clustering of Layer A/C, no re-running
  Layer B — just this pass, standalone). Result: **4 scenarios graduated, 164 pairs rescued
  from the sink pool, `kb_pairs` total unchanged (4,605→4,605), and every one of the 164
  rerouted pairs confirmed `is_coachable=false` before this ran** — i.e. the "never disturb an
  already-homed pair" protection held, verified directly against the snapshot, not assumed.
  Flag reverted to `false` afterward pending further review before letting it run unattended.

- **Hit `IdleInTransactionSessionTimeout`'s sibling bug again, in two new places.** The very
  first real invocation crashed with `SSL connection has been closed unexpectedly` —
  the connection sat idle across the batched Gemma adjudication calls and Neon killed it.
  This is the *exact* existing `storage.reconnect_if_closed` gotcha below, just missed in two
  new call sites (right after `adjudicate_clusters`, and again after `_generate_metadata`
  inside the graduation path) — **any new code path that does a slow Gemma call before
  touching the DB again needs this called explicitly, it is never automatic.**

- **New gotcha, specific to this module:** it's the first Brain script to use a persistent
  `logging` file handler instead of `print()`. That handler is a module-level singleton, so
  pytest runs against the same module silently wrote fake `candidate_id`/`scenario_key`
  entries into the real production log file, unless a test explicitly disables it
  (`monkeypatch.setattr(module._logger, "disabled", True)`).

### Layer D (Ego Trap) realigned with the main pipeline (2026-08-10)

`ego_trap/` was written before the V2 evidence-triage rework and had absorbed none of three
later changes: `kb_pairs.scenario_keys[]` (2026-06-29), sinks making `scenarios` a
two-population table (2026-07-27), and layer_b replacing its absolute cosine floor with
relative top-K. All of it is now aligned. Zero schema DDL — every new record fits inside the
existing unconstrained `gap_events.gaps` JSONB, and severity is derived at query time.

**The design decision that shapes the rest: the sink filter is PER-MODE, not global.** The two
Step 0 modes need sinks for opposite reasons, and conflating them breaks one of them:

- **gemma mode gets the coachable-only map.** Listing `conversational_confirmation_and_fillers`
  in `PROMPT_STEP0_SIGNAL_CHECK` is an *invitation* to report backchannel as coachable — the
  root cause the 2026-07-06 zero-hit-rate investigation already landed on. Measured: the prompt
  menu drops from 32,575 chars / 161 scenarios to 19,778 / 85 (39% smaller).

- **similarity mode gets the FULL map, sinks included**, because a sink winning the match is the
  *only* mechanism that says "this turn is not a signal". Remove sinks and the best match is a
  non-sink by construction, so every client turn becomes a signal — the old 0.35-floor pathology
  wearing a relative margin.

So **never filter inside `storage.get_scenarios` or `pipeline._load_scenario_map`** — a filter at
either point destroys similarity mode's rejection mechanism. `ego_trap/scenario_pool.py` holds the
split as pure functions, keyed on `is_coachable` (what `relative_match.is_sink_flags` and
`assign_scenarios` use — Layer D must not invent a second definition of "sink") and **not** on
`rubric_status`, because a `skipped_insufficient_responses` scenario is a genuinely coachable
topic whose signals are the most useful thing Layer D produces.

- `shared/relative_match.py` (new) — `_topk_pick`/`_flat_pick` extracted verbatim from
  `v1/layer_b.py` plus `is_sink_flags` (replacing the comprehension that was triplicated at
  layer_b :107/:203/:350) and `cosine_sims`. `layer_b` re-imports them under the old private
  names so `from v1.layer_b import _topk_pick` still works. Behaviour-preserving, proven by the
  35 pre-existing tests in `test_layer_b_assignment`/`test_two_stage_matching`/`test_sink_rescue`
  passing unchanged. The extraction is also what lets the harness measure the real rule.

- **`milestone_id` is now the 1-based ARRAY POSITION, not the `order` field.** `milestone['order']`
  was bracket-accessed, and v1-fallback rubrics (a normal part of the population — 31 of 82
  scenarios in one measured snapshot) store Gemma's raw array with zero validation, so a real
  rubric could `KeyError` the whole run; a *duplicate* `order` was worse, silently merging two
  distinct milestones into one `milestone_performance` row under its
  `(csm_id, rubric_id, milestone_id)` PK. **Migration guarantee:** v2 writes `order = index + 1`
  over the same list it stores, so for every v2 rubric the positional id is byte-identical to the
  old `f"M{order}"` — no existing row is orphaned. Not content-hashed: Gemma rewords descriptions
  every Layer C run, so a hashed id would fragment a CSM's history per run.

- **`sequencing_type == "conditional"` is RECORDED but deliberately never acted on.** Three
  reasons, in force order: `PROMPT_LAYER_C_V2_ORDER` defines it as *ordering* variance, not
  optionality; the producing path (`v2/layer_c._sequence_milestones`, :322-341) only fires for
  `position_variance > 0.3` and only assigns a verdict when a 2-4 word Gemma label appears as a
  **substring of two raw clauses**, so it is rarely populated at all; and excluding conditional
  misses from `attempts` would shrink the score denominator and flatter CSMs with no audit trail.
  Any future rule belongs at query time over `gap_events.gaps`, never in a new column.

- **Evidence is persisted, never used to weight.** `support_calls`/`support_clauses`/
  `relevance_mean`/`position_variance`/`sequencing_type`/`source_v` are copied into each
  `Milestone_Omission` gap, defaulting to **`None`, not `0`** (`0` would assert "recurs in zero
  calls", which is false; `None` says "never measured"). A copy rather than a join back to
  `rubrics.milestones` because `upsert_rubric` replaces that column in place under the same
  `rubric_id`, so the next Layer C run destroys the evidence a past gap_event was graded against.
  Weighting a score by support strength was **rejected** — it conflates CSM performance with
  rubric confidence and no validated support→weight mapping exists.

- `get_rubric_for_scenario` now selects `pipeline_version`; consumers are observability only, no
  behavioural branch. A run whose gap records come mostly from v1-fallback rubrics is measuring
  Gemma free-text, not clustering evidence, and `RUN_NOTES.md` numbers are uninterpretable
  without that split.

- **New `Rubric_Coverage_Gap` gap_event.** A recognized, coachable signal on a rubric-less
  scenario used to produce **no DB row anywhere** — printed as `UNMAPPED_SCENARIO` and dropped.
  It deliberately does *not* touch `signal_recognition_gaps`: the CSM recognized and answered, so
  `recognized=True` would inflate the recognition rate with un-scored events and `missed=True`
  would be a lie. Live surface today is small (1 of 85 coachable scenarios: `rfp_process_disclosure`).

- **Benchmark references now read `scenario_keys[]` and rank by cosine, not `pair_id` order.**
  New `storage.get_responses_for_scenario_multilabel` — a *separate* function, because
  `get_naren_responses_for_scenario`'s `WHERE` is Layer C's clause-pool predicate and widening it
  would silently rewrite the pool for all 148 rubrics and invalidate the 385-milestone replay
  baseline. Measured gain: candidate pool 2,904 → 5,463 responses, 81 of 85 scenarios gained
  candidates, the chosen top-2 changed for **85/85**, and 70 chosen responses are secondary-label
  only (previously invisible). Cosine separation confirms the ranking works: chosen
  `p50=0.646` vs discarded `p50=0.575`, with chosen p10 above the discarded median. Free on a warm
  cache — the same texts were already `embed_document`-ed by Layer B.

- Fixed a real connection leak: `ops/run_ego_trap.py` closed the handle *it* created, but every
  `reconnect_if_closed` swap rebinds the local inside `run_ego_trap_batch`, so the runner closed a
  dead handle and leaked one live Neon connection per swap. `run_ego_trap_batch` now returns the
  live conn. Also added the missing `reconnect_if_closed` at Stage 3.

- Soft-skill ratings: the prompt now enumerates `excellent`/`adequate`/`failing` and
  `_normalize_rating` clamps anything else to **`adequate`** with a warning (never to `failing` —
  that would put a fabricated coaching finding in front of a human). Previously a returned
  `"poor"` produced no gap and no trace. A synonym map was rejected as a curated list.

- `calibration/dry_run_ego_trap.py` (new) — zero-Gemma / zero-write / zero-Pinecone by default,
  imports production code rather than reimplementing it. `--step0-gemma` (1 call per transcript,
  once) and `--pinecone-compare` are opt-in; `--load` replays the persisted artifact for free.
  **Harness bug worth remembering:** its chosen-vs-discarded band initially read "no data" because
  it called `rank_benchmark_responses` with `limit == len(rows)`, hitting that function's own
  `<= limit` short-circuit which returns rows *unranked and without* `scenario_similarity`. The
  one check that proves the ranking separates anything was silently measuring nothing — the same
  class of self-inflicted harness error as the merge-blind `_match_milestones`.

- **Pinecone `query_triggers` is NOT used for matching** (kept only as a `--pinecone-compare`
  measurement). Three reasons: ~40% of the `"triggers"` namespace is itself sink-filed and its
  metadata carries no `is_coachable`, so **the sink-rejection rule is not expressible against it**
  without a per-match DB round trip; the exemplar's `scenario_key` is layer_b's scalar best match,
  i.e. exactly the assignments the sink-rescue investigation documented as unreliable; and the
  margin is calibrated against the trigger-vs-scenario band, whereas Pinecone's
  utterance-vs-utterance band has never been measured here.

- **NEVER clear Layer D data while another pipeline run might still be alive — and "the task was
  reported stopped" is NOT evidence that it is dead.** Cost a full run and ~80 Gemma calls on
  2026-08-10. A background Layer D run was reported as stopped by the agent harness; that is the
  harness's own bookkeeping, not the OS process state. The process kept running, so when the
  tables and checkpoints were cleared and a replacement launched, **two runs shared one database
  and one `checkpoints.db`**: the survivor kept marking transcripts done, the new run skipped 10
  of 19 as `already done`, and `upsert_milestone_performance`'s `attempts = attempts + 1` inflated
  attempts 889 -> 905 across 28 doubly-scored signals. **The log still printed
  `Ego Trap batch complete`** and `calibration/measure_scoring_noise.py` still reported a
  plausible-looking floor. Check the OS, not the harness:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'run_ego_trap' }`.
  Note the venv's `python.exe` is a shim that re-execs the base interpreter, so **one run always
  shows as two PIDs in a parent/child pair** — two PIDs is normal, two different start times is
  not. `ops/run_noisefloor.ps1` now performs this check automatically and aborts before clearing;
  prefer it over doing the clear by hand.
- **Operational rule:** run `ops/clear_ego_trap_data.py` before any real re-run, and after any
  Layer C re-run. `gap_events` has only a SERIAL PK so re-processing **appends duplicates**, and
  `upsert_milestone_performance` does `attempts = attempts + 1` on conflict so it **double-counts**.
  Separately, `upsert_rubric`'s `ON CONFLICT (scenario_id)` keeps `rubric_id` stable while
  replacing `milestones`, so a Layer C re-run can make `M2` mean a different milestone while rows
  keep accumulating under it.

- Still open, noted not fixed: `pipeline.py`'s Gemma-failure path skips a batch but still marks the
  transcript checkpoint done, so those signals are permanently lost on resume while a forced
  re-run double-counts instead.

### Layer C rebuild — three changes, all shipped OFF (2026-08-12/13)

Design: `docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md`. Narrative and
the methodology failures: `Brain/PROBLEMS_AND_FIXES.md`.

**Root cause, and why a fourth wording pass cannot work.** Read from
`v2/layer_c.py::_describe_milestones_batch` — the model writing each criterion sees the
scenario's KEY STRING, its own response clauses, and nothing else. It has never seen a client
turn, so it cannot state a precondition (234 of 235 milestones are labelled `fixed`; the
conditional trigger fires **0 of 226**), and it is told to strip specifics on top. That is a
missing-INPUT problem. Asking a better-worded question of a blind model changes nothing.

| what | where | flag |
| --- | --- | --- |
| situated describe inputs | `PROMPT_LAYER_C_MILESTONE_DESCRIBE_SITUATED`, `v2/layer_c._describe_situated` | `layer_c.describe_mode: legacy` |
| coverage areas + 4th verdict | `shared/coverage_areas.py`, `PROMPT_LAYER_C_COVERAGE_AREAS`, `milestone_scoring.score_coverage_batch` | same key, value `coverage` |
| skills (profile axes) | `shared/skills.py`, `PROMPT_SKILL_ABSTRACT_BATCH` | not wired to production |
| the trial harness | `calibration/trial_layer_c_arms.py` | read-only, artifacts only |

- **`describe_mode` ships `legacy`; production Layer C is byte-identical.** The situated path
  needs `build_clause_pool`'s 4th return value (`clause_pairs`) and `trigger_text` on
  `get_naren_responses_for_scenario` — both additive, both threaded through `_relevance_filter`
  into each cluster's `pair_ids`. Verified live: `client_reacts_to_anomaly` has 34 pairs across
  27 calls, so 7 calls contribute more than one pair and attributing triggers by
  `call_filename` would hand a cluster the trigger of a moment that never produced the move.
- **Half of the 2026-08-10 rule is DROPPED in the situated prompt.** That rewrite banned two
  things in one breath: "never narrate a person" (correct, kept, ~4x the noise band) and "never
  state the specific instance" (**the over-correction** — it is what made criteria
  scenario-agnostic). A criterion may now name its subject matter; it still may not name a
  person.
- **Batching is per SCENARIO in the situated path**, not 5 milestones across all scenarios.
  That is what lets a move see its siblings, which the legacy prompt had to forbid because its
  batches mixed unrelated scenarios. Cost is unchanged: 81 calls vs ~82.
- **`_describe_*` take an optional `model=`, defaulting to None.** The situated/coverage
  prompts pack a whole scenario and cannot fit `gemma-4-31b-it`'s 16k TPM ceiling — measured
  2026-08-13, one call burned 8+ minutes of backoff. Only the trial passes the flash-lite
  chain, so production is unaffected.

**Established by the trial so far (corpus-level, replicated):**

- **Do NOT remove Naren's benchmark response from the scorer.** Hypothesis was that it makes
  the grader match on resemblance and inflates the null. **Refuted, and it goes the other
  way:** removing it moved discrimination 1.30 -> **1.12**, null rising 0.130 -> 0.150. It
  anchors the grader to a scenario-appropriate standard. Valid despite the sampling bug below —
  paired comparison, same rubrics both sides.
- **"Did this moment call for this move" has now failed TWICE, in two different framings.**
  The standalone applicability judge: 0.147 matched vs 0.120 unrelated (1.22:1). The coverage
  judge with the client turn AND response in front of it: **64.9% `not_called_for` matched vs
  65.7% unrelated**. Treat a third attempt as speculative, not routine.
- **Corpus-level is stable, per-scenario is not.** Baseline reproduced at 1.30 / 1.30 / 1.21
  across three separate runs with spreads of +/-0.002-0.018. That is why the gate is
  corpus-level and why arm comparison works at all.
- **`ops/run_visible.ps1`** runs a Brain script in a real window that stays open, with the
  neon DNS bypass built in. Three bugs are documented in the script so they are not
  reintroduced: `-Args` is a PowerShell automatic variable; the inner script must call the venv
  python by full path; and `-ScriptArgs` must be ONE STRING because `-File` does not preserve
  array syntax.
- **Always smoke-test a harness end to end before a full run.** `--sample 2 --per-scenario 2
  --reps 1` costs ~20 calls and exercises every path. Two full launches died mid-generation on
  a missing import and a positional slice (`ARMS[2:]`) — **`py_compile` catches neither**.
  `score_naren_ceiling.py` already had this in `--max-items-per-arm`.

### Skills vocabulary — can a per-person profile be built at all? No (2026-08-13)

Pre-registration: `docs/superpowers/specs/2026-08-13-layer-c-skills-vocabulary-design.md`.
Harness `calibration/trial_skills.py`, artifacts `skills_trial.json` (full) /
`skills_trial_pilot.json`, logs `logs/trial_skills_full.log`. Zero Postgres writes.

The question is independent of the criteria failure and survives it: **the arms decide
whether criteria can grade; this decides whether there are axes to report on.** 405 axes at
~4-8 observations each is arithmetic no scoring fix repairs.

- **`skills.sweep`'s own honest-failure signal CANNOT fail.** `cross_scenario_coverage`
  goes to 1.0 by construction as the threshold falls (everything merges into one group), so
  the sweep alone always says yes at *some* granularity. Same defect class as the
  merge-blind `_match_milestones`: a metric that only counts the good outcome. The fix is a
  second curve that gets WORSE as groups fuse — merge validity `V(t)`, a batched judge
  returning a verdict on every group.
- **The gate is a WINDOW between two curves**, constraining from opposite sides: `V(t)`
  bounds coarseness from above, statistical power bounds it from below. PASS = some judged
  `t` has `K(t) <= bound` and `V(t) >= 0.80`. The lower bound is derived, never chosen —
  from 889 attempts / 405 milestones and the ±0.006 noise floor, giving K <= 11/17/18/35 for
  four standards. **K is optimistic; the operative gate is the MEDIAN skill's member count**
  (>=38/24/23/12), because K assumes an even split that never holds.
- **Result: no window at any bound.** Power is satisfiable only at t<=0.675 (K=6, median 13);
  `V` there is **0.20** against a bar of 0.80 — off by 4x, not a near miss. Validity rises
  monotonically 0.20 -> 0.25 -> 0.50 -> 1.00 as clustering gets finer, which is the shape a
  working counterweight should have.
- **The negative is trustworthy because the instrument passed its own checks first:** judge
  null 12/12 rejected (blinded, size-matched disguised pairs), positive control V=1.00 at
  t=0.95, as-written control confirms the abstraction is NOT inert (56 groups written vs 14
  abstracted at t=0.7), order permutation drift 0.11-0.17 at full scale. **First judge in
  this whole effort to pass its own null** — the applicability judge failed at 1.22:1 and
  the coverage judge at 64.9% vs 65.7%.
- **The cause: 78% of milestones (315/405) abstract to a behaviour string occurring exactly
  ONCE.** Only 22% recur at all, 11% recur 5+ times. So behaviours DO repeat — an
  *explains-a-mechanism* family covers 55 items, `call mechanics` 11, *asks open questions*
  8 — but they cover ~a fifth of the corpus. Pooling 405 into <=35 axes requires merging 315
  genuinely distinct one-off moves. **This 78% figure is exact string matching, not
  embeddings** — a better embedder cannot un-write 342 different sentences.
- **What this DOES support:** a *partial* vocabulary of the ~6-27 skills that genuinely
  recur, covering 11-22% of milestones, with the rest in `skills.UNASSIGNED`. What it rules
  out is a complete vocabulary at any granularity where every axis has enough observations.
- **Identified but NOT pulled:** the abstraction prompt asks the model to keep the *why*
  ("Keep what the person is DOING and WHY"), which splinters *explains a mechanism* into 30
  strings over 55 items. Dropping the WHY clause would materially move the curve. Left
  alone deliberately — re-running after a negative with a tweaked prompt is how a result
  gets tuned into existence, and three wording passes have already failed here. It needs a
  fresh pre-registration, not a retry.
- **The pilot could not open the window by construction** (91 milestones = 22% of the
  observations the floors were derived from) and the floors were deliberately NOT rescaled
  to fit — a bound moved to fit the run it is judging is not a bound. The report printed the
  stopping-condition verdict anyway on the first pass; now gated on the full corpus. Also
  note the pilot's order-permutation failure at t=0.725 (drift 0.44) did **not** reproduce
  at full scale — it was a small-sample artifact.

### Embedding backend: local bge vs hosted Gemini (2026-08-13)

`preprocessing/embedder.py` grew a `gemini` backend beside local bge, selected by
`tuning.yaml`'s `embedding.backend` and **shipping `local`** so nothing moved. Harness
`calibration/compare_embedders.py`, artifact `embedder_compare.json`.

**Four facts measured against the live API, none of them assumable:**

- **`embed_content` does NOT batch.** `contents=[3 strings]` returns **ONE** embedding — the
  list is treated as the parts of a single document. N texts cost N requests. This first
  surfaced as an `IndexError` several lines downstream because 161 scenarios in 2 batches
  produced 2 vectors and a boolean mask happened to check the length; **had the count been
  2 it would have run clean and produced fabricated numbers.** `_encode_gemini` now asserts
  one vector per text. **Consequence: a 74k-clause backfill is 74k requests against a
  1k/day cap = 74 days. `client.batches.create_embeddings` is mandatory for production, not
  an optimisation.**
- **Tokens bind, not requests, and by a wide margin.** Measured on the first real run:
  **34.66K/30K TPM while RPM sat at 6/100 and RPD at 7/1000.** Pacing on request count alone
  429s immediately. `_throttle` tracks both over a rolling 60s window.
- **`genai.Client` must be cached at module level.** Built inline it is garbage-collected
  mid-request — `Cannot send a request, as the client has been closed`. Same rule
  `pinecone_store` already carries.
- **`output_dimensionality` IS accepted; native width is 3072.** The model is
  Matryoshka-trained, so one call yields every width.

**Comparison result (150-pair labelled sample + 161 scenarios): 1 of 3 pre-registered
criteria — DOES NOT PASS.** But two of the three criteria were badly built by me, so this is
an inconclusive instrument rather than a clean no:

| space | margin(corr) | coupling | p50 | spread |
| --- | --- | --- | --- | --- |
| bge_768 | 0.561 | 0.617 | 0.558 | 0.141 |
| gemini_3072 | 0.672 | 0.560 | 0.672 | 0.083 |
| gemini_768 | **0.686** | 0.569 | 0.686 | 0.082 |

- **`sink_real_margin` 0.561 -> 0.686 is a real, clean win**, clearing its bar at every
  width. That signal's failure was explicitly diagnosed as an embedding-space problem
  ("real and sink centroids sit too close together"), and the diagnosis was right.
- **768 BEAT 3072** (0.686 vs 0.672), so the wide vector earns nothing: no new Pinecone
  index, no 867 MiB Layer A matrix, no migration.
- **The `spread` criterion measures the wrong thing.** p10-p90 of best-match cosine is the
  model's cosine SCALE, not its discrimination — Gemini's scores are uniformly higher and
  bunched. The right measure is top-1 minus top-2 per trigger, which was never taken.
- **The `coupling` criterion is confounded by the harness.** Triggers went in as
  `RETRIEVAL_QUERY` and responses as `RETRIEVAL_DOCUMENT` — correct for trigger-vs-scenario,
  wrong for comparing a trigger to its own response, which needs one symmetric task type.
  The bge baseline had no such split.
- **`sink_real_margin`'s published AUC 0.437 is NOT "worse than chance".** The signal is
  inverted by construction (higher = more filler-like), so it is direction-correct and worth
  **0.563** corrected. A pass mark set at ">=0.55" would have passed on zero improvement.
- **Harness miss to not repeat: the raw vectors were not persisted**, only the derived
  scores — so changing a criterion costs another 461 requests. Flush the PAID artifact, not
  just the conclusions drawn from it.

**Every threshold in `tuning.yaml` was calibrated against bge's cosine bands.** Gemini's p50
is 0.686 vs bge's 0.558 — switching backends invalidates `relative_margin`,
`merge_cosine_threshold`, the p40 relevance percentile and Layer D's sink comparison until
they are re-derived. That re-calibration, not the model, is the cost of the swap.

### Default Gemma model is now `gemini-3.5-flash-lite` (2026-08-13)

`shared/gemma.py::_DEFAULT_MODEL`, was `gemma-4-31b-it`, which stays last in the fallback
chain. Its 16k TPM ceiling could not hold the prompts this pipeline sends (one situated
describe call burned 8+ minutes of backoff), so call sites had been overriding it one at a
time; `v2/layer_c._FAST_DESCRIBE_MODEL` matched. **This changes production output, and every
number in this file was produced under `gemma-4-31b-it`** — comparisons against them are
model-confounded exactly as `arm0_baseline` (1.58) vs `arm0r_legacy_regen` (1.04) already is.

### Layer C milestones were narration, not criteria — found and fixed (2026-08-10)

**The single most important Layer D finding to date, and it was never a Layer D bug.** All
405 stored milestone descriptions were *descriptions of what one expert did* rather than
*criteria a different person could satisfy*: 37% named Naren, 63% said "the speaker", 91%
used he/she/his/her — **100% used narrative-about-a-person phrasing.** Example:
`"He uses hypothetical numerical examples of job slots to illustrate how the platform can
scale."` Layer D scores a CSM's response against those descriptions and `detection_hint`s,
so a CSM could handle a call correctly and still miss every milestone by not reproducing
one person's improvisation.

Root cause was two prompts, both now fixed:

- `PROMPT_LAYER_C_MILESTONE_DESCRIBE_BATCH` opened `"Describe each recurring communicative
  move in Naren Shankar's sales responses"` and asked for prose `"grounded in the clauses
  above"` — an instruction to summarise a transcript. Now asks for the criterion a
  DIFFERENT person's response must satisfy, forbids names/pronouns/"the speaker", and
  requires generalising past specific numbers, clients and anecdotes.

- `PROMPT_LAYER_C_V1` was worse: the flaw was in its **few-shot example**
  (`"description": "Naren explicitly validates the client worry..."`), priming the model to
  copy that shape. Example and rules block both fixed.

**Repaired the 405 existing descriptions in place rather than re-running Layer C.** New
`ops/rewrite_milestone_criteria.py` (`--dry-run` / `--apply`). Re-running Layer C would
change the milestone SET, not just its wording — UMAP+HDBSCAN is not reproducible across
process launches (385/398/403-407 for identical input), which reshuffles clusters, orphans
every `milestone_performance` row (`milestone_id` is the array POSITION) and moves the
baseline, all to fix prose. The clusters are well evidenced (support up to 112 calls / 337
clauses); only the text was wrong. Result: **405/405 rewritten, 41/41 batches clean,
person language 100% → 3%** (and all 13 residuals are regex false positives — generic
*their/they*), **0 rubrics changed milestone count**, all 391 `support_calls` preserved
byte-for-byte. Each rewritten milestone carries `criteria_rewritten: true`.

- Batch size is **10, not 20**: at 20, one batch in 21 returned truncated JSON and those 20
  milestones were left unrewritten. 41 calls is nothing against 500/day; truncation is the
  binding constraint here, not requests.

**Controlled A/B (rare in this codebase — identical transcripts, taxonomy, clusters, ids and
evidence fields; only wording differed), snapshot `pre_criteria_20260810`:**

| | before | after |
| --- | --- | --- |
| attempts | 864 | 963 |
| full hits | 21 (2.4%) | 29 (3.0%) |
| partial hits | 32 (3.7%) | **73 (7.6%)** |
| weighted | 0.043 | **0.068 (x1.6)** |

43 milestones improved, 17 worsened, 189 unchanged. **Verdict: wording was a real cause but
NOT the whole cause** — 3.0% full hits is still very low, so do not treat this as closed.
Partials doubled while full hits barely moved: a narration milestone is effectively binary
(you reproduced the improvisation or you didn't) so it collapses to `miss`, whereas a
behavioural criterion admits partial credit — the rewrite made the rubric **gradable**, which
matters more for coaching than the headline rate. The +11.5% attempt drift is benign — the
baseline arm lost ~99 attempts to 2 Gemma batch failures; the after arm had zero.

**MEASURED AGAINST THE NOISE FLOOR (2026-08-11) — read this before citing any number above.**
Two runs of arm 3 with *nothing whatsoever changed* (identical transcripts, code, config,
rubrics; both arms verified as exactly one run each) gave `889 att / 28 hits (3.1%) / weighted
0.074` and `889 att / 33 hits (3.7%) / weighted 0.080`. So:

- **The noise band is ±0.006 weighted, and 15.6% of milestones (37/237) move on their own.**
- **The criteria rewrite's +0.025 is ~4.1x that band — it is real.** That claim survives.
- **The uncoachable-skip's +0.006 is EXACTLY 1.0x the band — it is not measurable.** It was
  previously written up here as 3.0% -> 3.1%; that is retracted. Keep the change anyway, but on
  the grounds that never depended on the metric: it stopped 74 pieces of coaching advice
  instructing a CSM to do something impossible.
- **No per-milestone winner or loser from any A/B is citable** — 24.6% observed movement against
  a 15.6% floor.
- **A single hit-rate figure needs the band attached.** Pure variance moved the headline 3.1% ->
  3.7%, a 19% relative swing, so every "3.x%" in this file means 3.x% ± 0.6pp.
- **An earlier argument here was wrong and is withdrawn.** It claimed noise would be *symmetric*,
  so the rewrite's lopsided 43-up/17-down must be signal. The floor is itself lopsided (24 up /
  13 down, net +2.12) because at a ~3% hit rate almost every milestone sits at 0 and a random
  flip can only move UP — variance is structurally upward-biased against a floor. Compare
  magnitude (rewrite net +4.48 vs floor net +2.12, ~2x), never shape.
- **Consequence for future work: at this sample size any change below ~+0.02 weighted is
  unmeasurable.** Two of this session's three changes landed inside the noise. Do not tune
  against this metric until the ceiling is established (see the open question below).

Baselines: `arm3_run1_20260810` and `arm3_run2_noisefloor_20260811`.
`calibration/measure_scoring_noise.py` runs the comparison and **refuses** to report a floor
unless each arm is provably a single run — a guard added after an earlier attempt silently
reported a floor computed from two concurrent runs blended together (see the concurrency
gotcha below).

**Still suppressing the rate (all confirmed by reading real samples, none of them wording):**

- **Step 0 false positives.** A URL-configuration exchange (`"did you already make changes to
  the URL?"` / `"For the older job or the new job?"`) was matched to
  `contract_renewal_anxiety` and scored against a milestone about reframing "middle person"
  perception. The verdict was technically correct and the question was meaningless.

- **36% of `gap_events` are `Signal_Recognition_Failure`** — no CSM response existed to score
  at all. And `extract_csm_response_window` sometimes captures scheduling chatter instead of
  the substantive answer (seen in `rec6` @ turn 135).

- **17 of 405 milestones are unhittable by construction** — found by
  `ops/flag_uncoachable_milestones.py` sweeping all 405 (the rewriter had volunteered 4 of them
  incidentally). 5 require seniority or personal relationships a CSM does not have
  (`"leverage professional relationships"`, support 15 calls; `"establish authority"`, 18), 4
  have no observable criterion (`"share a vulnerable personal story"`), and 8 are call mechanics
  that leaked past `milestone_sink_similarity_percentile` triage (`"offer screen-sharing"`,
  `"manage speaking turns"`). All are well-evidenced clusters — the clustering found something
  real that simply is not coachable. **The proof they are impossible rather than merely hard:
  74 attempts, 0 hits, across 12 distinct milestones.** Flagged and skipped via
  `layer_d.skip_uncoachable_milestones`; that change is NOT justified by its metric effect
  (which is inside the noise band) but by removing 74 fabricated coaching instructions.

**The level, not the improvements, is the finding.** After all three fixes the rate is
3.1-3.7%. A working CSM is being told she fails ~96% of the standard. Two readings, and the
data cannot separate them: either she genuinely performs that badly against Naren's bar
(implausible for someone doing the job), or **the measurement is still fundamentally broken and
the narration bug was one layer of something deeper.** Weight the second: a defect as severe as
"100% of rubrics were narration" bought only +0.025 on a 0-1 scale, so the binding constraint
is elsewhere.

**THAT EXPERIMENT HAS BEEN RUN (2026-08-11/12) AND IT INVALIDATES EVERY NUMBER ABOVE. READ THIS
BEFORE CITING ANY HIT RATE ON THIS PAGE.** Naren was scored against his own rubrics with both
circularities closed (call-level benchmark holdout, plus a secondary-label-AND-zero-primary-call
holdout), against a control arm scoring the same responses on a deliberately UNRELATED scenario's
rubric.

| arm | W | |
| --- | --- | --- |
| A1 primary label (leaked) | 0.161 | |
| **A3 call-level holdout (clean)** | **0.114** | the ceiling |
| **B unrelated rubric (control)** | **0.090** | same-model subset |
| CSM reference | 0.074 | **below the control** |

**Signal-to-null is 1.2 : 1, reproduced three independent times** (0.114/0.090, 0.116/0.095).
Both pre-registered failure conditions fired. **Every Layer D hit rate in this document, including
the entire 2.4% -> 3.1% arc and the ±0.006 noise band it was read against, is uninterpretable as
CSM performance.** Leakage was NOT the cause — clean vs leaked is 0.114 vs 0.161. The cause is
that the criteria are scenario-agnostic: the 2026-08-10 rewrite conflated "never narrate a person"
(correct) with "never state the specific instance" (an over-correction), so criteria stopped
identifying a situation.

**Do not treat the per-scenario decomposition as established.** `PROBLEMS_AND_FIXES.md` records a
bimodal split (16 of 40 discriminating, 7 inverted, 7 with a zero control). That labelling failed
replication on 2026-08-12: three independent measurements of the same 49 scenarios agreed on the
verdict only **41–47%** of the time, with SHIP<->DISABLE sign flips on the most extreme cases, and
the per-scenario gap moves a median of **0.138** against a ±0.05 band. Only the CORPUS-level result
above survives. Nothing may be shipped, disabled or gated per scenario on those numbers.

**Also measured and closed 2026-08-12:** the per-milestone objective function
(`shared/rubric_validation.py`, `calibration/validate_rubrics.py`,
`layer_d.require_validated_milestones`) was built and run. At 8 attempts per arm W quantizes to
steps of 0.0625, so its discrimination gate trips on one stray partial hit — the 7 known-good
scenarios produced 0 of 33 scoreable milestones. Its applicability judge failed its own null
(0.147 matched vs 0.120 unrelated, 1.22 : 1) despite demonstrably varying with the client turn.
Both gates fired, nothing was written to the DB, and the flag stays `false`.

**Next step is the four-arm Layer C rebuild trial**, which writes nothing to Postgres:
`docs/superpowers/specs/2026-08-12-layer-c-profile-rebuild-design.md`. Original ceiling design:
`docs/superpowers/specs/2026-08-11-naren-ceiling-measurement-design.md`.

`calibration/compare_criteria_ab.py` runs this comparison against any snapshot schema, joins
on `(rubric_id, milestone_id, csm_id)`, lists per-milestone winners/losers, and **checks
attempt-count drift** — refusing to call it a clean wording-only comparison above 15%.

### Brain Architecture Notes

- `run_id` is a stable sha1 hash of sorted transcript stems — same transcript files across re-runs reuse checkpoints automatically; adding/removing a transcript generates a new run_id
- `assign_scenarios` (v1/layer_b.py): per-pair cosine sim ≥ 0.30 → multi-match into `scenario_keys`; pairs that match nothing fall back to call centroid — no pair is ever left `None`; `_is_substantive()` removes scheduling/filler pairs before they reach assignment
- `v1/layer_a.py` splits into `identify_scenarios()` (Gemma only, no DB) and `store_scenarios()` (DB only); pipeline closes the Postgres connection before the Gemma call and opens a fresh one after — prevents idle SSL drops
- `storage.get_connection()` uses TCP keepalives (idle=30s, interval=10s, count=5) to survive long LLM calls
- `gemma.py` retries (max 5, exponential backoff) on 429/500/503/504/internal/deadline errors; 3-min HTTP timeout. **Fixed 2026-07-31 (uncommitted):** raw `httpx.TransportError` subclasses (SSL read drops, connect timeouts, protocol resets) were falling through the string-marker check and raising immediately instead of retrying — string-matching error text couldn't keep up with how many ways a socket layer phrases a drop (`"_ssl.c:2580"` etc.). Now checked by type (`isinstance(e, httpx.TransportError)`) alongside the marker list.
- Utility scripts (2026-07-30/31): `run_v2_subset.py <dir>` — non-interactive V2 pipeline runner against an arbitrary recordings directory, for calibration on a call subset; use this instead of `main.py` for scripted/unattended runs since `main.py` blocks on an interactive V1-vs-V2 prompt. `calibration/compare_matching_subset.py` — zero-Gemma harness comparing flat matching against `assign_scenarios_two_stage`'s strict/soft/fallback strategies on an already-populated DB; `--sweep-floor` sweeps `two_stage_fallback_floor` and reports agreement/recall-proxy/Jaccard against flat per floor value. `calibration/compare_sink_rescue.py` — zero-Gemma harness comparing flat matching against `assign_scenarios_with_sink_rescue`'s response_only/or_rule/blended strategies on an already-populated DB; prints the response-vs-scenario similarity percentiles plus rescue rates and verbatim sample pairs per strategy (see the sink-rescue section above). `calibration/dry_run_ego_trap.py` (added 2026-08-10) — the Layer D equivalent: zero-Gemma/zero-write/zero-Pinecone by default, reports the scenario-pool split, retro-classifies already-stored `gap_events` against `is_coachable`, measures similarity mode's cosine band and sink-rejection rate with a margin sweep, A/Bs the `turn_match_mode` tiers through the production resolver, and diffs benchmark selection old-vs-new. `--step0-gemma` and `--pinecone-compare` are the only non-free paths and both are opt-in; `--load` replays the persisted artifact at zero cost.
- Utility scripts: `ops/backfill_scenarios.py` (reassign scenario_keys on existing pairs), `ops/rerun_layer_c.py` (re-run Layer C for specific scenarios)
- Real CSM call recordings (`csm_recordings/*.txt`) have no timestamps or role tags — same plain blank-line-separated `Name`/`Utterance` format as `recordings/`, not the `[HH:MM:SS] Name (ROLE):` format `Ego_trap.md` specs; `ego_trap/transcript_parser.py` resolves CSM vs OTHER_JOVEO vs CLIENT via `csm_recordings/mapping.csv`'s `csm_name` (must match the transcript speaker line) plus `JOVEO_SPEAKER_NAMES`
- `preprocessing/embedder.py` batches at 96 inputs per call — Pinecone's hard limit for `llama-text-embed-v2`; a single long call transcript (100+ turns) will 400 without it
- `milestone_scoring.score_milestones()`/`score_soft_skills()` (one Gemma call per milestone / per soft-skill name) were **deleted 2026-08-10** — nothing but their own tests called them, and keeping a second prompt that states the verdict rules while never being exercised is how a rule change lands in only one of two places. `PROMPT_STEP3_MILESTONE_SCORE` / `PROMPT_STEP3_SOFT_SKILL_SCORE` went with them. Use `score_milestones_batch()`/`score_soft_skills_batch()`; the batch size is the module constant `ego_trap/pipeline.py::_GEMMA_BATCH_SIZE` (4), deliberately **not** a `tuning.yaml` key since request packing is not a property of the data — the precedent is `v2/layer_c._DESCRIBE_BATCH_SIZE`
- `ego_trap/pipeline.py`'s `run_ego_trap_batch()` runs 5 staged passes per transcript (response-check → rubric lookup → batch-pull response/benchmark text → Gemma batch-score → write) — each stage processes all signals before the next starts, not a single per-signal loop
- `Brain/ego_trap/RUN_NOTES.md` tracks gap-analysis results across pipeline runs/threshold tuning for comparison — update it after Ego Trap tuning runs since clearing data destroys the prior run's DB state
- `signal_check.py`'s response classification is `response_outcome` (`"csm"` / `"other_joveo"` / `"none"`), not a `csm_responded` boolean — computed in code by `transcript_parser.classify_response_outcome` from actual turn roles, never asked of the LLM (even in `STEP_0_MODE=gemma`). `"other_joveo"` (a teammate answered, not the CSM) writes a `Deferred_To_Teammate` gap_event via `gap_output.write_deferred_to_teammate` and is excluded from `signal_recognition_gaps` recognized/missed counters; only `"none"` writes `Signal_Recognition_Failure`
- Milestone scoring (Step 3) returns a 3-tier `verdict` (`full_hit`/`partial_hit`/`miss`) with `quote`/`gap_to_ideal` evidence gated to non-`full_hit`, not a boolean `hit` (changed 2026-07-13, see `docs/superpowers/specs/2026-07-13-milestone-verdict-tiers-design.md`) — `milestone_performance.hits` now means full_hit count only, `partial_hits` tracks partial separately, weighted score = `(hits + 0.5*partial_hits)/attempts` computed at query time, not stored
- A 0% (or near-0%) milestone hit rate is not necessarily a rubric-wording/prompt-bias problem — confirmed on 2026-07-06 by reading actual Gemma `reason` text in `gap_events.gaps`: every miss was a legitimate content critique, none referenced the responder's name/identity. The real cause was the `EGO_TRAP_SIMILARITY_THRESHOLD` (0.35) matching topic-irrelevant small talk (e.g. "I'm good, thank you", calendar chat) to real scenarios — milestone scoring was correctly failing content-empty false-positive signals, not misbehaving. Before assuming a rubric/prompt fix, pull the stored reasons and cross-check a sample against the source transcript at its `signal_turn_index` first
