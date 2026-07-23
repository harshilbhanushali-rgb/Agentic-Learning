# Naren's Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot Python pipeline that extracts Layers A, B, and C of Naren's Brain from call transcripts, storing relational metadata, vector pairs, and evaluation rubrics in PostgreSQL.

**Architecture:** Shared preprocessing (transcript parser → spaCy segmenter → BGE-M3 embedder) feeds two versioned pipelines — V1 uses Gemma 4 31B directly for all LLM steps; V2 swaps in BERTopic + HDBSCAN clustering for the statistical steps, keeping Gemma only for prose generation. `main.py` asks the user which to run.

**Tech Stack:** Python 3.11, `google-genai` (Gemma 4 31B via Google AI Studio), `FlagEmbedding` (BGE-M3), `spacy` (en_core_web_lg), `psycopg[binary]` + `pgvector`, `bertopic` + `umap-learn` + `hdbscan` (V2), `pytest` + `pytest-mock`.

## Global Constraints

- All Python files live under `Brain/` (project root). Run all commands from `Brain/`.
- The venv is at `c:\PF\Joveo\CS-platform\.venv` — activate with `.venv\Scripts\activate` (Windows).
- uv is the package manager: use `uv pip install -r requirements.txt` or `uv add <pkg>`.
- Transcript `.txt` files go in `Brain/recordings/`. One file = one call. Filename stem = call_id.
- Real transcript format: `SpeakerName\n` then utterance text, blank lines between turns. **No participant header block.**
- Speaker classification is config-driven via `JOVEO_SPEAKER_NAMES` env var (comma-separated). No speaker names hardcoded in Python files.
- Remote PostgreSQL. The `pgvector` extension must already be enabled on the server.
- All Gemma calls use `response_mime_type="application/json"` — no post-hoc JSON parsing fragility.
- V2 clustering imports are deferred inside `if` branches in `main.py` — a V1 run must not fail if V2 packages are absent.
- `pipeline_version` column distinguishes V1 vs V2 rubrics: `'v1'` or `'v2'`.

---

## File Structure

```
Brain/
├── recordings/                    ← place .txt transcript files here
├── tests/
│   ├── conftest.py
│   ├── test_transcript_parser.py
│   ├── test_segmenter.py
│   └── test_layer_b_v1.py
├── preprocessing/
│   ├── __init__.py
│   ├── transcript_parser.py       ← .txt → list[Turn]
│   ├── segmenter.py               ← spaCy clause splitting
│   └── embedder.py                ← BGE-M3 singleton (query + document modes)
├── shared/
│   ├── __init__.py
│   ├── gemma.py                   ← google-genai wrapper, JSON output, retry
│   ├── storage.py                 ← psycopg3 + pgvector CRUD
│   └── prompts.py                 ← all Gemma prompt templates
├── db/
│   ├── schema.sql                 ← CREATE TABLE / INDEX statements
│   └── init_db.py                 ← runs schema.sql against DB
├── v1/
│   ├── __init__.py
│   ├── layer_a.py                 ← Gemma-direct scenario identification
│   ├── layer_b.py                 ← rule-based extraction + embed + store
│   ├── layer_c.py                 ← Gemma-direct milestone + rubric generation
│   └── pipeline.py                ← V1 orchestration
├── v2/
│   ├── __init__.py
│   ├── layer_a.py                 ← BERTopic scenario clustering + Gemma labelling
│   ├── layer_b.py                 ← re-export of v1.layer_b (no duplication)
│   ├── layer_c.py                 ← HDBSCAN clause clustering + median ordering
│   └── pipeline.py                ← V2 orchestration
├── main.py                        ← entry point: asks V1 or V2, runs pipeline
├── config.py                      ← loads .env, returns frozen Config dataclass
├── pyproject.toml
└── .env.example
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `Brain/pyproject.toml`
- Create: `Brain/.env.example`
- Create: `Brain/recordings/` (empty folder, add `.gitkeep`)
- Create all `__init__.py` stubs

- [ ] **Step 1: Create `Brain/pyproject.toml`**

```toml
[project]
name = "narens-brain"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "psycopg[binary]>=3.1",
    "pgvector>=0.3",
    "spacy>=3.7",
    "FlagEmbedding>=1.2",
    "torch>=2.1",
    "google-genai>=0.8",
    "python-dotenv>=1.0",
    "numpy>=1.26",
    "bertopic>=0.16",
    "umap-learn>=0.5",
    "hdbscan>=0.8",
    "scikit-learn>=1.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.14",
]
```

- [ ] **Step 2: Create `Brain/.env.example`**

```
GEMMA_API_KEY=your_google_ai_studio_key_here
DATABASE_URL=postgresql://user:pass@host:5432/narens_brain
JOVEO_SPEAKER_NAMES=Naren Shankar,Collin Osburn,Doug Shonrock
NAREN_SPEAKER_NAME=Naren Shankar
```

Copy to `.env` and fill in real values. `DATABASE_URL` must point to a Postgres instance with `pgvector` extension already enabled.

- [ ] **Step 3: Install packages from `Brain/` directory**

```bash
cd "c:\PF\Joveo\CS-platform"
.venv\Scripts\activate
cd Brain
uv pip install -e ".[dev]"
python -m spacy download en_core_web_lg
```

Expected: no errors. `python -c "import spacy; spacy.load('en_core_web_lg')"` exits cleanly.

- [ ] **Step 4: Create folder stubs**

Create `Brain/recordings/.gitkeep` (empty file).
Create empty `__init__.py` in: `preprocessing/`, `shared/`, `v1/`, `v2/`, `tests/`.

- [ ] **Step 5: Commit**

```bash
git add Brain/
git commit -m "feat: scaffold Naren's Brain Python project"
```

---

## Task 2: Config + DB Schema

**Files:**
- Create: `Brain/config.py`
- Create: `Brain/db/schema.sql`
- Create: `Brain/db/init_db.py`

**Interfaces:**
- Produces: `Config` dataclass consumed by all pipeline modules

- [ ] **Step 1: Write failing test for config**

`tests/test_config.py`:
```python
import os, pytest
from unittest.mock import patch

def test_load_config_success():
    env = {
        "GEMMA_API_KEY": "test_key",
        "DATABASE_URL": "postgresql://localhost/test",
        "JOVEO_SPEAKER_NAMES": "Naren Shankar,Collin Osburn",
        "NAREN_SPEAKER_NAME": "Naren Shankar",
    }
    with patch.dict(os.environ, env, clear=True):
        from config import load_config
        cfg = load_config()
    assert cfg.gemma_api_key == "test_key"
    assert "naren shankar" in cfg.joveo_speakers_lower
    assert cfg.naren_name_lower == "naren shankar"

def test_load_config_missing_key_raises():
    with patch.dict(os.environ, {}, clear=True):
        from config import load_config
        with pytest.raises((KeyError, ValueError)):
            load_config()
```

Run: `pytest tests/test_config.py -v`
Expected: FAIL (config.py doesn't exist)

- [ ] **Step 2: Write `Brain/config.py`**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    gemma_api_key: str
    database_url: str
    joveo_speakers_lower: frozenset  # lowercased for case-insensitive matching
    naren_name_lower: str            # lowercased Naren's name

def load_config() -> Config:
    api_key = os.environ["GEMMA_API_KEY"]
    db_url = os.environ["DATABASE_URL"]
    joveo_raw = os.environ["JOVEO_SPEAKER_NAMES"]
    naren_raw = os.environ["NAREN_SPEAKER_NAME"]
    joveo_lower = frozenset(n.strip().lower() for n in joveo_raw.split(",") if n.strip())
    return Config(
        gemma_api_key=api_key,
        database_url=db_url,
        joveo_speakers_lower=joveo_lower,
        naren_name_lower=naren_raw.strip().lower(),
    )
```

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 3: Write `Brain/db/schema.sql`**

```sql
-- Enable pgvector (requires superuser or pre-installed on cloud provider)
CREATE EXTENSION IF NOT EXISTS vector;

-- Call registry
CREATE TABLE IF NOT EXISTS calls (
    call_id     SERIAL PRIMARY KEY,
    filename    TEXT UNIQUE NOT NULL,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

-- Layer A: scenario taxonomy
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id   SERIAL PRIMARY KEY,
    scenario_key  TEXT UNIQUE NOT NULL,
    primary_topic TEXT NOT NULL,
    sub_topic     TEXT NOT NULL,
    keyphrases    TEXT[] NOT NULL DEFAULT '{}',
    soft_skills   TEXT[] NOT NULL DEFAULT '{}',
    bloom_level   TEXT NOT NULL CHECK (bloom_level IN (
                      'remember','understand','apply','analyze','evaluate','create'
                  )),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scenarios_keyphrases
    ON scenarios USING GIN(keyphrases);

-- Layer B: trigger-response pairs
-- trigger_vec: BGE-M3 query-mode embedding of CLIENT utterance
-- response_vec: BGE-M3 document-mode embedding of Naren's response
CREATE TABLE IF NOT EXISTS kb_pairs (
    pair_id          SERIAL PRIMARY KEY,
    call_id          INTEGER NOT NULL REFERENCES calls(call_id),
    scenario_id      INTEGER REFERENCES scenarios(scenario_id),
    scenario_key     TEXT,
    turn_index       INTEGER NOT NULL,
    trigger_text     TEXT NOT NULL,
    response_text    TEXT NOT NULL,
    benchmark_response TEXT,
    trigger_vec      vector(1024),
    response_vec     vector(1024),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kb_trigger_vec
    ON kb_pairs USING hnsw (trigger_vec vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_kb_response_vec
    ON kb_pairs USING hnsw (response_vec vector_cosine_ops);

-- Layer C: evaluation rubrics (one per scenario)
CREATE TABLE IF NOT EXISTS rubrics (
    rubric_id        SERIAL PRIMARY KEY,
    scenario_id      INTEGER NOT NULL UNIQUE REFERENCES scenarios(scenario_id),
    scenario_key     TEXT NOT NULL,
    milestones       JSONB NOT NULL DEFAULT '[]',
    soft_skill_rubric JSONB NOT NULL DEFAULT '{}',
    anti_patterns    JSONB NOT NULL DEFAULT '[]',
    pipeline_version TEXT NOT NULL CHECK (pipeline_version IN ('v1', 'v2')),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
```

- [ ] **Step 4: Write `Brain/db/init_db.py`**

```python
import psycopg
from pathlib import Path

def init_db(database_url: str) -> None:
    """Run schema.sql against the database. Idempotent — safe to call on every run."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(sql)

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    init_db(os.environ["DATABASE_URL"])
    print("Database initialized.")
```

- [ ] **Step 5: Run `init_db.py` to verify DB connection**

```bash
python db/init_db.py
```

Expected: `Database initialized.` — no errors. Verify tables exist with your cloud DB console or `psql`.

- [ ] **Step 6: Commit**

```bash
git add Brain/config.py Brain/db/
git commit -m "feat: add config loader and DB schema for Layers A/B/C"
```

---

## Task 3: Shared Storage Layer

**Files:**
- Create: `Brain/shared/storage.py`

**Interfaces:**
- Consumes: open `psycopg.Connection`, dicts matching DB columns
- Produces: `upsert_call()->int`, `upsert_scenario()->int`, `insert_kb_pair()->int`, `upsert_rubric()->int`, `get_scenarios()->list[dict]`

- [ ] **Step 1: Write `Brain/shared/storage.py`**

```python
import json
import psycopg
from pgvector.psycopg import register_vector, Vector

def get_connection(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url)
    register_vector(conn)
    return conn

def upsert_call(conn: psycopg.Connection, filename: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO calls (filename) VALUES (%s)
            ON CONFLICT (filename) DO UPDATE SET filename = EXCLUDED.filename
            RETURNING call_id
        """, (filename,))
        call_id = cur.fetchone()[0]
    conn.commit()
    return call_id

def upsert_scenario(conn: psycopg.Connection, scenario: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scenarios
              (scenario_key, primary_topic, sub_topic, keyphrases, soft_skills, bloom_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (scenario_key) DO UPDATE SET
                primary_topic = EXCLUDED.primary_topic,
                sub_topic     = EXCLUDED.sub_topic,
                keyphrases    = EXCLUDED.keyphrases,
                soft_skills   = EXCLUDED.soft_skills,
                bloom_level   = EXCLUDED.bloom_level
            RETURNING scenario_id
        """, (
            scenario["scenario_key"],
            scenario["primary_topic"],
            scenario["sub_topic"],
            scenario["keyphrases"],
            scenario["soft_skills"],
            scenario["bloom_level"],
        ))
        scenario_id = cur.fetchone()[0]
    conn.commit()
    return scenario_id

def insert_kb_pair(conn: psycopg.Connection, pair: dict) -> int:
    trigger_vec = Vector(pair["trigger_vec"]) if pair.get("trigger_vec") else None
    response_vec = Vector(pair["response_vec"]) if pair.get("response_vec") else None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kb_pairs
              (call_id, scenario_id, scenario_key, turn_index,
               trigger_text, response_text, trigger_vec, response_vec)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING pair_id
        """, (
            pair["call_id"],
            pair.get("scenario_id"),
            pair.get("scenario_key"),
            pair["turn_index"],
            pair["trigger_text"],
            pair["response_text"],
            trigger_vec,
            response_vec,
        ))
        pair_id = cur.fetchone()[0]
    conn.commit()
    return pair_id

def upsert_rubric(conn: psycopg.Connection, rubric: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO rubrics
              (scenario_id, scenario_key, milestones, soft_skill_rubric, anti_patterns, pipeline_version)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (scenario_id) DO UPDATE SET
                milestones        = EXCLUDED.milestones,
                soft_skill_rubric = EXCLUDED.soft_skill_rubric,
                anti_patterns     = EXCLUDED.anti_patterns,
                pipeline_version  = EXCLUDED.pipeline_version
            RETURNING rubric_id
        """, (
            rubric["scenario_id"],
            rubric["scenario_key"],
            json.dumps(rubric["milestones"]),
            json.dumps(rubric["soft_skill_rubric"]),
            json.dumps(rubric["anti_patterns"]),
            rubric["pipeline_version"],
        ))
        rubric_id = cur.fetchone()[0]
    conn.commit()
    return rubric_id

def get_scenarios(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT scenario_id, scenario_key, sub_topic, primary_topic, keyphrases FROM scenarios")
        rows = cur.fetchall()
    return [
        {"scenario_id": r[0], "scenario_key": r[1], "sub_topic": r[2],
         "primary_topic": r[3], "keyphrases": r[4]}
        for r in rows
    ]

def get_naren_responses_for_scenario(conn: psycopg.Connection, scenario_key: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.pair_id, p.response_text, c.filename
            FROM kb_pairs p JOIN calls c ON p.call_id = c.call_id
            WHERE p.scenario_key = %s
        """, (scenario_key,))
        rows = cur.fetchall()
    return [{"pair_id": r[0], "response_text": r[1], "call_filename": r[2]} for r in rows]
```

- [ ] **Step 2: Commit**

```bash
git add Brain/shared/storage.py
git commit -m "feat: add storage layer (psycopg3 + pgvector CRUD)"
```

---

## Task 4: Transcript Parser

**Files:**
- Create: `Brain/preprocessing/transcript_parser.py`
- Create: `Brain/tests/test_transcript_parser.py`

**Interfaces:**
- Produces: `parse_transcript(path, joveo_speakers_lower, naren_name_lower) -> list[Turn]`
- `Turn`: dataclass with `index:int, speaker_raw:str, role:SpeakerRole, text:str, call_id:str`

- [ ] **Step 1: Write failing tests**

`Brain/tests/test_transcript_parser.py`:
```python
import pytest
from pathlib import Path
from preprocessing.transcript_parser import parse_transcript, SpeakerRole

JOVEO = frozenset(["naren shankar", "collin osburn"])
NAREN = "naren shankar"

def _txt(content: str, tmp_path: Path) -> str:
    p = tmp_path / "call_test.txt"
    p.write_text(content, encoding="utf-8")
    return str(p)

def test_basic_roles(tmp_path):
    txt = _txt("Naren Shankar\nHere is my response.\n\nAnna\nI have a concern.\n\nCollin Osburn\nGood point.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert len(turns) == 3
    assert turns[0].role == SpeakerRole.NAREN
    assert turns[1].role == SpeakerRole.CLIENT
    assert turns[2].role == SpeakerRole.JOVEO_OTHER

def test_call_id_is_filename_stem(tmp_path):
    txt = _txt("Naren Shankar\nHello.\n\nAnna\nHi.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert turns[0].call_id == "call_test"

def test_empty_utterance_skipped(tmp_path):
    txt = _txt("Naren Shankar\n\nAnna\nActual utterance.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert len(turns) == 1
    assert turns[0].role == SpeakerRole.CLIENT

def test_partial_name_joveo(tmp_path):
    txt = _txt("Collin\nInterjects here.\n\nAnna\nQuestion.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert turns[0].role == SpeakerRole.JOVEO_OTHER

def test_crlf_line_endings(tmp_path):
    content = "Naren Shankar\r\nResponse text.\r\n\r\nAnna\r\nQuestion here."
    p = tmp_path / "call_crlf.txt"
    p.write_bytes(content.encode("utf-8"))
    turns = parse_transcript(str(p), JOVEO, NAREN)
    assert len(turns) == 2
    assert turns[0].text == "Response text."

def test_turn_indices_sequential(tmp_path):
    txt = _txt("Naren Shankar\nA.\n\nAnna\nB.\n\nNaren Shankar\nC.", tmp_path)
    turns = parse_transcript(txt, JOVEO, NAREN)
    assert [t.index for t in turns] == [0, 1, 2]
```

Run: `pytest tests/test_transcript_parser.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 2: Write `Brain/preprocessing/transcript_parser.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class SpeakerRole(Enum):
    NAREN = "NAREN"
    JOVEO_OTHER = "JOVEO_OTHER"
    CLIENT = "CLIENT"


@dataclass
class Turn:
    index: int
    speaker_raw: str
    role: SpeakerRole
    text: str
    call_id: str


def _classify(speaker_raw: str, joveo_lower: frozenset, naren_lower: str) -> SpeakerRole:
    s = speaker_raw.strip().lower()
    if s == naren_lower or naren_lower.startswith(s) or s.startswith(naren_lower):
        return SpeakerRole.NAREN
    for jname in joveo_lower:
        if s == jname or jname.startswith(s) or s.startswith(jname):
            return SpeakerRole.JOVEO_OTHER
    return SpeakerRole.CLIENT


def parse_transcript(
    path: str,
    joveo_speakers_lower: frozenset,
    naren_name_lower: str,
) -> list[Turn]:
    """Parse a .txt transcript into a list of Turn objects."""
    raw = Path(path).read_text(encoding="utf-8")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments = re.split(r"\n{2,}", raw.strip())

    call_id = Path(path).stem
    turns: list[Turn] = []

    for seg in segments:
        lines = [l.strip() for l in seg.strip().splitlines()]
        lines = [l for l in lines if l]
        if not lines:
            continue
        speaker_raw = lines[0]
        utterance = " ".join(lines[1:]).strip()
        if not utterance:
            continue
        role = _classify(speaker_raw, joveo_speakers_lower, naren_name_lower)
        turns.append(Turn(
            index=len(turns),
            speaker_raw=speaker_raw,
            role=role,
            text=utterance,
            call_id=call_id,
        ))

    return turns
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_transcript_parser.py -v
```

Expected: 6 PASS

- [ ] **Step 4: Commit**

```bash
git add Brain/preprocessing/transcript_parser.py Brain/tests/test_transcript_parser.py
git commit -m "feat: transcript parser — classifies turns by speaker role"
```

---

## Task 5: Segmenter + Embedder

**Files:**
- Create: `Brain/preprocessing/segmenter.py`
- Create: `Brain/preprocessing/embedder.py`
- Create: `Brain/tests/test_segmenter.py`

**Interfaces:**
- Produces: `segment_into_clauses(text:str) -> list[str]`
- Produces: `embed_query(texts:list[str]) -> list[list[float]]`, `embed_document(texts:list[str]) -> list[list[float]]`

- [ ] **Step 1: Write failing segmenter tests**

`Brain/tests/test_segmenter.py`:
```python
from preprocessing.segmenter import segment_into_clauses

def test_multi_idea_utterance():
    text = ("We tried programmatic before through an agency and it didn't work. "
            "I'm not sure we have the budget right now. "
            "Our team is pretty small so we'd need a lot of hand-holding.")
    clauses = segment_into_clauses(text)
    assert len(clauses) >= 2

def test_short_noise_filtered():
    assert segment_into_clauses("K.") == []
    assert segment_into_clauses("Yeah.") == []
    assert segment_into_clauses("I mean.") == []

def test_normal_sentence_preserved():
    text = "We are looking for a way to reduce our cost-per-apply."
    clauses = segment_into_clauses(text)
    assert len(clauses) == 1
    assert clauses[0] == text

def test_empty_string():
    assert segment_into_clauses("") == []
```

Run: `pytest tests/test_segmenter.py -v`
Expected: FAIL

- [ ] **Step 2: Write `Brain/preprocessing/segmenter.py`**

```python
from __future__ import annotations
import spacy

_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_lg")
    return _nlp

def segment_into_clauses(text: str) -> list[str]:
    """
    Split utterance text into clause-level strings.
    Filters out sub-4-token segments (disfluencies, backchannels).
    """
    text = text.strip()
    if not text:
        return []
    nlp = _get_nlp()
    doc = nlp(text)
    clauses: list[str] = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if len(sent) < 4:
            continue
        clauses.append(sent_text)
    return clauses
```

Run: `pytest tests/test_segmenter.py -v`
Expected: PASS

- [ ] **Step 3: Write `Brain/preprocessing/embedder.py`**

BGE-M3 downloads ~2 GB on first call and caches in HuggingFace cache dir.

```python
from __future__ import annotations

_model = None

def _get_model():
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel
        print("[embedder] Loading BGE-M3 model (first run downloads ~2GB)...")
        _model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        print("[embedder] BGE-M3 ready.")
    return _model

def embed_query(texts: list[str]) -> list[list[float]]:
    """Embed in query mode (for CLIENT utterances / Oracle queries). Max 512 tokens."""
    if not texts:
        return []
    model = _get_model()
    output = model.encode(texts, batch_size=12, max_length=512, return_dense=True,
                          return_sparse=False, return_colbert_vecs=False)
    return output["dense_vecs"].tolist()

def embed_document(texts: list[str]) -> list[list[float]]:
    """Embed in document mode (for Naren responses stored in DB). Max 8192 tokens."""
    if not texts:
        return []
    model = _get_model()
    output = model.encode(texts, batch_size=8, max_length=8192, return_dense=True,
                          return_sparse=False, return_colbert_vecs=False)
    return output["dense_vecs"].tolist()
```

Verify: `python -c "from preprocessing.embedder import embed_query; print(len(embed_query(['test'])[0]))"` → `1024`

- [ ] **Step 4: Commit**

```bash
git add Brain/preprocessing/segmenter.py Brain/preprocessing/embedder.py Brain/tests/test_segmenter.py
git commit -m "feat: spaCy clause segmenter and BGE-M3 asymmetric embedder"
```

---

## Task 6: Gemma Client + Prompts

**Files:**
- Create: `Brain/shared/gemma.py`
- Create: `Brain/shared/prompts.py`

**Interfaces:**
- Produces: `call_gemma(prompt:str, api_key:str, **kwargs) -> dict`

- [ ] **Step 1: Write `Brain/shared/gemma.py`**

```python
from __future__ import annotations
import json
import time


class GemmaError(Exception):
    pass


def call_gemma(
    prompt: str,
    api_key: str,
    *,
    model: str = "gemma-4-31b-it",
    temperature: float = 0.2,
    max_output_tokens: int = 8192,
    max_retries: int = 3,
) -> dict:
    """
    Call Gemma via Google AI Studio. Forces JSON output mode.
    Returns parsed dict. Retries up to max_retries on 429/503.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = response.text.strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise GemmaError(f"Gemma returned non-JSON: {e}\nRaw: {text[:500]}")
        except Exception as e:
            err_str = str(e).lower()
            if attempt < max_retries - 1 and any(code in err_str for code in ["429", "503", "rate"]):
                wait = 2 ** (attempt + 1)
                print(f"[gemma] Rate-limited (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            raise GemmaError(f"Gemma API error: {e}") from e

    raise GemmaError("Max retries exceeded")
```

- [ ] **Step 2: Write `Brain/shared/prompts.py`**

```python
PROMPT_LAYER_A_V1 = """\
You are an expert sales coach analyzing call transcripts for Joveo, a programmatic job advertising company.

Below are complete transcripts of customer success calls. Identify ALL distinct CLIENT scenarios — each unique situation, objection, question, or concern raised by CLIENT speakers that Naren (Joveo's CS manager) must navigate.

TRANSCRIPTS:
{transcripts_text}

Soft skills taxonomy — use ONLY these exact strings:
empathy, active_listening, reframing, confidence, conciseness, storytelling, objection_handling, discovery, rapport_building, closing

Bloom levels — use ONLY these lowercase strings:
remember, understand, apply, analyze, evaluate, create

Bloom definitions:
- remember: client needs Joveo to recall a fact
- understand: client needs explanation of how something works
- apply: Naren must use knowledge in this specific client context
- analyze: Naren must break down the situation before responding
- evaluate: Naren must assess or judge something for the client
- create: Naren must develop a novel approach or solution

Respond ONLY with valid JSON matching this exact schema:
{{
  "scenarios": [
    {{
      "scenario_key": "budget_objection",
      "primary_topic": "Objection Handling",
      "sub_topic": "Budget Constraints",
      "keyphrases": ["budget concern", "cost too high", "no budget right now"],
      "soft_skills": ["empathy", "reframing"],
      "bloom_level": "apply",
      "call_ids": ["lumbertonisd_call_2026"]
    }}
  ]
}}

Rules:
1. Only create scenarios for CLIENT-speaker content, not Joveo-speaker content
2. Each scenario must appear in at least one call
3. Do not duplicate — merge similar situations into one scenario
4. scenario_key must be unique, lowercase, underscored
5. call_ids must be the filename stems provided in the transcript headers
"""

PROMPT_LAYER_A_V2_LABEL = """\
You are labelling a semantic cluster of CLIENT utterances from sales call transcripts for Joveo (programmatic job advertising).

CLUSTER ID: {cluster_id}
CLUSTER KEYWORDS (c-TF-IDF): {keywords}

REPRESENTATIVE UTTERANCES FROM THIS CLUSTER:
{representative_utterances}

This cluster represents a distinct scenario that clients raise. Label it.

Respond ONLY with valid JSON:
{{
  "scenario_key": "snake_case_identifier",
  "primary_topic": "High-level category",
  "sub_topic": "Specific scenario description (1 sentence)",
  "keyphrases": ["2-4 word identifying phrase", "another phrase"],
  "soft_skills": ["empathy"],
  "bloom_level": "apply"
}}

Soft skills: empathy, active_listening, reframing, confidence, conciseness, storytelling, objection_handling, discovery, rapport_building, closing
Bloom levels: remember, understand, apply, analyze, evaluate, create
"""

PROMPT_LAYER_C_V1 = """\
You are analyzing how Naren Shankar (senior CS manager at Joveo) consistently responds to a specific client scenario.

SCENARIO KEY: {scenario_key}
SCENARIO: {sub_topic} ({primary_topic})

Below are ALL of Naren's responses to this scenario across {n_instances} call(s). Each is labeled with its source file.

{responses_text}

Identify the recurring strategic milestones Naren uses. A milestone = a distinct communicative move appearing in 2+ responses.

Respond ONLY with valid JSON:
{{
  "milestones": [
    {{
      "order": 1,
      "label": "Acknowledge concern",
      "description": "Naren explicitly validates the client worry before solving it. He restates the concern in his own words or uses phrases like 'That is a completely fair point'.",
      "detection_hint": "Present if Naren names or restates the concern BEFORE mentioning any Joveo solution or data.",
      "sequencing_type": "fixed",
      "source_v": "v1_gemma"
    }}
  ],
  "soft_skill_rubric": {{
    "excellent_execution": "2-3 specific observable behaviors from the real examples above that characterize excellent execution",
    "failing_execution": "[inferred, unverified] What a poor response looks like — inferred only from what Naren consistently avoids",
    "confidence": "inferred"
  }},
  "anti_patterns": [
    {{
      "pattern": "[inferred] Jumping to product features without acknowledging the concern first",
      "confidence": "inferred, unverified"
    }}
  ]
}}

Rules:
- Only include milestones that appear in 2+ of the responses above
- Order by when they appear (first in response = order 1)
- sequencing_type: 'fixed' if consistent position, 'conditional' if variable
- soft_skill_rubric.failing_execution MUST include prefix '[inferred, unverified]'
- anti_patterns MUST include '[inferred]' prefix on each inferred item
- Do NOT invent — only describe behaviors literally present in the responses
"""

PROMPT_LAYER_C_V2_ORDER = """\
You are reviewing milestone ordering for a sales scenario rubric.

SCENARIO: {scenario_key}
Based on {n_instances} response instances, milestones were ordered by median clause position. Some have high position variance (>0.3), meaning their position changes across instances.

MILESTONES WITH HIGH VARIANCE:
{milestones_text}

For each HIGH VARIANCE milestone, determine whether:
a) "conditional" — the position genuinely depends on call context
b) "fixed" — variance is statistical noise (small sample)

Respond ONLY with valid JSON:
{{
  "milestone_sequencing": [
    {{
      "label": "milestone label",
      "sequencing_type": "fixed",
      "sequencing_rationale": "1-2 sentences explaining why this milestone's position is fixed or conditional"
    }}
  ]
}}
"""

PROMPT_LAYER_C_MILESTONE_DESCRIBE = """\
You are writing a precise description of one recurring communicative move in Naren Shankar's sales responses.

SCENARIO: {scenario_key}
MILESTONE ORDER: {order} of {total}

These clauses from Naren's responses were statistically grouped into this milestone cluster:

{cluster_clauses}

Describe what Naren is doing. Focus on communicative intent and what makes it effective.

Respond ONLY with valid JSON:
{{
  "label": "2-4 word action label",
  "description": "2-3 sentences grounded in the clauses above — what Naren does and why it works",
  "detection_hint": "How to tell this milestone is present vs a near-miss with similar surface-level words"
}}
"""

PROMPT_LAYER_B_CLEAN = """\
Clean the following sales call transcript excerpt. Remove speech disfluencies (um, uh, like/you know/I mean when used as fillers) while preserving all substantive content and the speaker's natural voice.

ORIGINAL:
{raw_text}

Respond ONLY with valid JSON:
{{"cleaned": "cleaned text here"}}
"""
```

- [ ] **Step 3: Smoke-test Gemma connection**

```bash
python -c "
from shared.gemma import call_gemma
import os; from dotenv import load_dotenv; load_dotenv()
result = call_gemma('Respond with JSON: {\"status\": \"ok\"}', os.environ['GEMMA_API_KEY'])
print(result)
"
```

Expected: `{'status': 'ok'}` or similar JSON. No error.

- [ ] **Step 4: Commit**

```bash
git add Brain/shared/gemma.py Brain/shared/prompts.py
git commit -m "feat: Gemma API client with retry and all prompt templates"
```

---

## Task 7: V1 Layer B (Trigger→Response Extraction)

**Files:**
- Create: `Brain/v1/layer_b.py`
- Create: `Brain/tests/test_layer_b_v1.py`

**Interfaces:**
- Consumes: `list[Turn]`, scenario_map dict, call_id (int)
- Produces: pairs written to `kb_pairs` table via `embed_and_store_pairs`

- [ ] **Step 1: Write failing tests**

`Brain/tests/test_layer_b_v1.py`:
```python
from preprocessing.transcript_parser import Turn, SpeakerRole
from v1.layer_b import extract_pairs

def _turn(idx, role, text, call_id="c1"):
    return Turn(index=idx, speaker_raw="X", role=role, text=text, call_id=call_id)

def test_basic_client_naren_pair():
    turns = [
        _turn(0, SpeakerRole.CLIENT, "What is your pricing?"),
        _turn(1, SpeakerRole.NAREN,  "We price on a CPApply model."),
    ]
    pairs = extract_pairs(turns, {}, db_call_id=1)
    assert len(pairs) == 1
    assert pairs[0]["trigger_text"] == "What is your pricing?"
    assert "CPApply" in pairs[0]["response_text"]

def test_joveo_other_interjection_skipped_response_continues():
    turns = [
        _turn(0, SpeakerRole.CLIENT,      "How does billing work?"),
        _turn(1, SpeakerRole.NAREN,       "So we bill monthly."),
        _turn(2, SpeakerRole.JOVEO_OTHER, "Right, exactly."),
        _turn(3, SpeakerRole.NAREN,       "And there are no setup fees."),
        _turn(4, SpeakerRole.CLIENT,      "OK thanks."),
    ]
    pairs = extract_pairs(turns, {}, db_call_id=1)
    assert len(pairs) == 1
    assert "monthly" in pairs[0]["response_text"]
    assert "setup fees" in pairs[0]["response_text"]

def test_no_naren_response_no_pair():
    turns = [
        _turn(0, SpeakerRole.CLIENT,      "Question?"),
        _turn(1, SpeakerRole.JOVEO_OTHER, "Not Naren."),
        _turn(2, SpeakerRole.CLIENT,      "Another question?"),
    ]
    pairs = extract_pairs(turns, {}, db_call_id=1)
    assert len(pairs) == 0

def test_multi_consecutive_naren_turns_joined():
    turns = [
        _turn(0, SpeakerRole.CLIENT, "Tell me about Joveo."),
        _turn(1, SpeakerRole.NAREN,  "Joveo is a programmatic platform."),
        _turn(2, SpeakerRole.NAREN,  "We work with 2000+ job boards."),
        _turn(3, SpeakerRole.NAREN,  "And we optimize in real time."),
    ]
    pairs = extract_pairs(turns, {}, db_call_id=1)
    assert len(pairs) == 1
    assert "2000+" in pairs[0]["response_text"]
    assert "real time" in pairs[0]["response_text"]
```

Run: `pytest tests/test_layer_b_v1.py -v`
Expected: FAIL

- [ ] **Step 2: Write `Brain/v1/layer_b.py`**

```python
from __future__ import annotations
import psycopg
from preprocessing.transcript_parser import Turn, SpeakerRole
from preprocessing import embedder
from shared import storage


def extract_pairs(
    turns: list[Turn],
    scenario_map: dict[str, dict],
    db_call_id: int,
) -> list[dict]:
    """
    Rule-based extraction of CLIENT trigger → Naren response pairs.
    JOVEO_OTHER turns are skipped but do not break a Naren response sequence.
    """
    pairs = []
    i = 0
    while i < len(turns):
        turn = turns[i]
        if turn.role != SpeakerRole.CLIENT:
            i += 1
            continue
        trigger_turn = turn
        response_parts = []
        j = i + 1
        while j < len(turns):
            t = turns[j]
            if t.role == SpeakerRole.NAREN:
                response_parts.append(t.text)
                j += 1
            elif t.role == SpeakerRole.JOVEO_OTHER:
                j += 1
            else:
                break
        if response_parts:
            response_text = " ".join(response_parts)
            scenario_key, scenario_id = _match_scenario(trigger_turn.text, scenario_map)
            pairs.append({
                "call_id": db_call_id,
                "scenario_id": scenario_id,
                "scenario_key": scenario_key,
                "turn_index": trigger_turn.index,
                "trigger_text": trigger_turn.text,
                "response_text": response_text,
                "trigger_vec": None,
                "response_vec": None,
            })
        i = j if response_parts else i + 1

    return pairs


def _match_scenario(trigger_text: str, scenario_map: dict[str, dict]) -> tuple:
    """Assign scenario by keyphrase overlap (>= 2 matches required)."""
    if not scenario_map:
        return None, None
    trigger_lower = trigger_text.lower()
    best_key, best_id, best_count = None, None, 0
    for scenario_key, info in scenario_map.items():
        matches = sum(1 for kp in info.get("keyphrases", []) if kp.lower() in trigger_lower)
        if matches > best_count:
            best_count = matches
            best_key = scenario_key
            best_id = info["scenario_id"]
    return (best_key, best_id) if best_count >= 2 else (None, None)


def embed_and_store_pairs(
    pairs: list[dict],
    conn: psycopg.Connection,
) -> list[int]:
    """Batch-embed all triggers and responses, then write to DB."""
    if not pairs:
        return []
    trigger_vecs = embedder.embed_query([p["trigger_text"] for p in pairs])
    response_vecs = embedder.embed_document([p["response_text"] for p in pairs])
    pair_ids = []
    for i, pair in enumerate(pairs):
        pair["trigger_vec"] = trigger_vecs[i]
        pair["response_vec"] = response_vecs[i]
        pair_ids.append(storage.insert_kb_pair(conn, pair))
    return pair_ids
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_layer_b_v1.py -v
```

Expected: 4 PASS

- [ ] **Step 4: Commit**

```bash
git add Brain/v1/layer_b.py Brain/tests/test_layer_b_v1.py
git commit -m "feat: V1 Layer B — rule-based trigger-response extraction"
```

---

## Task 8: V1 Layer A + Layer C

**Files:**
- Create: `Brain/v1/layer_a.py`
- Create: `Brain/v1/layer_c.py`

- [ ] **Step 1: Write `Brain/v1/layer_a.py`**

```python
from __future__ import annotations
import psycopg
from config import Config
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_A_V1
from shared import storage


def run_layer_a(
    transcripts_text: str,
    config: Config,
    conn: psycopg.Connection,
) -> dict[str, dict]:
    """
    Send all transcript text to Gemma to identify scenarios.
    Returns scenario_key → {scenario_id, keyphrases, sub_topic, primary_topic}.
    """
    prompt = PROMPT_LAYER_A_V1.format(transcripts_text=transcripts_text)
    print("[Layer A] Calling Gemma for scenario identification...")
    result = call_gemma(prompt, config.gemma_api_key)
    scenarios = result.get("scenarios", [])
    print(f"[Layer A] Gemma identified {len(scenarios)} scenario(s).")

    scenario_map: dict[str, dict] = {}
    for s in scenarios:
        scenario_id = storage.upsert_scenario(conn, s)
        scenario_map[s["scenario_key"]] = {
            "scenario_id": scenario_id,
            "keyphrases": s.get("keyphrases", []),
            "sub_topic": s.get("sub_topic", ""),
            "primary_topic": s.get("primary_topic", ""),
        }
        print(f"  ✓ {s['scenario_key']} → scenario_id={scenario_id}")

    return scenario_map
```

- [ ] **Step 2: Write `Brain/v1/layer_c.py`**

```python
from __future__ import annotations
import psycopg
from config import Config
from shared.gemma import call_gemma
from shared.prompts import PROMPT_LAYER_C_V1
from shared import storage


def run_layer_c(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
) -> None:
    """
    For each scenario, gather Naren's responses from DB and call Gemma
    to generate milestones, soft_skill_rubric, and anti_patterns.
    """
    for scenario_key, info in scenario_map.items():
        print(f"[Layer C] Processing scenario: {scenario_key}")
        responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
        if not responses:
            print(f"  ⚠ No Naren responses found for {scenario_key} — skipping rubric.")
            continue

        responses_text = "\n\n".join(
            f"[{r['call_filename']}]\n{r['response_text']}"
            for r in responses
        )
        prompt = PROMPT_LAYER_C_V1.format(
            scenario_key=scenario_key,
            sub_topic=info["sub_topic"],
            primary_topic=info["primary_topic"],
            n_instances=len(responses),
            responses_text=responses_text,
        )
        result = call_gemma(prompt, config.gemma_api_key)
        rubric = {
            "scenario_id": info["scenario_id"],
            "scenario_key": scenario_key,
            "milestones": result.get("milestones", []),
            "soft_skill_rubric": result.get("soft_skill_rubric", {}),
            "anti_patterns": result.get("anti_patterns", []),
            "pipeline_version": "v1",
        }
        rubric_id = storage.upsert_rubric(conn, rubric)
        print(f"  ✓ Rubric stored (id={rubric_id}), {len(rubric['milestones'])} milestone(s).")
```

- [ ] **Step 3: Commit**

```bash
git add Brain/v1/layer_a.py Brain/v1/layer_c.py
git commit -m "feat: V1 Layer A (Gemma scenario ID) and Layer C (Gemma rubrics)"
```

---

## Task 9: V1 Pipeline + main.py

**Files:**
- Create: `Brain/v1/pipeline.py`
- Create: `Brain/main.py`

- [ ] **Step 1: Write `Brain/v1/pipeline.py`**

```python
from __future__ import annotations
from pathlib import Path
import psycopg
from config import Config
from preprocessing.transcript_parser import parse_transcript
from shared import storage
from v1 import layer_a, layer_b, layer_c


def run_v1(recordings_dir: str, config: Config, conn: psycopg.Connection) -> None:
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    print(f"\n[V1] Found {len(txt_files)} transcript(s).")

    all_turns_by_file: dict[str, tuple] = {}
    for txt_path in txt_files:
        turns = parse_transcript(str(txt_path), config.joveo_speakers_lower, config.naren_name_lower)
        call_id = storage.upsert_call(conn, txt_path.name)
        all_turns_by_file[txt_path.stem] = (turns, call_id)
        print(f"  Parsed {txt_path.name}: {len(turns)} turns")

    # Build combined transcript text for Layer A
    sections = []
    for stem, _ in all_turns_by_file.items():
        raw = (rec_path / f"{stem}.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
        sections.append(f"=== CALL: {stem} ===\n{raw}")
    transcripts_text = "\n\n".join(sections)

    # Layer A
    scenario_map = layer_a.run_layer_a(transcripts_text, config, conn)

    # Layer B — per call
    for stem, (turns, db_call_id) in all_turns_by_file.items():
        print(f"\n[Layer B] Processing {stem}...")
        pairs = layer_b.extract_pairs(turns, scenario_map, db_call_id)
        print(f"  Extracted {len(pairs)} trigger-response pair(s). Embedding...")
        pair_ids = layer_b.embed_and_store_pairs(pairs, conn)
        print(f"  Stored {len(pair_ids)} pair(s).")

    # Layer C
    print("\n[Layer C] Generating rubrics...")
    layer_c.run_layer_c(scenario_map, config, conn)

    print(f"\n✓ V1 pipeline complete. Scenarios: {len(scenario_map)}")
```

- [ ] **Step 2: Write `Brain/main.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from config import load_config
from shared import storage
import db.init_db as init_module


def main() -> None:
    print("\n=== Naren's Brain Builder ===")
    config = load_config()

    recordings_dir = Path(__file__).parent / "recordings"
    txts = sorted(recordings_dir.glob("*.txt"))
    if not txts:
        print(f"ERROR: No .txt transcript files found in {recordings_dir}")
        print("Place your transcript files in the recordings/ directory and try again.")
        sys.exit(1)

    print(f"\nFound {len(txts)} transcript(s) in recordings/:")
    for t in txts:
        print(f"  - {t.name}")

    print("\nChoose pipeline version:")
    print("  [1] V1 — Gemma-direct  (recommended for ≤5 calls)")
    print("  [2] V2 — Statistical clustering  (requires 30+ calls for Layer A, 5+ per scenario for Layer C)")
    choice = input("\nEnter 1 or 2: ").strip()

    print("\nInitializing database...")
    init_module.init_db(config.database_url)

    conn = storage.get_connection(config.database_url)
    try:
        if choice == "1":
            from v1.pipeline import run_v1
            run_v1(str(recordings_dir), config, conn)
        elif choice == "2":
            from v2.pipeline import run_v2
            run_v2(str(recordings_dir), config, conn)
        else:
            print(f"Invalid choice '{choice}'. Enter 1 or 2.")
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: End-to-end V1 smoke test**

With at least one `.txt` transcript in `recordings/` and `.env` filled:

```bash
python main.py
# When prompted: enter 1
```

Expected (no errors):
```
=== Naren's Brain Builder ===
Found 1 transcript(s) in recordings/: ...
[V1] Found 1 transcript(s).
  Parsed call_X.txt: N turns
[Layer A] Calling Gemma for scenario identification...
[Layer A] Gemma identified M scenario(s).
[Layer B] Processing call_X...
  Extracted K pair(s). Embedding...
  [embedder] Loading BGE-M3 model (first run downloads ~2GB)...
  Stored K pair(s).
[Layer C] Generating rubrics...
✓ V1 pipeline complete. Scenarios: M
```

Verify in DB:
```sql
SELECT scenario_key, primary_topic FROM scenarios;
SELECT count(*) FROM kb_pairs;
SELECT scenario_key, jsonb_array_length(milestones) FROM rubrics;
```

- [ ] **Step 4: Commit**

```bash
git add Brain/v1/pipeline.py Brain/main.py
git commit -m "feat: V1 pipeline orchestration and main.py entry point"
```

---

## Task 10: V2 Layer A (BERTopic)

**Files:**
- Create: `Brain/v2/layer_a.py`

- [ ] **Step 1: Write `Brain/v2/layer_a.py`**

```python
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
    """
    V2 scenario identification via BERTopic + Gemma labelling.
    Requires 30+ calls / 10+ instances per scenario for reliable clustering.
    """
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer

    client_clauses: list[str] = []
    for turn in all_turns:
        if turn.role == SpeakerRole.CLIENT:
            client_clauses.extend(segmenter.segment_into_clauses(turn.text))

    if not client_clauses:
        raise ValueError("No CLIENT clauses found — check transcript parsing.")

    print(f"[V2 Layer A] Segmented {len(client_clauses)} CLIENT clauses. Embedding...")
    vecs = embedder.embed_query(client_clauses)
    embeddings_matrix = np.array(vecs)

    umap_model = UMAP(n_components=5, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=42)
    hdbscan_model = HDBSCAN(min_cluster_size=10, min_samples=5, metric="euclidean",
                             cluster_selection_method="eom", prediction_data=True)
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

        # Deduplicate scenario_key if Gemma returns a collision
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
        print(f"  ✓ cluster {topic_id} → {key} (scenario_id={scenario_id})")

    return scenario_map
```

- [ ] **Step 2: Commit**

```bash
git add Brain/v2/layer_a.py
git commit -m "feat: V2 Layer A — BERTopic clustering + Gemma labelling"
```

---

## Task 11: V2 Layer B + V2 Layer C (HDBSCAN + Median)

**Files:**
- Create: `Brain/v2/layer_b.py`
- Create: `Brain/v2/layer_c.py`

- [ ] **Step 1: Write `Brain/v2/layer_b.py`**

```python
# V2 Layer B: identical to V1 — rule-based extraction + BGE-M3 embeddings.
# If V2 ever needs different behavior, replace this re-export with a real override.
from v1.layer_b import extract_pairs, embed_and_store_pairs  # noqa: F401

__all__ = ["extract_pairs", "embed_and_store_pairs"]
```

- [ ] **Step 2: Write `Brain/v2/layer_c.py`**

```python
from __future__ import annotations
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
from shared import storage


def run_layer_c_v2(
    scenario_map: dict[str, dict],
    config: Config,
    conn: psycopg.Connection,
) -> None:
    """V2: HDBSCAN clause clustering + median ordering + Gemma prose generation."""
    from hdbscan import HDBSCAN

    for scenario_key, info in scenario_map.items():
        print(f"[V2 Layer C] Processing scenario: {scenario_key}")
        responses = storage.get_naren_responses_for_scenario(conn, scenario_key)
        if len(responses) < 2:
            print(f"  ⚠ Fewer than 2 responses — falling back to V1 Gemma approach.")
            _fallback_v1(scenario_key, info, responses, config, conn)
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
            print(f"  ⚠ Too few clauses ({len(all_clauses)}) — falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn)
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
            print(f"  ⚠ HDBSCAN found no clusters — falling back to V1.")
            _fallback_v1(scenario_key, info, responses, config, conn)
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

        # Sanity check high-variance milestones with Gemma
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
                config.gemma_api_key,
            )
            for item in hv_result.get("milestone_sequencing", []):
                for m in high_var:
                    if item["label"].lower() in " ".join(m["clauses"][:2]).lower():
                        sequencing_map[m["cluster_id"]] = item["sequencing_type"]

        # Describe each milestone cluster
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
                config.gemma_api_key,
            )
            milestones.append({
                "order": order_idx + 1,
                "label": desc.get("label", f"Milestone {order_idx+1}"),
                "description": desc.get("description", ""),
                "detection_hint": desc.get("detection_hint", ""),
                "sequencing_type": sequencing_map.get(cluster["cluster_id"], "fixed"),
                "position_variance": cluster["position_variance"],
                "source_v": "v2_hdbscan",
            })

        # Soft skill rubric and anti_patterns via V1 prompt
        responses_text = "\n\n".join(
            f"[{r['call_filename']}]\n{r['response_text']}" for r in responses
        )
        rubric_result = call_gemma(
            PROMPT_LAYER_C_V1.format(
                scenario_key=scenario_key,
                sub_topic=info["sub_topic"],
                primary_topic=info["primary_topic"],
                n_instances=len(responses),
                responses_text=responses_text,
            ),
            config.gemma_api_key,
        )

        rubric_id = storage.upsert_rubric(conn, {
            "scenario_id": info["scenario_id"],
            "scenario_key": scenario_key,
            "milestones": milestones,
            "soft_skill_rubric": rubric_result.get("soft_skill_rubric", {}),
            "anti_patterns": rubric_result.get("anti_patterns", []),
            "pipeline_version": "v2",
        })
        print(f"  ✓ Rubric stored (id={rubric_id}), {len(milestones)} milestone(s).")


def _fallback_v1(scenario_key, info, responses, config, conn):
    from v1.layer_c import run_layer_c
    run_layer_c({scenario_key: info}, config, conn)
```

- [ ] **Step 3: Commit**

```bash
git add Brain/v2/layer_b.py Brain/v2/layer_c.py
git commit -m "feat: V2 Layer B (re-export) and Layer C (HDBSCAN + median ordering)"
```

---

## Task 12: V2 Pipeline + Full Test Suite

**Files:**
- Create: `Brain/v2/pipeline.py`

- [ ] **Step 1: Write `Brain/v2/pipeline.py`**

```python
from __future__ import annotations
from pathlib import Path
import psycopg
from config import Config
from preprocessing.transcript_parser import parse_transcript
from shared import storage
from v2 import layer_a, layer_b, layer_c


def run_v2(recordings_dir: str, config: Config, conn: psycopg.Connection) -> None:
    rec_path = Path(recordings_dir)
    txt_files = sorted(rec_path.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {recordings_dir}")

    print(f"\n[V2] Found {len(txt_files)} transcript(s).")

    all_turns = []
    all_turns_by_file: dict[str, tuple] = {}
    for txt_path in txt_files:
        turns = parse_transcript(str(txt_path), config.joveo_speakers_lower, config.naren_name_lower)
        call_id = storage.upsert_call(conn, txt_path.name)
        all_turns.extend(turns)
        all_turns_by_file[txt_path.stem] = (turns, call_id)
        print(f"  Parsed {txt_path.name}: {len(turns)} turns")

    # Layer A — BERTopic
    scenario_map = layer_a.run_layer_a_v2(all_turns, config, conn)

    # Layer B — same as V1
    for stem, (turns, db_call_id) in all_turns_by_file.items():
        print(f"\n[Layer B] Processing {stem}...")
        pairs = layer_b.extract_pairs(turns, scenario_map, db_call_id)
        print(f"  Extracted {len(pairs)} pair(s). Embedding...")
        pair_ids = layer_b.embed_and_store_pairs(pairs, conn)
        print(f"  Stored {len(pair_ids)} pair(s).")

    # Layer C — HDBSCAN + median
    print("\n[V2 Layer C] Generating rubrics...")
    layer_c.run_layer_c_v2(scenario_map, config, conn)

    print(f"\n✓ V2 pipeline complete. Scenarios: {len(scenario_map)}")
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests in `test_transcript_parser.py`, `test_segmenter.py`, `test_layer_b_v1.py` pass. Zero failures.

- [ ] **Step 3: Commit**

```bash
git add Brain/v2/pipeline.py
git commit -m "feat: V2 pipeline orchestration — Brain complete"
```

---

## Verification

### Unit tests

```bash
cd Brain
pytest tests/ -v
```

Expected: all unit tests pass (no DB or LLM calls required for unit tests).

### Embedder dimension check

```bash
python -c "from preprocessing.embedder import embed_query; print(len(embed_query(['test'])[0]))"
```

Expected: `1024`

### End-to-end V1

1. Place `.txt` transcripts in `Brain/recordings/`
2. Fill `.env` with real `GEMMA_API_KEY` and `DATABASE_URL`
3. `python main.py` → enter `1`
4. Verify in DB:

```sql
SELECT scenario_key, primary_topic, sub_topic FROM scenarios;
SELECT count(*) FROM kb_pairs;
SELECT scenario_key, jsonb_array_length(milestones) AS milestone_count FROM rubrics WHERE pipeline_version = 'v1';
```

### End-to-end V2 (when 30+ calls available)

1. Add 30+ transcripts to `recordings/`
2. `python main.py` → enter `2`
3. Verify:

```sql
SELECT scenario_key, jsonb_array_length(milestones) FROM rubrics WHERE pipeline_version = 'v2';
SELECT jsonb_path_query_array(milestones, '$[*].source_v') FROM rubrics WHERE pipeline_version = 'v2';
```

Expected: `source_v` values are `"v2_hdbscan"` (or `"v1_gemma"` for fallback scenarios).

---

*Plan complete and saved. Two execution options:*

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
**2. Inline Execution** — execute tasks in this session using executing-plans

Which approach?
