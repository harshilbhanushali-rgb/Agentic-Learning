#!/usr/bin/env python3
"""Name the Pinecone index a Brain database is served from (`brain_meta.vector_index`).

Ask Naren reads this row at startup (ops/serve_ask_naren.py `_vector_index_for`), so a
database and its index switch TOGETHER -- restoring a database restores its index with it.

REFUSES unless the index holds exactly one trigger and one response vector per kb_pair in
that database (same count, and every sampled trigger id present). A row naming the wrong
index would serve one Brain's texts under another's ranking, which is the failure this exists
to prevent.

    python ops/set_brain_index.py --env-key DATABASE_URL_BRIDGE --index narens-brain-v3-3072
    python ops/set_brain_index.py --env-key DATABASE_URL_BRIDGE --show
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-key", required=True, help="which Brain/.env key holds the database URL")
    ap.add_argument("--index", help="the index to name")
    ap.add_argument("--show", action="store_true", help="print the current value and exit")
    a = ap.parse_args()
    import psycopg
    from pinecone import Pinecone
    from shared.neon_dns import with_hostaddr
    url = with_hostaddr(os.environ[a.env_key])
    with psycopg.connect(url, connect_timeout=30) as conn:
        exists = conn.execute("SELECT to_regclass('public.brain_meta')").fetchone()[0]
        current = (conn.execute("SELECT value FROM brain_meta WHERE key='vector_index'").fetchone()
                   if exists else None)
        print(f"[{a.env_key}] brain_meta.vector_index = {current[0] if current else '(none)'}")
        if a.show or not a.index:
            return 0
        ids = [r[0] for r in conn.execute("SELECT pair_id FROM kb_pairs")]
        ix = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(a.index)
        ns = {k: v["vector_count"] for k, v in
              (ix.describe_index_stats().get("namespaces") or {}).items()}
        if ns.get("triggers") != len(ids) or ns.get("responses") != len(ids):
            print(f"REFUSED: {a.index} holds {ns}, this database has {len(ids)} kb_pairs")
            return 1
        sample = [f"trigger_{i}" for i in random.Random(3).sample(ids, min(500, len(ids)))]
        found = set()
        for i in range(0, len(sample), 100):
            found |= set(ix.fetch(ids=sample[i:i + 100], namespace="triggers").vectors)
        if len(found) != len(sample):
            print(f"REFUSED: {len(sample) - len(found)} of {len(sample)} sampled trigger ids "
                  f"missing from {a.index}")
            return 1
        with conn.transaction():
            conn.execute("CREATE TABLE IF NOT EXISTS brain_meta "
                         "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("GRANT SELECT ON brain_meta TO PUBLIC")
            conn.execute("INSERT INTO brain_meta (key, value) VALUES ('vector_index', %s) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (a.index,))
        print(f"[{a.env_key}] brain_meta.vector_index -> {a.index} "
              f"({len(ids)} pairs, counts and {len(sample)} sampled ids verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
