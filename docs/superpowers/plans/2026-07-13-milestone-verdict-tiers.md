# Milestone Verdict Tiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the binary `hit: true/false` milestone-scoring output with a 3-tier `verdict` (`full_hit` / `partial_hit` / `miss`) plus evidence (`quote`, `gap_to_ideal`) gated to non-full-hit records, per `docs/superpowers/specs/2026-07-13-milestone-verdict-tiers-design.md`.

**Architecture:** Gemma's Step-3 milestone-scoring prompt returns a `verdict` tier instead of a boolean, plus `quote`/`gap_to_ideal` evidence fields (empty on `full_hit`). `milestone_performance` gains a `partial_hits` column so the aggregate can be weighted (`(hits + 0.5*partial_hits) / attempts`) instead of a flat hit-rate. `gap_events` gains a `milestones_partial_hit` column. Verdict thresholds reuse the entailment-probability boundaries already documented for the not-yet-built V2 NLI scorer (`Ego_trap.md` Step 3 V2), so nothing needs to change in meaning when that scorer is eventually built.

**Tech Stack:** Python 3.11, Gemma 4 31B (`shared/gemma.py`), PostgreSQL (`psycopg`), pytest + `pytest-mock`.

## Global Constraints

- No backward-compatible boolean is kept anywhere — `hit: bool` is fully replaced by `verdict: str`. Ego Trap tables are wiped between tuning runs (`clear_ego_trap_data.py`); there is no external consumer of the old shape.
- Verdict values are exactly one of: `"full_hit"`, `"partial_hit"`, `"miss"`. Any unrecognized or missing value from Gemma defaults to `"miss"` (fail conservative, matching today's `bool(result.get("hit"))` defaulting to `False` on missing data).
- `quote` and `gap_to_ideal` are only meaningful (non-empty) for `partial_hit` and `miss` — `full_hit` records carry empty strings for both, matching the design's "full hits produce no evidence" rule.
- Soft skill scoring (`score_soft_skills`, `score_soft_skills_batch`) is unchanged — out of scope per the design doc.
- Schema changes use `ADD COLUMN IF NOT EXISTS` so `db/init_db.py` (already idempotent, run on every deploy) upgrades the live database without a separate migration script.

---

### Task 1: Verdict-tier milestone scoring (prompts + scoring logic)

**Files:**
- Modify: `Brain/shared/prompts.py:183-200` (`PROMPT_STEP3_MILESTONE_SCORE`), `Brain/shared/prompts.py:219-230` (`PROMPT_STEP3_MILESTONE_SCORE_BATCH`)
- Modify: `Brain/ego_trap/milestone_scoring.py:14-38` (`score_milestones`), `Brain/ego_trap/milestone_scoring.py:71-110` (`score_milestones_batch`)
- Test: `Brain/tests/test_ego_trap_milestone_scoring.py` (new file)

**Interfaces:**
- Consumes: `shared.gemma.call_gemma(prompt: str, api_key: str) -> dict` (unchanged signature; mocked in tests via `mocker.patch("ego_trap.milestone_scoring.call_gemma", ...)`), `config.Config` (frozen dataclass — construct directly in tests, no `.env` needed).
- Produces: `score_milestones(rubric: dict, csm_response_text: str, benchmark_response: str, config: Config) -> list[dict]` and `score_milestones_batch(items: list[dict], config: Config) -> list[list[dict]]`, where each result dict has exactly these keys: `milestone_id: str`, `milestone_description: str`, `verdict: str` (one of `"full_hit"`/`"partial_hit"`/`"miss"`), `confidence: str`, `reason: str`, `quote: str`, `gap_to_ideal: str`. Task 3 consumes this exact shape.

- [ ] **Step 1: Write the failing tests**

Create `Brain/tests/test_ego_trap_milestone_scoring.py`:

```python
from config import Config
from ego_trap import milestone_scoring


def _config():
    return Config(
        gemma_api_key="key",
        database_url="",
        joveo_speakers_lower=frozenset(),
        naren_name_lower="",
        pinecone_api_key="",
        pinecone_index_name="",
    )


def test_score_milestones_full_hit_has_no_evidence(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={"verdict": "full_hit", "confidence": "high", "reason": "Covered fully.", "quote": "", "gap_to_ideal": ""},
    )
    rubric = {"milestones": [{"order": 1, "description": "Acknowledge urgency", "detection_hint": "hint"}]}

    results = milestone_scoring.score_milestones(rubric, "We'll fix this today.", "benchmark text", _config())

    assert results == [{
        "milestone_id": "M1",
        "milestone_description": "Acknowledge urgency",
        "verdict": "full_hit",
        "confidence": "high",
        "reason": "Covered fully.",
        "quote": "",
        "gap_to_ideal": "",
    }]


def test_score_milestones_partial_hit_carries_evidence(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={
            "verdict": "partial_hit",
            "confidence": "medium",
            "reason": "Acknowledged but no timeline given.",
            "quote": "We'll look into it.",
            "gap_to_ideal": "Should have committed to a specific resolution date.",
        },
    )
    rubric = {"milestones": [{"order": 1, "description": "Commit to a resolution date", "detection_hint": "hint"}]}

    results = milestone_scoring.score_milestones(rubric, "We'll look into it.", "benchmark text", _config())

    assert results[0]["verdict"] == "partial_hit"
    assert results[0]["quote"] == "We'll look into it."
    assert results[0]["gap_to_ideal"] == "Should have committed to a specific resolution date."


def test_score_milestones_unrecognized_verdict_defaults_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value={"confidence": "low", "reason": "unparseable"},
    )
    rubric = {"milestones": [{"order": 1, "description": "d", "detection_hint": "h"}]}

    results = milestone_scoring.score_milestones(rubric, "text", "benchmark", _config())

    assert results[0]["verdict"] == "miss"
    assert results[0]["quote"] == ""
    assert results[0]["gap_to_ideal"] == ""


def test_score_milestones_batch_matches_by_id_and_defaults_missing_to_miss(mocker):
    mocker.patch(
        "ego_trap.milestone_scoring.call_gemma",
        return_value=[
            {"id": "S0_M1", "verdict": "full_hit", "confidence": "high", "reason": "r0", "quote": "", "gap_to_ideal": ""},
            {"id": "S1_M1", "verdict": "miss", "confidence": "high", "reason": "r1", "quote": "", "gap_to_ideal": "Should have addressed pricing."},
        ],
    )
    items = [
        {"rubric": {"milestones": [{"order": 1, "description": "d0", "detection_hint": "h0"}]}, "csm_response_text": "resp0", "benchmark_response": "bench0"},
        {"rubric": {"milestones": [{"order": 1, "description": "d1", "detection_hint": "h1"}]}, "csm_response_text": "resp1", "benchmark_response": "bench1"},
        {"rubric": {"milestones": [{"order": 1, "description": "d2", "detection_hint": "h2"}]}, "csm_response_text": "resp2", "benchmark_response": "bench2"},
    ]

    results_by_item = milestone_scoring.score_milestones_batch(items, _config())

    assert results_by_item[0][0]["verdict"] == "full_hit"
    assert results_by_item[1][0]["verdict"] == "miss"
    assert results_by_item[1][0]["gap_to_ideal"] == "Should have addressed pricing."
    # item 2's id (S2_M1) was never returned by Gemma -> defaults to miss, not a crash
    assert results_by_item[2][0]["verdict"] == "miss"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `..\.venv\Scripts\pytest Brain/tests/test_ego_trap_milestone_scoring.py -v` (from repo root, per `CLAUDE.md`'s note to use the root venv directly)
Expected: FAIL — `results[0]["verdict"]` raises `KeyError: 'verdict'` (current code produces `"hit"`, not `"verdict"`).

- [ ] **Step 3: Update the prompts**

In `Brain/shared/prompts.py`, replace the `PROMPT_STEP3_MILESTONE_SCORE` block (lines 183-200):

```python
PROMPT_STEP3_MILESTONE_SCORE = """\
You are evaluating whether a CSM's response satisfies a specific milestone.

MILESTONE: {milestone_description}
DETECTION HINT: {detection_hint}
NAREN'S BENCHMARK RESPONSE (for reference only): {benchmark_response}

CSM RESPONSE:
"{csm_response}"

Score how well the CSM's response satisfies this milestone, using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

Respond ONLY with valid JSON:
{{
  "verdict": "full_hit",
  "confidence": "high",
  "reason": "one sentence explanation",
  "quote": "verbatim excerpt from the CSM response this verdict is based on (empty string if verdict is full_hit)",
  "gap_to_ideal": "one sentence on what a full_hit response would have included (empty string if verdict is full_hit)"
}}
"""
```

And replace `PROMPT_STEP3_MILESTONE_SCORE_BATCH` (lines 219-230):

```python
PROMPT_STEP3_MILESTONE_SCORE_BATCH = """\
You are evaluating whether CSM responses satisfy specific milestones, across multiple independent items.
Each item below has a unique "id". Evaluate EACH item independently — do not let one item influence another.

Score each item using exactly one of three verdicts:
- "full_hit": the milestone is fully satisfied
- "partial_hit": the CSM attempted this milestone but the response is incomplete or weak
- "miss": the milestone was not addressed at all

ITEMS:
{items_block}

Respond ONLY with valid JSON — a single array with exactly one object per item, in this shape:
[
  {{"id": "<id>", "verdict": "full_hit", "confidence": "high", "reason": "one sentence explanation", "quote": "verbatim excerpt (empty string if verdict is full_hit)", "gap_to_ideal": "one sentence (empty string if verdict is full_hit)"}}
]
"""
```

- [ ] **Step 4: Update `score_milestones` and `score_milestones_batch`**

In `Brain/ego_trap/milestone_scoring.py`, add this helper near the top (after the imports, before `_DEFAULT_SKILL_NAME`):

```python
_VALID_VERDICTS = {"full_hit", "partial_hit", "miss"}


def _normalize_verdict(raw: dict) -> str:
    verdict = raw.get("verdict")
    return verdict if verdict in _VALID_VERDICTS else "miss"
```

Replace the body of `score_milestones` (lines 30-37):

```python
        result = call_gemma(prompt, config.gemma_api_key)
        results.append({
            "milestone_id": milestone_id,
            "milestone_description": milestone.get("description", ""),
            "verdict": _normalize_verdict(result),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
            "quote": result.get("quote", ""),
            "gap_to_ideal": result.get("gap_to_ideal", ""),
        })
```

Replace the tail of `score_milestones_batch` (lines 101-109):

```python
    for i, milestone_id, description in entries:
        r = by_id.get(f"S{i}_{milestone_id}", {})
        results_by_item[i].append({
            "milestone_id": milestone_id,
            "milestone_description": description,
            "verdict": _normalize_verdict(r),
            "confidence": r.get("confidence", "low"),
            "reason": r.get("reason", ""),
            "quote": r.get("quote", ""),
            "gap_to_ideal": r.get("gap_to_ideal", ""),
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `..\.venv\Scripts\pytest Brain/tests/test_ego_trap_milestone_scoring.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add Brain/shared/prompts.py Brain/ego_trap/milestone_scoring.py Brain/tests/test_ego_trap_milestone_scoring.py
git commit -m "feat: replace milestone hit boolean with full_hit/partial_hit/miss verdict"
```

---

### Task 2: Verdict-aware storage (schema + upsert logic)

**Files:**
- Modify: `Brain/db/schema.sql:62-72` (`milestone_performance` table), `Brain/db/schema.sql:87-98` (`gap_events` table)
- Modify: `Brain/shared/storage.py:182-200` (`upsert_milestone_performance`), `Brain/shared/storage.py:222-241` (`insert_gap_event`)

**Interfaces:**
- Consumes: nothing new — `psycopg.Connection`, already-established connection patterns.
- Produces: `storage.upsert_milestone_performance(conn, csm_id: str, rubric_id: int, milestone_id: str, scenario_key: str, verdict: str) -> None` (replaces the old `hit: bool` parameter). `storage.insert_gap_event(conn, event: dict) -> int` now reads an additional `event["milestones_partial_hit"]` key (defaults to `[]` if absent). Task 3 calls both of these with the new signatures.

No automated test for this task — `Brain/tests/` has no existing coverage for `storage.py` (it requires a live PostgreSQL connection, same reason `test_ego_trap_gap_output.py` never touches the DB layer directly). Verification is manual, via Step 6 below.

- [ ] **Step 1: Add `partial_hits` to `milestone_performance`**

In `Brain/db/schema.sql`, replace the `milestone_performance` table block (lines 62-72):

```sql
-- milestone_id is synthesized as f"M{order}" from rubrics.milestones (no stable id in that JSONB)
-- hits = full_hit count only; partial_hits tracks partial_hit count separately.
-- Weighted score is computed at query time: (hits + 0.5 * partial_hits) / attempts.
CREATE TABLE IF NOT EXISTS milestone_performance (
    csm_id         TEXT NOT NULL REFERENCES csms(csm_id),
    rubric_id      INTEGER NOT NULL REFERENCES rubrics(rubric_id),
    milestone_id   TEXT NOT NULL,
    scenario_key   TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    hits           INTEGER NOT NULL DEFAULT 0,
    partial_hits   INTEGER NOT NULL DEFAULT 0,
    last_attempted TIMESTAMPTZ,
    PRIMARY KEY (csm_id, rubric_id, milestone_id)
);
ALTER TABLE milestone_performance ADD COLUMN IF NOT EXISTS partial_hits INTEGER NOT NULL DEFAULT 0;
```

- [ ] **Step 2: Add `milestones_partial_hit` to `gap_events`**

In the same file, replace the `gap_events` table block (lines 87-98):

```sql
-- Raw per-call gap output, kept for traceability. Writes here are gated by
-- ego_trap.settings.ENABLE_GAP_EVENTS so this can be disabled without a code change.
-- signal_turn_index: position in the parsed transcript, not a wall-clock time — these
-- transcripts carry no timestamps (see ego_trap/transcript_parser.py).
-- milestones_hit = full_hit ids only; milestones_partial_hit tracks partial_hit ids separately.
CREATE TABLE IF NOT EXISTS gap_events (
    gap_event_id           SERIAL PRIMARY KEY,
    call_id                TEXT NOT NULL,
    csm_id                 TEXT NOT NULL REFERENCES csms(csm_id),
    scenario_key           TEXT NOT NULL,
    rubric_id              INTEGER REFERENCES rubrics(rubric_id),
    signal_turn_index      INTEGER,
    gaps                   JSONB NOT NULL DEFAULT '[]',
    milestones_hit         TEXT[] NOT NULL DEFAULT '{}',
    milestones_partial_hit TEXT[] NOT NULL DEFAULT '{}',
    milestones_missed      TEXT[] NOT NULL DEFAULT '{}',
    created_at             TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE gap_events ADD COLUMN IF NOT EXISTS milestones_partial_hit TEXT[] NOT NULL DEFAULT '{}';
```

- [ ] **Step 3: Apply the schema change to the live database**

Run (from `Brain/`, with venv active and `.env` present):

```bash
python db/init_db.py
```

Expected output: `Database initialized.` with no errors — confirms both `ADD COLUMN IF NOT EXISTS` statements ran cleanly against the existing tables.

- [ ] **Step 4: Update `upsert_milestone_performance`**

In `Brain/shared/storage.py`, replace the function (lines 182-200):

```python
def upsert_milestone_performance(
    conn: psycopg.Connection,
    csm_id: str,
    rubric_id: int,
    milestone_id: str,
    scenario_key: str,
    verdict: str,
) -> None:
    hits = 1 if verdict == "full_hit" else 0
    partial_hits = 1 if verdict == "partial_hit" else 0
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO milestone_performance
              (csm_id, rubric_id, milestone_id, scenario_key, attempts, hits, partial_hits, last_attempted)
            VALUES (%s, %s, %s, %s, 1, %s, %s, NOW())
            ON CONFLICT (csm_id, rubric_id, milestone_id) DO UPDATE SET
                attempts = milestone_performance.attempts + 1,
                hits = milestone_performance.hits + EXCLUDED.hits,
                partial_hits = milestone_performance.partial_hits + EXCLUDED.partial_hits,
                last_attempted = NOW()
        """, (csm_id, rubric_id, milestone_id, scenario_key, hits, partial_hits))
    conn.commit()
```

- [ ] **Step 5: Update `insert_gap_event`**

In the same file, replace the function (lines 222-241, up through `return gap_event_id`):

```python
def insert_gap_event(conn: psycopg.Connection, event: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gap_events
              (call_id, csm_id, scenario_key, rubric_id, signal_turn_index,
               gaps, milestones_hit, milestones_partial_hit, milestones_missed)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING gap_event_id
        """, (
            event["call_id"],
            event["csm_id"],
            event["scenario_key"],
            event.get("rubric_id"),
            event.get("signal_turn_index"),
            json.dumps(event.get("gaps", [])),
            event.get("milestones_hit", []),
            event.get("milestones_partial_hit", []),
            event.get("milestones_missed", []),
        ))
        gap_event_id = cur.fetchone()[0]
    conn.commit()
    return gap_event_id
```

- [ ] **Step 6: Manually verify the new columns**

Run (from `Brain/`, venv active):

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
import psycopg
conn = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True)
cur = conn.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='milestone_performance' AND column_name='partial_hits'\")
print('milestone_performance.partial_hits:', cur.fetchone())
cur = conn.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='gap_events' AND column_name='milestones_partial_hit'\")
print('gap_events.milestones_partial_hit:', cur.fetchone())
"
```

Expected: both print a non-`None` tuple (e.g. `('partial_hits',)` and `('milestones_partial_hit',)`), confirming both columns exist.

- [ ] **Step 7: Commit**

```bash
git add Brain/db/schema.sql Brain/shared/storage.py
git commit -m "feat: add partial_hits/milestones_partial_hit columns for verdict aggregation"
```

---

### Task 3: Verdict-aware gap records

**Files:**
- Modify: `Brain/ego_trap/gap_output.py:21-98` (`build_gap_record`, `write_gap_record`)
- Test: `Brain/tests/test_ego_trap_gap_output.py:17-38` (`test_build_gap_record_separates_hits_and_misses`)

**Interfaces:**
- Consumes: `milestone_scoring`'s result-dict shape from Task 1 (`verdict`, `confidence`, `reason`, `quote`, `gap_to_ideal` keys), `storage.upsert_milestone_performance(conn, csm_id, rubric_id, milestone_id, scenario_key, verdict: str)` and `storage.insert_gap_event(conn, event: dict)` from Task 2.
- Produces: `build_gap_record(...) -> dict` with keys `call_id, csm_id, scenario_key, rubric_id, turn_index, gaps, milestones_hit, milestones_partial_hit, milestones_missed` (adds `milestones_partial_hit`; `milestones_hit` now means full_hit only). `ego_trap/pipeline.py:137` reads `gap_record['milestones_missed']` for a print statement — unaffected, that key is unchanged.

- [ ] **Step 1: Update the failing test**

In `Brain/tests/test_ego_trap_gap_output.py`, replace `test_build_gap_record_separates_hits_and_misses` (lines 17-38) with:

```python
def test_build_gap_record_separates_full_hit_partial_hit_and_miss():
    signal = {"turn_index": 4, "client_utterance": "..."}
    milestone_results = [
        {"milestone_id": "M1", "milestone_description": "d1", "verdict": "full_hit", "confidence": "high", "reason": "r1", "quote": "", "gap_to_ideal": ""},
        {"milestone_id": "M2", "milestone_description": "d2", "verdict": "partial_hit", "confidence": "medium", "reason": "r2", "quote": "q2", "gap_to_ideal": "g2"},
        {"milestone_id": "M3", "milestone_description": "d3", "verdict": "miss", "confidence": "high", "reason": "r3", "quote": "q3", "gap_to_ideal": "g3"},
    ]
    soft_skill_results = [
        {"skill": "Confidence Under Pushback", "rating": "failing", "confidence": "high", "reason": "r4"},
        {"skill": "Empathy", "rating": "excellent", "confidence": "high", "reason": "r5"},
    ]

    record = gap_output.build_gap_record(
        "call1", "CSM_X", "scenario_a", 7, signal, milestone_results, soft_skill_results
    )

    assert record["milestones_hit"] == ["M1"]
    assert record["milestones_partial_hit"] == ["M2"]
    assert record["milestones_missed"] == ["M3"]
    assert len(record["gaps"]) == 3

    partial_gap = record["gaps"][0]
    assert partial_gap["gap_type"] == "Milestone_Omission"
    assert partial_gap["verdict"] == "partial_hit"
    assert partial_gap["quote"] == "q2"
    assert partial_gap["gap_to_ideal"] == "g2"

    miss_gap = record["gaps"][1]
    assert miss_gap["verdict"] == "miss"
    assert miss_gap["quote"] == "q3"

    assert record["gaps"][2]["gap_type"] == "Soft_Skill_Failure"
    assert record["gaps"][2]["skill"] == "Confidence Under Pushback"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\.venv\Scripts\pytest Brain/tests/test_ego_trap_gap_output.py::test_build_gap_record_separates_full_hit_partial_hit_and_miss -v`
Expected: FAIL with `KeyError: 'verdict'` (current code reads `m["hit"]`, a boolean).

- [ ] **Step 3: Update `build_gap_record`**

In `Brain/ego_trap/gap_output.py`, replace the function (lines 21-67):

```python
def build_gap_record(
    call_id: str,
    csm_id: str,
    scenario_key: str,
    rubric_id: int,
    signal: dict,
    milestone_results: list[dict],
    soft_skill_results: list[dict],
) -> dict:
    """Step 4: assemble the gap output structure from Ego_trap.md section 5."""
    gaps = []
    milestones_hit = []
    milestones_partial_hit = []
    milestones_missed = []

    for m in milestone_results:
        verdict = m["verdict"]
        if verdict == "full_hit":
            milestones_hit.append(m["milestone_id"])
            continue

        if verdict == "partial_hit":
            milestones_partial_hit.append(m["milestone_id"])
        else:
            milestones_missed.append(m["milestone_id"])

        gaps.append({
            "gap_type": "Milestone_Omission",
            "milestone_id": m["milestone_id"],
            "milestone_description": m["milestone_description"],
            "verdict": verdict,
            "confidence": m["confidence"],
            "reason": m["reason"],
            "quote": m["quote"],
            "gap_to_ideal": m["gap_to_ideal"],
        })

    for s in soft_skill_results:
        if s["rating"] == "failing":
            gaps.append({
                "gap_type": "Soft_Skill_Failure",
                "skill": s["skill"],
                "rating": s["rating"],
                "reason": s["reason"],
            })

    return {
        "call_id": call_id,
        "csm_id": csm_id,
        "scenario_key": scenario_key,
        "rubric_id": rubric_id,
        "turn_index": signal["turn_index"],
        "gaps": gaps,
        "milestones_hit": milestones_hit,
        "milestones_partial_hit": milestones_partial_hit,
        "milestones_missed": milestones_missed,
    }
```

- [ ] **Step 4: Update `write_gap_record`**

In the same file, replace the function (lines 70-98):

```python
def write_gap_record(
    conn: psycopg.Connection,
    csm_id: str,
    csm_name: str,
    rubric_id: int,
    gap_record: dict,
) -> None:
    storage.upsert_csm(conn, csm_id, csm_name)
    for milestone_id in gap_record["milestones_hit"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="full_hit"
        )
    for milestone_id in gap_record["milestones_partial_hit"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="partial_hit"
        )
    for milestone_id in gap_record["milestones_missed"]:
        storage.upsert_milestone_performance(
            conn, csm_id, rubric_id, milestone_id, gap_record["scenario_key"], verdict="miss"
        )
    storage.upsert_signal_recognition_gap(conn, csm_id, gap_record["scenario_key"], recognized=True)

    if settings.ENABLE_GAP_EVENTS:
        storage.insert_gap_event(conn, {
            "call_id": gap_record["call_id"],
            "csm_id": csm_id,
            "scenario_key": gap_record["scenario_key"],
            "rubric_id": rubric_id,
            "signal_turn_index": gap_record["turn_index"],
            "gaps": gap_record["gaps"],
            "milestones_hit": gap_record["milestones_hit"],
            "milestones_partial_hit": gap_record["milestones_partial_hit"],
            "milestones_missed": gap_record["milestones_missed"],
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `..\.venv\Scripts\pytest Brain/tests/test_ego_trap_gap_output.py -v`
Expected: PASS (all tests in the file, including the 3 `compute_severity` tests, which are untouched)

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `..\.venv\Scripts\pytest Brain/tests/ -v`
Expected: PASS — no other test file references milestone `hit`/`verdict`.

- [ ] **Step 7: Commit**

```bash
git add Brain/ego_trap/gap_output.py Brain/tests/test_ego_trap_gap_output.py
git commit -m "feat: build gap records from full_hit/partial_hit/miss verdicts"
```

---

### Task 4: Sync `Ego_trap.md` spec to the implemented behavior

**Files:**
- Modify: `Ego_trap.md:225-244` (Step 3 V1 prompt example), `Ego_trap.md:266-293` (Step 3 V2 NLI section), `Ego_trap.md:303-333` (Step 4 gap output JSON example), `Ego_trap.md:348-357` (Layer D upsert SQL)

**Interfaces:** None — this task only edits documentation to match the code shipped in Tasks 1-3. No code interfaces are produced or consumed.

- [ ] **Step 1: Update the Step 3 V1 prompt example**

In `Ego_trap.md`, replace the prompt-structure code block under "V1 — Gemma 4 31B (Google AI Studio)" (lines 227-244):

```
Did the CSM's response satisfy this milestone?
Respond with a JSON object using exactly one of three verdicts:
{
  "verdict": "full_hit" | "partial_hit" | "miss",
  "confidence": "high"/"medium"/"low",
  "reason": "one sentence explanation",
  "quote": "verbatim excerpt this verdict is based on (empty string if verdict is full_hit)",
  "gap_to_ideal": "what a full_hit response would have included (empty string if verdict is full_hit)"
}
```

Immediately below that block, add:

> **Verdict tiers:** `full_hit` (milestone fully satisfied), `partial_hit` (attempted but incomplete/weak), `miss` (not addressed). These three tiers are the same boundaries the V2 NLI scorer below uses (`entailment_score >= 0.80` / `0.55-0.79` / `< 0.55`), so a `partial_hit` means the same thing regardless of which scorer produced it.
>
> **Evidence gating:** `quote` and `gap_to_ideal` are only populated for `partial_hit`/`miss` — a `full_hit` never needs evidence, since nothing is surfaced to a coach for it.

- [ ] **Step 2: Update the Step 3 V2 NLI section**

Replace the `score_milestone_nli` function body (lines 277-289):

```python
def score_milestone_nli(csm_response: str, milestone_description: str) -> dict:
    # NLI labels: contradiction, neutral, entailment
    score = nli_model.predict([(csm_response, milestone_description)])
    entailment_score = score[0][2]  # entailment probability

    if entailment_score >= 0.80:
        return {"verdict": "full_hit", "confidence": "high", "method": "nli"}
    elif entailment_score >= 0.55:
        # Borderline — escalate to Gemma, which decides full_hit vs partial_hit vs miss
        return score_milestone_gemma(csm_response, milestone_description)
    else:
        # Confident miss — still needs evidence (quote + gap_to_ideal), so a
        # separate small Gemma call generates that even though NLI decided the tier.
        return score_milestone_evidence_only(csm_response, milestone_description, verdict="miss")
```

Update the line below it (line 291, "Gemma fallback: ...") to:

> **Gemma fallback:** fires when NLI confidence is borderline (0.55-0.80) to decide the tier, and always for soft skill rubric scoring where tone and delivery judgment is needed — NLI cannot evaluate those reliably. A separate, narrower Gemma call (`score_milestone_evidence_only`) also fires whenever NLI confidently decides `miss` on its own, purely to generate `quote`/`gap_to_ideal` evidence — this scales with gap count, not call count, so it doesn't undermine V2's cost-reduction goal.

- [ ] **Step 3: Update the Step 4 gap output JSON example**

Replace the JSON example (lines 303-333):

```json
{
  "call_id": "CALL_CSM_PRIYA_2025_Q3_007",
  "csm_id": "CSM_PRIYA_001",
  "scenario_key": "competitive_objection:appcast",
  "rubric_id": "RUB_NRN_APPCAST_001",
  "timestamp": "00:00:12",
  "gaps": [
    {
      "gap_type": "Milestone_Omission",
      "milestone_id": "M3",
      "milestone_description": "Deliver security by introducing immediate structural auditing capabilities",
      "verdict": "miss",
      "confidence": "high",
      "reason": "CSM explained the product difference but never introduced a concrete auditing or transparency guardrail",
      "quote": "We're definitely more affordable than Appcast for this volume.",
      "gap_to_ideal": "Should have named a specific auditing or transparency capability, not just a cost comparison",
      "severity": "critical",
      "bloom_level": "Evaluate",
      "naren_example_chunk_id": "CHK_NRN_APPCAST_001"
    },
    {
      "gap_type": "Soft_Skill_Failure",
      "skill": "Confidence Under Pushback",
      "rating": "failing",
      "reason": "CSM became defensive and validated the client's negative premise without reframing",
      "severity": "high"
    }
  ],
  "milestones_hit": ["M1", "M2"],
  "milestones_partial_hit": [],
  "milestones_missed": ["M3"]
}
```

- [ ] **Step 4: Update the Layer D upsert SQL**

Replace the milestone performance upsert SQL (lines 348-357):

```sql
-- Milestone performance upsert
-- hits = full_hit count only; partial_hits tracks partial_hit count separately.
-- Weighted score computed at query time: (hits + 0.5 * partial_hits) / attempts.
INSERT INTO milestone_performance
  (csm_id, rubric_id, milestone_id, scenario_key, attempts, hits, partial_hits, last_attempted)
VALUES ($1, $2, $3, $4, 1, $5, $6, NOW())
ON CONFLICT (csm_id, rubric_id, milestone_id)
DO UPDATE SET
  attempts = milestone_performance.attempts + 1,
  hits = milestone_performance.hits + EXCLUDED.hits,
  partial_hits = milestone_performance.partial_hits + EXCLUDED.partial_hits,
  last_attempted = NOW();
```

- [ ] **Step 5: Commit**

```bash
git add Ego_trap.md
git commit -m "docs: sync Ego_trap.md Step 3/4 spec with full_hit/partial_hit/miss verdicts"
```

---

## Self-Review Notes

- **Spec coverage:** verdict tiers (Task 1), evidence gating (Tasks 1 & 3), storage aggregation (Task 2), gap_events shape (Tasks 2 & 3), doc sync (Task 4) — all five spec sections have a task.
- **Placeholder scan:** no TBD/TODO; every step has literal code or an exact command with expected output.
- **Type consistency:** `verdict: str` and the `quote`/`gap_to_ideal`/`confidence`/`reason` keys are identical across Task 1's producer and Task 3's consumer. `storage.upsert_milestone_performance`'s `verdict` parameter (Task 2) matches the string literals `"full_hit"`/`"partial_hit"`/`"miss"` passed by `write_gap_record` (Task 3).
