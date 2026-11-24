-- 0002: the trigger vectors Ask Naren searches, replacing Pinecone's `triggers` namespace.
--
-- One row per kb_pair: the gemini-embedding-2 vector (3072 dims, unit length) of the client
-- line Naren answered. A situation is matched against these.
--
-- NO FOREIGN KEY to brain.kb_pairs, deliberately: kb_pairs is created by Brain's own
-- schema.sql when a Brain is copied in, after this migration. It costs nothing, because the
-- search JOINS kb_pairs (see ask_naren/vector_store.PgVectorTriggerStore): a vector whose
-- pair is gone can never be returned, and a pair with no vector is what the startup coverage
-- guard and GET /verify report.
--
-- NO ANN INDEX, deliberately. pgvector's HNSW and IVFFlat indexes stop at 2,000 dimensions
-- for `vector`, and these are 3072. At this corpus size (thousands of rows) an exact scan is
-- fast enough and is EXACT -- Pinecone's search was approximate (vector_store.py measures
-- it). If the corpus grows past that, add an HNSW index on a `halfvec(3072)` expression,
-- which pgvector indexes up to 4,000 dimensions.

create table if not exists brain.trigger_vectors (
    pair_id    integer primary key,
    embedding  extensions.vector(3072) not null,
    model      text not null,
    loaded_at  timestamptz not null default now()
);

-- A 3072-float vector is ~12 KB, so it is stored out of line whatever we do. EXTERNAL skips
-- the compression attempt: floats barely compress, and every exact scan would pay to undo it.
alter table brain.trigger_vectors alter column embedding set storage external;
