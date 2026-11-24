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


_URI_SCHEMES = ("postgres", "postgresql")


def _require_uri(url: str) -> None:
    """Every URL here must be a `postgresql://` URI.

    A libpq key=value string (`host=... password=...`) parses as no URI at all: `is_rds` then
    said False, so the RDS host was NOT upgraded to verified TLS, and `redacted` returned the
    whole string -- password included -- into logs, GET /verify and brain_meta. Found in a bug
    hunt (2026-11-23). Refusing is the fix; supporting both forms is a second place to get
    redaction wrong.
    """
    if urlparse(url).scheme not in _URI_SCHEMES:
        raise ValueError("database URL must be a postgresql:// URI, not a key=value "
                         "connection string")


def is_rds(url: str) -> bool:
    _require_uri(url)
    return (urlparse(url).hostname or "").endswith(".rds.amazonaws.com")


def connection_url(url: str) -> str:
    """`url`, with the server's certificate VERIFIED when it is RDS.

    RDS certificates are signed by Amazon's own RDS authorities, which no default trust
    store holds, so `sslmode=require` is the tempting setting -- and it encrypts without
    checking who answered. This upgrades an RDS URL to `verify-full` against the bundled
    authorities instead. An explicit `sslrootcert` in the URL is left alone.

    A NON-RDS URL that already asks for verification (`verify-full`/`verify-ca`, e.g. the web
    app's Neon URL) gets certifi's public authorities. libpq otherwise looks for
    ~/.postgresql/root.crt, which no container has, and the psycopg wheel's own OpenSSL does
    not see the system store: measured 2026-11-24, that URL failed from Python while Node
    connected, and connected verified once certifi's bundle was named. Any other URL passes
    through unchanged.
    """
    rds = is_rds(url)  # raises on anything that is not a postgresql:// URI
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "sslrootcert" in query:
        return url
    if rds:
        query["sslrootcert"] = str(RDS_CA_BUNDLE)
        query["sslmode"] = "verify-full"
    elif query.get("sslmode") in ("verify-full", "verify-ca"):
        try:
            import certifi
        except ImportError:
            return url
        query["sslrootcert"] = certifi.where()
    else:
        return url
    return urlunparse(parts._replace(query=urlencode(query)))


def redacted(url: str) -> str:
    """`user@host/db` -- what a log line may say about a URL. Never the password, and never
    the raw string when it is not a URI (it would carry the password verbatim)."""
    p = urlparse(url)
    if p.scheme not in _URI_SCHEMES:
        return "<not a postgresql:// URI>"
    return f"{p.username}@{p.hostname}{p.path}"
