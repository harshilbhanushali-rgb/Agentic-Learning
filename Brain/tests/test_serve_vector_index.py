"""The vector index is named BY THE BRAIN DATABASE it belongs to (2026-11-11).

Vector ids are that database's kb_pairs serials, so a database and an index only work as a
pair. A `brain_meta` row (key `vector_index`) in the database names its index; a database with
no such table or row is served from the constant, which is how the pre-2026-11-11 Brain (and
its rollback copy) keeps working unchanged."""
from ops import serve_ask_naren as serve


class _Conn:
    def __init__(self, table_exists: bool, value=None):
        self.table_exists, self.value = table_exists, value
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(f"{sql} {params or ''}")
        conn = self

        class _Cur:
            def fetchone(self):
                if "to_regclass" in sql:
                    return ("brain_meta" if conn.table_exists else None,)
                return (conn.value,) if conn.value is not None else None
        return _Cur()


def test_a_database_without_brain_meta_uses_the_constant():
    assert serve._vector_index_for(_Conn(table_exists=False)) == serve.VECTOR_INDEX_NAME


def test_a_database_with_an_empty_brain_meta_uses_the_constant():
    assert serve._vector_index_for(_Conn(table_exists=True)) == serve.VECTOR_INDEX_NAME


def test_a_database_naming_its_index_is_served_from_that_index():
    conn = _Conn(table_exists=True, value="narens-brain-v3-3072")
    assert serve._vector_index_for(conn) == "narens-brain-v3-3072"
    assert any("vector_index" in s for s in conn.sql)


def test_brain_meta_is_found_through_the_search_path_not_a_hard_coded_schema():
    """`public` on Neon, `brain` on RDS: a `public.` prefix would miss the RDS Brain's row."""
    conn = _Conn(table_exists=True, value="x")
    serve._vector_index_for(conn)
    assert any("to_regclass('brain_meta')" in s for s in conn.sql)
    assert not any("public." in s for s in conn.sql)


# --- which STORE: the RDS Brain names pgvector; a Neon Brain names nothing (2026-11-23) ---

def test_a_brain_without_a_store_row_keeps_searching_pinecone(monkeypatch):
    monkeypatch.setattr(serve, "VECTOR_STORE", "pinecone")
    assert serve._vector_store_for(_Conn(table_exists=False)) == "pinecone"
    assert serve._vector_store_for(_Conn(table_exists=True)) == "pinecone"


def test_a_brain_naming_pgvector_is_searched_in_postgres(monkeypatch):
    monkeypatch.setattr(serve, "VECTOR_STORE", "pinecone")
    conn = _Conn(table_exists=True, value="pgvector")
    assert serve._vector_store_for(conn) == "pgvector"
    assert any("vector_store" in s for s in conn.sql)


def test_the_memory_rollback_overrides_whatever_the_database_says(monkeypatch):
    monkeypatch.setattr(serve, "VECTOR_STORE", "memory")
    assert serve._vector_store_for(_Conn(table_exists=True, value="pgvector")) == "memory"
