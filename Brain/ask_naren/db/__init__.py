"""Ask Naren's Postgres on AWS RDS: migrations, grants, and how to connect.

    migrations/NNNN_*.sql   applied in order by migrate.py, each once, tracked in
                            brain.schema_migrations
    grants.sql              what ask_naren_service may read; re-run after migrations and copies
    rds-global-bundle.pem   Amazon's public RDS certificate authorities (not a secret)

`connection_url` is the one place a URL is turned into what psycopg connects with, so the
migration runner, the copy script and the running service verify the server the same way.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"
GRANTS = HERE / "grants.sql"
RDS_CA_BUNDLE = HERE / "rds-global-bundle.pem"


def is_rds(url: str) -> bool:
    return (urlparse(url).hostname or "").endswith(".rds.amazonaws.com")


def connection_url(url: str) -> str:
    """`url`, with the server's certificate VERIFIED when it is RDS.

    RDS certificates are signed by Amazon's own RDS authorities, which no default trust
    store holds, so `sslmode=require` is the tempting setting -- and it encrypts without
    checking who answered. This upgrades an RDS URL to `verify-full` against the bundled
    authorities instead. An explicit `sslrootcert` in the URL is left alone. Non-RDS URLs
    (Neon, a local Docker Postgres) pass through unchanged.
    """
    if not is_rds(url):
        return url
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "sslrootcert" in query:
        return url
    query["sslrootcert"] = str(RDS_CA_BUNDLE)
    query["sslmode"] = "verify-full"
    return urlunparse(parts._replace(query=urlencode(query)))


def redacted(url: str) -> str:
    """`user@host/db` -- what a log line may say about a URL. Never the password."""
    p = urlparse(url)
    return f"{p.username}@{p.hostname}{p.path}"
