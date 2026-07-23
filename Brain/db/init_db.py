import psycopg
from pathlib import Path


def init_db(database_url: str) -> None:
    """Run schema.sql against the database. Idempotent — safe to call on every run."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8-sig")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(sql)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    init_db(os.environ["DATABASE_URL"])
    print("Database initialized.")
