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
        self.sql.append(sql)
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
