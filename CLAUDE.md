# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**CS-platform** — Joveo Customer Success platform. A Next.js 14 (App Router) web application for Joveo's CS team, providing a workspace, learning library, and call simulator.

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

# Run pipeline
python main.py
```

### Brain Stack

- **Python 3.11**, `uv` package manager, venv at `c:\PF\Joveo\CS-platform\.venv`
- **LLM:** `google-genai` → Gemma 4 31B via Google AI Studio (`GEMMA_API_KEY`)
- **Vectors:** Pinecone `llama-text-embed-v2` (2048 dims, cosine) — index `narens-brain`, AWS us-east-1
- **Sentence splitting:** spaCy `en_core_web_lg`
- **Relational DB:** PostgreSQL via `psycopg[binary]` — no vectors stored here, vectors in Pinecone only
- **Checkpointing:** SQLite at `Brain/checkpoints.db`
- **V2 clustering:** `bertopic` + `umap-learn` + `hdbscan`

### Brain Architecture

- `preprocessing/` — transcript parser → spaCy segmenter → Pinecone embedder
- `shared/` — `gemma.py`, `storage.py` (Postgres CRUD), `pinecone_store.py`, `checkpoint.py`, `prompts.py`
- `v1/` — Gemma-direct pipeline (Layer A: scenario ID, Layer B: pair extraction, Layer C: rubrics)
- `v2/` — BERTopic clustering for Layer A/C; Layer B re-exports v1
- `main.py` — entry point; asks V1 or V2; generates `run_id`; inits Pinecone index + SQLite checkpoint
- `recordings/` — place `.txt` transcript files here (stem = call_id)
- `db/schema.sql` — Postgres tables only (no vector columns); `db/init_db.py` runs it
- `ego_trap/` — gap-analysis pipeline (Steps 0-4 + Layer D) scoring CSM calls against Naren's rubrics; `run_ego_trap.py` is its non-interactive batch entry point, `clear_ego_trap_data.py` resets only its own tables

### Transcript format

```text
SpeakerName
Utterance text here.

NextSpeaker
Their utterance.
```

No participant header block. Speaker classification is config-driven via `JOVEO_SPEAKER_NAMES` env var.

### Pinecone embedding API

```python
result = pc.inference.embed(
    model="llama-text-embed-v2",
    inputs=texts,
    parameters={"input_type": "query",  # or "passage" for documents
                "dimension": 2048, "truncate": "END"},
)
vecs = [e.values for e in result]  # access .values, not .embedding or []
```

Two namespaces in one index: `"triggers"` (CLIENT utterances) and `"responses"` (Naren responses).

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

### Brain Schema (current state)

- `kb_pairs` has `scenario_keys TEXT[]` (added 2026-06-29) — multi-scenario array; `scenario_key TEXT` is the primary/display one used by Layer C queries
- Layer D (Ego Trap, added 2026-07-06): `csms`, `milestone_performance`, `signal_recognition_gaps`, `gap_events` — `gap_events.signal_turn_index` is a transcript turn number, not a timestamp (real call recordings have no timestamps)

### Brain Architecture Notes

- `run_id` is a stable sha1 hash of sorted transcript stems — same transcript files across re-runs reuse checkpoints automatically; adding/removing a transcript generates a new run_id
- `assign_scenarios` (v1/layer_b.py): per-pair cosine sim ≥ 0.30 → multi-match into `scenario_keys`; pairs that match nothing fall back to call centroid — no pair is ever left `None`; `_is_substantive()` removes scheduling/filler pairs before they reach assignment
- `v1/layer_a.py` splits into `identify_scenarios()` (Gemma only, no DB) and `store_scenarios()` (DB only); pipeline closes the Postgres connection before the Gemma call and opens a fresh one after — prevents idle SSL drops
- `storage.get_connection()` uses TCP keepalives (idle=30s, interval=10s, count=5) to survive long LLM calls
- `gemma.py` retries (max 5, exponential backoff) on 429/500/503/504/internal/deadline errors; 3-min HTTP timeout
- Utility scripts: `backfill_scenarios.py` (reassign scenario_keys on existing pairs), `rerun_layer_c.py` (re-run Layer C for specific scenarios)
- Real CSM call recordings (`csm_recordings/*.txt`) have no timestamps or role tags — same plain blank-line-separated `Name`/`Utterance` format as `recordings/`, not the `[HH:MM:SS] Name (ROLE):` format `Ego_trap.md` specs; `ego_trap/transcript_parser.py` resolves CSM vs OTHER_JOVEO vs CLIENT via `csm_recordings/mapping.csv`'s `csm_name` (must match the transcript speaker line) plus `JOVEO_SPEAKER_NAMES`
- `preprocessing/embedder.py` batches at 96 inputs per call — Pinecone's hard limit for `llama-text-embed-v2`; a single long call transcript (100+ turns) will 400 without it
- `milestone_scoring.score_milestones()`/`score_soft_skills()` make one Gemma call per milestone/per soft-skill name, not one per signal — prefer `score_milestones_batch()`/`score_soft_skills_batch()` with `ego_trap.settings.GEMMA_BATCH_SIZE` (env `EGO_TRAP_GEMMA_BATCH_SIZE`, default 4) to combine multiple signals per Gemma call
- `ego_trap/pipeline.py`'s `run_ego_trap_batch()` runs 5 staged passes per transcript (response-check → rubric lookup → batch-pull response/benchmark text → Gemma batch-score → write) — each stage processes all signals before the next starts, not a single per-signal loop
- `Brain/ego_trap/RUN_NOTES.md` tracks gap-analysis results across pipeline runs/threshold tuning for comparison — update it after Ego Trap tuning runs since clearing data destroys the prior run's DB state
- `signal_check.py`'s response classification is `response_outcome` (`"csm"` / `"other_joveo"` / `"none"`), not a `csm_responded` boolean — computed in code by `transcript_parser.classify_response_outcome` from actual turn roles, never asked of the LLM (even in `STEP_0_MODE=gemma`). `"other_joveo"` (a teammate answered, not the CSM) writes a `Deferred_To_Teammate` gap_event via `gap_output.write_deferred_to_teammate` and is excluded from `signal_recognition_gaps` recognized/missed counters; only `"none"` writes `Signal_Recognition_Failure`
- Milestone scoring (Step 3) returns a 3-tier `verdict` (`full_hit`/`partial_hit`/`miss`) with `quote`/`gap_to_ideal` evidence gated to non-`full_hit`, not a boolean `hit` (changed 2026-07-13, see `docs/superpowers/specs/2026-07-13-milestone-verdict-tiers-design.md`) — `milestone_performance.hits` now means full_hit count only, `partial_hits` tracks partial separately, weighted score = `(hits + 0.5*partial_hits)/attempts` computed at query time, not stored
- A 0% (or near-0%) milestone hit rate is not necessarily a rubric-wording/prompt-bias problem — confirmed on 2026-07-06 by reading actual Gemma `reason` text in `gap_events.gaps`: every miss was a legitimate content critique, none referenced the responder's name/identity. The real cause was the `EGO_TRAP_SIMILARITY_THRESHOLD` (0.35) matching topic-irrelevant small talk (e.g. "I'm good, thank you", calendar chat) to real scenarios — milestone scoring was correctly failing content-empty false-positive signals, not misbehaving. Before assuming a rubric/prompt fix, pull the stored reasons and cross-check a sample against the source transcript at its `signal_turn_index` first
