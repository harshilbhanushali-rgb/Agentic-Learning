# Brain — Gotchas

[Back to Brain/CLAUDE.md](../CLAUDE.md)

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
- **Both substantive filters delete the word "Indeed", and one of them is live — measured 2026-08-14.** They count `t.is_alpha and not t.is_stop` against spaCy `en_core_web_lg`'s stoplist, and **`'indeed' in nlp.Defaults.stop_words` is `True`** (both cased forms). In a recruitment-advertising corpus that removes the name of a major job board from every sentence it appears in, while `ZipRecruiter` and `Greenhouse` are *not* stopwords — so the filter is inconsistent across competitors in the same domain. Measured: `"So right now we post everything manually to Indeed and ZipRecruiter."` keeps only `['right','post','manually','ZipRecruiter']` = **4, below the floor of 5** (`everything` and `now` go too). This is not hypothetical — **`layer_b._is_substantive` is ACTIVE and gates every trigger/response pair entering `kb_pairs`**, so genuinely substantive domain content can fall below the bar and never reach the KB. NOT FIXED. Note the trap in the obvious fix: whitelisting domain terms is exactly the "threshold must never be a curated list" anti-pattern this file forbids elsewhere, so this needs a different substantive test rather than a stopword exception list. Also blocks calibrating any new content-word floor (e.g. a chunk-gluing rule) until resolved
- **`layer_a.min_content_words: 5` is INERT in production — measured 2026-08-14.** `v2/layer_a.py::run_layer_a_v2` calls `build_client_clause_pool(all_turns)` with **no argument**, so the signature default `min_content_words: int = 0` wins and no pre-filter runs on the CLIENT clause pool. The tuning value is honoured only by `calibration/dry_run_layer_a.py`'s opt-in `--prefilter` flag. A configured key that reads as authoritative while doing nothing is the same failure class as the retired `ego_trap/settings.py`. Left off deliberately: enabling it would move a second variable in any Layer A pool experiment
- **The "Indeed" bug is now QUANTIFIED, and its cost is almost entirely a CLAUSE-MODE cost — measured 2026-08-16.** The bullet above says NOT FIXED with no measure of what it costs; here it is. Re-confirmed against the live stoplist: `'indeed'` is a stopword while **`ziprecruiter`, `greenhouse`, `workday` and `linkedin` are not**, so the filter is inconsistent across direct competitors. Against `layer_b._is_substantive` (the LIVE gate on every `kb_pair`): `"Indeed has $3 cost per API call."` keeps `['cost','API']` = **2**, `"They have the feed to Indeed. That's where the jobs get posted."` keeps 3, `"So right now we post everything manually to Indeed and ZipRecruiter."` keeps 4 — all **DROPPED**. **But every one of those is SENTENCE-length, i.e. the CLAUSE unit.** Over the 23,949-turn pool (mean 45.7 words, median 25): 674 turns (2.8%) mention Indeed, only **21** fail the filter, and only **7 would flip if `indeed` counted — 0.029% of the pool**. A whole turn does not cross a 5-word floor by losing one word; a sentence does. **So `pool_unit: turn` substantially MITIGATES this bug as a side effect, and it is a live confound in clause mode sitting directly on top of job-board content.** Weigh that in any clause-vs-turn comparison. Still unfixed, and `layer_b._is_substantive` gates `kb_pairs` at any unit, so a rescued Indeed turn is still not guaranteed to reach the KB
- `storage.get_scenarios` **must** select `is_coachable` and `cluster_kind`. It backs `_load_scenario_map`, which is the checkpoint-resume path — without them a resumed run treats every mechanics sink as coachable and generates rubrics for backchannel
- `layer_c`'s `min_milestone_calls_floor: 3` means a scenario whose responses span fewer than 3 calls can never satisfy the support gate, so it always falls through to the V1 Gemma fallback. That is intended (V1 still produces a rubric), but it means small scenarios are not clustered — don't read it as a bug
- V2 Layer A adjudication deliberately makes **no DB calls inside the Gemma loop**; all scenarios are written in one pass afterwards. Holding a Postgres connection across ~200 sequential Gemma calls invites the `IdleInTransactionSessionTimeout` / SSL-drop failure mode. Don't add an `upsert` back into that loop
- `tuning.yaml` keys are validated on load — an unknown or missing key raises rather than silently falling back to a default. Add the key to both `tuning.yaml` and the dataclass in `shared/tuning.py`, or the loader fails
- A threshold must never be a count of outputs or a curated list. Every knob in `tuning.yaml` is a property of the data (fraction of calls, cosine distance, relative margin, percentile) so that adding transcripts re-derives every bound. `MAX_CLUSTERS=150` is the cautionary tale: a count halts at N whether duplication remains or not
- `.gitignore` never applies to already-tracked files. `Brain/*.log` sat in `.gitignore` while 19 logs stayed tracked — they were committed before the rule existed, so 5.2MB of run output rode along in git. If run output appears in `git status` as tracked, the fix is `git rm --cached <file>` (leaves it on disk); editing `.gitignore` does nothing
- **Running the whole suite in one process is unreliable on 16GB Windows; run it file-by-file instead.** spaCy `en_core_web_lg` needs a **contiguous** 392MiB vector table, and four test files load it (`test_layer_b_assignment`, `test_layer_b_v1`, `test_sink_rescue`, `test_two_stage_matching`). Collection dies with any of `numpy._core._exceptions._ArrayMemoryError`, `MemoryError`, `ValueError: Could not reserve memory`, or torch's `OSError [WinError 1455] The paging file is too small`. **Free-MB is not the predictor and none of the obvious fixes work** — measured 2026-08-08/09: failed at 2.1GB free *and* at 2.7GB free, with a 20GB pagefile and 4.7GB commit free; killing 4 stale python processes freed only ~76MB and changed nothing. It is address-space fragmentation, not exhaustion, so don't resize the pagefile or hunt for a memory hog. One file per process always works (each releases its memory on exit) and yields the same 219 passed — in bash: `for f in tests/test_*.py; do ../.venv/Scripts/python.exe -m pytest "$f" -q; done`
- Before moving any Brain script into a subdirectory: grep `__file__` in it (every `Path(__file__).parent / "x"` silently re-resolves to the new subdirectory and needs `.parent.parent`) and confirm it has a `sys.path` bootstrap so `from config import ...` still resolves. Both bit the 2026-08-08 `ops/` move — 11 broken paths and 3 missing bootstraps
- Design specs under `docs/superpowers/specs/` still cite pre-2026-08-08 script paths (`dry_run_layer_a.py`, not `calibration/dry_run_layer_a.py`). Deliberately left alone as dated historical records — CLAUDE.md and each script's own docstring carry the live paths. Don't treat a stale path in a spec as a bug


---

## The gateway caps embeddings at 150 requests per window per key (2026-08-19)

`gemini-embedding-2` through the Joveo gateway returns
`HTTP 429 ... "Limit type: requests. Current limit: 150, Remaining: 0"`. The window is short
(sequential requests succeed again within a minute), so it is a rate cap, not a daily quota.

**Every fetch before 2026-08-19 was under 258 requests, so this had never been hit** and the
transport's inability to handle it was invisible. A corpus-sized fetch (11,872 texts) at
`workers=20` took 429s on every thread simultaneously and then **hard-failed** — because the
retry ladder waited 2+4+8 = **14 seconds against a ~60-second window** and could never have
recovered.

`calibration/trial_gateway.py` now carries a **module-level token bucket** (`EMBED_PER_MINUTE`,
default 140, override with `BRAIN_GATEWAY_EMBED_RPM`). Module-level is deliberate: the limit is
per API **key**, so two `GatewayClient` instances in one process must draw from one bucket or
they simply race each other into the same 429. Rate-limit retries escalate toward a full window
AND call `penalise()` on the shared bucket so sibling threads stop too.

**Plan corpus-sized embedding work in minutes, not seconds:** ~140/min means 12k texts is
~85 minutes. Order long jobs so the paced fetch runs LAST, after everything that does not need
it — routing consumes trigger and scenario vectors only, so a fetch of response vectors blocks
nothing if it is scheduled after the database writes.

## The gateway enforces a SECOND, independent limit: max_parallel_requests = 8 (2026-08-19)

Not the same wall as the one above, and pacing does not help with it:

```
HTTP 429 ... "Limit type: max_parallel_requests. Current limit: 8, Remaining: 0."
```

That is a **concurrency** ceiling — how many requests may be IN FLIGHT at once — while the
150/window cap is a **rate** ceiling. The token bucket controls how often a request STARTS and
says nothing about how many are outstanding, so the two need separate mechanisms.

**How it bit:** `ship_layer_b.py` hardcoded `embed_cached(..., 8)`, i.e. exactly the ceiling.
The fetch therefore ran permanently AT the limit with zero headroom, and since a retry is
itself a request, any request the gateway had not finished releasing rejected the next one. It
survived 70 minutes and **7,200 of 7,472 vectors** before losing all four retries inside one
window and hard-failing — the worst possible place to discover a concurrency limit.

**Fixed in `shared/gateway.py`, in the transport rather than at the call site:** a module-level
`threading.Semaphore(EMBED_MAX_PARALLEL)`, default **6**, held across the ENTIRE `_post`
including its retries (releasing it before a retry would let another request start while this
one is still logically alive). Module level for the same reason as the rate limiter — the limit
is per API KEY. Clamping in the transport matters because every calibration script that predates
this passes `workers=20` and none of them can be trusted to change.

**A concurrency 429 must NOT take the quota ladder.** It clears the moment a sibling request
finishes, so it gets a short JITTERED wait (`_PARALLEL_MARKERS`) and deliberately does not
`penalise()` the shared bucket — slowing the whole job down does not create a free parallel
slot, and releasing every worker on the same schedule just reproduces the collision.

## Editing a module while a process has it imported corrupts that process's traceback

Python has already compiled the module into memory, so **an edit does not change the running
code** — but a traceback re-reads the file from disk to render source lines. After
`calibration/trial_gateway.py` was rewritten mid-run, its crash printed
`"embed_batched output is positionally correct either way",` as the failing line inside
`_post`, which is a line from a completely different function. The line NUMBERS were from the
old file, the TEXT from the new one.

Harmless to execution, actively misleading to debugging. If a traceback's source line makes no
sense for the function it claims to be in, check whether the file changed after the process
started, and trust the exception message over the rendered source.

## Pinecone: dimension is immutable, and batch size must follow the vector width

`shared/pinecone_store.py::init_index` hardcoded `dimension=768` (bge's width) and was therefore
incapable of creating an index for `gemini-embedding-2@3072`. **A Pinecone index's dimension
cannot be altered after creation** — a wrong value means creating a new index, not fixing one.
It now derives the width from `embedding.backend`/`gemini_dimensions` or takes it explicitly.

`upsert_pairs` likewise hardcoded `BATCH=100`, which is ~0.31 MB per request at 768 and
**~1.2 MB at 3072** — close enough to Pinecone's ~2 MB request cap that a few long metadata
fields tip it over mid-job. The batch is now derived from the actual width (768 stays at exactly
100, pinned by test; 3072 lands at 26). `upsert_pairs` also takes a `namespaces` argument so
triggers and responses can land independently.

## Replacing the taxonomy is a REPLACEMENT, never an upsert

`upsert_scenario` is `ON CONFLICT (scenario_key) DO UPDATE`, which sounds right and is wrong for
a new map. Measured 2026-08-19: 161 live keys vs 259 new, **only 4 overlapping**. Upserting would
leave a 416-row table — 157 dead scenarios beside 255 new ones — and the 4 "updates" silently
rewrite a key to describe a different cluster from a different corpus.

Every dependent FK is `ON DELETE NO ACTION`, so Postgres **refuses** the parent delete until the
children go: `gap_events` + `milestone_performance` → `rubrics` → `kb_pairs` → `scenarios`. Use
`ops/ship_union_taxonomy.py`, which snapshots all ten tables into a dated schema (the pattern
this project already has fourteen of), **verifies every row count against source before deleting
anything**, and runs the deletes plus the load in one transaction.

**Two traps in the same area.** `calls` is an FK target for `kb_pairs` and it can be far short of
the corpus (416 rows against 1,059 calls) — upsert every transcript before any pair. And
`layer_bc_arms.scenario_map_from_rows` sets `scenario_id` to the artifact's **row index**, not the
database SERIAL ("a synthetic index. Nothing here touches Postgres"); rebind every key to the live
`scenarios.scenario_id` before writing `kb_pairs`, or pairs attach to whichever scenario happens
to hold that serial.

**Do not "fill in" adjudication rows with an empty `business_description`.** They are
`kind=merged` — pointers whose turns are already folded into their target's member set. Loading
them as scenarios double-counts their targets' evidence.

## `taxonomy_sha` is register-dependent and cannot compare arms

`layer_bc_arms.taxonomy_sha` hashes `scenario_text()`, which resolves
`layer_a.scenario_vector_mode`. So it **differs between a concat arm and a keyphrases arm by
construction**, and using it as a cross-arm identity check rejects an arm for being that arm.
Two blind code audits read that guard and neither flagged it; running it surfaced it in seconds.

Use `routing_playbook_ab.taxonomy_identity_sha` (key | coachability | description | keyphrases)
for cross-arm identity, and keep the register-dependent hash as a **positive** check: it must
DIFFER between arms whose register differs, which proves the treatment applied.

## The Bash tool's working directory can reset between calls

A `cd Brain && <command>` chain short-circuited when the shell's cwd had already moved to the
repo root — and because the `&&` failed silently while a trailing `; echo` still ran, the wrapper
**reported success having executed nothing**. It happened twice in one session, both times
looking like completion rather than failure.

**Use absolute paths for anything unattended**, and prefer `ops/run_visible.ps1` for long runs —
it does its own `Set-Location` internally, which is why the visible-window launches never hit
this.

## Reasoning effort is limited BY MODEL, not by the gateway (2026-08-20, corrected same day)

`high` was already known unreachable (~120s LiteLLM cap). **`medium` is also unusable**, and the
real limit is tighter and different from the one on record:

```text
HTTP 408 ... litellm.Timeout: Connection timed out. Timeout passed=15.0
```

**The gateway times its UPSTREAM call out at 15 seconds**, regardless of the 120s the client
allows. Measured on identical 50-pair map prompts, `gemini-3.5-flash-lite`:

| reasoning | calls | median | max | failures |
| --- | --- | --- | --- | --- |
| `low` | 15 | **4.0s** | 21.7s | **0** |
| `medium` | 2 | 16.0s | 76.7s (4 internal retries on one attempt) | **1 of 2** |

Low sits at a median of 4s with comfortable headroom. Medium roughly quadruples per-call time
and the map prompt stops fitting. **Backoff does not help** — the failure is request DURATION,
not rate, so the 2/4/8s transient ladder retries the same too-slow request and each retry costs
another counted attempt (one `call()` burned 76.7s across four 408s).

If medium or high is ever genuinely needed, the lever is **prompt size, not patience**: cut
`BATCH_MAX` (25 → ~12) so each request finishes inside 15s. That doubles the map calls per
document, so budget for it — and note it confounds any A/B that was holding batch size fixed.

**CORRECTION, same day — the paragraph above overgeneralised from one model.** "The gateway
times its upstream call out at 15 seconds" is FALSE as a general rule. Re-measured on
`gemini-3.6-flash`, identical 50-pair prompts, medium reasoning:

| model | effort | median | max | failures |
| --- | --- | --- | --- | --- |
| `gemini-3.5-flash-lite` | low | 4.0s | 21.7s | 0 |
| `gemini-3.5-flash-lite` | **medium** | 8.9s | 16.0s | **1 of 2 — 408 wall** |
| `gemini-3.6-flash` | low | 9.0s | 29.5s | 0 |
| `gemini-3.6-flash` | **medium** | **60.8s** | **70.7s** | **0** |

`gemini-3.6-flash` sustains 60-70 SECOND requests with zero timeouts. So the 15s figure in the
408 text is whatever timeout applied to flash-lite's upstream route, **not a gateway-wide cap**,
and `medium`/`high` are not categorically unavailable — they are unavailable ON THAT MODEL.

**Lesson worth more than the number:** an error message quoting a specific limit
(`Timeout passed=15.0`) invites you to treat it as a property of the system. It was a property
of one route. Re-measure on the model you actually intend to use before concluding a level is
unreachable — the first version of this entry would have wrongly ruled out the configuration
that went on to pass every gate.

## A blind-read `usable%` is NOT an absolute rate — only within-packet contrasts survive (2026-08-24)

The blind-read protocol was recorded as "reproducible to ~3pt between independent runs". That
claim came from one arm scoring 81% and 84% across two reads. **It was luck, and it is
retracted.** Measured twice on the same day, from two independent directions:

| what varied | population | result |
| --- | --- | --- |
| packet composition (which arm it sat beside) | the SAME 59 relevance-arm quotes | **95% then 78%** |
| reader framing (lenient vs strict prompt) | the SAME 123 live criteria | **84% then 17% gradable** |

The framing run also **inverted the cohort ranking** — the original 5 came out worst under one
framing and best under the other. So the absolute level is a property of the instrument, not of
the documents.

**The rule:** run every arm you want to compare **inside ONE packet**, counterbalanced, read by
one reader. Report contrasts ("gradability beat relevance 4 of 5 situations, 89% vs 78%"), never
levels. Never compare a number from one audit to a number from another.

**What this invalidates on the record:** every cross-audit absolute in the findings file,
including §11.3's headline "a 5-doc probe said 95%, 28 documents said 73%, so the probe
overestimates". Part of that 22-point gap is the instrument, not the sample size. The direction
is probably still right — more documents will regress from five — but the magnitude was never
measured. **Do not cite 95%→73% as a measured probe-inflation effect.**

Two mechanisms explain why the strict framing landed so much lower, and both are real
gradability defects that pull in OPPOSITE directions — which is why one number cannot capture
them:
- **evaluative vagueness** — "clearly explain the business impact" has no concrete anchor.
- **bundling** — "name the exact tracking columns AND walk through drop-off analysis" is two
  demands, so a quote satisfying one clause reads as partial.
The gradability rule attacks the first and, by forcing narrower criteria, also reduced the
second. Layer D's shipped `checks` arm asks a strictly BINARY `performed: true/false` per move
(`partial` is produced only by the `pairwise` arm), so bundling there does not cause grader
disagreement — it causes **hit inflation**, because the grader anchors its mandatory verbatim
quote on the easiest clause.

## The `calls` corpus contains real transcript duplicates under different filenames (2026-08-26)

Measured while auditing `ask-naren/prototype/eval_pairs_vs_playbook.py`'s retrieval-holdout logic: some transcripts were ingested twice into `calls`/`kb_pairs` under two different `filename` values, with byte-identical `(trigger_text, response_text)` pairs on both sides. Confirmed against the live coachable-scenario pool (6,528 rows): **64 rows are exact content duplicates — 32 distinct pairs, each present under 2 different call filenames — spread across 15 of the 34 coachable scenarios** (e.g. `Call5.txt` and `2a2bd7c6-4920-4762-a62b-41f5ae1dec50.txt` share all 16 pairs; similarly for `Call3.txt`/`Call4.txt` and their UUID-named twins).

`calls.filename` is UNIQUE (`db/schema.sql`), so these are genuinely two distinct rows in `calls`, not a constraint violation — Postgres has no way to know they're the same recording. Anything that assumes "one call = one filename = one real conversation" (a leave-one-call-out holdout, a `support_calls`/account-diversity count, a call-level dedup) can silently double-count a duplicate or fail to exclude its content-twin.

**Not fixed at the source.** `ask-naren/prototype/eval_pairs_vs_playbook.py` works around it downstream by deduping its own retrieval pool on normalized `(trigger_text, response_text)` content before use (`_load_coachable_pool`) — a per-consumer patch, not a corpus fix. Layer C's playbook `support_calls`/single-account diversity gates and Layer D's `move_events` may already be inflated by these duplicates, and this has **not** been checked. Worth a `calls`-level audit (e.g. grouping filenames whose transcripts hash identically) before trusting any per-call diversity metric at face value.

## A hardcoded status list in a plan summary hid five documents from the approval step (2026-08-24)

`ops/load_playbooks.py` printed its dry-run plan with `for status in ("live", "placebo",
"trial")`. When the playbook promotion introduced `'superseded'`, the summary printed counts
totalling 60 under a header reading **"PLAN 65 documents"** — five documents invisible in the
very output a human reads before typing `--apply`.

Nothing failed. Every gate passed, because the gates count rows in the database and the bug was
in the display. **A dry run is a safety mechanism only to the extent that it shows everything it
is about to do.** Fixed by iterating the statuses actually present and asserting the summarised
count equals the document count, so an unaccounted-for status now raises instead of vanishing.

Same class as `EXPECTED_COUNTS` meaning two things: a literal list that must be kept in sync
with data it does not derive from.

## `SET SESSION default_transaction_read_only = on` leaks across clients through Neon's pooler (2026-08-26)

A Layer D regrade kept failing with `cannot execute INSERT in a read-only transaction` —
repeatedly, across unrelated attempts, with no `ALTER DATABASE`/`ALTER ROLE` setting it
(`pg_db_role_setting` was empty) and no replica involved (`pg_is_in_recovery()` was `False`).
**Root cause, confirmed by direct reproduction, not inferred:** four scripts
(`ops/serve_ask_naren.py`, `calibration/probe_retrieval_gate.py`,
`calibration/score_naren_ceiling.py`, `calibration/layer_d_output_audit.py`) each open a
"safety" connection with `SET SESSION default_transaction_read_only = on` and then `conn.close()`
**without resetting it first**. Neon's pooled endpoint (PgBouncer transaction pooling) reuses the
same backend server connection across totally unrelated clients, so the leftover session GUC
poisons whichever client is handed that backend next — including a completely different script
in a completely different process, minutes later.

**Reproduced and fixed live, both directions**: poisoning a connection then opening a fresh one
made the fresh one inherit `read-only`; running `SET SESSION default_transaction_read_only = off`
on a "read-only" connection cleared it instantly, every time — proof it was always a leaked
session setting, never a genuine Neon-enforced restriction (a real restriction cannot be
overridden by a plain session `SET`). Fixed at the source in all four scripts: `.close()` is now
wrapped to reset the setting before the real close. Fixed defensively in Layer D itself too
(`storage.clear_read_only`, wired into every write loop in `layer_d/pipeline.py`): rather than
merely detecting read-only and aborting, it actively resets a leaked setting first and only
treats it as genuine if the reset doesn't take — because an unidentified fifth source of the same
anti-pattern can exist outside this codebase's control (e.g. another app sharing the database),
and detect-and-abort alone kept losing a full run's progress to something nobody could fix from
here.

**If you write a new "read-only connection" helper**: never leave `SET SESSION
default_transaction_read_only = on` in place when a connection returns to the pool. Either reset
it explicitly before `.close()` (see any of the four fixed scripts for the wrapped-close pattern)
or use `storage.get_connection` + `storage.clear_read_only` instead of hand-rolling it.

**Update 2026-08-28: a FIFTH in-repo instance existed** — `calibration/layer_d_grader_ab.py`
(the C2 harness) set the GUC in two places and closed without resetting; found during the
say-arm pre-spend audit pass. Fixed by removing the GUC entirely (the script never writes; the
"safety" bought nothing and the leak was real). If a sixth read-only "safety" connection exists
somewhere, this is the grep: `default_transaction_read_only = on`.


## Bash heredocs eat backslashes, and backticks get command-substituted (2026-08-27)

Feeding a Python script to `python -` through a **quoted** bash heredoc (`<<'PYEOF'`) does not
reliably preserve the content on this machine. Two distinct corruptions, both silent:

1. **`"\n"` arrives as a real newline.** A patch script containing
   `return "\n".join(lines)` wrote a file with an unterminated string literal. The script
   reported success, because the replacement it performed was a no-op — its `old` and `new`
   strings had both been mangled identically, so the assertion on occurrence count passed.
   It took three attempts to see it.
2. **Backticks are command-substituted even inside a quoted heredoc.** A markdown doc written
   this way silently lost the file path inside `` `like_this` `` — bash tried to execute it and
   substituted the empty result. The doc committed cleanly with a sentence beginning
   " measures what the frame does."

Both failures produce plausible-looking output, which is what makes them worth a gotcha.

**What works:** build such strings with `chr(10)` and `chr(92)` instead of escapes, or write
the script to a file with the Write tool and run it as a file. For markdown or any content
containing backticks, use the Write/Edit tools and never a heredoc.

## A monotonically numbered directory cannot refuse a duplicate (2026-08-27)

Two sessions were working the same worktree and branch. One listed `ask-naren/docs/adr/` at
session start, saw 0001 and 0002, and later wrote a new ADR as 0003. The other session had
committed **0003 and 0004** in between. Two files carried the same number, and both were
committed before anyone noticed; `c2521cd` renumbered the later one to 0005 and fixed three
references.

Nothing detects this — the filesystem accepts the name, git accepts the commit, and both
documents read as authoritative. **Re-list a numbered directory immediately before writing
into it, not once at the start of a session.** The same applies to migration files, fixture
numbers, and anything else whose identity is a counter.

Corollary, since the same conditions caused it: when another session may be writing to the
worktree, stage explicit paths and never `git add -A`. That discipline is what kept this
session's ten commits free of the other session's uncommitted Layer D work.
